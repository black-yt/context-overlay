from __future__ import annotations

import copy
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import ContentSourceConfig, ContextOverlayConfig, TransformConfig
from .matching import message_text, request_matches
from .skills import SkillStore, render_skills

LOGGER = logging.getLogger(__name__)
UVICORN_LOGGER = logging.getLogger("uvicorn.error")


def _log_info(message: str, *args: Any) -> None:
    LOGGER.info(message, *args)
    UVICORN_LOGGER.info(message, *args)


def _log_timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _content_source_summary(content: str | ContentSourceConfig | None) -> str:
    if content is None:
        return "none"
    if isinstance(content, str):
        return "inline_text"
    if content.type == "file":
        return f"file:{content.path}"
    if content.type == "skill_dir":
        return f"skill_dir:{content.path}:top_k={content.top_k}"
    return content.type


def _transform_summary(transform: TransformConfig) -> str:
    parts = [
        f"type={transform.type}",
        f"target={transform.target}",
    ]
    if transform.pattern:
        parts.append("pattern=yes")
    if transform.model:
        parts.append(f"model={transform.model}")
    if transform.upstream_base_url:
        parts.append("route_upstream=yes")
    parts.append(f"content={_content_source_summary(transform.content)}")
    return ";".join(parts)


def ensure_messages(body: dict[str, Any]) -> list[dict[str, Any]]:
    messages = body.setdefault("messages", [])
    if not isinstance(messages, list):
        raise ValueError("Request body field 'messages' must be a list")
    return messages


def ensure_system_message(messages: list[dict[str, Any]]) -> dict[str, Any]:
    for message in messages:
        if message.get("role") == "system":
            if not isinstance(message.get("content"), str):
                message["content"] = str(message.get("content", ""))
            return message
    system = {"role": "system", "content": ""}
    messages.insert(0, system)
    return system


def ensure_last_user_message(messages: list[dict[str, Any]]) -> dict[str, Any]:
    for message in reversed(messages):
        if message.get("role") == "user":
            if not isinstance(message.get("content"), str):
                message["content"] = _content_to_text(message.get("content"))
            return message
    user = {"role": "user", "content": ""}
    messages.append(user)
    return user


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
        return "\n".join(parts)
    return str(content or "")


def resolve_content(content: str | ContentSourceConfig | None, body: dict[str, Any]) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if content.type == "text":
        return content.text or ""
    if content.type == "file":
        if not content.path:
            raise ValueError("file content source requires path")
        return Path(content.path).read_text(encoding="utf-8")
    if content.type == "skill_dir":
        if not content.path:
            raise ValueError("skill_dir content source requires path")
        store = SkillStore.from_dir(content.path)
        skills = store.retrieve(message_text(body.get("messages") or []), top_k=content.top_k)
        return render_skills(skills, title=content.title, max_chars=content.max_chars)
    raise ValueError(f"Unsupported content source: {content.type}")


def _join(prefix: str, suffix: str) -> str:
    if not prefix:
        return suffix
    if not suffix:
        return prefix
    return prefix.rstrip() + "\n\n" + suffix.lstrip()


def apply_transform(body: dict[str, Any], transform: TransformConfig) -> dict[str, Any]:
    messages = ensure_messages(body)
    overlay = resolve_content(transform.content, body)
    if transform.type == "reject":
        raise PermissionError(transform.reason or "Request rejected by context-overlay rule")
    if transform.type == "route":
        if transform.model:
            body["model"] = transform.model
        if transform.upstream_base_url:
            body["_context_overlay_upstream_base_url"] = transform.upstream_base_url
        return body
    if transform.type in {"prepend_system", "append_system"}:
        target = ensure_system_message(messages)
    elif transform.type in {"prepend_user", "append_user"}:
        target = ensure_last_user_message(messages)
    elif transform.type in {"insert_before", "insert_after", "regex_replace"}:
        target = ensure_last_user_message(messages) if transform.target == "user" else ensure_system_message(messages)
    else:
        raise ValueError(f"Unsupported transform type: {transform.type}")

    content = str(target.get("content") or "")
    if transform.type in {"prepend_system", "prepend_user"}:
        target["content"] = _join(overlay, content)
    elif transform.type in {"append_system", "append_user"}:
        target["content"] = _join(content, overlay)
    elif transform.type == "insert_before":
        if not transform.pattern:
            target["content"] = _join(overlay, content)
        else:
            target["content"] = re.sub(transform.pattern, lambda match: overlay + "\n\n" + match.group(0), content, count=1)
    elif transform.type == "insert_after":
        if not transform.pattern:
            target["content"] = _join(content, overlay)
        else:
            target["content"] = re.sub(transform.pattern, lambda match: match.group(0) + "\n\n" + overlay, content, count=1)
    elif transform.type == "regex_replace":
        if not transform.pattern:
            raise ValueError("regex_replace requires pattern")
        replacement = transform.replacement if transform.replacement is not None else overlay
        target["content"] = re.sub(transform.pattern, replacement, content)
    return body


def apply_rules(body: dict[str, Any], config: ContextOverlayConfig, path: str = "/v1/chat/completions") -> dict[str, Any]:
    transformed = copy.deepcopy(body)
    model = str(transformed.get("model", ""))
    matched = 0
    for rule in config.rules:
        if not request_matches(path, transformed, rule.match):
            continue
        matched += 1
        transforms = " | ".join(_transform_summary(transform) for transform in rule.transforms)
        _log_info(
            "context_overlay timestamp=%s event=rule_matched path=%s model=%s rule=%s transform_count=%s transforms=%s",
            _log_timestamp(),
            path,
            model,
            rule.name,
            len(rule.transforms),
            transforms,
        )
        for transform in rule.transforms:
            transformed = apply_transform(transformed, transform)
    if matched == 0:
        _log_info(
            "context_overlay timestamp=%s event=no_rule_matched path=%s model=%s rules_checked=%s",
            _log_timestamp(),
            path,
            model,
            len(config.rules),
        )
    return transformed
