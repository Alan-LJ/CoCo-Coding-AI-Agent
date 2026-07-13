from __future__ import annotations

import asyncio
from pathlib import Path

from coco_code.config import Config, ProviderConfig
from coco_code.conversation import Conversation
from coco_code.tui.app import CoCoCodeApp


class QuickSubAgentForApp:
    async def run_to_completion(self, conv, task, *, events=None):  # noqa: ARG002
        return "subagent result"


def provider_config() -> ProviderConfig:
    return ProviderConfig(
        name="Fake OpenAI",
        protocol="openai",
        model="fake-model",
        api_key="secret-key",
    )


def test_app_registers_subagent_tools(tmp_path: Path) -> None:
    app = CoCoCodeApp(
        Config(providers=[provider_config()]),
        cwd=tmp_path,
        show_startup_resume=False,
    )

    for name in ("Agent", "TaskList", "TaskGet", "TaskStop", "SendMessage"):
        assert app.tool_registry.get(name).spec.name == name


def test_subagent_task_done_notifies_runtime(tmp_path: Path) -> None:
    async def run() -> None:
        app = CoCoCodeApp(
            Config(providers=[provider_config()]),
            cwd=tmp_path,
            show_startup_resume=False,
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            await app.task_manager.launch(
                QuickSubAgentForApp(),
                Conversation(),
                "worker",
                "task",
            )
            for _ in range(50):
                await pilot.pause(0.02)
                reminders = list(app.runtime.pending_hook_reminders)
                if any("SubAgent task worker completed" in item for item in reminders):
                    break
            else:
                raise AssertionError("subagent completion reminder was not emitted")

    asyncio.run(run())
