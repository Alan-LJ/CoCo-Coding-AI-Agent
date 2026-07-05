from __future__ import annotations

import asyncio
from pathlib import Path

from coco_code.agent import AgentMode
from coco_code.config import Config, ProviderConfig
from coco_code.conversation import ToolResultItem
from coco_code.llm import StreamEvent, StreamEventType
from coco_code.permission import Mode as PermissionMode
from coco_code.permission.engine import Engine
from coco_code.tools import ToolCall, ToolContext
from coco_code.tui.app import CoCoCodeApp, SessionState, next_permission_mode, parse_agent_request
from coco_code.tui.view import mode_status_text


class FakeProvider:
    name = "fake"
    model = "fake-model"
    protocol = "openai"

    def __init__(self, events_by_call: list[list[StreamEvent]]) -> None:
        self.events_by_call = events_by_call
        self.calls = 0
        self.tools_seen = []
        self.messages_seen = []

    async def stream(self, messages, tools=None):
        self.calls += 1
        self.messages_seen.append(messages)
        self.tools_seen.append(tools)
        for event in self.events_by_call[self.calls - 1]:
            yield event


async def _wait_until_idle(app: CoCoCodeApp) -> None:
    for _ in range(50):
        await asyncio.sleep(0.02)
        if app.state == SessionState.IDLE:
            return
    raise AssertionError("app did not return to idle")


def provider_config() -> ProviderConfig:
    return ProviderConfig(name="Fake", protocol="openai", model="fake-model", api_key="secret")


def test_parse_agent_request_permission_modes_and_next_mode() -> None:
    assert parse_agent_request("hello").permission_mode is None
    assert parse_agent_request("/plan inspect").permission_mode == PermissionMode.PLAN
    assert parse_agent_request("/do execute").permission_mode == PermissionMode.DEFAULT
    assert next_permission_mode(PermissionMode.DEFAULT) == PermissionMode.ACCEPT_EDITS
    assert next_permission_mode(PermissionMode.ACCEPT_EDITS) == PermissionMode.PLAN
    assert next_permission_mode(PermissionMode.PLAN) == PermissionMode.BYPASS
    assert next_permission_mode(PermissionMode.BYPASS) == PermissionMode.DEFAULT


def test_status_text_shows_permission_mode_without_provider_name() -> None:
    provider = provider_config()
    text = mode_status_text(provider, AgentMode.AGENT, 0, None, PermissionMode.BYPASS).plain
    assert "BYPASS" in text
    assert provider.name not in text
    assert provider.model in text


def test_app_shift_tab_cycles_permission_mode(tmp_path: Path) -> None:
    async def run() -> None:
        app = CoCoCodeApp(Config(providers=[provider_config()]), cwd=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.permission_mode == PermissionMode.DEFAULT
            await pilot.press("shift+tab")
            await pilot.pause()
            assert app.permission_mode == PermissionMode.ACCEPT_EDITS
            await pilot.press("shift+tab")
            await pilot.pause()
            assert app.permission_mode == PermissionMode.PLAN

    asyncio.run(run())


def test_app_permission_engine_allows_write_once_with_modal(tmp_path: Path) -> None:
    async def run() -> None:
        call = ToolCall(
            "call-1",
            "WriteFile",
            {"path": "created.txt", "content": "ok", "overwrite": False},
            "{}",
        )
        provider = FakeProvider(
            [
                [StreamEvent(type=StreamEventType.TOOL_CALL, tool_call=call)],
                [
                    StreamEvent(type=StreamEventType.TEXT_DELTA, text="written"),
                    StreamEvent(type=StreamEventType.DONE),
                ],
            ]
        )
        engine = Engine(
            root=str(tmp_path.resolve()),
            local_path=str(tmp_path / ".coco-code" / "settings.local.yaml"),
        )
        app = CoCoCodeApp(
            Config(providers=[provider_config()]),
            cwd=tmp_path,
            tool_context=ToolContext(workspace=tmp_path, confirm_timeout_seconds=2),
            permission_engine=engine,
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            app.provider = provider
            app.submit_user_text("write")
            await pilot.pause(0.2)
            await pilot.click("#allow-once")
            await _wait_until_idle(app)
            assert (tmp_path / "created.txt").read_text(encoding="utf-8") == "ok"
            tool_results = [
                item.result for item in app.conversation.items() if isinstance(item, ToolResultItem)
            ]
            assert tool_results[0].ok is True
            assert not Path(engine.local_path).exists()

    asyncio.run(run())


def test_app_permission_engine_allow_forever_persists(tmp_path: Path) -> None:
    async def run() -> None:
        call = ToolCall("call-1", "WriteFile", {"path": "forever.txt", "content": "ok"}, "{}")
        provider = FakeProvider(
            [
                [StreamEvent(type=StreamEventType.TOOL_CALL, tool_call=call)],
                [StreamEvent(type=StreamEventType.DONE)],
            ]
        )
        engine = Engine(
            root=str(tmp_path.resolve()),
            local_path=str(tmp_path / ".coco-code" / "settings.local.yaml"),
        )
        app = CoCoCodeApp(
            Config(providers=[provider_config()]),
            cwd=tmp_path,
            tool_context=ToolContext(workspace=tmp_path, confirm_timeout_seconds=2),
            permission_engine=engine,
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            app.provider = provider
            app.submit_user_text("write forever")
            await pilot.pause(0.2)
            await pilot.click("#allow-forever")
            await _wait_until_idle(app)
            assert "Write(forever.txt)" in Path(engine.local_path).read_text(encoding="utf-8")

    asyncio.run(run())
