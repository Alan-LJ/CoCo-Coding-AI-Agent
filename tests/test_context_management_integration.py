from __future__ import annotations

import asyncio
from pathlib import Path

from coco_code.agent import AgentEventType, AgentLimits, AgentLoop, AgentMode, AgentRunRequest
from coco_code.agent.runtime import new_session_runtime
from coco_code.agent.stream import collect_stream_turn
from coco_code.agent.types import CompactPhase
from coco_code.config import ProviderConfig, effective_context_window
from coco_code.conversation import Conversation
from coco_code.llm import PromptTooLongError, StreamEvent, StreamEventType
from coco_code.tools import ToolContext, ToolExecutor, create_default_registry
from coco_code.tui.commands import format_compact_notice

SUMMARY = (
    "<analysis>draft</analysis><summary>"
    + "\n".join(
        [
            "1. 主要请求和意图\n内容",
            "2. 关键技术概念\n内容",
            "3. 文件和代码段\n内容",
            "4. 错误和修复\n内容",
            "5. 问题解决过程\n内容",
            "6. 所有用户消息原文\nhello",
            "7. 待办任务\n内容",
            "8. 当前工作\n内容",
            "9. 可能的下一步\n内容",
        ]
    )
    + "</summary>"
)


class ScriptProvider:
    name = "fake"
    model = "fake-model"
    protocol = "openai"

    def __init__(self, scripts: list[list[StreamEvent]]) -> None:
        self.scripts = scripts
        self.calls = 0
        self.tools_seen = []
        self.messages_seen = []

    async def stream(self, messages, tools=None):
        self.calls += 1
        self.messages_seen.append(messages)
        self.tools_seen.append(tools)
        events = self.scripts[self.calls - 1] if self.calls <= len(self.scripts) else []
        for event in events:
            yield event


def make_loop(provider: ScriptProvider, conversation: Conversation, tmp_path: Path, runtime=None):
    registry = create_default_registry()

    async def confirm(call, spec):  # noqa: ARG001
        return True

    executor = ToolExecutor(registry, ToolContext(workspace=tmp_path), confirm)
    return AgentLoop(
        provider,
        conversation,
        registry,
        executor,
        AgentLimits(max_iterations=2),
        runtime=runtime,
    )


def test_effective_context_window_defaults_and_override() -> None:
    assert effective_context_window(ProviderConfig("a", "anthropic", "m")) == 200_000
    assert effective_context_window(ProviderConfig("o", "openai", "m")) == 128_000
    assert effective_context_window(ProviderConfig("c", "openai-compat", "m")) == 128_000
    provider = ProviderConfig("x", "anthropic", "m", context_window=80_000)
    assert effective_context_window(provider) == 80_000


def test_collect_stream_turn_returns_last_usage() -> None:
    async def run() -> None:
        provider = ScriptProvider(
            [
                [
                    StreamEvent(type="usage", usage={"input_tokens": 7, "output_tokens": 3}),
                    StreamEvent(type=StreamEventType.TEXT_DELTA, text="ok"),
                    StreamEvent(type=StreamEventType.DONE),
                ]
            ]
        )
        seen = []

        async def on_event(event):
            seen.append(event)

        result = await collect_stream_turn(provider, [], None, on_event)
        assert result.reply == "ok"
        assert result.usage == {"input_tokens": 7, "output_tokens": 3}
        assert any(event.type == AgentEventType.USAGE for event in seen)

    asyncio.run(run())


def test_agent_emits_auto_compact_events_and_updates_usage(tmp_path: Path) -> None:
    async def run() -> None:
        conversation = Conversation()
        runtime = new_session_runtime(tmp_path, context_window=20_000)
        provider = ScriptProvider(
            [
                [
                    StreamEvent(type=StreamEventType.TEXT_DELTA, text=SUMMARY),
                    StreamEvent(type=StreamEventType.DONE),
                ],
                [
                    StreamEvent(type="usage", usage={"input_tokens": 11, "output_tokens": 5}),
                    StreamEvent(type=StreamEventType.TEXT_DELTA, text="done"),
                    StreamEvent(type=StreamEventType.DONE),
                ],
            ]
        )
        loop = make_loop(provider, conversation, tmp_path, runtime)
        events = [event async for event in loop.run(AgentRunRequest("hello", AgentMode.AGENT))]
        phases = [event.compact.phase for event in events if event.compact is not None]
        assert phases == [CompactPhase.BEFORE_AUTO, CompactPhase.AFTER_AUTO]
        assert runtime.usage_anchor == 16
        assert events[-1].type == AgentEventType.STOPPED

    asyncio.run(run())


def test_agent_emergency_compact_retries_once(tmp_path: Path) -> None:
    async def run() -> None:
        conversation = Conversation()
        runtime = new_session_runtime(tmp_path, context_window=200_000)
        provider = ScriptProvider(
            [
                [StreamEvent(type=StreamEventType.ERROR, error=PromptTooLongError("too long"))],
                [
                    StreamEvent(type=StreamEventType.TEXT_DELTA, text=SUMMARY),
                    StreamEvent(type=StreamEventType.DONE),
                ],
                [
                    StreamEvent(type=StreamEventType.TEXT_DELTA, text="ok"),
                    StreamEvent(type=StreamEventType.DONE),
                ],
            ]
        )
        loop = make_loop(provider, conversation, tmp_path, runtime)
        events = [event async for event in loop.run(AgentRunRequest("hello", AgentMode.AGENT))]
        phases = [event.compact.phase for event in events if event.compact is not None]
        assert phases == [CompactPhase.BEFORE_EMERGENCY, CompactPhase.AFTER_EMERGENCY]
        assert provider.calls == 3
        assert events[-1].type == AgentEventType.STOPPED

    asyncio.run(run())


def test_format_compact_notice_for_done_event() -> None:
    from coco_code.agent import CompactEvent

    text = format_compact_notice(
        CompactEvent(phase=CompactPhase.AFTER_AUTO, before_tokens=120, after_tokens=40)
    )
    assert "120" in text
    assert "40" in text
