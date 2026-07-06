from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from coco_code.compact.recovery import RecoveryState
from coco_code.compact.state import (
    CompactCircuitBreaker,
    ContentReplacementState,
    SessionContext,
    new_session_context,
)
from coco_code.skills.active import ActiveSkills


@dataclass
class SessionRuntime:
    replacement: ContentReplacementState
    recovery: RecoveryState
    circuit_breaker: CompactCircuitBreaker
    session: SessionContext
    context_window: int
    usage_anchor: int = 0
    anchor_item_len: int = 0
    turn_count: int = 0
    memory_update_task: asyncio.Task[None] | None = None
    active_skills: ActiveSkills = field(default_factory=ActiveSkills)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    turn_tasks: set[asyncio.Task[Any]] = field(default_factory=set)

    def track_turn_task(self, task: asyncio.Task[Any]) -> None:
        if task.done():
            self._consume_task_exception(task)
            return
        self.turn_tasks.add(task)
        task.add_done_callback(self._forget_turn_task)

    def cancel_turn_tasks(self) -> None:
        for task in tuple(self.turn_tasks):
            if not task.done():
                task.cancel()

    def _forget_turn_task(self, task: asyncio.Task[Any]) -> None:
        self.turn_tasks.discard(task)
        self._consume_task_exception(task)

    @staticmethod
    def _consume_task_exception(task: asyncio.Task[Any]) -> None:
        if not task.done():
            return
        with suppress(asyncio.CancelledError, Exception):
            task.exception()


def new_session_runtime(workspace: Path, context_window: int = 0) -> SessionRuntime:
    return SessionRuntime(
        replacement=ContentReplacementState(),
        recovery=RecoveryState(),
        circuit_breaker=CompactCircuitBreaker(),
        session=new_session_context(workspace),
        context_window=context_window,
    )
