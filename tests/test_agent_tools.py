from __future__ import annotations

import asyncio
from pathlib import Path
from time import monotonic

from coco_code.agent import AgentEventType, AgentMode
from coco_code.agent.tools import (
    ToolBatcher,
    execute_tool_batches,
    registry_for_mode,
    validate_tool_allowed,
)
from coco_code.tools import ToolCall, ToolContext, ToolExecutor, create_default_registry


def test_plan_mode_filters_to_read_only_safe_tools() -> None:
    registry = create_default_registry()
    plan_registry = registry_for_mode(registry, AgentMode.PLAN)
    names = {spec.name for spec in plan_registry.list_specs()}
    assert names == {"ReadFile", "Glob", "Grep"}
    assert registry_for_mode(registry, AgentMode.DO) is registry


def test_plan_mode_rejects_disallowed_tool() -> None:
    registry = create_default_registry()
    result = validate_tool_allowed(
        ToolCall("1", "WriteFile", {"path": "a.txt", "content": "x"}, "{}"),
        registry,
        AgentMode.PLAN,
    )
    assert result is not None
    assert result.ok is False
    assert "不允许" in (result.error or "")


def test_tool_batcher_groups_read_only_and_serializes_side_effects() -> None:
    registry = create_default_registry()
    calls = [
        ToolCall("1", "Glob", {"pattern": "**/*.py"}, "{}"),
        ToolCall("2", "Grep", {"pattern": "Agent"}, "{}"),
        ToolCall("3", "EditFile", {"path": "a", "old_text": "x", "new_text": "y"}, "{}"),
        ToolCall("4", "Bash", {"command": "echo ok"}, "{}"),
    ]
    batches = ToolBatcher().build_batches(calls, registry, AgentMode.AGENT)
    assert [batch.concurrent for batch in batches] == [True, False, False]
    assert [call.name for call in batches[0].calls] == ["Glob", "Grep"]
    assert [batch.calls[0].name for batch in batches[1:]] == ["EditFile", "Bash"]


class DelayTool:
    def __init__(self, name: str, delay: float) -> None:
        from coco_code.tools import ConfirmationPolicy, ToolSpec

        self.name = name
        self.delay = delay
        self.started = 0.0
        self.finished = 0.0
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
            destructive=False,
        )

    @property
    def spec(self):
        return self._spec

    async def run(self, params, context):  # noqa: ARG002
        from coco_code.tools import ToolResult

        self.started = monotonic()
        await asyncio.sleep(self.delay)
        self.finished = monotonic()
        return ToolResult("", self.name, True, self.name, {}, None, 0)


def test_execute_tool_batches_runs_read_only_concurrently_and_returns_order(tmp_path: Path) -> None:
    from coco_code.tools.registry import ToolRegistry

    async def run() -> None:
        first = DelayTool("First", 0.05)
        second = DelayTool("Second", 0.05)
        registry = ToolRegistry()
        registry.register(first)
        registry.register(second)

        async def confirm(call, spec):  # noqa: ARG001
            return True

        executor = ToolExecutor(registry, ToolContext(workspace=tmp_path), confirm)
        calls = [ToolCall("1", "First", {}, "{}"), ToolCall("2", "Second", {}, "{}")]
        batches = ToolBatcher().build_batches(calls, registry, AgentMode.AGENT)
        events = []

        async def on_event(event):
            events.append(event)

        results = await execute_tool_batches(batches, executor, on_event, concurrency_limit=2)
        assert [result.tool_name for result in results] == ["First", "Second"]
        assert first.started < second.finished
        assert second.started < first.finished
        assert any(event.type == AgentEventType.TOOL_BATCH_STARTED for event in events)

    asyncio.run(run())
