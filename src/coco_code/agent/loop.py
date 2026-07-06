from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from pathlib import Path

from coco_code.agent.runtime import SessionRuntime, new_session_runtime
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
    AgentMode,
    AgentProgress,
    AgentRunRequest,
    AgentStopReason,
    CompactEvent,
    CompactPhase,
    StreamTurnResult,
)
from coco_code.compact.manager import (
    ManageInput,
    ManageOutput,
    TriggerKind,
    auto_threshold,
    manage_context,
    manual_threshold,
)
from coco_code.compact.token import estimate_tokens, usage_anchor
from coco_code.conversation import ChatMessage, Conversation, ConversationItem
from coco_code.llm import PromptTooLongError, Provider
from coco_code.memory import MemoryManager
from coco_code.permission import Mode as PermissionMode
from coco_code.tools.base import ToolCall, ToolResult
from coco_code.tools.executor import ToolExecutor
from coco_code.tools.registry import ToolRegistry

type CollectQueueItem = AgentEvent | StreamTurnResult
type ExecuteQueueItem = AgentEvent | tuple[ToolResult, ...]
type SystemPromptBuilder = Callable[[], str]


class AgentLoop:
    def __init__(
        self,
        provider: Provider,
        conversation: Conversation,
        registry: ToolRegistry,
        executor: ToolExecutor,
        limits: AgentLimits,
        runtime: SessionRuntime | None = None,
        memory_manager: MemoryManager | None = None,
        system_prompt_builder: SystemPromptBuilder | None = None,
    ) -> None:
        self._provider = provider
        self._conversation = conversation
        self._registry = registry
        self._executor = executor
        self._limits = limits
        self._batcher = ToolBatcher()
        self._workspace = _workspace_from_executor(executor)
        self._memory_manager = memory_manager
        self._system_prompt_builder = system_prompt_builder
        self._runtime = runtime or new_session_runtime(
            self._workspace,
            _default_context_window(provider.protocol),
        )
        if self._runtime.context_window <= 0:
            self._runtime.context_window = _default_context_window(provider.protocol)

    async def run(self, request: AgentRunRequest) -> AsyncIterator[AgentEvent]:
        async with self._runtime.lock:
            async for event in self._run_locked(request):
                yield event

    async def _run_locked(self, request: AgentRunRequest) -> AsyncIterator[AgentEvent]:
        permission_mode = request.permission_mode or _permission_mode_for_agent_mode(request.mode)
        effective_mode = _effective_agent_mode(request.mode, permission_mode)
        turn_start_index = len(self._conversation.items())
        self._conversation.add_user(request.text)
        yield AgentEvent(
            type=AgentEventType.MODE_CHANGED,
            mode=effective_mode,
            permission_mode=permission_mode,
        )
        unknown_count = 0

        try:
            for iteration in range(1, self._limits.max_iterations + 1):
                active_base_registry = self._active_base_registry()
                active_registry = registry_for_mode(active_base_registry, effective_mode)
                self._refresh_system_prompt()
                yield self._progress(iteration, "waiting_model")
                async for compact_event in self._auto_manage_context(active_registry):
                    yield compact_event

                result: StreamTurnResult | None = None
                async for collect_item in self._collect_with_emergency_retry(active_registry):
                    if isinstance(collect_item, StreamTurnResult):
                        result = collect_item
                    else:
                        yield collect_item
                assert result is not None

                if result.error is not None:
                    yield AgentEvent(type=AgentEventType.ERROR, error=result.error)
                    yield self._stopped(AgentStopReason.STREAM_ERROR)
                    return

                if result.usage is not None:
                    self._runtime.usage_anchor = usage_anchor(result.usage)
                    self._runtime.anchor_item_len = len(self._conversation.items())

                if result.reply:
                    self._conversation.add_assistant(result.reply)
                    yield AgentEvent(type=AgentEventType.ASSISTANT_MESSAGE, text=result.reply)

                if not result.tool_calls:
                    self._schedule_memory_update(turn_start_index)
                    yield self._stopped(AgentStopReason.MODEL_DONE)
                    return

                self._conversation.add_tool_calls(result.tool_calls)
                yield AgentEvent(type=AgentEventType.TOOL_CALLS, tool_calls=result.tool_calls)

                if iteration >= self._limits.max_iterations:
                    for skipped in self._iteration_limit_results(result.tool_calls):
                        await self._record_recovery_if_read_file(skipped, None)
                        self._conversation.add_tool_result(skipped)
                        yield AgentEvent(type=AgentEventType.TOOL_RESULT, tool_result=skipped)
                    yield self._stopped(AgentStopReason.ITERATION_LIMIT)
                    return

                invalid_results: dict[str, ToolResult] = {}
                valid_calls: list[ToolCall] = []
                for call in result.tool_calls:
                    invalid = validate_tool_allowed(call, active_base_registry, effective_mode)
                    if invalid is None:
                        valid_calls.append(call)
                    else:
                        invalid_results[call.id] = invalid
                        unknown_count += 1

                if unknown_count >= self._limits.unknown_tool_limit:
                    call_by_id = {call.id: call for call in result.tool_calls}
                    for ordered in self._ordered_results(result.tool_calls, invalid_results, {}):
                        await self._record_recovery_if_read_file(
                            ordered,
                            call_by_id.get(ordered.tool_call_id),
                        )
                        self._conversation.add_tool_result(ordered)
                        yield AgentEvent(type=AgentEventType.TOOL_RESULT, tool_result=ordered)
                    yield self._stopped(AgentStopReason.UNKNOWN_TOOL_LIMIT)
                    return
                if not invalid_results:
                    unknown_count = 0

                executed_results: dict[str, ToolResult] = {}
                if valid_calls:
                    yield self._progress(iteration, "executing_tools")
                    batches = self._batcher.build_batches(
                        valid_calls, active_registry, effective_mode
                    )
                    async for exec_item in self._execute_batches_stream(batches, permission_mode):
                        if isinstance(exec_item, tuple):
                            executed_results = {result.tool_call_id: result for result in exec_item}
                        else:
                            yield exec_item

                call_by_id = {call.id: call for call in result.tool_calls}
                for ordered in self._ordered_results(
                    result.tool_calls,
                    invalid_results,
                    executed_results,
                ):
                    await self._record_recovery_if_read_file(
                        ordered,
                        call_by_id.get(ordered.tool_call_id),
                    )
                    self._conversation.add_tool_result(ordered)
                    yield AgentEvent(type=AgentEventType.TOOL_RESULT, tool_result=ordered)

            yield self._stopped(AgentStopReason.ITERATION_LIMIT)
        except asyncio.CancelledError:
            yield self._stopped(AgentStopReason.USER_CANCELLED)
            raise

    async def run_force_compact(self, mode: AgentMode | None = None) -> ManageOutput:
        async with self._runtime.lock:
            self._refresh_system_prompt()
            active_registry = self._effective_registry(mode or AgentMode.AGENT)
            estimated = self._estimate_tokens()
            return await manage_context(
                ManageInput(
                    conversation=self._conversation,
                    provider=self._provider,
                    tools=active_registry,
                    runtime=self._runtime,
                    trigger=TriggerKind.MANUAL,
                    estimated_tokens=estimated,
                )
            )

    async def _auto_manage_context(
        self, active_registry: ToolRegistry
    ) -> AsyncIterator[AgentEvent]:
        estimated = self._estimate_tokens()
        will_try_summary = (
            estimated >= auto_threshold(self._runtime.context_window)
            and not await self._runtime.circuit_breaker.tripped()
        )
        if will_try_summary:
            yield self._compact_event(CompactPhase.BEFORE_AUTO, estimated, estimated)
        try:
            output = await manage_context(
                ManageInput(
                    conversation=self._conversation,
                    provider=self._provider,
                    tools=active_registry,
                    runtime=self._runtime,
                    trigger=TriggerKind.AUTO,
                    estimated_tokens=estimated,
                )
            )
        except Exception as exc:
            if will_try_summary:
                yield self._compact_event(
                    CompactPhase.AFTER_AUTO,
                    estimated,
                    self._estimate_tokens(),
                    error=exc,
                )
            return
        if will_try_summary and output.compacted:
            yield self._compact_event(
                CompactPhase.AFTER_AUTO,
                output.before_tokens,
                output.after_tokens,
                offloaded_results=output.offloaded_results,
            )

    async def _collect_with_emergency_retry(
        self,
        active_registry: ToolRegistry,
    ) -> AsyncIterator[CollectQueueItem]:
        emergency_retried = False
        while True:
            result: StreamTurnResult | None = None
            async for item in self._collect_turn_stream(active_registry):
                if isinstance(item, StreamTurnResult):
                    result = item
                else:
                    yield item
            assert result is not None
            if not isinstance(result.error, PromptTooLongError):
                yield result
                return
            if emergency_retried:
                yield result
                return

            emergency_retried = True
            before = self._estimate_tokens()
            yield self._compact_event(CompactPhase.BEFORE_EMERGENCY, before, before)
            try:
                output = await manage_context(
                    ManageInput(
                        conversation=self._conversation,
                        provider=self._provider,
                        tools=active_registry,
                        runtime=self._runtime,
                        trigger=TriggerKind.EMERGENCY,
                        estimated_tokens=before,
                    )
                )
            except Exception as exc:
                yield self._compact_event(
                    CompactPhase.AFTER_EMERGENCY,
                    before,
                    self._estimate_tokens(),
                    error=exc,
                )
                yield StreamTurnResult(reply="", error=exc)
                return
            self._runtime.usage_anchor = 0
            self._runtime.anchor_item_len = 0
            after = self._estimate_tokens()
            yield self._compact_event(
                CompactPhase.AFTER_EMERGENCY,
                output.before_tokens,
                after,
                offloaded_results=output.offloaded_results,
            )
            if after >= manual_threshold(self._runtime.context_window):
                yield result
                return

    async def _collect_turn_stream(self, tools: ToolRegistry) -> AsyncIterator[CollectQueueItem]:
        queue: asyncio.Queue[CollectQueueItem] = asyncio.Queue()
        task = asyncio.create_task(self._collect_turn_task(tools, queue))
        self._runtime.track_turn_task(task)
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
        stream_task = asyncio.create_task(
            collect_stream_turn(
                self._provider,
                self._conversation.items(),
                tools,
                self._queue_collect_event(queue),
            )
        )
        self._runtime.track_turn_task(stream_task)
        try:
            done, _ = await asyncio.wait(
                {stream_task}, timeout=self._limits.response_timeout_seconds
            )
            if stream_task not in done:
                stream_task.cancel()
                result = StreamTurnResult(
                    reply="",
                    error=TimeoutError("Model response timed out; this turn was stopped."),
                )
            else:
                result = await stream_task
        except asyncio.CancelledError:
            stream_task.cancel()
            raise
        except Exception as exc:
            result = StreamTurnResult(reply="", error=exc)
        await queue.put(result)

    def _queue_collect_event(self, queue: asyncio.Queue[CollectQueueItem]):
        async def on_event(event: AgentEvent) -> None:
            await queue.put(event)

        return on_event

    async def _execute_batches_stream(
        self,
        batches,
        permission_mode: PermissionMode,
    ) -> AsyncIterator[ExecuteQueueItem]:
        queue: asyncio.Queue[ExecuteQueueItem] = asyncio.Queue()
        task = asyncio.create_task(self._execute_batches_task(batches, queue, permission_mode))
        self._runtime.track_turn_task(task)
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
        permission_mode: PermissionMode,
    ) -> None:
        results = await execute_tool_batches(
            batches,
            self._executor,
            self._queue_execute_event(queue),
            self._limits.read_tool_concurrency,
            permission_mode,
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

    def _compact_event(
        self,
        phase: CompactPhase,
        before_tokens: int,
        after_tokens: int,
        *,
        offloaded_results: int = 0,
        error: Exception | str | None = None,
    ) -> AgentEvent:
        return AgentEvent(
            type=AgentEventType.COMPACT,
            compact=CompactEvent(
                phase=phase,
                before_tokens=before_tokens,
                after_tokens=after_tokens,
                offloaded_results=offloaded_results,
                error=error,
            ),
        )

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

    async def _record_recovery_if_read_file(
        self, result: ToolResult, call: ToolCall | None
    ) -> None:
        if not result.ok or result.tool_name != "ReadFile":
            return
        path_text = result.data.get("path")
        if not isinstance(path_text, str) and call is not None:
            value = call.arguments.get("path")
            path_text = value if isinstance(value, str) else None
        if not isinstance(path_text, str) or not path_text:
            return
        path = Path(path_text)
        if not path.is_absolute():
            path = self._workspace / path
        try:
            content = await asyncio.to_thread(path.read_text, encoding="utf-8", errors="replace")
        except OSError:
            return
        await self._runtime.recovery.record_file(path, content)

    def _estimate_tokens(self) -> int:
        return estimate_tokens(
            self._runtime.usage_anchor,
            self._conversation.items(),
            self._runtime.anchor_item_len,
        )

    def _schedule_memory_update(self, turn_start_index: int) -> None:
        if self._memory_manager is None:
            return
        self._runtime.turn_count += 1
        recent_items = self._conversation.items()[turn_start_index:]
        if not self._should_update_memory(recent_items):
            return
        existing = self._runtime.memory_update_task
        if existing is not None and not existing.done():
            return
        self._runtime.memory_update_task = asyncio.create_task(
            self._memory_manager.update_async(list(recent_items))
        )

    def _refresh_system_prompt(self) -> None:
        if self._system_prompt_builder is None:
            return
        setter = getattr(self._provider, "set_system_prompt", None)
        if callable(setter):
            setter(self._system_prompt_builder())

    def _active_base_registry(self) -> ToolRegistry:
        allowed_tools = self._runtime.active_skills.allowed_tool_union()
        if not allowed_tools:
            return self._registry
        return self._registry.filtered_by_names(allowed_tools)

    def _effective_registry(self, mode: AgentMode) -> ToolRegistry:
        return registry_for_mode(self._active_base_registry(), mode)

    def _should_update_memory(self, recent_items: list[ConversationItem]) -> bool:
        if self._runtime.turn_count % 5 == 0:
            return True
        text = "\n".join(
            item.content for item in recent_items if isinstance(item, ChatMessage)
        ).casefold()
        return any(
            keyword in text
            for keyword in ("\u8bb0\u4f4f", "\u8bb0\u5fc6", "\u522b\u5fd8", "remember", "memo")
        )


def _permission_mode_for_agent_mode(mode: AgentMode) -> PermissionMode:
    if mode == AgentMode.PLAN:
        return PermissionMode.PLAN
    return PermissionMode.DEFAULT


def _effective_agent_mode(mode: AgentMode, permission_mode: PermissionMode) -> AgentMode:
    if permission_mode == PermissionMode.PLAN:
        return AgentMode.PLAN
    return mode


def _workspace_from_executor(executor: ToolExecutor) -> Path:
    context = getattr(executor, "_context", None)
    workspace = getattr(context, "workspace", None)
    if isinstance(workspace, Path):
        return workspace
    return Path.cwd()


def _default_context_window(protocol: str) -> int:
    if protocol in {"openai", "openai-compat"}:
        return 128_000
    return 200_000



