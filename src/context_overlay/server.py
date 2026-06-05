from __future__ import annotations

from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from .config import ContextOverlayConfig
from .transforms import apply_rules


def _check_auth(config: ContextOverlayConfig, authorization: str | None) -> None:
    expected = config.auth.api_key
    if not expected:
        return
    if authorization == f"Bearer {expected}":
        return
    raise HTTPException(status_code=401, detail="Invalid context-overlay API key")


def _upstream_url(config: ContextOverlayConfig, path: str, body: dict[str, Any] | None = None) -> str:
    base_url = config.upstream.base_url.rstrip("/")
    if body and body.get("_context_overlay_upstream_base_url"):
        base_url = str(body["_context_overlay_upstream_base_url"]).rstrip("/")
    suffix = path.removeprefix("/v1")
    return base_url + suffix


def _forward_headers(config: ContextOverlayConfig, request: Request) -> dict[str, str]:
    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in {"host", "content-length", "authorization"}
    }
    api_key = config.upstream.api_key
    if api_key:
        headers["authorization"] = f"Bearer {api_key}"
    return headers


def create_app(config: ContextOverlayConfig) -> FastAPI:
    app = FastAPI(title="context-overlay")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.api_route("/v1/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    async def proxy(path: str, request: Request, authorization: str | None = Header(default=None)) -> Response:
        _check_auth(config, authorization)
        full_path = f"/v1/{path}"
        method = request.method
        headers = _forward_headers(config, request)
        timeout = httpx.Timeout(config.upstream.timeout_seconds)

        if method == "POST" and full_path == "/v1/chat/completions":
            body = await request.json()
            try:
                body = apply_rules(body, config, path=full_path)
            except PermissionError as exc:
                raise HTTPException(status_code=403, detail=str(exc)) from exc
            except Exception as exc:  # noqa: BLE001 - return explicit transform errors.
                raise HTTPException(status_code=400, detail=f"context-overlay transform error: {exc}") from exc
            stream = bool(body.get("stream"))
            upstream_url = _upstream_url(config, full_path, body)
            body.pop("_context_overlay_upstream_base_url", None)
            if stream:
                return await _stream_request(method, upstream_url, headers, json_body=body, timeout=timeout)
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.request(method, upstream_url, headers=headers, json=body)
            return Response(
                content=response.content,
                status_code=response.status_code,
                media_type=response.headers.get("content-type"),
            )

        upstream_url = _upstream_url(config, full_path)
        content = await request.body()
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.request(method, upstream_url, headers=headers, content=content, params=request.query_params)
        return Response(
            content=response.content,
            status_code=response.status_code,
            media_type=response.headers.get("content-type"),
        )

    return app


async def _stream_request(
    method: str,
    url: str,
    headers: dict[str, str],
    json_body: dict[str, Any],
    timeout: httpx.Timeout,
) -> StreamingResponse:
    client = httpx.AsyncClient(timeout=timeout)
    request = client.build_request(method, url, headers=headers, json=json_body)
    response = await client.send(request, stream=True)

    async def iterator():
        try:
            async for chunk in response.aiter_bytes():
                yield chunk
        finally:
            await response.aclose()
            await client.aclose()

    return StreamingResponse(
        iterator(),
        status_code=response.status_code,
        media_type=response.headers.get("content-type", "text/event-stream"),
    )
