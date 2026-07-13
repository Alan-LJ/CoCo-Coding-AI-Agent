from __future__ import annotations

import asyncio
from pathlib import Path

from coco_code.command import CommandContext, parse_command
from coco_code.command.handlers import handle_hooks
from coco_code.hook import Event, HookEngine
from coco_code.hook.rule import HookAction, HookRule, PromptAction


class HookUI:
    def __init__(self, engine: HookEngine | None) -> None:
        self.engine = engine
        self.messages: list[str] = []

    def hook_rules(self):
        return [] if self.engine is None else list(self.engine.rules())

    def hook_sources(self):
        return [] if self.engine is None else [str(path) for path in self.engine.sources()]

    def show_message(self, text: str) -> None:
        self.messages.append(text)

    def show_error(self, text: str) -> None:
        raise AssertionError(text)


def test_hooks_command_empty() -> None:
    async def run() -> None:
        ui = HookUI(None)
        await handle_hooks(CommandContext(parse_command("/hooks")), ui)
        assert ui.messages == ["No hooks loaded."]

    asyncio.run(run())


def test_hooks_command_lists_rules(tmp_path: Path) -> None:
    async def run() -> None:
        source = tmp_path / ".coco-code" / "hooks.yaml"
        engine = HookEngine(
            [
                HookRule(
                    "once",
                    Event.SESSION_START,
                    HookAction("prompt", PromptAction("hi")),
                    only_once=True,
                    async_mode=False,
                )
            ],
            [source],
        )
        ui = HookUI(engine)
        await handle_hooks(CommandContext(parse_command("/hooks")), ui)
        output = ui.messages[0]
        assert "SessionStart" in output
        assert "once" in output
        assert "prompt" in output
        assert "[once]" in output
        assert "Loaded from:" in output

    asyncio.run(run())
