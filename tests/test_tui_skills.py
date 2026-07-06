from __future__ import annotations

import asyncio
from pathlib import Path

from coco_code.config import Config, ProviderConfig
from coco_code.tui.app import CoCoCodeApp, SessionState
from coco_code.tui.commands import dispatch_command


def provider_config() -> ProviderConfig:
    return ProviderConfig("Fake OpenAI", "openai", "fake-model", api_key="secret-key")


def test_tui_registers_skill_tools_and_commands(tmp_path: Path) -> None:
    async def run() -> None:
        app = CoCoCodeApp(
            Config(providers=[provider_config()]), cwd=tmp_path, show_startup_resume=False
        )
        assert app.tool_registry.get("LoadSkill").spec.system is True
        assert app.tool_registry.get("InstallSkill").spec.system is False
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.state == SessionState.IDLE
            assert app.command_registry.lookup("skill") is not None
            assert app.command_registry.lookup("commit") is not None
            assert app.command_registry.lookup("review") is not None
            assert app.command_registry.lookup("test") is not None

    asyncio.run(run())


def test_tui_prompt_builder_includes_catalog_and_active_skills(tmp_path: Path) -> None:
    async def run() -> None:
        app = CoCoCodeApp(
            Config(providers=[provider_config()]), cwd=tmp_path, show_startup_resume=False
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            app.runtime.active_skills.activate("demo", "Full SOP body", ())
            prompt = app.build_current_system_prompt()
            assert "Available Skills:" in prompt
            assert "commit" in prompt
            assert "## Active Skills" in prompt
            assert "Full SOP body" in prompt

    asyncio.run(run())


def test_tui_clear_clears_conversation_and_active_skills(tmp_path: Path) -> None:
    async def run() -> None:
        app = CoCoCodeApp(
            Config(providers=[provider_config()]), cwd=tmp_path, show_startup_resume=False
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            app.conversation.add_user("hello")
            app.runtime.active_skills.activate("demo", "body", ())
            assert await dispatch_command(app, "/clear") is True
            assert app.conversation.items() == []
            assert app.runtime.active_skills.snapshot() == ()

    asyncio.run(run())


def test_tui_validation_removes_skill_with_missing_tool(tmp_path: Path) -> None:
    skill_dir = tmp_path / ".coco-code" / "skills" / "bad"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        '---\nname: bad\ndescription: bad skill\nallowed_tools: ["NoSuchTool"]\n---\nBody\n',
        encoding="utf-8",
    )

    async def run() -> None:
        app = CoCoCodeApp(
            Config(providers=[provider_config()]), cwd=tmp_path, show_startup_resume=False
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.skill_catalog.get("bad") is None
            assert app.command_registry.lookup("bad") is None

    asyncio.run(run())


def test_tui_append_assistant_message_updates_visible_and_main_history(tmp_path: Path) -> None:
    async def run() -> None:
        app = CoCoCodeApp(
            Config(providers=[provider_config()]), cwd=tmp_path, show_startup_resume=False
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            app.append_assistant_message("fork summary")
            assert app.conversation.messages()[-1].content == "fork summary"

    asyncio.run(run())
