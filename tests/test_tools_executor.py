from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from coco_code.tools import ConfirmationPolicy, ToolCall, ToolContext, ToolExecutor, ToolSpec
from coco_code.tools.base import ToolParams, ToolResult
from coco_code.tools.registry import ToolRegistry, create_default_registry


class FakeTool:
    def __init__(
        self,
        *,
        name: str = "fake",
        confirmation: ConfirmationPolicy = ConfirmationPolicy.NEVER,
        delay: float = 0,
        fail: bool = False,
        cancel: bool = False,
        spec_timeout_seconds: float | None = None,
    ) -> None:
        self.ran = False
        self._name = name
        self._confirmation = confirmation
        self._delay = delay
        self._fail = fail
        self._cancel = cancel
        self._spec_timeout_seconds = spec_timeout_seconds

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self._name,
            description="fake",
            parameters_schema={
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
            confirmation=self._confirmation,
            timeout_seconds=self._spec_timeout_seconds,
        )

    async def run(self, params: ToolParams, context: ToolContext) -> ToolResult:  # noqa: ARG002
        self.ran = True
        if self._cancel:
            raise asyncio.CancelledError
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._fail:
            raise RuntimeError("boom")
        return ToolResult("", self._name, True, "ok", {"params": params}, None, 0)


def executor_for(
    tool: FakeTool,
    *,
    approved: bool = True,
    timeout_seconds: float = 1,
    confirm_timeout_seconds: float = 1,
):
    registry = ToolRegistry()
    registry.register(tool)

    async def confirm(call: ToolCall, spec: ToolSpec) -> bool:  # noqa: ARG001
        return approved

    return ToolExecutor(
        registry,
        ToolContext(
            workspace=Path.cwd(),
            timeout_seconds=timeout_seconds,
            confirm_timeout_seconds=confirm_timeout_seconds,
        ),
        confirm,
    )


def test_executor_runs_tool_without_confirmation() -> None:
    tool = FakeTool()
    result = asyncio.run(executor_for(tool).execute(ToolCall("1", "fake", {}, "{}")))
    assert result.ok is True
    assert result.tool_call_id == "1"
    assert tool.ran is True


def test_executor_waits_for_required_confirmation() -> None:
    tool = FakeTool(confirmation=ConfirmationPolicy.REQUIRED)
    result = asyncio.run(executor_for(tool, approved=True).execute(ToolCall("1", "fake", {}, "{}")))
    assert result.ok is True
    assert tool.ran is True


def test_executor_returns_rejected_result_without_running_tool() -> None:
    tool = FakeTool(confirmation=ConfirmationPolicy.REQUIRED)
    result = asyncio.run(
        executor_for(tool, approved=False).execute(ToolCall("1", "fake", {}, "{}"))
    )
    assert result.ok is False
    assert result.data["rejected"] is True
    assert tool.ran is False


def test_executor_times_out_confirmation_without_running_tool() -> None:
    tool = FakeTool(confirmation=ConfirmationPolicy.REQUIRED)
    registry = ToolRegistry()
    registry.register(tool)

    async def confirm(call: ToolCall, spec: ToolSpec) -> bool:  # noqa: ARG001
        await asyncio.sleep(1)
        return True

    executor = ToolExecutor(
        registry,
        ToolContext(workspace=Path.cwd(), confirm_timeout_seconds=0.01),
        confirm,
    )
    result = asyncio.run(executor.execute(ToolCall("1", "fake", {}, "{}")))
    assert result.ok is False
    assert "confirmation timed out" in (result.error or "").casefold()
    assert tool.ran is False


def test_executor_returns_confirmation_error_without_running_tool() -> None:
    tool = FakeTool(confirmation=ConfirmationPolicy.REQUIRED)
    registry = ToolRegistry()
    registry.register(tool)

    async def confirm(call: ToolCall, spec: ToolSpec) -> bool:  # noqa: ARG001
        raise RuntimeError("confirm failed")

    executor = ToolExecutor(registry, ToolContext(workspace=Path.cwd()), confirm)
    result = asyncio.run(executor.execute(ToolCall("1", "fake", {}, "{}")))
    assert result.ok is False
    assert "confirmation failed" in (result.error or "").casefold()
    assert tool.ran is False


def test_executor_wraps_unknown_tool_and_exceptions() -> None:
    registry = ToolRegistry()

    async def confirm(call: ToolCall, spec: ToolSpec) -> bool:  # noqa: ARG001
        return True

    executor = ToolExecutor(
        registry,
        ToolContext(workspace=Path.cwd()),
        confirm,
    )
    unknown = asyncio.run(executor.execute(ToolCall("1", "missing", {}, "{}")))
    assert unknown.ok is False

    failing = FakeTool(fail=True)
    failed = asyncio.run(executor_for(failing).execute(ToolCall("2", "fake", {}, "{}")))
    assert failed.ok is False
    assert "boom" in (failed.error or "")


def test_executor_rejects_parameters_that_do_not_match_schema() -> None:
    tool = FakeTool()
    result = asyncio.run(
        executor_for(tool).execute(ToolCall("1", "fake", {"extra": 1}, '{"extra":1}'))
    )
    assert result.ok is False
    assert "unknown fields" in (result.error or "").casefold()
    assert tool.ran is False


def test_executor_rejects_missing_required_parameters() -> None:
    registry = create_default_registry()

    async def confirm(call: ToolCall, spec: ToolSpec) -> bool:  # noqa: ARG001
        return True

    executor = ToolExecutor(registry, ToolContext(workspace=Path.cwd()), confirm)
    result = asyncio.run(executor.execute(ToolCall("1", "ReadFile", {}, "{}")))
    assert result.ok is False
    assert "missing required" in (result.error or "").casefold()


def test_executor_times_out_tool() -> None:
    tool = FakeTool(delay=1)
    result = asyncio.run(
        executor_for(tool, timeout_seconds=0.01).execute(ToolCall("1", "fake", {}, "{}"))
    )
    assert result.ok is False
    assert "execution timed out" in (result.error or "").casefold()


def test_executor_uses_tool_specific_timeout_over_context_timeout() -> None:
    tool = FakeTool(delay=0.05, spec_timeout_seconds=0.2)
    result = asyncio.run(
        executor_for(tool, timeout_seconds=0.01).execute(ToolCall("1", "fake", {}, "{}"))
    )
    assert result.ok is True


def test_executor_propagates_cancelled_error() -> None:
    tool = FakeTool(cancel=True)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(executor_for(tool).execute(ToolCall("1", "fake", {}, "{}")))
