from __future__ import annotations

import asyncio
from pathlib import Path

from coco_code.agent import AgentLimits, AgentLoop, AgentMode, AgentRunRequest
from coco_code.agent.runtime import new_session_runtime
from coco_code.conversation import Conversation, ToolResultItem
from coco_code.llm import StreamEvent, StreamEventType
from coco_code.tools import ToolCall, ToolContext, ToolExecutor, create_default_registry
from coco_code.tools.load_skill import LoadSkillTool


class PromptProvider:
    name = "fake"
    model = "fake-model"
    protocol = "openai"

    def __init__(self, scripts: list[list[StreamEvent]]) -> None:
        self.scripts = scripts
        self.calls = 0
        self.prompts: list[str] = []
        self.tools_seen = []

    def set_system_prompt(self, text: str) -> None:
        self.prompts.append(text)

    async def stream(self, messages, tools=None):  # noqa: ARG002
        self.calls += 1
        self.tools_seen.append(tools)
        script = self.scripts[self.calls - 1] if self.calls <= len(self.scripts) else []
        for event in script:
            yield event


def make_loop(provider: PromptProvider, tmp_path: Path, runtime=None) -> AgentLoop:
    registry = create_default_registry()
    registry.register(LoadSkillTool())

    async def confirm(call, spec):  # noqa: ARG001
        return True

    executor = ToolExecutor(registry, ToolContext(workspace=tmp_path), confirm)
    return AgentLoop(
        provider,
        Conversation(),
        registry,
        executor,
        AgentLimits(max_iterations=2),
        runtime=runtime,
        system_prompt_builder=lambda: "dynamic prompt",
    )


def tool_names(registry) -> set[str]:
    return {spec.name for spec in registry.list_specs()}


def test_agent_loop_updates_prompt_before_model_turn(tmp_path: Path) -> None:
    async def run() -> None:
        runtime = new_session_runtime(tmp_path)
        provider = PromptProvider([[StreamEvent(type=StreamEventType.DONE)]])
        loop = make_loop(provider, tmp_path, runtime)
        async for _event in loop.run(AgentRunRequest("hello", AgentMode.AGENT)):
            pass
        assert provider.prompts == ["dynamic prompt"]

    asyncio.run(run())


def test_active_skill_whitelist_filters_model_visible_tools(tmp_path: Path) -> None:
    async def run() -> None:
        runtime = new_session_runtime(tmp_path)
        runtime.active_skills.activate("review", "body", ("ReadFile",))
        provider = PromptProvider([[StreamEvent(type=StreamEventType.DONE)]])
        events = [
            event
            async for event in make_loop(provider, tmp_path, runtime).run(
                AgentRunRequest("hello", AgentMode.AGENT)
            )
        ]
        names = tool_names(provider.tools_seen[0])
        assert {"ReadFile", "LoadSkill"}.issubset(names)
        assert "WriteFile" not in names
        assert events[-1].stop_reason.value == "model_done"

    asyncio.run(run())


def test_multiple_active_skill_whitelists_are_unioned(tmp_path: Path) -> None:
    async def run() -> None:
        runtime = new_session_runtime(tmp_path)
        runtime.active_skills.activate("a", "body", ("ReadFile",))
        runtime.active_skills.activate("b", "body", ("Glob",))
        provider = PromptProvider([[StreamEvent(type=StreamEventType.DONE)]])
        async for _event in make_loop(provider, tmp_path, runtime).run(
            AgentRunRequest("hello", AgentMode.AGENT)
        ):
            pass
        names = tool_names(provider.tools_seen[0])
        assert {"ReadFile", "Glob", "LoadSkill"}.issubset(names)
        assert "Bash" not in names

    asyncio.run(run())


def test_hidden_tool_call_is_rejected_before_executor(tmp_path: Path) -> None:
    async def run() -> None:
        runtime = new_session_runtime(tmp_path)
        runtime.active_skills.activate("safe", "body", ("ReadFile",))
        provider = PromptProvider(
            [
                [
                    StreamEvent(
                        type=StreamEventType.TOOL_CALL,
                        tool_call=ToolCall("1", "WriteFile", {"path": "x", "content": "bad"}, "{}"),
                    )
                ],
                [StreamEvent(type=StreamEventType.DONE)],
            ]
        )
        conversation = Conversation()
        registry = create_default_registry()
        registry.register(LoadSkillTool())

        async def confirm(call, spec):  # noqa: ARG001
            return True

        executor = ToolExecutor(registry, ToolContext(workspace=tmp_path), confirm)
        loop = AgentLoop(
            provider,
            conversation,
            registry,
            executor,
            AgentLimits(max_iterations=2),
            runtime=runtime,
            system_prompt_builder=lambda: "prompt",
        )
        await asyncio.gather(*[asyncio.create_task(_drain(loop))])
        assert not (tmp_path / "x").exists()
        result = next(
            item.result for item in conversation.items() if isinstance(item, ToolResultItem)
        )
        assert result.ok is False
        assert "Unknown tool" in (result.error or "")

    asyncio.run(run())


async def _drain(loop: AgentLoop) -> None:
    async for _event in loop.run(AgentRunRequest("go", AgentMode.AGENT)):
        pass
