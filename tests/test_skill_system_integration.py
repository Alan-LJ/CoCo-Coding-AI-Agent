from __future__ import annotations

import asyncio
from pathlib import Path

from coco_code.agent import AgentLimits, AgentLoop, AgentMode, AgentRunRequest
from coco_code.agent.runtime import new_session_runtime
from coco_code.config import ProviderConfig
from coco_code.conversation import Conversation
from coco_code.llm import StreamEvent, StreamEventType
from coco_code.prompt import build_system_prompt
from coco_code.skills.catalog import SkillCatalog
from coco_code.skills.render import render_active_skills_block
from coco_code.tools import ToolCall, ToolContext, ToolExecutor, create_default_registry
from coco_code.tools.load_skill import LoadSkillTool


class LoadingProvider:
    name = "fake"
    model = "fake-model"
    protocol = "openai"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def set_system_prompt(self, text: str) -> None:
        self.prompts.append(text)

    async def stream(self, messages, tools=None):  # noqa: ARG002
        if len(self.prompts) == 1:
            yield StreamEvent(
                type=StreamEventType.TOOL_CALL,
                tool_call=ToolCall("1", "LoadSkill", {"name": "demo", "arguments": "abc"}, "{}"),
            )
            return
        yield StreamEvent(type=StreamEventType.DONE)


def test_model_load_skill_pins_full_sop_on_next_turn(tmp_path: Path) -> None:
    skill_dir = tmp_path / "builtin" / "demo"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: demo\ndescription: demo skill\n---\nSOP body $ARGUMENTS\n",
        encoding="utf-8",
    )
    catalog = SkillCatalog(
        tmp_path,
        builtin_dir=tmp_path / "builtin",
        user_dir=tmp_path / "user",
        project_dir=tmp_path / "project",
    )
    catalog.reload()
    runtime = new_session_runtime(tmp_path)
    provider = LoadingProvider()
    registry = create_default_registry()
    registry.register(LoadSkillTool(catalog, runtime.active_skills))

    async def confirm(call, spec):  # noqa: ARG001
        return True

    cfg = ProviderConfig("fake", "openai", "fake-model", api_key="secret")

    def prompt_builder() -> str:
        return build_system_prompt(
            tmp_path,
            cfg,
            skills_catalog=catalog.catalog_text(),
            active_skills=render_active_skills_block(runtime.active_skills.snapshot()),
        )

    async def run() -> None:
        loop = AgentLoop(
            provider,
            Conversation(),
            registry,
            ToolExecutor(registry, ToolContext(workspace=tmp_path), confirm),
            AgentLimits(max_iterations=2),
            runtime=runtime,
            system_prompt_builder=prompt_builder,
        )
        async for _event in loop.run(AgentRunRequest("please use demo", AgentMode.AGENT)):
            pass

    asyncio.run(run())
    assert "demo skill" in provider.prompts[0]
    assert "SOP body" not in provider.prompts[0]
    assert "SOP body abc" in provider.prompts[1]
