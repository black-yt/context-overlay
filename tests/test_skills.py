import json
from pathlib import Path

from context_overlay.skills import SkillStore, render_skills


def test_skill_store_retrieves_relevant_skill(tmp_path: Path) -> None:
    (tmp_path / "glacier.json").write_text(
        json.dumps(
            {
                "name": "glacier_plan",
                "description": "Analyze glacier mass balance",
                "category": "scientific_analysis",
                "content": "Compute regional glacier mass loss and uncertainty.",
                "score": 5,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "chem.json").write_text(
        json.dumps(
            {
                "name": "molecule_plan",
                "description": "Analyze molecular graph neural networks",
                "content": "Compare ROC-AUC for molecular property models.",
            }
        ),
        encoding="utf-8",
    )
    store = SkillStore.from_dir(tmp_path)
    skills = store.retrieve("global glacier uncertainty mass", top_k=1)
    assert skills[0].name == "glacier_plan"


def test_render_skills_respects_budget(tmp_path: Path) -> None:
    (tmp_path / "a.json").write_text(
        json.dumps({"name": "a", "description": "d", "content": "x" * 1000}),
        encoding="utf-8",
    )
    store = SkillStore.from_dir(tmp_path)
    rendered = render_skills(store.skills, max_chars=200)
    assert len(rendered) <= 220
    assert "truncated" in rendered.lower()
