from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from coco_code.agent.stream import collect_stream_turn
from coco_code.agent.tools import (
    ToolBatcher,
    execute_tool_batches,
    registry_for_mode,
    validate_tool_allowed,
)
from coco_code.agent.types import (
    AgentEvent,
    AgentEventType,
    AgentLimits,
    AgentProgress,
    AgentRunRequest,
    AgentStopReason,
    StreamTurnResult,
)
from coco_code.conversation import Conversation
from coco_code.llm import Provider
from coco_code.tools.base import ToolCall, ToolResult
from coco_code.tools.executor import ToolExecutor
from coco_code.tools.registry import ToolRegistry

type CollectQueueItem = AgentEvent | StreamTurnResult
type ExecuteQueueItem = AgentEvent | tuple[ToolResult, ...]


class AgentLoop:
    def __init__(
        self,
        provider: Provider,
        conversation: Conversation,
        registry: ToolRegistry,
        executor: ToolExecutor,
        limits: AgentLimits,
    ) -> None:
        self._provider = provider
        self._conversation = conversation
        self._registry = registry
        self._executor = executor
        self._limits = limits
        self._batcher = ToolBatcher()

    async def run(self, request: AgentRunRequest) -> AsyncIterator[AgentEvent]:
        self._conversation.add_user(request.text)
        yield AgentEvent(type=AgentEventType.MODE_CHANGED, mode=request.mode)
        unknown_count = 0
        active_registry = registry_for_mode(self._registry, request.mode)

        try:
            for iteration in range(1, self._limits.max_iterations + 1):
                yield self._progress(iteration, "waiting_model")
                result: StreamTurnResult | None = None
                async for item in self._collect_turn_stream(active_registry):
                    if isinstance(item, StreamTurnResult):
                        result = item
                    else:
                        yield item
                assert result is not None

                if result.reply:
                    self._conversation.add_assistant(result.reply)
                    yield AgentEvent(type=AgentEventType.ASSISTANT_MESSAGE, text=result.reply)

                if result.error is not None:
                    yield AgentEvent(type=AgentEventType.ERROR, error=result.error)
                    yield self._stopped(AgentStopReason.STREAM_ERROR)
                    return

                if not result.tool_calls:
                    yield self._stopped(AgentStopReason.MODEL_DONE)
                    return

                self._conversation.add_tool_calls(result.tool_calls)
                yield AgentEvent(type=AgentEventType.TOOL_CALLS, tool_calls=result.tool_calls)

                if iteration >= self._limits.max_iterations:
                    for skipped in self._iteration_limit_results(result.tool_calls):
                        self._conversation.add_tool_result(skipped)
                        yield AgentEvent(type=AgentEventType.TOOL_RESULT, tool_result=skipped)
                    yield self._stopped(AgentStopReason.ITERATION_LIMIT)
                    return

                invalid_results: dict[str, ToolResult] = {}
                valid_calls: list[ToolCall] = []
                for call in result.tool_calls:
                    invalid = validate_tool_allowed(call, self._registry, request.mode)
                    if invalid is None:
                        valid_calls.append(call)
                    else:
                        invalid_results[call.id] = invalid
                        unknown_count += 1

                if unknown_count >= self._limits.unknown_tool_limit:
                    for ordered in self._ordered_results(result.tool_calls, invalid_results, {}):
                        self._conversation.add_tool_result(ordered)
                        yield AgentEvent(type=AgentEventType.TOOL_RESULT, tool_result=ordered)
                    yield self._stopped(AgentStopReason.UNKNOWN_TOOL_LIMIT)
                    return
                if not invalid_results:
                    unknown_count = 0

                executed_results: dict[str, ToolResult] = {}
                if valid_calls:
                    yield self._progress(iteration, "executing_tools")
                    batches = self._batcher.build_batches(valid_calls, self._registry, request.mode)
                    async for exec_item in self._execute_batches_stream(batches):
                        if isinstance(exec_item, tuple):
                            executed_results = {
                                result.tool_call_id: result for result in exec_item
                            }
                        else:
                            yield exec_item

                for ordered in self._ordered_results(
                    result.tool_calls,
                    invalid_results,
                    executed_results,
                ):
                    self._conversation.add_tool_result(ordered)
                    yield AgentEvent(type=AgentEventType.TOOL_RESULT, tool_result=ordered)

            yield self._stopped(AgentStopReason.ITERATION_LIMIT)
        except asyncio.CancelledError:
            yield self._stopped(AgentStopReason.USER_CANCELLED)
            raise

    async def _collect_turn_stream(
        self,
        tools: ToolRegistry,
    ) -> AsyncIterator[CollectQueueItem]:
        queue: asyncio.Queue[CollectQueueItem] = asyncio.Queue()
        task = asyncio.create_task(self._collect_turn_task(tools, queue))
        try:
            while True:
                item = await queue.get()
                yield item
                if isinstance(item, StreamTurnResult):
                    await task
                    return
        except asyncio.CancelledError:
            task.cancel()
            raise

    async def _collect_turn_task(
        self,
        tools: ToolRegistry,
        queue: asyncio.Queue[CollectQueueItem],
    ) -> None:
        try:
            result = await asyncio.wait_for(
                collect_stream_turn(
                    self._provider,
                    self._conversation.items(),
                    tools,
                    self._queue_collect_event(queue),
                ),
                timeout=self._limits.response_timeout_seconds,
            )
        except TimeoutError:
            result = StreamTurnResult(
                reply="",
                error=TimeoutError("模型响应超时，已停止本轮操作。"),
            )
        except Exception as exc:
            result = StreamTurnResult(reply="", error=exc)
        await queue.put(result)

    def _queue_collect_event(self, queue: asyncio.Queue[CollectQueueItem]):
        async def on_event(event: AgentEvent) -> None:
            await queue.put(event)

        return on_event

    async def _execute_batches_stream(self, batches) -> AsyncIterator[ExecuteQueueItem]:
        queue: asyncio.Queue[ExecuteQueueItem] = asyncio.Queue()
        task = asyncio.create_task(self._execute_batches_task(batches, queue))
        try:
            while True:
                item = await queue.get()
                yield item
                if isinstance(item, tuple):
                    await task
                    return
        except asyncio.CancelledError:
            task.cancel()
            raise

    async def _execute_batches_task(
        self,
        batches,
        queue: asyncio.Queue[ExecuteQueueItem],
    ) -> None:
        results = await execute_tool_batches(
            batches,
            self._executor,
            self._queue_execute_event(queue),
            self._limits.read_tool_concurrency,
        )
        await queue.put(tuple(results))

    def _queue_execute_event(self, queue: asyncio.Queue[ExecuteQueueItem]):
        async def on_event(event: AgentEvent) -> None:
            await queue.put(event)

        return on_event

    def _progress(self, iteration: int, phase: str) -> AgentEvent:
        return AgentEvent(
            type=AgentEventType.PROGRESS,
            progress=AgentProgress(
                iteration=iteration,
                max_iterations=self._limits.max_iterations,
                phase=phase,
            ),
        )

    def _stopped(self, reason: AgentStopReason) -> AgentEvent:
        return AgentEvent(type=AgentEventType.STOPPED, stop_reason=reason)

    def _ordered_results(
        self,
        calls,
        invalid_results: dict[str, ToolResult],
        executed_results: dict[str, ToolResult],
    ) -> list[ToolResult]:
        results: list[ToolResult] = []
        for call in calls:
            result = invalid_results.get(call.id) or executed_results.get(call.id)
            if result is not None:
                results.append(result)
        return results

    def _iteration_limit_results(self, calls: tuple[ToolCall, ...]) -> list[ToolResult]:
        return [
            ToolResult(
                tool_call_id=call.id,
                tool_name=call.name,
                ok=False,
                summary="Tool was not executed because the agent reached the iteration limit.",
                data={"skipped": True, "reason": AgentStopReason.ITERATION_LIMIT.value},
                error="Tool call skipped: iteration limit reached.",
                elapsed_ms=0,
            )
            for call in calls
        ]
