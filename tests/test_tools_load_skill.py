from __future__ import annotations

import asyncio
from pathlib import Path

from coco_code.skills.active import ActiveSkills
from coco_code.skills.catalog import SkillCatalog
from coco_code.tools.base import ToolContext
from coco_code.tools.load_skill import LoadSkillTool


def write_skill(root: Path) -> None:
    root.mkdir(parents=True)
    (root / "demo.md").write_text(
        "---\nname: demo\ndescription: Demo\nallowed_tools: [ReadFile]\n---\nHello $ARGUMENTS\n",
        encoding="utf-8",
    )


def test_load_skill_activates_without_returning_sop(tmp_path: Path) -> None:
    async def run() -> None:
        project = tmp_path / "project"
        write_skill(project)
        catalog = SkillCatalog(
            tmp_path,
            builtin_dir=tmp_path / "none",
            user_dir=tmp_path / "user",
            project_dir=project,
        )
        catalog.reload()
        active = ActiveSkills()
        tool = LoadSkillTool(catalog, active)

        result = await tool.run({"name": "demo", "arguments": "world"}, ToolContext(tmp_path))

        assert result.ok is True
        assert result.data == {"skill": "demo"}
        assert "Hello world" not in result.summary
        snapshot = active.snapshot()
        assert snapshot[0].rendered_body == "Hello world\n"
        assert snapshot[0].allowed_tools == ("ReadFile",)

    asyncio.run(run())


def test_load_skill_unknown_returns_error(tmp_path: Path) -> None:
    async def run() -> None:
        catalog = SkillCatalog(
            tmp_path,
            builtin_dir=tmp_path / "none",
            user_dir=tmp_path / "user",
            project_dir=tmp_path / "project",
        )
        catalog.reload()
        tool = LoadSkillTool(catalog, ActiveSkills())

        result = await tool.run({"name": "missing"}, ToolContext(tmp_path))

        assert result.ok is False
        assert "Unknown Skill" in result.error

    asyncio.run(run())


def test_load_skill_spec_is_system_read_only() -> None:
    spec = LoadSkillTool().spec

    assert spec.name == "LoadSkill"
    assert spec.read_only is True
    assert spec.system is True
