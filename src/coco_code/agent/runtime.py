from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

from coco_code.compact.recovery import RecoveryState
from coco_code.compact.state import (
    CompactCircuitBreaker,
    ContentReplacementState,
    SessionContext,
    new_session_context,
)


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
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


def new_session_runtime(workspace: Path, context_window: int = 0) -> SessionRuntime:
    return SessionRuntime(
        replacement=ContentReplacementState(),
        recovery=RecoveryState(),
        circuit_breaker=CompactCircuitBreaker(),
        session=new_session_context(workspace),
        context_window=context_window,
    )
