from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field


class UpstreamConfig(BaseModel):
    base_url: str
    api_key: str | None = None
    timeout_seconds: float = 600.0


class AuthConfig(BaseModel):
    api_key: str | None = None


class MatchConfig(BaseModel):
    path: str | None = None
    model_regex: str | None = None
    messages_regex: list[str] = Field(default_factory=list)
    extra_body: dict[str, Any] = Field(default_factory=dict)


class ContentSourceConfig(BaseModel):
    type: Literal["text", "file", "skill_dir"]
    text: str | None = None
    path: str | None = None
    top_k: int = 3
    max_chars: int = 24000
    title: str = "Context Overlay"


class TransformConfig(BaseModel):
    type: Literal[
        "prepend_system",
        "append_system",
        "insert_before",
        "insert_after",
        "regex_replace",
        "prepend_user",
        "append_user",
        "route",
        "reject",
    ]
    target: Literal["system", "user"] = "system"
    pattern: str | None = None
    replacement: str | None = None
    content: str | ContentSourceConfig | None = None
    upstream_base_url: str | None = None
    model: str | None = None
    reason: str | None = None


class RuleConfig(BaseModel):
    name: str
    match: MatchConfig = Field(default_factory=MatchConfig)
    transforms: list[TransformConfig] = Field(default_factory=list)


class ContextOverlayConfig(BaseModel):
    upstream: UpstreamConfig
    auth: AuthConfig = Field(default_factory=AuthConfig)
    rules: list[RuleConfig] = Field(default_factory=list)


def _expand_env(value: Any) -> Any:
    if isinstance(value, str):
        return os.path.expandvars(value)
    if isinstance(value, list):
        return [_expand_env(item) for item in value]
    if isinstance(value, dict):
        return {key: _expand_env(item) for key, item in value.items()}
    return value


def load_config(path: str | Path) -> ContextOverlayConfig:
    config_path = Path(path)
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    expanded = _expand_env(raw)
    return ContextOverlayConfig.model_validate(expanded)
