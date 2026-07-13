from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from coco_code.agent.agent_tool import AgentTool
from coco_code.agent.fork import FORK_BOILERPLATE_TAG
from coco_code.agent.runtime import new_session_runtime
from coco_code.agent.types import AgentLimits
from coco_code.config import ProviderConfig
from coco_code.conversation import Conversation
from coco_code.llm import StreamEvent, StreamEventType
from coco_code.permission import Mode as PermissionMode
from coco_code.subagent import Catalog, Definition, Source
from coco_code.task import Manager
from coco_code.tools import ToolContext, create_default_registry
from coco_code.tools.registry import ToolRegistry


@dataclass
class ProviderCall:
    system_prompt: str
    messages: list[object]
    tools: tuple[str, ...]


class FakeProvider:
    name = "fake"
    model = "fake-sonnet"
    protocol = "openai"

    def __init__(self, system_prompt: str, calls: list[ProviderCall]) -> None:
        self._system_prompt = system_prompt
        self._calls = calls

    def set_system_prompt(self, text: str) -> None:
        self._system_prompt = text

    async def stream(self, messages, tools=None):
        self._calls.append(
            ProviderCall(
                system_prompt=self._system_prompt,
                messages=list(messages),
                tools=tuple(tools.names()) if tools is not None else (),
            )
        )
        yield StreamEvent(type=StreamEventType.TEXT_DELTA, text="ok")
        yield StreamEvent(type=StreamEventType.DONE)


class SlowProvider(FakeProvider):
    async def stream(self, messages, tools=None):
        await asyncio.sleep(0.05)
        async for event in super().stream(messages, tools):
            yield event
async def approve(*args) -> bool:  # noqa: ANN002
    return True


def build_tool(
    tmp_path: Path,
    catalog: Catalog,
    registry: ToolRegistry,
    conversation: Conversation,
    manager: Manager,
    calls: list[ProviderCall],
    *,
    background_enabled=True,
    auto_background_seconds: float = 120.0,
    provider_cls=FakeProvider,
) -> AgentTool:
    provider_cfg = ProviderConfig(name="sonnet", protocol="openai", model="fake-sonnet")
    runtime = new_session_runtime(tmp_path, 128_000)
    return AgentTool(
        catalog=catalog,
        manager=manager,
        registry=registry,
        tool_context=ToolContext(workspace=tmp_path),
        confirm_callback=approve,
        provider_config_getter=lambda: provider_cfg,
        provider_configs_getter=lambda: (provider_cfg,),
        conversation_getter=lambda: conversation,
        runtime_getter=lambda: runtime,
        permission_mode_getter=lambda: PermissionMode.DEFAULT,
        prompt_builder=lambda _cfg, _runtime: "parent prompt",
        agent_limits=AgentLimits(response_timeout_seconds=1),
        provider_factory=lambda _cfg, prompt: provider_cls(prompt, calls),
        background_enabled=background_enabled,
        auto_background_seconds=auto_background_seconds,
    )


def test_defined_agent_runs_foreground_with_role_prompt(tmp_path: Path) -> None:
    async def run() -> None:
        catalog = Catalog()
        catalog.add(
            Definition(
                name="research",
                description="research",
                tools=("ReadFile",),
                max_turns=2,
                system_prompt="role prompt",
                source=Source.PROJECT,
            )
        )
        registry = create_default_registry()
        manager = Manager()
        calls: list[ProviderCall] = []
        tool = build_tool(tmp_path, catalog, registry, Conversation(), manager, calls)
        registry.register(tool)

        result = await tool.run(
            {"prompt": "do it", "subagent_type": "research"},
            ToolContext(workspace=tmp_path),
        )

        assert result.ok is True
        assert result.data["result"] == "ok"
        assert calls[0].system_prompt == "role prompt"
        assert calls[0].tools == ("ReadFile",)

    asyncio.run(run())


def test_fork_agent_is_background_and_inherits_parent_history(tmp_path: Path) -> None:
    async def run() -> None:
        catalog = Catalog()
        registry = create_default_registry()
        manager = Manager()
        conversation = Conversation()
        conversation.add_user("parent context")
        calls: list[ProviderCall] = []
        tool = build_tool(tmp_path, catalog, registry, conversation, manager, calls)
        registry.register(tool)

        result = await tool.run(
            {"prompt": "fork task", "type": "fork", "run_in_background": False, "name": "fork"},
            ToolContext(workspace=tmp_path),
        )

        assert result.ok is True
        task_id = result.data["task_id"]
        assert await asyncio.wait_for(manager.subscribe_done().get(), timeout=2) == task_id
        task = manager.get(task_id)
        assert task is not None
        messages = task.conv.messages()
        assert messages[0].content == "parent context"
        assert any(FORK_BOILERPLATE_TAG in message.content for message in messages)
        assert "Agent" not in calls[0].tools

    asyncio.run(run())


def test_nested_fork_is_rejected(tmp_path: Path) -> None:
    async def run() -> None:
        catalog = Catalog()
        registry = create_default_registry()
        manager = Manager()
        conversation = Conversation()
        conversation.add_user(FORK_BOILERPLATE_TAG)
        calls: list[ProviderCall] = []
        tool = build_tool(tmp_path, catalog, registry, conversation, manager, calls)

        result = await tool.run(
            {"prompt": "fork task", "type": "fork"},
            ToolContext(workspace=tmp_path),
        )

        assert result.ok is False
        assert "nested forks" in result.error

    asyncio.run(run())


def test_background_disabled_rejects_background_agents(tmp_path: Path) -> None:
    async def run() -> None:
        catalog = Catalog()
        catalog.add(Definition(name="worker", description="worker", source=Source.PROJECT))
        registry = create_default_registry()
        manager = Manager()
        calls: list[ProviderCall] = []
        tool = build_tool(
            tmp_path,
            catalog,
            registry,
            Conversation(),
            manager,
            calls,
            background_enabled=False,
        )

        result = await tool.run(
            {
                "prompt": "do it",
                "subagent_type": "worker",
                "run_in_background": True,
            },
            ToolContext(workspace=tmp_path),
        )

        assert result.ok is False
        assert "disabled" in result.error

    asyncio.run(run())

def test_defined_agent_timeout_moves_to_background(tmp_path: Path) -> None:
    async def run() -> None:
        catalog = Catalog()
        catalog.add(Definition(name="worker", description="worker", source=Source.PROJECT))
        registry = create_default_registry()
        manager = Manager()
        calls: list[ProviderCall] = []
        tool = build_tool(
            tmp_path,
            catalog,
            registry,
            Conversation(),
            manager,
            calls,
            auto_background_seconds=0.001,
            provider_cls=SlowProvider,
        )

        result = await tool.run(
            {"prompt": "slow work", "subagent_type": "worker", "name": "slow"},
            ToolContext(workspace=tmp_path),
        )

        assert result.ok is True
        assert result.data["status"] == "timed_out_to_background"
        task_id = result.data["task_id"]
        assert await asyncio.wait_for(manager.subscribe_done().get(), timeout=2) == task_id
        task = manager.get(task_id)
        assert task is not None
        assert task.name == "slow"
        assert task.task == "slow work"
        assert task.result == "ok"

    asyncio.run(run())
