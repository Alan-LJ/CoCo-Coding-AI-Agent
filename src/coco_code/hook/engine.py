from __future__ import annotations

import asyncio
import sys
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from coco_code.hook.event import Event, is_blocking
from coco_code.hook.executor import ActionOutcome, HookExecutor
from coco_code.hook.matcher import eval_condition
from coco_code.hook.rule import HookRule

if TYPE_CHECKING:
    from coco_code.agent.runtime import SessionRuntime


@dataclass
class DispatchResult:
    blocked: bool = False
    reason: str = ""
    blocking_hook_name: str = ""
    injected_prompts: list[str] = field(default_factory=list)


class HookEngine:
    def __init__(
        self,
        rules: Sequence[HookRule],
        sources: Sequence[str | Path],
        executor: HookExecutor | None = None,
    ) -> None:
        self._rules = tuple(rules)
        self._sources = tuple(Path(source) for source in sources)
        self._executor = executor or HookExecutor()
        self._fallback_fired: set[str] = set()

    async def dispatch(
        self,
        event: Event,
        payload: Mapping[str, Any],
        runtime: SessionRuntime | None = None,
    ) -> DispatchResult:
        result = DispatchResult()
        blocking = is_blocking(event)
        for rule in self._rules:
            if rule.event != event:
                continue
            fired = _fired_set(runtime, self._fallback_fired)
            if rule.only_once and rule.name in fired:
                continue
            if not eval_condition(rule.condition, payload):
                continue
            if rule.async_mode:
                task = asyncio.create_task(self._run_async(rule, payload))
                _track_task(runtime, task)
                if rule.only_once:
                    fired.add(rule.name)
                continue

            outcome = await self._run_sync(rule, payload, blocking=blocking)
            if outcome.error is not None:
                _log_failure(rule, outcome.error)
                continue
            if outcome.prompt:
                result.injected_prompts.append(outcome.prompt)
            if rule.only_once:
                fired.add(rule.name)
            if blocking and outcome.blocked:
                result.blocked = True
                result.reason = outcome.reason
                result.blocking_hook_name = rule.name
                break
        return result

    def rules(self) -> tuple[HookRule, ...]:
        return self._rules

    def sources(self) -> tuple[Path, ...]:
        return self._sources

    async def _run_sync(
        self,
        rule: HookRule,
        payload: Mapping[str, Any],
        *,
        blocking: bool,
    ) -> ActionOutcome:
        return await self._executor.run(rule, payload, blocking=blocking)

    async def _run_async(self, rule: HookRule, payload: Mapping[str, Any]) -> None:
        try:
            outcome = await self._executor.run(rule, payload, blocking=False)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _log_failure(rule, str(exc))
            return
        if outcome.error is not None:
            _log_failure(rule, outcome.error)


def _fired_set(runtime: SessionRuntime | None, fallback: set[str]) -> set[str]:
    if runtime is not None and hasattr(runtime, "fired_hooks"):
        return runtime.fired_hooks
    return fallback


def _track_task(runtime: SessionRuntime | None, task: asyncio.Task[Any]) -> None:
    if runtime is not None and hasattr(runtime, "track_hook_task"):
        runtime.track_hook_task(task)
        return
    task.add_done_callback(_consume_task_exception)


def _consume_task_exception(task: asyncio.Task[Any]) -> None:
    if not task.done():
        return
    with suppress(asyncio.CancelledError, Exception):
        task.exception()


def _log_failure(rule: HookRule, reason: str) -> None:
    print(f"[hook {rule.name}] {rule.event.value} failed: {reason}", file=sys.stderr)
