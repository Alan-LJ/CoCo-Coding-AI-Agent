from __future__ import annotations

import asyncio

from coco_code.agent.types import AgentEvent, AgentEventType
from coco_code.conversation import Conversation
from coco_code.task.manager import Manager, Status
from coco_code.tools.base import ToolCall


class FakeSubAgent:
    def __init__(self, result: str = "done", fail: BaseException | None = None) -> None:
        self.result = result
        self.fail = fail
        self.calls: list[str] = []
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.block = False

    async def run_to_completion(self, conv, task, *, events=None):
        self.calls.append(task)
        self.started.set()
        if events is not None:
            await events.put(
                AgentEvent(
                    type=AgentEventType.TOOL_STARTED,
                    tool_call=ToolCall("1", "ReadFile", {}, "{}"),
                )
            )
            await events.put(
                AgentEvent(type=AgentEventType.USAGE, usage={"input_tokens": 3})
            )
        if self.block:
            await self.release.wait()
        if self.fail is not None:
            raise self.fail
        return self.result


async def wait_done(manager: Manager) -> str:
    return await asyncio.wait_for(manager.subscribe_done().get(), timeout=2)


def test_launch() -> None:
    async def run() -> None:
        manager = Manager()
        task_id = await manager.launch(FakeSubAgent("ok"), Conversation(), "demo", "task")
        assert await wait_done(manager) == task_id
        task = manager.get(task_id)
        assert task is not None
        assert task.status == Status.COMPLETED
        assert task.result == "ok"
        assert task.tool_count == 1
        assert task.usage.input_tokens == 3

    asyncio.run(run())


def test_launch_failure_sets_failed_status() -> None:
    async def run() -> None:
        manager = Manager()
        task_id = await manager.launch(
            FakeSubAgent(fail=RuntimeError("boom")), Conversation(), "demo", "task"
        )
        await wait_done(manager)
        task = manager.get(task_id)
        assert task is not None
        assert task.status == Status.FAILED
        assert "boom" in str(task.err)

    asyncio.run(run())


def test_stop_cancels_running_task() -> None:
    async def run() -> None:
        manager = Manager()
        agent = FakeSubAgent()
        agent.block = True
        task_id = await manager.launch(agent, Conversation(), "demo", "task")
        await asyncio.wait_for(agent.started.wait(), timeout=2)
        assert await manager.stop(task_id) is True
        await wait_done(manager)
        assert manager.get(task_id).status == Status.CANCELLED

    asyncio.run(run())


def test_send_message_reruns_completed_named_task() -> None:
    async def run() -> None:
        manager = Manager()
        agent = FakeSubAgent("first")
        task_id = await manager.launch(agent, Conversation(), "worker", "first task")
        await wait_done(manager)
        agent.result = "second"
        assert await manager.send_message("worker", "second task") == task_id
        await wait_done(manager)
        task = manager.get(task_id)
        assert task.status == Status.COMPLETED
        assert task.result == "second"
        assert agent.calls == ["first task", "second task"]

    asyncio.run(run())


def test_name_index_points_to_latest_task() -> None:
    async def run() -> None:
        manager = Manager()
        first = await manager.launch(FakeSubAgent("first"), Conversation(), "worker", "one")
        second = await manager.launch(FakeSubAgent("second"), Conversation(), "worker", "two")
        await wait_done(manager)
        await wait_done(manager)
        assert first != second
        assert await manager.send_message("worker", "again") == second

    asyncio.run(run())
