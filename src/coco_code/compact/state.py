from __future__ import annotations

import asyncio
import inspect
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from coco_code.compact.constants import MAX_CONSECUTIVE_AUTO_COMPACT_FAILURES
from coco_code.tools.base import ToolResult


@dataclass(frozen=True)
class SessionContext:
    session_id: str
    session_dir: Path
    spill_dir: Path


def new_session_context(workspace: Path) -> SessionContext:
    session_id = new_session_id()
    session_dir = workspace / ".coco-code" / "sessions" / session_id
    spill_dir = session_dir / "tool-results"
    try:
        spill_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        session_dir = Path.cwd() / ".coco-code" / "sessions" / session_id
        spill_dir = session_dir / "tool-results"
        spill_dir.mkdir(parents=True, exist_ok=True)
    return SessionContext(session_id=session_id, session_dir=session_dir, spill_dir=spill_dir)


def new_session_id(now: datetime | None = None) -> str:
    timestamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    return f"{timestamp}-{secrets.token_hex(2)}"


def open_session_context(workspace: Path, session_id: str) -> SessionContext:
    session_dir = workspace / ".coco-code" / "sessions" / session_id
    return SessionContext(
        session_id=session_id,
        session_dir=session_dir,
        spill_dir=session_dir / "tool-results",
    )


def parse_session_time(session_id: str) -> datetime | None:
    try:
        if len(session_id) != 20 or session_id[15] != "-":
            return None
        return datetime.strptime(session_id[:15], "%Y%m%d-%H%M%S")
    except ValueError:
        return None


@dataclass(frozen=True)
class ReplacementDecision:
    kind: Literal["kept", "replaced", "skip"]
    result: ToolResult | None = None


DecisionFactory = Callable[[], ReplacementDecision | Awaitable[ReplacementDecision]]


class ContentReplacementState:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._seen_ids: set[str] = set()
        self._replacements: dict[str, ToolResult] = {}

    async def decide_once(
        self,
        tool_call_id: str,
        original: ToolResult,
        decide: DecisionFactory,
    ) -> ToolResult:
        async with self._lock:
            if tool_call_id in self._replacements:
                return self._replacements[tool_call_id]
            if tool_call_id in self._seen_ids:
                return original

            decision = decide()
            if inspect.isawaitable(decision):
                decision = await decision

            if decision.kind == "skip":
                return original
            if decision.kind == "replaced":
                if decision.result is None:
                    raise ValueError("replacement decision requires a result")
                self._seen_ids.add(tool_call_id)
                self._replacements[tool_call_id] = decision.result
                return decision.result

            self._seen_ids.add(tool_call_id)
            return original


class CompactCircuitBreaker:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._consecutive_failures = 0

    async def record_success(self) -> None:
        async with self._lock:
            self._consecutive_failures = 0

    async def record_failure(self) -> None:
        async with self._lock:
            self._consecutive_failures += 1

    async def tripped(self) -> bool:
        async with self._lock:
            return self._consecutive_failures >= MAX_CONSECUTIVE_AUTO_COMPACT_FAILURES
