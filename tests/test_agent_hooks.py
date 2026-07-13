from __future__ import annotations

import asyncio
from pathlib import Path

from coco_code.agent import AgentLimits, AgentLoop, AgentMode, AgentRunRequest
from coco_code.agent.runtime import new_session_runtime
from coco_code.agent.tools import execute_tool_batches
from coco_code.agent.types import AgentEventType, ToolBatch
from coco_code.conversation import Conversation
from coco_code.hook import DispatchResult, Event, HookEngine
from coco_code.hook.rule import HookAction, HookRule, PromptAction
from coco_code.llm import StreamEvent, StreamEventType
from coco_code.tools import ToolCall, ToolContext, ToolExecutor, ToolResult, create_default_registry


class PromptProvider:
    name = "fake"
    model = "fake-model"
    protocol = "openai"

    def __init__(self) -> None:
        self.system_prompts: list[str] = []

    def set_system_prompt(self, prompt: str) -> None:
        self.system_prompts.append(prompt)

    async def stream(self, messages, tools=None):  # noqa: ARG002
        yield StreamEvent(type=StreamEventType.DONE)


async def collect(loop: AgentLoop, request: AgentRunRequest):
    return [event async for event in loop.run(request)]


def test_session_runtime_hook_reminders_and_reset(tmp_path: Path) -> None:
    runtime = new_session_runtime(tmp_path)
    runtime.append_hook_reminders(["one", "", "two"])
    assert runtime.take_hook_reminders() == ["one", "two"]
    assert runtime.take_hook_reminders() == []
    runtime.append_hook_reminders(["again"])
    runtime.fired_hooks.add("once")
    runtime.reset_hook_state()
    assert runtime.pending_hook_reminders == []
    assert runtime.fired_hooks == set()


def test_agent_loop_pre_user_message_injects_hook_prompt(tmp_path: Path) -> None:
    async def run() -> None:
        provider = PromptProvider()
        conversation = Conversation()
        registry = create_default_registry()

        async def confirm(call, spec):  # noqa: ARG001
            return True

        executor = ToolExecutor(registry, ToolContext(workspace=tmp_path), confirm)
        hook_engine = HookEngine(
            [
                HookRule(
                    "remind",
                    Event.PRE_USER_MESSAGE,
                    HookAction("prompt", PromptAction("Use zh-CN")),
                )
            ],
            [],
        )
        loop = AgentLoop(
            provider,
            conversation,
            registry,
            executor,
            AgentLimits(),
            system_prompt_builder=lambda: "base prompt",
            hook_engine=hook_engine,
        )

        events = await collect(loop, AgentRunRequest("hello", AgentMode.AGENT))

        assert events[-1].type == AgentEventType.STOPPED
        assert provider.system_prompts
        assert "Hook Reminders" in provider.system_prompts[0]
        assert "Use zh-CN" in provider.system_prompts[0]
        assert loop._runtime.take_hook_reminders() == []

    asyncio.run(run())


def test_execute_tool_batches_pre_tool_hook_blocked_result() -> None:
    async def run() -> None:
        class FailingExecutor:
            async def execute(self, call, permission_mode):  # noqa: ARG002
                raise AssertionError("executor should not run")

        async def hook_dispatcher(event, payload):
            assert event == Event.PRE_TOOL_USE
            assert payload["tool_name"] == "WriteFile"
            return DispatchResult(blocked=True, reason="blocked", blocking_hook_name="guard")

        events = []

        async def on_event(event):
            events.append(event)

        results = await execute_tool_batches(
            [ToolBatch(calls=(ToolCall("1", "WriteFile", {"path": "x"}, "{}"),), concurrent=False)],
            FailingExecutor(),
            on_event,
            concurrency_limit=1,
            hook_dispatcher=hook_dispatcher,
        )
        assert results[0].ok is False
        assert results[0].data["hook_blocked"] is True
        assert "[hook guard] blocked" in (results[0].error or "")
        assert any(event.type == AgentEventType.TOOL_STARTED for event in events)

    asyncio.run(run())


def test_execute_tool_batches_post_tool_hook_runs() -> None:
    async def run() -> None:
        seen = []

        class Executor:
            async def execute(self, call, permission_mode):  # noqa: ARG002
                return ToolResult(call.id, call.name, True, "ok", {}, None, 0)

        async def hook_dispatcher(event, payload):
            seen.append((event, payload))
            return DispatchResult()

        async def on_event(event):  # noqa: ARG001
            return None

        await execute_tool_batches(
            [ToolBatch(calls=(ToolCall("1", "ReadFile", {"path": "x"}, "{}"),), concurrent=False)],
            Executor(),
            on_event,
            concurrency_limit=1,
            hook_dispatcher=hook_dispatcher,
        )
        assert [event for event, _payload in seen] == [Event.PRE_TOOL_USE, Event.POST_TOOL_USE]
        assert seen[1][1]["tool_result"] == "ok"
        assert seen[1][1]["is_error"] is False

    asyncio.run(run())
