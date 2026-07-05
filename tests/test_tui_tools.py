from __future__ import annotations

import asyncio
from pathlib import Path

from coco_code.config import Config, ProviderConfig
from coco_code.conversation import ToolResultItem
from coco_code.llm import StreamEvent, StreamEventType
from coco_code.tools import ConfirmationPolicy, ToolCall, ToolContext, ToolResult, ToolSpec
from coco_code.tui.app import CoCoCodeApp, SessionState
from coco_code.tui.stream import consume_provider_stream
from coco_code.tui.view import (
    second_tool_block,
    tool_call_block,
    tool_confirm_block,
    tool_result_block,
)


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


class FailingProvider:
    name = "fake"
    model = "fake-model"
    protocol = "openai"

    def __init__(self) -> None:
        self.calls = 0

    async def stream(self, messages, tools=None):  # noqa: ARG002
        self.calls += 1
        raise RuntimeError("provider failed")
        if False:
            yield StreamEvent(type=StreamEventType.DONE)


class HangingProvider:
    name = "fake"
    model = "fake-model"
    protocol = "openai"

    def __init__(self) -> None:
        self.calls = 0
        self.tools_seen = []
        self.messages_seen = []

    async def stream(self, messages, tools=None):
        self.calls += 1
        self.messages_seen.append(messages)
        self.tools_seen.append(tools)
        await asyncio.sleep(60)
        if False:
            yield StreamEvent(type=StreamEventType.DONE)


def test_consume_provider_stream_returns_tool_call() -> None:
    call = ToolCall("call-1", "ReadFile", {"path": "a.txt"}, '{"path":"a.txt"}')
    provider = FakeProvider([[StreamEvent(type=StreamEventType.TOOL_CALL, tool_call=call)]])

    async def on_text(text: str) -> None:  # noqa: ARG001
        raise AssertionError("no text expected")

    result = asyncio.run(consume_provider_stream(provider, [], on_text))
    assert result.tool_call == call
    assert result.blocked_by_second_tool_call is False


def test_consume_provider_stream_marks_second_tool_blocked() -> None:
    call = ToolCall("call-1", "ReadFile", {}, "{}")
    provider = FakeProvider([[StreamEvent(type=StreamEventType.TOOL_CALL, tool_call=call)]])

    async def on_text(text: str) -> None:  # noqa: ARG001
        pass

    result = asyncio.run(consume_provider_stream(provider, [], on_text, allow_tool_call=False))
    assert result.tool_call == call
    assert result.blocked_by_second_tool_call is True


def test_tool_view_blocks_render() -> None:
    call = ToolCall("call-1", "ReadFile", {"path": "a.txt"}, "{}")
    spec = ToolSpec("ReadFile", "璇诲彇鏂囦欢", {}, ConfirmationPolicy.NEVER)
    result = ToolResult("call-1", "ReadFile", True, "ok", {}, None, 3)
    output_result = ToolResult(
        "call-2",
        "Bash",
        False,
        "command failed with exit code 7",
        {"stdout": "hello", "stderr": "bad"},
        "command exited 7: bad",
        3,
    )
    output_panel = tool_result_block(output_result)
    assert tool_call_block(call, spec) is not None
    assert tool_confirm_block(call, spec) is not None
    assert tool_result_block(result) is not None
    assert "stdout" in output_panel.renderable.plain
    assert "stderr" in output_panel.renderable.plain
    assert second_tool_block(call) is not None


async def _wait_until_idle(app: CoCoCodeApp) -> None:
    for _ in range(50):
        await asyncio.sleep(0.02)
        if app.state == SessionState.IDLE:
            return
    raise AssertionError("app did not return to idle")


def provider_config() -> ProviderConfig:
    return ProviderConfig(name="Fake", protocol="openai", model="fake-model", api_key="secret")


