from __future__ import annotations

from pathlib import Path

from coco_code.config import ProviderConfig
from coco_code.prompt import build_system_prompt
from coco_code.skills.active import ActiveSkillEntry
from coco_code.skills.render import render_active_skills_block, render_skills_catalog
from coco_code.skills.types import Skill, SkillMeta, SkillSource


def test_render_skills_catalog_uses_only_name_and_description(tmp_path: Path) -> None:
    skill = Skill(
        meta=SkillMeta(name="demo", description="Demo skill"),
        prompt_body="SECRET SOP",
        entry_path=tmp_path / "demo.md",
        package_dir=tmp_path,
        source=SkillSource.PROJECT,
        is_directory=False,
    )

    catalog = render_skills_catalog((skill,))

    assert "demo" in catalog
    assert "Demo skill" in catalog
    assert "SECRET SOP" not in catalog


def test_render_active_skills_block_contains_full_sops_in_order() -> None:
    block = render_active_skills_block(
        (
            ActiveSkillEntry("one", "First body"),
            ActiveSkillEntry("two", "Second body"),
        )
    )

    assert block.index("First body") < block.index("Second body")
    assert "## Active Skills" in block


def test_build_system_prompt_includes_skill_sections(tmp_path: Path) -> None:
    provider = ProviderConfig(name="p", protocol="openai", model="m", api_key="k")
    prompt = build_system_prompt(
        tmp_path,
        provider,
        skills_catalog="Available Skills:\n- demo: Demo",
        active_skills="## Active Skills\n\n### Skill: demo\n\nBody",
    )

    assert "Available Skills" in prompt
    assert "### Skill: demo" in prompt
