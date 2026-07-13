from __future__ import annotations

import asyncio
import secrets
import sys
from contextlib import suppress
from dataclasses import dataclass, field
from enum import StrEnum
from time import monotonic
from typing import Any

from coco_code.agent.types import AgentEventType
from coco_code.conversation import Conversation


class Status(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read: int = 0
    cache_write: int = 0

    def add(self, usage: dict[str, int] | None) -> None:
        if not usage:
            return
        self.input_tokens += int(usage.get("input_tokens", 0) or 0)
        self.output_tokens += int(usage.get("output_tokens", 0) or 0)
        self.cache_read += int(usage.get("cache_read", 0) or 0)
        self.cache_write += int(usage.get("cache_write", 0) or 0)

    def as_dict(self) -> dict[str, int]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read": self.cache_read,
            "cache_write": self.cache_write,
        }


@dataclass
class PartialState:
    result: str = ""
    tool_count: int = 0
    last_activity: str = ""
    usage: Usage = field(default_factory=Usage)


@dataclass
class BackgroundTask:
    id: str
    name: str
    sub_agent: Any
    conv: Conversation
    task: str
    run_task: str | None = None
    status: Status = Status.RUNNING
    result: str = ""
    err: BaseException | None = None
    start_time: float = 0.0
    end_time: float = 0.0
    handle: asyncio.Task[Any] | None = None
    usage: Usage = field(default_factory=Usage)
    tool_count: int = 0
    last_activity: str = ""

    def as_dict(self, *, include_result: bool = True) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "status": self.status.value,
            "task": self.task,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "tool_count": self.tool_count,
            "last_activity": self.last_activity,
            "usage": self.usage.as_dict(),
        }
        if include_result:
            data["result"] = self.result
            data["error"] = str(self.err) if self.err is not None else None
        return data


class TaskBusy(RuntimeError):
    pass


class TaskNotFound(KeyError):
    pass


class Manager:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._tasks: dict[str, BackgroundTask] = {}
        self._by_name: dict[str, str] = {}
        self._done: asyncio.Queue[str] = asyncio.Queue(maxsize=32)

    async def launch(
        self,
        sub_agent: Any,
        conv: Conversation,
        name: str,
        task_text: str,
        run_text: str | None = None,
    ) -> str:
        task_id = self._next_id()
        background = BackgroundTask(
            id=task_id,
            name=name,
            sub_agent=sub_agent,
            conv=conv,
            task=task_text,
            run_task=run_text,
            start_time=monotonic(),
        )
        async with self._lock:
            self._tasks[task_id] = background
            if name:
                self._by_name[name] = task_id
        background.handle = asyncio.create_task(self._run(background))
        return task_id

    async def stop(self, task_id: str) -> bool:
        task = self.get(task_id)
        if task is None or task.handle is None:
            return False
        if task.handle.done():
            return False
        task.handle.cancel()
        asyncio.create_task(self._finalize_cancelled_before_start(task))
        return True

    async def send_message(self, name: str, message: str) -> str:
        task_id = self._by_name.get(name)
        if task_id is None:
            raise TaskNotFound(name)
        task = self._tasks[task_id]
        if task.status != Status.COMPLETED:
            raise TaskBusy(f"Task {name!r} is not completed.")
        task.status = Status.RUNNING
        task.task = message
        task.run_task = None
        task.result = ""
        task.err = None
        task.start_time = monotonic()
        task.end_time = 0.0
        task.handle = asyncio.create_task(self._run(task))
        return task_id

    async def adopt_running(
        self,
        sub_agent: Any,
        conv: Conversation,
        name: str,
        task_text: str,
        handle: asyncio.Task[Any],
        partial: PartialState | None = None,
    ) -> str:
        task_id = self._next_id()
        partial = partial or PartialState()
        background = BackgroundTask(
            id=task_id,
            name=name,
            sub_agent=sub_agent,
            conv=conv,
            task=task_text,
            run_task=None,
            start_time=monotonic(),
            result=partial.result,
            tool_count=partial.tool_count,
            last_activity=partial.last_activity,
            usage=partial.usage,
            handle=handle,
        )
        async with self._lock:
            self._tasks[task_id] = background
            if name:
                self._by_name[name] = task_id
        asyncio.create_task(self._watch_adopted(background))
        return task_id

    def get(self, task_id: str) -> BackgroundTask | None:
        return self._tasks.get(task_id)

    def list(self) -> list[BackgroundTask]:
        return [self._tasks[key] for key in sorted(self._tasks)]

    def subscribe_done(self) -> asyncio.Queue[str]:
        return self._done

    async def _run(self, task: BackgroundTask) -> None:
        events: asyncio.Queue[Any] = asyncio.Queue(maxsize=64)
        aggregator = asyncio.create_task(self._aggregate_task_events(events, task))
        try:
            task.result = await task.sub_agent.run_to_completion(
                task.conv,
                task.task if task.run_task is None else task.run_task,
                events=events,
            )
            task.status = Status.COMPLETED
        except asyncio.CancelledError:
            task.status = Status.CANCELLED
        except BaseException as exc:
            task.status = Status.FAILED
            task.err = exc
        finally:
            task.end_time = monotonic()
            with suppress(asyncio.TimeoutError):
                await asyncio.wait_for(events.join(), timeout=0.5)
            aggregator.cancel()
            with suppress(asyncio.CancelledError):
                await aggregator
            await self._notify_done(task.id)

    async def _finalize_cancelled_before_start(self, task: BackgroundTask) -> None:
        await asyncio.sleep(0)
        handle = task.handle
        if handle is None or not handle.done() or not handle.cancelled():
            return
        if task.status != Status.RUNNING:
            return
        task.status = Status.CANCELLED
        task.end_time = monotonic()
        await self._notify_done(task.id)

    async def _watch_adopted(self, task: BackgroundTask) -> None:
        assert task.handle is not None
        try:
            result = await task.handle
            if isinstance(result, str):
                task.result = result
            if task.status == Status.RUNNING:
                task.status = Status.COMPLETED
        except asyncio.CancelledError:
            task.status = Status.CANCELLED
        except BaseException as exc:
            task.status = Status.FAILED
            task.err = exc
        finally:
            task.end_time = monotonic()
            await self._notify_done(task.id)

    async def _aggregate_task_events(
        self,
        events: asyncio.Queue[Any],
        task: BackgroundTask,
    ) -> None:
        while True:
            event = await events.get()
            try:
                event_type = getattr(event, "type", None)
                if event_type == AgentEventType.TOOL_STARTED:
                    task.tool_count += 1
                    tool_call = getattr(event, "tool_call", None)
                    task.last_activity = getattr(tool_call, "name", "") or task.last_activity
                elif event_type == AgentEventType.USAGE:
                    task.usage.add(getattr(event, "usage", None))
            finally:
                events.task_done()

    async def _notify_done(self, task_id: str) -> None:
        try:
            self._done.put_nowait(task_id)
        except asyncio.QueueFull:
            print(
                f"task manager: done queue full, dropping notification for {task_id}",
                file=sys.stderr,
            )

    def _next_id(self) -> str:
        return f"task_{secrets.token_hex(4)}"
