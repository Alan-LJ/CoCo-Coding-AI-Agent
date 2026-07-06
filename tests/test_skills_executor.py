from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

from coco_code.agent import AgentLimits, AgentMode
from coco_code.agent.runtime import new_session_runtime
from coco_code.config import ProviderConfig
from coco_code.conversation import Conversation
from coco_code.llm import StreamEvent, StreamEventType
from coco_code.permission import Mode as PermissionMode
from coco_code.skills.catalog import SkillCatalog
from coco_code.skills.executor import SkillExecutor
from coco_code.tools import ToolContext, create_default_registry
from coco_code.tools.load_skill import LoadSkillTool


@dataclass
class RecordingUI:
    sent: list[tuple[str, str | None, AgentMode | None, PermissionMode | None]] = field(
        default_factory=list
    )
    summaries: list[str] = field(default_factory=list)
    conversation: Conversation | None = None

    def send_user_message(
        self,
        text: str,
        *,
        display_label: str | None = None,
        mode: AgentMode | None = None,
        permission_mode: PermissionMode | None = None,
    ) -> None:
        self.sent.append((text, display_label, mode, permission_mode))

    def append_assistant_message(self, text: str) -> None:
        self.summaries.append(text)
        if self.conversation is not None:
            self.conversation.add_assistant(text)


class ForkProvider:
    name = "fake"
    model = "fake-model"
    protocol = "openai"

    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.messages_seen = []
        self.tools_seen = []

    def set_system_prompt(self, text: str) -> None:
        self.prompts.append(text)

    async def stream(self, messages, tools=None):
        self.messages_seen.append(messages)
        self.tools_seen.append(tools)
        yield StreamEvent(type=StreamEventType.TEXT_DELTA, text="summary")
        yield StreamEvent(type=StreamEventType.DONE)


def write_skill(
    root: Path,
    name: str,
    body: str,
    *,
    mode: str = "inline",
    context: str = "none",
    tools: str = "",
) -> None:
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    allowed = f"allowed_tools: [{tools}]\n" if tools else ""
    (skill_dir / "SKILL.md").write_text(
        (
            f"---\nname: {name}\ndescription: {name} skill\n{allowed}"
            f"mode: {mode}\ncontext: {context}\n---\n{body}\n"
        ),
        encoding="utf-8",
    )


def make_catalog(tmp_path: Path) -> SkillCatalog:
    catalog = SkillCatalog(
        tmp_path,
        builtin_dir=tmp_path / "builtin",
        user_dir=tmp_path / "user",
        project_dir=tmp_path / "project",
    )
    catalog.reload()
    return catalog


def make_executor(
    tmp_path: Path,
    catalog: SkillCatalog,
    conversation: Conversation,
    provider: ForkProvider | None = None,
) -> SkillExecutor:
    registry = create_default_registry()
    registry.register(LoadSkillTool())
    provider_cfg = ProviderConfig("fake", "openai", "fake-model", api_key="secret")

    async def confirm(call, spec):  # noqa: ARG001
        return True

    def provider_factory(cfg, prompt):  # noqa: ARG001
        assert provider is not None
        provider.set_system_prompt(prompt)
        return provider

    return SkillExecutor(
        catalog=catalog,
        runtime=new_session_runtime(tmp_path),
        conversation=conversation,
        registry=registry,
        tool_context=ToolContext(workspace=tmp_path),
        confirm_callback=confirm,
        provider_config=provider_cfg,
        provider_configs=(provider_cfg,),
        agent_limits=AgentLimits(max_iterations=1),
        provider_factory=provider_factory,
        prompt_builder=lambda cfg, runtime: (
            "prompt " + ",".join(entry.name for entry in runtime.active_skills.snapshot())
        ),
    )


def test_inline_skill_activates_and_sends_concise_trigger(tmp_path: Path) -> None:
    async def run() -> None:
        write_skill(tmp_path / "builtin", "commit", "Commit SOP $ARGUMENTS")
        catalog = make_catalog(tmp_path)
        conversation = Conversation()
        executor = make_executor(tmp_path, catalog, conversation)
        ui = RecordingUI()
        await executor.execute_command("commit", "use imperative mood", ui)
        active = executor._runtime.active_skills.snapshot()  # noqa: SLF001
        assert active[0].rendered_body.strip() == "Commit SOP use imperative mood"
        assert ui.sent == [
            (
                "Run active Skill 'commit' for this request: use imperative mood",
                "/commit use imperative mood",
                AgentMode.AGENT,
                None,
            )
        ]

    asyncio.run(run())


def test_fork_skill_isolates_none_context_and_appends_summary(tmp_path: Path) -> None:
    async def run() -> None:
        write_skill(tmp_path / "builtin", "review", "Review SOP", mode="fork", context="none")
        catalog = make_catalog(tmp_path)
        conversation = Conversation()
        conversation.add_user("old main history")
        provider = ForkProvider()
        executor = make_executor(tmp_path, catalog, conversation, provider)
        ui = RecordingUI(conversation=conversation)
        await executor.execute_command("review", "check it", ui)
        assert ui.summaries == ["summary"]
        assert conversation.messages()[-1].content == "summary"
        child_text = "\n".join(message.content for message in provider.messages_seen[0])
        assert "old main history" not in child_text
        assert "check it" in child_text

    asyncio.run(run())


def test_fork_recent_and_full_context_policies(tmp_path: Path) -> None:
    async def run() -> None:
        write_skill(tmp_path / "builtin", "recent", "Recent SOP", mode="fork", context="recent")
        write_skill(tmp_path / "builtin", "full", "Full SOP", mode="fork", context="full")
        catalog = make_catalog(tmp_path)
        conversation = Conversation()
        for index in range(6):
            conversation.add_user(f"m{index}")
        recent_provider = ForkProvider()
        await make_executor(tmp_path, catalog, conversation, recent_provider).execute_fork(
            catalog.get("recent"), ""
        )
        recent_text = "\n".join(message.content for message in recent_provider.messages_seen[0])
        assert "m0" not in recent_text
        assert "m5" in recent_text

        full_provider = ForkProvider()
        await make_executor(tmp_path, catalog, conversation, full_provider).execute_fork(
            catalog.get("full"), ""
        )
        full_text = "\n".join(message.content for message in full_provider.messages_seen[0])
        assert "m0" in full_text
        assert "m5" in full_text

    asyncio.run(run())


def test_fork_registry_uses_skill_whitelist_plus_system_tools(tmp_path: Path) -> None:
    async def run() -> None:
        write_skill(
            tmp_path / "builtin",
            "reader",
            "Read SOP",
            mode="fork",
            context="none",
            tools='"ReadFile"',
        )
        catalog = make_catalog(tmp_path)
        provider = ForkProvider()
        await make_executor(tmp_path, catalog, Conversation(), provider).execute_fork(
            catalog.get("reader"), ""
        )
        names = {spec.name for spec in provider.tools_seen[0].list_specs()}
        assert {"ReadFile", "LoadSkill"}.issubset(names)
        assert "WriteFile" not in names

    asyncio.run(run())

