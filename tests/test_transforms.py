import json
import logging
from pathlib import Path

from context_overlay.config import ContextOverlayConfig
from context_overlay.transforms import apply_rules


def test_append_system_creates_system_message() -> None:
    config = ContextOverlayConfig.model_validate(
        {
            "upstream": {"base_url": "http://up/v1"},
            "rules": [
                {
                    "name": "r",
                    "match": {"messages_regex": ["hello"]},
                    "transforms": [{"type": "append_system", "content": "Injected"}],
                }
            ],
        }
    )
    body = {"messages": [{"role": "user", "content": "hello"}]}
    out = apply_rules(body, config)
    assert out["messages"][0]["role"] == "system"
    assert "Injected" in out["messages"][0]["content"]


def test_insert_before_uses_pattern() -> None:
    config = ContextOverlayConfig.model_validate(
        {
            "upstream": {"base_url": "http://up/v1"},
            "rules": [
                {
                    "name": "r",
                    "match": {},
                    "transforms": [
                        {
                            "type": "insert_before",
                            "target": "system",
                            "pattern": "Current date:",
                            "content": "Overlay",
                        }
                    ],
                }
            ],
        }
    )
    body = {"messages": [{"role": "system", "content": "Base\n\nCurrent date: 2026"}]}
    out = apply_rules(body, config)
    assert "Overlay\n\nCurrent date:" in out["messages"][0]["content"]


def test_apply_rules_logs_matched_rule(caplog) -> None:
    config = ContextOverlayConfig.model_validate(
        {
            "upstream": {"base_url": "http://up/v1"},
            "rules": [
                {
                    "name": "inject_demo",
                    "match": {"messages_regex": ["hello"]},
                    "transforms": [{"type": "append_system", "content": "Injected"}],
                }
            ],
        }
    )
    body = {"model": "demo-model", "messages": [{"role": "user", "content": "hello"}]}
    with caplog.at_level(logging.INFO, logger="context_overlay.transforms"):
        apply_rules(body, config, path="/v1/chat/completions")
    assert "context_overlay timestamp=" in caplog.text
    assert "event=rule_matched" in caplog.text
    assert "path=/v1/chat/completions" in caplog.text
    assert "model=demo-model" in caplog.text
    assert "rule=inject_demo" in caplog.text
    assert "transform_count=1" in caplog.text
    assert "type=append_system;target=system" in caplog.text


def test_apply_rules_logs_no_match(caplog) -> None:
    config = ContextOverlayConfig.model_validate(
        {
            "upstream": {"base_url": "http://up/v1"},
            "rules": [
                {
                    "name": "inject_demo",
                    "match": {"messages_regex": ["hello"]},
                    "transforms": [{"type": "append_system", "content": "Injected"}],
                }
            ],
        }
    )
    body = {"model": "demo-model", "messages": [{"role": "user", "content": "plain"}]}
    with caplog.at_level(logging.INFO, logger="context_overlay.transforms"):
        apply_rules(body, config, path="/v1/chat/completions")
    assert "context_overlay timestamp=" in caplog.text
    assert "event=no_rule_matched" in caplog.text
    assert "path=/v1/chat/completions" in caplog.text
    assert "model=demo-model" in caplog.text
    assert "rules_checked=1" in caplog.text


def test_skill_dir_content_source(tmp_path: Path) -> None:
    (tmp_path / "skill.json").write_text(
        json.dumps({"name": "glacier", "description": "glacier plan", "content": "mass balance"}),
        encoding="utf-8",
    )
    config = ContextOverlayConfig.model_validate(
        {
            "upstream": {"base_url": "http://up/v1"},
            "rules": [
                {
                    "name": "r",
                    "match": {"messages_regex": ["glacier"]},
                    "transforms": [
                        {
                            "type": "append_system",
                            "content": {
                                "type": "skill_dir",
                                "path": str(tmp_path),
                                "top_k": 1,
                                "max_chars": 2000,
                            },
                        }
                    ],
                }
            ],
        }
    )
    body = {"messages": [{"role": "user", "content": "glacier task"}]}
    out = apply_rules(body, config)
    assert "glacier plan" in out["messages"][0]["content"]


def test_regex_replace() -> None:
    config = ContextOverlayConfig.model_validate(
        {
            "upstream": {"base_url": "http://up/v1"},
            "rules": [
                {
                    "name": "r",
                    "match": {},
                    "transforms": [
                        {
                            "type": "regex_replace",
                            "target": "system",
                            "pattern": "old",
                            "replacement": "new",
                        }
                    ],
                }
            ],
        }
    )
    body = {"messages": [{"role": "system", "content": "old prompt"}]}
    out = apply_rules(body, config)
    assert out["messages"][0]["content"] == "new prompt"


def test_regex_replace_can_target_user_message() -> None:
    config = ContextOverlayConfig.model_validate(
        {
            "upstream": {"base_url": "http://up/v1"},
            "rules": [
                {
                    "name": "r",
                    "match": {"messages_regex": ["test"]},
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
    body = {"messages": [{"role": "user", "content": "please test this"}]}
    out = apply_rules(body, config)
    assert out["messages"][0]["content"] == "please test[skill] this"


def test_route_sets_model_and_upstream_marker() -> None:
    config = ContextOverlayConfig.model_validate(
        {
            "upstream": {"base_url": "http://up/v1"},
            "rules": [
                {
                    "name": "r",
                    "match": {"model_regex": "old"},
                    "transforms": [
                        {
                            "type": "route",
                            "model": "new-model",
                            "upstream_base_url": "http://other/v1",
                        }
                    ],
                }
            ],
        }
    )
    body = {"model": "old-model", "messages": []}
    out = apply_rules(body, config)
    assert out["model"] == "new-model"
    assert out["_context_overlay_upstream_base_url"] == "http://other/v1"
