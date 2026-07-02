from __future__ import annotations

import asyncio
from pathlib import Path

from coco_code.agent import (
    AgentEventType,
    AgentLimits,
    AgentLoop,
    AgentMode,
    AgentRunRequest,
    AgentStopReason,
)
from coco_code.conversation import Conversation, ToolResultItem
from coco_code.llm import StreamEvent, StreamEventType
from coco_code.tools import ToolCall, ToolContext, ToolExecutor, create_default_registry


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
        events = (
            self.events_by_call[self.calls - 1] if self.calls <= len(self.events_by_call) else []
        )
        for event in events:
            yield event


def make_loop(provider: FakeProvider, conversation: Conversation, tmp_path: Path, **limits):
    registry = create_default_registry()

    async def confirm(call, spec):  # noqa: ARG001
        return True

    executor = ToolExecutor(registry, ToolContext(workspace=tmp_path), confirm)
    return AgentLoop(provider, conversation, registry, executor, AgentLimits(**limits))


async def collect(loop: AgentLoop, request: AgentRunRequest):
    return [event async for event in loop.run(request)]


def test_agent_loop_plain_conversation_streams_and_stops(tmp_path: Path) -> None:
    async def run() -> None:
        conversation = Conversation()
        provider = FakeProvider(
            [
                [
                    StreamEvent(type=StreamEventType.TEXT_DELTA, text="hi"),
                    StreamEvent(type=StreamEventType.DONE),
                ]
            ]
        )
        events = await collect(
            make_loop(provider, conversation, tmp_path),
            AgentRunRequest("hello", AgentMode.AGENT),
        )
        assert [event.type for event in events if event.type == AgentEventType.TEXT_DELTA]
        assert conversation.messages()[-1].content == "hi"
        assert events[-1].stop_reason == AgentStopReason.MODEL_DONE

    asyncio.run(run())


def test_agent_loop_runs_multi_turn_tool_chain(tmp_path: Path) -> None:
    async def run() -> None:
        (tmp_path / "a.txt").write_text("old", encoding="utf-8")
        conversation = Conversation()
        provider = FakeProvider(
            [
                [
                    StreamEvent(
                        type=StreamEventType.TOOL_CALL,
                        tool_call=ToolCall(
                            "1", "Glob", {"pattern": "*.txt"}, '{"pattern":"*.txt"}'
                        ),
                    )
                ],
                [
                    StreamEvent(
                        type=StreamEventType.TOOL_CALL,
                        tool_call=ToolCall("2", "ReadFile", {"path": "a.txt"}, '{"path":"a.txt"}'),
                    )
                ],
                [
                    StreamEvent(
                        type=StreamEventType.TOOL_CALL,
                        tool_call=ToolCall(
                            "3",
                            "EditFile",
                            {"path": "a.txt", "old_text": "old", "new_text": "new"},
                            "{}",
                        ),
                    )
                ],
                [
                    StreamEvent(type=StreamEventType.TEXT_DELTA, text="done"),
                    StreamEvent(type=StreamEventType.DONE),
                ],
            ]
        )
        events = await collect(
            make_loop(provider, conversation, tmp_path),
            AgentRunRequest("update", AgentMode.AGENT),
        )
        assert provider.calls == 4
        assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "new"
        assert sum(1 for item in conversation.items() if isinstance(item, ToolResultItem)) == 3
        assert events[-1].stop_reason == AgentStopReason.MODEL_DONE

    asyncio.run(run())


def test_agent_loop_iteration_limit_records_skipped_tool_result_without_executing(
    tmp_path: Path,
) -> None:
    async def run() -> None:
        conversation = Conversation()
        provider = FakeProvider(
            [
                [
                    StreamEvent(
                        type=StreamEventType.TOOL_CALL,
                        tool_call=ToolCall(
                            "1",
                            "WriteFile",
                            {"path": "created.txt", "content": "no"},
                            "{}",
                        ),
                    )
                ]
            ]
        )
        events = await collect(
            make_loop(provider, conversation, tmp_path, max_iterations=1),
            AgentRunRequest("loop", AgentMode.AGENT),
        )
        assert events[-1].stop_reason == AgentStopReason.ITERATION_LIMIT
        assert not (tmp_path / "created.txt").exists()
        tool_results = [
            item.result for item in conversation.items() if isinstance(item, ToolResultItem)
        ]
        assert len(tool_results) == 1
        assert tool_results[0].ok is False
        assert tool_results[0].tool_call_id == "1"
        assert tool_results[0].data == {"skipped": True, "reason": "iteration_limit"}

    asyncio.run(run())


def test_agent_loop_unknown_tool_limit_stops(tmp_path: Path) -> None:
    async def run() -> None:
        conversation = Conversation()
        provider = FakeProvider(
            [
                [
                    StreamEvent(
                        type=StreamEventType.TOOL_CALL, tool_call=ToolCall("1", "Missing", {}, "{}")
                    )
                ],
                [
                    StreamEvent(
                        type=StreamEventType.TOOL_CALL, tool_call=ToolCall("2", "Missing", {}, "{}")
                    )
                ],
            ]
        )
        events = await collect(
            make_loop(provider, conversation, tmp_path, unknown_tool_limit=2),
            AgentRunRequest("bad", AgentMode.AGENT),
        )
        assert events[-1].stop_reason == AgentStopReason.UNKNOWN_TOOL_LIMIT
        assert sum(1 for item in conversation.items() if isinstance(item, ToolResultItem)) == 2

    asyncio.run(run())


def test_agent_loop_stream_error_stops(tmp_path: Path) -> None:
    async def run() -> None:
        conversation = Conversation()
        provider = FakeProvider(
            [[StreamEvent(type=StreamEventType.ERROR, error=RuntimeError("boom"))]]
        )
        events = await collect(
            make_loop(provider, conversation, tmp_path),
            AgentRunRequest("fail", AgentMode.AGENT),
        )
        assert any(event.type == AgentEventType.ERROR for event in events)
        assert events[-1].stop_reason == AgentStopReason.STREAM_ERROR

    asyncio.run(run())


def test_plan_mode_rejects_write_file_without_executing(tmp_path: Path) -> None:
    async def run() -> None:
        conversation = Conversation()
        provider = FakeProvider(
            [
                [
                    StreamEvent(
                        type=StreamEventType.TOOL_CALL,
                        tool_call=ToolCall(
                            "1",
                            "WriteFile",
                            {"path": "no.txt", "content": "no"},
                            "{}",
                        ),
                    )
                ],
                [
                    StreamEvent(type=StreamEventType.TEXT_DELTA, text="planned"),
                    StreamEvent(type=StreamEventType.DONE),
                ],
            ]
        )
        events = await collect(
            make_loop(provider, conversation, tmp_path),
            AgentRunRequest("plan", AgentMode.PLAN),
        )
        assert not (tmp_path / "no.txt").exists()
        assert events[-1].stop_reason == AgentStopReason.MODEL_DONE
        result = next(
            item.result for item in conversation.items() if isinstance(item, ToolResultItem)
        )
        assert result.ok is False
        assert "不允许" in (result.error or "")

    asyncio.run(run())


def test_do_mode_uses_full_tool_registry(tmp_path: Path) -> None:
    async def run() -> None:
        conversation = Conversation()
        provider = FakeProvider([[StreamEvent(type=StreamEventType.DONE)]])
        await collect(
            make_loop(provider, conversation, tmp_path),
            AgentRunRequest("do", AgentMode.DO),
        )
        names = {spec.name for spec in provider.tools_seen[0].list_specs()}
        assert {"WriteFile", "EditFile", "Bash"}.issubset(names)

    asyncio.run(run())
