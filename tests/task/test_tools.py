from __future__ import annotations

import asyncio

from coco_code.conversation import Conversation
from coco_code.task.manager import Manager
from coco_code.task.tools import SendMessageTool, TaskGetTool, TaskListTool, TaskStopTool
from coco_code.tools.base import ToolContext


class SlowAgent:
    def __init__(self) -> None:
        self.release = asyncio.Event()

    async def run_to_completion(self, conv, task, *, events=None):  # noqa: ARG002
        await self.release.wait()
        return "ok"


class QuickAgent:
    async def run_to_completion(self, conv, task, *, events=None):  # noqa: ARG002
        return f"result {task}"


def test_task_tools() -> None:
    async def run() -> None:
        manager = Manager()
        task_id = await manager.launch(QuickAgent(), Conversation(), "worker", "one")
        await manager.subscribe_done().get()
        context = ToolContext(workspace=__import__("pathlib").Path.cwd())

        list_result = await TaskListTool(manager).run({}, context)
        assert list_result.ok is True
        assert list_result.data["tasks"][0]["id"] == task_id

        get_result = await TaskGetTool(manager).run({"task_id": task_id}, context)
        assert get_result.ok is True
        assert get_result.data["result"] == "result one"

        missing = await TaskGetTool(manager).run({"task_id": "missing"}, context)
        assert missing.ok is False

        resumed = await SendMessageTool(manager).run(
            {"name": "worker", "message": "two"}, context
        )
        assert resumed.ok is True
        await manager.subscribe_done().get()
        assert manager.get(task_id).result == "result two"

    asyncio.run(run())


def test_task_stop_tool() -> None:
    async def run() -> None:
        manager = Manager()
        agent = SlowAgent()
        task_id = await manager.launch(agent, Conversation(), "slow", "wait")
        context = ToolContext(workspace=__import__("pathlib").Path.cwd())
        result = await TaskStopTool(manager).run({"task_id": task_id}, context)
        assert result.ok is True
        await manager.subscribe_done().get()
        assert manager.get(task_id).status.value == "cancelled"

    asyncio.run(run())
