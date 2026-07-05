from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from coco_code.config import Config, ProviderConfig
from coco_code.tools import ConfirmationPolicy, ToolContext, ToolResult, ToolSpec
from coco_code.tui.app import CoCoCodeApp


class StaticTool:
    def __init__(self, name: str) -> None:
        self._spec = ToolSpec(
            name=name,
            description=name,
            parameters_schema={
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
            confirmation=ConfirmationPolicy.NEVER,
            read_only=True,
        )

    @property
    def spec(self) -> ToolSpec:
        return self._spec

    async def run(self, params: dict[str, Any], context: ToolContext) -> ToolResult:  # noqa: ARG002
        return ToolResult("", self._spec.name, True, "ok", {}, None, 0)


class FakeMcpManager:
    def __init__(self, tools: list[StaticTool]) -> None:
        self._tools = tools
        self.started = False
        self.closed = False

    async def start(self) -> None:
        self.started = True

    def tools(self) -> list[StaticTool]:
        return self._tools

    async def close(self) -> None:
        self.closed = True


def _config() -> Config:
    return Config(
        providers=[
            ProviderConfig(
                name="Fake OpenAI",
                protocol="openai",
                model="fake-model",
                api_key="secret-key",
            )
        ]
    )


def test_tui_mount_starts_mcp_manager_and_registers_tools(tmp_path: Path) -> None:
    async def run() -> None:
        manager = FakeMcpManager([StaticTool("mcp__demo__ping")])
        app = CoCoCodeApp(_config(), cwd=tmp_path, mcp_manager=manager)

        async with app.run_test() as pilot:
            await pilot.pause()
            assert manager.started is True
            assert app.tool_registry.get("mcp__demo__ping").spec.name == "mcp__demo__ping"

    asyncio.run(run())


def test_tui_mount_skips_mcp_tool_name_conflicts(tmp_path: Path) -> None:
    async def run() -> None:
        conflicting = StaticTool("ReadFile")
        manager = FakeMcpManager([conflicting, StaticTool("mcp__demo__ok")])
        app = CoCoCodeApp(_config(), cwd=tmp_path, mcp_manager=manager)

        async with app.run_test() as pilot:
            await pilot.pause()
            assert manager.started is True
            assert app.tool_registry.get("ReadFile") is not conflicting
            assert app.tool_registry.get("mcp__demo__ok").spec.name == "mcp__demo__ok"

    asyncio.run(run())


def test_request_quit_cancels_streaming_and_closes_mcp_manager(
    tmp_path: Path,
    monkeypatch,
) -> None:
    async def run() -> None:
        manager = FakeMcpManager([])
        app = CoCoCodeApp(_config(), cwd=tmp_path, mcp_manager=manager)
        exited = False

        def fake_exit() -> None:
            nonlocal exited
            exited = True

        monkeypatch.setattr(app, "exit", fake_exit)
        app.stream_task = asyncio.create_task(asyncio.sleep(10))

        app.request_quit()
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        assert app.stream_task.cancelled() is True
        assert manager.closed is True
        assert exited is True

    asyncio.run(run())
