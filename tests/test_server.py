import respx
from fastapi.testclient import TestClient
from httpx import Response

from context_overlay.config import ContextOverlayConfig
from context_overlay.server import create_app


def test_proxy_transforms_chat_completion() -> None:
    config = ContextOverlayConfig.model_validate(
        {
            "upstream": {"base_url": "http://upstream/v1", "api_key": "up-key"},
            "auth": {"api_key": "proxy-key"},
            "rules": [
                {
                    "name": "r",
                    "match": {"messages_regex": ["hello"]},
                    "transforms": [{"type": "append_system", "content": "Overlay"}],
                }
            ],
        }
    )
    app = create_app(config)
    client = TestClient(app)
    with respx.mock(assert_all_called=True) as router:
        route = router.post("http://upstream/v1/chat/completions").mock(
            return_value=Response(200, json={"ok": True})
        )
        response = client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer proxy-key"},
            json={"model": "m", "messages": [{"role": "user", "content": "hello"}]},
        )
    assert response.status_code == 200
    sent = route.calls[0].request
    assert sent.headers["authorization"] == "Bearer up-key"
    assert "Overlay" in sent.content.decode("utf-8")


def test_proxy_auth_required() -> None:
    config = ContextOverlayConfig.model_validate(
        {
            "upstream": {"base_url": "http://upstream/v1"},
            "auth": {"api_key": "proxy-key"},
        }
    )
    client = TestClient(create_app(config))
    response = client.get("/v1/models")
    assert response.status_code == 401
