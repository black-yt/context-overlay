from __future__ import annotations

import re
from typing import Any

from .config import MatchConfig


def message_text(messages: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
    return "\n".join(parts)


def _contains_extra_body(body: dict[str, Any], expected: dict[str, Any]) -> bool:
    for key, value in expected.items():
        if body.get(key) != value:
            return False
    return True


def request_matches(path: str, body: dict[str, Any], match: MatchConfig) -> bool:
    if match.path and match.path != path:
        return False
    if match.model_regex:
        model = str(body.get("model", ""))
        if not re.search(match.model_regex, model):
            return False
    if match.extra_body and not _contains_extra_body(body, match.extra_body):
        return False
    if match.messages_regex:
        text = message_text(body.get("messages") or [])
        if not all(re.search(pattern, text, flags=re.IGNORECASE) for pattern in match.messages_regex):
            return False
    return True
