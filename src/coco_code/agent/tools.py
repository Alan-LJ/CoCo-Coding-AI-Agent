from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from time import monotonic

from coco_code.agent.types import AgentEvent, AgentEventType, AgentMode, ToolBatch
from coco_code.permission import Mode as PermissionMode
from coco_code.tools.base import ConfirmationPolicy, ToolCall, ToolResult, ToolSpec
from coco_code.tools.executor import ToolExecutor
from coco_code.tools.registry import ToolRegistry, ToolRegistryError

AgentEventCallback = Callable[[AgentEvent], Awaitable[None]]


def registry_for_mode(registry: ToolRegistry, mode: AgentMode) -> ToolRegistry:
    if mode in {AgentMode.AGENT, AgentMode.DO}:
        return registry
    return registry.filtered(lambda spec: is_tool_allowed_in_mode(spec, mode))


def validate_tool_allowed(
    call: ToolCall,
    registry: ToolRegistry,
    mode: AgentMode,
) -> ToolResult | None:
    started = monotonic()
    try:
        spec = registry.get(call.name).spec
    except ToolRegistryError:
        return _tool_error(call, f"Unknown tool: {call.name}", started)
    if not is_tool_allowed_in_mode(spec, mode):
        return _tool_error(
            call, f"Tool is not allowed in current mode: {spec.name}", started, spec.name
        )
    return None


def is_tool_allowed_in_mode(spec: ToolSpec, mode: AgentMode) -> bool:
    if mode in {AgentMode.AGENT, AgentMode.DO}:
        return True
    return spec.read_only and not spec.destructive and spec.confirmation == ConfirmationPolicy.NEVER


class ToolBatcher:
    def build_batches(
        self,
        calls: Sequence[ToolCall],
        registry: ToolRegistry,
        mode: AgentMode,
    ) -> list[ToolBatch]:
        batches: list[ToolBatch] = []
        current_read_batch: list[ToolCall] = []
        for call in calls:
            spec = registry.get(call.name).spec
            if is_tool_allowed_in_mode(spec, mode) and _can_run_concurrently(spec):
                current_read_batch.append(call)
                continue
            if current_read_batch:
                batches.append(ToolBatch(calls=tuple(current_read_batch), concurrent=True))
                current_read_batch = []
            batches.append(ToolBatch(calls=(call,), concurrent=False))
        if current_read_batch:
            batches.append(ToolBatch(calls=tuple(current_read_batch), concurrent=True))
        return batches


async def execute_tool_batches(
    batches: Sequence[ToolBatch],
    executor: ToolExecutor,
    on_event: AgentEventCallback,
    concurrency_limit: int,
    permission_mode: PermissionMode = PermissionMode.DEFAULT,
) -> list[ToolResult]:
    results: list[ToolResult] = []
    total = len(batches)
    for index, batch in enumerate(batches, start=1):
        await on_event(AgentEvent(type=AgentEventType.TOOL_BATCH_STARTED, tool_calls=batch.calls))
        if batch.concurrent:
            results.extend(
                await _execute_concurrent_batch(
                    batch.calls,
                    executor,
                    on_event,
                    concurrency_limit,
                    permission_mode,
                )
            )
        else:
            for call in batch.calls:
                results.append(
                    await _execute_one(call, executor, on_event, index, total, permission_mode)
                )
    return results


async def _execute_concurrent_batch(
    calls: Sequence[ToolCall],
    executor: ToolExecutor,
    on_event: AgentEventCallback,
    concurrency_limit: int,
    permission_mode: PermissionMode,
) -> list[ToolResult]:
    semaphore = asyncio.Semaphore(max(1, concurrency_limit))

    async def run(call: ToolCall) -> ToolResult:
        async with semaphore:
            return await _execute_one(call, executor, on_event, None, None, permission_mode)

    return list(await asyncio.gather(*(run(call) for call in calls)))


async def _execute_one(
    call: ToolCall,
    executor: ToolExecutor,
    on_event: AgentEventCallback,
    batch_index: int | None,
    batch_total: int | None,
    permission_mode: PermissionMode,
) -> ToolResult:
    await on_event(AgentEvent(type=AgentEventType.TOOL_STARTED, tool_call=call))
    return await executor.execute(call, permission_mode)


def _can_run_concurrently(spec: ToolSpec) -> bool:
    return spec.read_only and not spec.destructive and spec.confirmation == ConfirmationPolicy.NEVER


def _tool_error(
    call: ToolCall,
    message: str,
    started: float,
    tool_name: str | None = None,
) -> ToolResult:
    return ToolResult(
        tool_call_id=call.id,
        tool_name=tool_name or call.name,
        ok=False,
        summary=message,
        data={},
        error=message,
        elapsed_ms=int((monotonic() - started) * 1000),
    )
