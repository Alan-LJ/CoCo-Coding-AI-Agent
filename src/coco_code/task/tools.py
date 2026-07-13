from __future__ import annotations

from time import monotonic
from typing import Any

from coco_code.task.manager import Manager, TaskBusy, TaskNotFound
from coco_code.tools.base import (
    ConfirmationPolicy,
    ToolCategory,
    ToolContext,
    ToolParams,
    ToolResult,
    ToolSpec,
)


class TaskListTool:
    def __init__(self, manager: Manager) -> None:
        self._manager = manager

    @property
    def spec(self) -> ToolSpec:
        return _spec("TaskList", "List in-memory SubAgent background tasks.", {}, [], True)

    async def run(self, params: ToolParams, context: ToolContext) -> ToolResult:  # noqa: ARG002
        started = monotonic()
        data = [task.as_dict(include_result=False) for task in self._manager.list()]
        return _success(self.spec.name, f"{len(data)} task(s).", {"tasks": data}, started)


class TaskGetTool:
    def __init__(self, manager: Manager) -> None:
        self._manager = manager

    @property
    def spec(self) -> ToolSpec:
        return _spec(
            "TaskGet",
            "Get details for a SubAgent background task.",
            {"task_id": {"type": "string"}},
            ["task_id"],
            True,
        )

    async def run(self, params: ToolParams, context: ToolContext) -> ToolResult:  # noqa: ARG002
        started = monotonic()
        task_id = params.get("task_id")
        if not isinstance(task_id, str) or not task_id.strip():
            return _failure(
                self.spec.name,
                "TaskGet parameter `task_id` must be a string.",
                started,
            )
        task = self._manager.get(task_id.strip())
        if task is None:
            return _failure(self.spec.name, f"Unknown task: {task_id}", started)
        return _success(
            self.spec.name,
            f"Task {task.id}: {task.status.value}.",
            task.as_dict(),
            started,
        )


class TaskStopTool:
    def __init__(self, manager: Manager) -> None:
        self._manager = manager

    @property
    def spec(self) -> ToolSpec:
        return _spec(
            "TaskStop",
            "Cancel a running SubAgent background task.",
            {"task_id": {"type": "string"}},
            ["task_id"],
            False,
        )

    async def run(self, params: ToolParams, context: ToolContext) -> ToolResult:  # noqa: ARG002
        started = monotonic()
        task_id = params.get("task_id")
        if not isinstance(task_id, str) or not task_id.strip():
            return _failure(
                self.spec.name,
                "TaskStop parameter `task_id` must be a string.",
                started,
            )
        if not await self._manager.stop(task_id.strip()):
            return _failure(self.spec.name, f"Unknown or inactive task: {task_id}", started)
        return _success(
            self.spec.name,
            f"Cancellation requested for task {task_id}.",
            {"task_id": task_id.strip(), "status": "cancellation_requested"},
            started,
        )


class SendMessageTool:
    def __init__(self, manager: Manager) -> None:
        self._manager = manager

    @property
    def spec(self) -> ToolSpec:
        return _spec(
            "SendMessage",
            "Send a follow-up message to a named completed SubAgent task.",
            {"name": {"type": "string"}, "message": {"type": "string"}},
            ["name", "message"],
            False,
        )

    async def run(self, params: ToolParams, context: ToolContext) -> ToolResult:  # noqa: ARG002
        started = monotonic()
        name = params.get("name")
        message = params.get("message")
        if not isinstance(name, str) or not name.strip():
            return _failure(
                self.spec.name,
                "SendMessage parameter `name` must be a string.",
                started,
            )
        if not isinstance(message, str) or not message.strip():
            return _failure(
                self.spec.name, "SendMessage parameter `message` must be a string.", started
            )
        try:
            task_id = await self._manager.send_message(name.strip(), message.strip())
        except (TaskBusy, TaskNotFound) as exc:
            return _failure(self.spec.name, str(exc), started)
        return _success(
            self.spec.name,
            f"Task {name} resumed.",
            {"task_id": task_id, "status": "resumed"},
            started,
        )


def _spec(
    name: str,
    description: str,
    properties: dict[str, dict[str, Any]],
    required: list[str],
    read_only: bool,
) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=description,
        parameters_schema={
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
        confirmation=ConfirmationPolicy.NEVER,
        category=ToolCategory.GENERAL,
        read_only=read_only,
        destructive=False,
        system=True,
    )


def _success(
    tool_name: str,
    summary: str,
    data: dict[str, Any],
    started: float,
) -> ToolResult:
    return ToolResult(
        tool_call_id="",
        tool_name=tool_name,
        ok=True,
        summary=summary,
        data=data,
        error=None,
        elapsed_ms=_elapsed_ms(started),
    )


def _failure(tool_name: str, message: str, started: float) -> ToolResult:
    return ToolResult(
        tool_call_id="",
        tool_name=tool_name,
        ok=False,
        summary=message,
        data={},
        error=message,
        elapsed_ms=_elapsed_ms(started),
    )


def _elapsed_ms(started: float) -> int:
    return int((monotonic() - started) * 1000)
