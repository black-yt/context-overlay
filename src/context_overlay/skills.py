from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


TOKEN_RE = re.compile(r"[A-Za-z0-9_+\-.]+")


def tokenize(text: str) -> set[str]:
    return {token.lower() for token in TOKEN_RE.findall(text) if len(token) > 2}


@dataclass(frozen=True)
class Skill:
    path: Path
    name: str
    description: str
    content: str
    category: str | None = None
    score: int | None = None

    @classmethod
    def from_json_file(cls, path: Path) -> "Skill":
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            path=path,
            name=str(data.get("name") or path.stem),
            description=str(data.get("description") or ""),
            content=str(data.get("content") or ""),
            category=data.get("category"),
            score=data.get("score"),
        )

    def searchable_text(self) -> str:
        return "\n".join(part for part in [self.name, self.description, self.category or "", self.content] if part)


class SkillStore:
    def __init__(self, skills: list[Skill]) -> None:
        self.skills = skills
        self._tokens = [tokenize(skill.searchable_text()) for skill in skills]

    @classmethod
    def from_dir(cls, path: str | Path) -> "SkillStore":
        root = Path(path)
        skills = [Skill.from_json_file(item) for item in sorted(root.glob("*.json"))]
        return cls(skills)

    def retrieve(self, query: str, top_k: int = 3) -> list[Skill]:
        query_tokens = tokenize(query)
        if not query_tokens:
            return self.skills[:top_k]
        scored: list[tuple[float, int, Skill]] = []
        for idx, (skill, skill_tokens) in enumerate(zip(self.skills, self._tokens)):
            if not skill_tokens:
                continue
            overlap = len(query_tokens & skill_tokens)
            if overlap == 0:
                continue
            score = overlap / (len(query_tokens) ** 0.5 * len(skill_tokens) ** 0.5)
            scored.append((score, -idx, skill))
        scored.sort(reverse=True)
        return [skill for _, _, skill in scored[:top_k]]


def render_skills(skills: list[Skill], title: str = "Context Overlay", max_chars: int = 24000) -> str:
    if not skills:
        return ""
    blocks = [f"# {title}", "Use the following planning context when relevant. Do not mention that it was injected."]
    for idx, skill in enumerate(skills, 1):
        blocks.append(f"\n## Skill {idx}: {skill.name}")
        if skill.description:
            blocks.append(f"Description: {skill.description}")
        if skill.category:
            blocks.append(f"Category: {skill.category}")
        blocks.append(skill.content)
    text = "\n".join(blocks).strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 80].rstrip() + "\n\n[Context overlay truncated to fit the configured budget.]"
