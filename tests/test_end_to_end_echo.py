from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from context_overlay.config import ContextOverlayConfig
from context_overlay.server import create_app


def create_echo_upstream() -> FastAPI:
    app = FastAPI()

    @app.post("/v1/chat/completions")
    async def chat(request: Request) -> dict:
        body = await request.json()
        messages = body.get("messages") or []
        last_user = ""
        for message in reversed(messages):
            if message.get("role") == "user":
                last_user = str(message.get("content", ""))
                break
        return {
            "id": "chatcmpl-echo",
            "object": "chat.completion",
            "model": body.get("model", "echo-model"),
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": last_user},
                    "finish_reason": "stop",
                }
            ],
        }

    return app


def test_end_to_end_echo_user_regex_overlay(monkeypatch) -> None:
    upstream_client = TestClient(create_echo_upstream())

    class MockAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> None:
            return None

        async def request(self, method, url, headers=None, json=None, content=None, params=None):
            if method == "POST":
                return upstream_client.post("/v1/chat/completions", json=json)
            return upstream_client.request(method, "/v1/models")

    monkeypatch.setattr("context_overlay.server.httpx.AsyncClient", MockAsyncClient)

    config = ContextOverlayConfig.model_validate(
        {
            "upstream": {"base_url": "http://echo-upstream/v1", "api_key": "unused"},
            "auth": {"api_key": "proxy-key"},
            "rules": [
                {
                    "name": "insert_skill_after_test",
                    "match": {
                        "path": "/v1/chat/completions",
                        "messages_regex": ["test"],
                    },
                    "transforms": [
                        {
                            "type": "regex_replace",
                            "target": "user",
                            "pattern": "test",
                            "replacement": "test[skill]",
                        }
                    ],
                }
            ],
        }
    )
    client = TestClient(create_app(config))

    unchanged = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer proxy-key"},
        json={"model": "echo-model", "messages": [{"role": "user", "content": "hello world"}]},
    )
    assert unchanged.status_code == 200
    assert unchanged.json()["choices"][0]["message"]["content"] == "hello world"

    changed = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer proxy-key"},
        json={"model": "echo-model", "messages": [{"role": "user", "content": "hello test world"}]},
    )
    assert changed.status_code == 200
    assert changed.json()["choices"][0]["message"]["content"] == "hello test[skill] world"
