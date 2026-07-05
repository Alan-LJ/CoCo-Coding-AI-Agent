from __future__ import annotations

import asyncio
from pathlib import Path

from coco_code.compact.layer1 import build_preview_result, offload_and_snip, spill_single
from coco_code.compact.manager import ManageInput, TriggerKind, manage_context
from coco_code.compact.recovery import RecoveryState, build_recovery_attachment
from coco_code.compact.state import (
    CompactCircuitBreaker,
    ContentReplacementState,
    ReplacementDecision,
    new_session_context,
)
from coco_code.compact.summary_prompt import SUMMARY_SECTIONS, build_summary_prompt, extract_summary
from coco_code.compact.token import estimate_tokens, usage_anchor
from coco_code.conversation import ChatMessage, Conversation, ToolResultItem
from coco_code.llm import StreamEvent, StreamEventType
from coco_code.tools import ToolCall, ToolResult, create_default_registry


def make_result(call_id: str, content: str, tool_name: str = "ReadFile") -> ToolResult:
    return ToolResult(
        tool_call_id=call_id,
        tool_name=tool_name,
        ok=True,
        summary="ok",
        data={"content": content},
        error=None,
        elapsed_ms=1,
    )


def summary_response() -> str:
    body = "\n".join(f"{section}\n内容" for section in SUMMARY_SECTIONS)
    return f"<analysis>草稿</analysis><summary>{body}</summary>"


class FakeSummaryProvider:
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
        yield StreamEvent(type=StreamEventType.TEXT_DELTA, text=summary_response())
        yield StreamEvent(type=StreamEventType.DONE)


def test_session_context_creates_spill_dir(tmp_path: Path) -> None:
    session = new_session_context(tmp_path)
    assert session.spill_dir.exists()
    assert session.spill_dir.name == "tool-results"
    assert len(session.session_id.split("-")) == 3


def test_replacement_state_and_circuit_breaker() -> None:
    async def run() -> None:
        state = ContentReplacementState()
        original = make_result("1", "small")
        kept = await state.decide_once("1", original, lambda: ReplacementDecision("kept"))
        assert kept is original
        replacement = make_result("2", "preview")
        first = await state.decide_once(
            "2", original, lambda: ReplacementDecision("replaced", replacement)
        )
        second = await state.decide_once("2", original, lambda: ReplacementDecision("kept"))
        assert first == replacement
        assert second == replacement
        skipped = await state.decide_once("3", original, lambda: ReplacementDecision("skip"))
        assert skipped is original
        breaker = CompactCircuitBreaker()
        await breaker.record_failure()
        await breaker.record_failure()
        assert not await breaker.tripped()
        await breaker.record_failure()
        assert await breaker.tripped()
        await breaker.record_success()
        assert not await breaker.tripped()

    asyncio.run(run())


def test_token_estimator_and_usage_anchor() -> None:
    conv = Conversation()
    conv.add_user("a" * 350)
    assert estimate_tokens(5000, conv.items(), 0) == 5100
    assert (
        usage_anchor({"input_tokens": 10, "output_tokens": 5, "cache_read": 2, "cache_write": 3})
        == 20
    )


def test_layer1_spills_large_result_and_is_idempotent(tmp_path: Path) -> None:
    async def run() -> None:
        session = new_session_context(tmp_path)
        state = ContentReplacementState()
        conv = Conversation()
        call = ToolCall("call-1", "ReadFile", {"path": "a.txt"}, '{"path":"a.txt"}')
        conv.add_tool_call(call)
        conv.add_tool_result(make_result("call-1", "x" * 60_000))
        first, count = await offload_and_snip(conv.items(), state, session)
        second, count2 = await offload_and_snip(first, state, session)
        assert count == 1
        assert count2 == 0
        result = next(item.result for item in first if isinstance(item, ToolResultItem))
        assert result.truncated is True
        assert result.tool_call_id == "call-1"
        assert "original size:" in result.summary
        assert "文件读取工具" in result.summary
        assert Path(result.data["path"]).exists()
        assert first == second

    asyncio.run(run())


def test_preview_limits_head(tmp_path: Path) -> None:
    async def run() -> None:
        session = new_session_context(tmp_path)
        result = make_result("preview", "\n".join(str(i) * 200 for i in range(100)))
        path = await spill_single(session, result)
        preview = build_preview_result(result, 100_000, path)
        head = preview.data["head preview"]
        assert head.count("\n") < 20
        assert len(head.encode("utf-8")) <= 2048

    asyncio.run(run())


def test_summary_prompt_extracts_only_summary() -> None:
    prompt = build_summary_prompt([ChatMessage("user", "hi")])
    content = prompt[0].content
    assert "禁止调用任何工具" in content
    assert "<analysis>" in content
    assert all(section in content for section in SUMMARY_SECTIONS)
    assert extract_summary("noise" + summary_response() + "tail").startswith(SUMMARY_SECTIONS[0])


def test_recovery_attachment_renders_recent_files_and_tools(tmp_path: Path) -> None:
    async def run() -> None:
        recovery = RecoveryState()
        for index in range(7):
            await recovery.record_file(tmp_path / f"f{index}.txt", f"content {index}")
        text = await build_recovery_attachment(recovery, create_default_registry())
        assert "最近读过的文件" in text
        assert "当前可用工具" in text
        assert "边界提示" in text
        assert "ReadFile" in text
        assert "f6.txt" in text
        assert "f0.txt" not in text

    asyncio.run(run())


def test_manager_auto_threshold_and_manual_force(tmp_path: Path) -> None:
    async def run() -> None:
        provider = FakeSummaryProvider()
        conv = Conversation()
        conv.add_user("hello")
        runtime = __import__("coco_code.agent.runtime").agent.runtime.new_session_runtime(
            tmp_path, context_window=200_000
        )
        tools = create_default_registry()
        output = await manage_context(
            ManageInput(conv, provider, tools, runtime, TriggerKind.AUTO, estimated_tokens=10)
        )
        assert output.compacted is False
        assert provider.calls == 0
        output = await manage_context(
            ManageInput(conv, provider, tools, runtime, TriggerKind.MANUAL, estimated_tokens=10)
        )
        assert output.compacted is True
        assert provider.calls == 1
        assert provider.tools_seen == [None]
        assert len(conv.items()) >= 2

    asyncio.run(run())