def test_app_orchestrates_ReadFile_tool(tmp_path: Path) -> None:
    async def run() -> None:
        (tmp_path / "a.txt").write_text("hello from tool", encoding="utf-8")
        call = ToolCall("call-1", "ReadFile", {"path": "a.txt"}, '{"path":"a.txt"}')
        provider = FakeProvider(
            [
                [StreamEvent(type=StreamEventType.TOOL_CALL, tool_call=call)],
                [
                    StreamEvent(type=StreamEventType.TEXT_DELTA, text="final"),
                    StreamEvent(type=StreamEventType.DONE),
                ],
            ]
        )
        app = CoCoCodeApp(
            Config(providers=[provider_config()]),
            cwd=tmp_path,
            tool_context=ToolContext(workspace=tmp_path),
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            app.provider = provider
            app.submit_user_text("read a.txt")
            await _wait_until_idle(app)
            assert provider.calls == 2
            assert app.conversation.messages()[-1].content == "final"
            assert any(isinstance(item, ToolResultItem) for item in app.conversation.items())
            assert provider.tools_seen[0] is app.tool_registry

    asyncio.run(run())


def test_app_rejects_WriteFile_tool(tmp_path: Path) -> None:
    async def reject(call: ToolCall, spec: ToolSpec) -> bool:  # noqa: ARG001
        return False

    async def run() -> None:
        call = ToolCall(
            "call-1",
            "WriteFile",
            {"path": "created.txt", "content": "no"},
            '{"path":"created.txt","content":"no"}',
        )
        provider = FakeProvider(
            [
                [StreamEvent(type=StreamEventType.TOOL_CALL, tool_call=call)],
                [
                    StreamEvent(type=StreamEventType.TEXT_DELTA, text="rejected"),
                    StreamEvent(type=StreamEventType.DONE),
                ],
            ]
        )
        app = CoCoCodeApp(
            Config(providers=[provider_config()]),
            cwd=tmp_path,
            tool_context=ToolContext(workspace=tmp_path),
            confirm_callback=reject,
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            app.provider = provider
            app.submit_user_text("write")
            await _wait_until_idle(app)
            assert not (tmp_path / "created.txt").exists()
            tool_results = [
                item.result for item in app.conversation.items() if isinstance(item, ToolResultItem)
            ]
            assert tool_results[0].ok is False
            assert tool_results[0].data["rejected"] is True

    asyncio.run(run())


def test_app_approves_WriteFile_with_modal(tmp_path: Path) -> None:
    async def run() -> None:
        call = ToolCall(
            "call-1",
            "WriteFile",
            {"path": "created.txt", "content": "ok", "overwrite": False},
            '{"path":"created.txt","content":"ok","overwrite":false}',
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
        app = CoCoCodeApp(
            Config(providers=[provider_config()]),
            cwd=tmp_path,
            tool_context=ToolContext(workspace=tmp_path, confirm_timeout_seconds=2),
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            app.provider = provider
            app.submit_user_text("write")
            await pilot.pause(0.2)
            await pilot.click("#approve")
            await _wait_until_idle(app)
            assert (tmp_path / "created.txt").read_text(encoding="utf-8") == "ok"
            tool_results = [
                item.result for item in app.conversation.items() if isinstance(item, ToolResultItem)
            ]
            assert tool_results[0].ok is True

    asyncio.run(run())


def test_app_times_out_write_confirmation(tmp_path: Path) -> None:
    async def never_confirm(call: ToolCall, spec: ToolSpec) -> bool:  # noqa: ARG001
        await asyncio.sleep(60)
        return True

    async def run() -> None:
        call = ToolCall(
            "call-1",
            "WriteFile",
            {"path": "created.txt", "content": "no"},
            '{"path":"created.txt","content":"no"}',
        )
        provider = FakeProvider(
            [
                [StreamEvent(type=StreamEventType.TOOL_CALL, tool_call=call)],
                [
                    StreamEvent(type=StreamEventType.TEXT_DELTA, text="timeout handled"),
                    StreamEvent(type=StreamEventType.DONE),
                ],
            ]
        )
        app = CoCoCodeApp(
            Config(providers=[provider_config()]),
            cwd=tmp_path,
            tool_context=ToolContext(workspace=tmp_path, confirm_timeout_seconds=0.01),
            confirm_callback=never_confirm,
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            app.provider = provider
            app.submit_user_text("write")
            await _wait_until_idle(app)
            assert not (tmp_path / "created.txt").exists()
            tool_results = [
                item.result for item in app.conversation.items() if isinstance(item, ToolResultItem)
            ]
            assert tool_results[0].ok is False
            assert "confirmation timed out" in (tool_results[0].error or "").casefold()
            assert app.conversation.messages()[-1].content == "timeout handled"

    asyncio.run(run())


def test_app_times_out_hanging_provider_stream(tmp_path: Path) -> None:
    async def run() -> None:
        provider = HangingProvider()
        app = CoCoCodeApp(
            Config(providers=[provider_config()]),
            cwd=tmp_path,
            tool_context=ToolContext(workspace=tmp_path),
            response_timeout_seconds=0.01,
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            app.provider = provider
            app.submit_user_text("hang")
            await _wait_until_idle(app)
            assert provider.calls == 1
            assert app.state == SessionState.IDLE

    asyncio.run(run())


def test_app_recovers_from_unhandled_stream_error(tmp_path: Path) -> None:
    async def run() -> None:
        provider = FailingProvider()
        app = CoCoCodeApp(
            Config(providers=[provider_config()]),
            cwd=tmp_path,
            tool_context=ToolContext(workspace=tmp_path),
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            app.provider = provider
            app.submit_user_text("fail")
            await _wait_until_idle(app)
            assert provider.calls == 1
            assert app.state == SessionState.IDLE

    asyncio.run(run())


def test_app_continues_second_tool_call(tmp_path: Path) -> None:
    async def run() -> None:
        (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
        first = ToolCall("call-1", "ReadFile", {"path": "a.txt"}, '{"path":"a.txt"}')
        second = ToolCall("call-2", "ReadFile", {"path": "a.txt"}, '{"path":"a.txt"}')
        provider = FakeProvider(
            [
                [StreamEvent(type=StreamEventType.TOOL_CALL, tool_call=first)],
                [StreamEvent(type=StreamEventType.TOOL_CALL, tool_call=second)],
                [
                    StreamEvent(type=StreamEventType.TEXT_DELTA, text="done"),
                    StreamEvent(type=StreamEventType.DONE),
                ],
            ]
        )
        app = CoCoCodeApp(
            Config(providers=[provider_config()]),
            cwd=tmp_path,
            tool_context=ToolContext(workspace=tmp_path),
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            app.provider = provider
            app.submit_user_text("read twice")
            await _wait_until_idle(app)
            tool_results = [
                item.result for item in app.conversation.items() if isinstance(item, ToolResultItem)
            ]
            assert len(tool_results) == 2
            assert provider.calls == 3
            assert app.conversation.messages()[-1].content == "done"

    asyncio.run(run())
