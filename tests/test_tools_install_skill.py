from __future__ import annotations

import asyncio
from pathlib import Path

import coco_code.tools.install_skill as install_tool_module
from coco_code.skills.install import InstallResult
from coco_code.tools.base import ConfirmationPolicy, ToolContext
from coco_code.tools.install_skill import InstallSkillTool


def test_install_skill_spec_requires_confirmation(tmp_path: Path) -> None:
    spec = InstallSkillTool(tmp_path).spec

    assert spec.name == "InstallSkill"
    assert spec.read_only is False
    assert spec.confirmation == ConfirmationPolicy.REQUIRED
    assert spec.system is False
    assert "skills.sh" in spec.description
    assert "source_url" in spec.parameters_schema["properties"]
    assert spec.typical_scenarios


def test_install_skill_invokes_reload_callback(monkeypatch, tmp_path: Path) -> None:
    async def run() -> None:
        async def fake_install(source_url: str, user_root: Path) -> InstallResult:
            assert source_url == "https://skills.sh/demo"
            return InstallResult("demo", user_root / "demo", 2, 42)

        called = False

        async def reload_callback() -> None:
            nonlocal called
            called = True

        monkeypatch.setattr(install_tool_module, "install_from_url", fake_install)
        tool = InstallSkillTool(tmp_path, reload_callback=reload_callback)

        result = await tool.run({"source_url": "https://skills.sh/demo"}, ToolContext(tmp_path))

        assert result.ok is True
        assert called is True
        assert result.data["skill"] == "demo"
        assert result.data["file_count"] == 2
        assert result.data["total_bytes"] == 42

    asyncio.run(run())
