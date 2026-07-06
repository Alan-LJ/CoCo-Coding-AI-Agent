from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

from coco_code.agent import (
    AgentEventType,
    AgentLimits,
    AgentLoop,
    AgentMode,
    AgentRunRequest,
    AgentStopReason,
)
from coco_code.agent.runtime import SessionRuntime, new_session_runtime
from coco_code.config import ProviderConfig, effective_context_window
from coco_code.conversation import ChatMessage, Conversation, ConversationItem
from coco_code.llm import Provider, new_provider
from coco_code.permission import Mode as PermissionMode
from coco_code.permission.engine import Engine
from coco_code.skills.catalog import SkillCatalog
from coco_code.skills.render import render_skill_body
from coco_code.skills.types import Skill, SkillContext, SkillMode
from coco_code.tools.base import ConfirmCallback, ToolContext
from coco_code.tools.executor import PermissionCallback, ToolExecutor
from coco_code.tools.registry import ToolRegistry

ProviderFactory = Callable[[ProviderConfig, str], Provider]
PromptBuilder = Callable[[ProviderConfig, SessionRuntime], str]

if TYPE_CHECKING:
    from coco_code.command.types import CommandUI


class SkillDependencyError(RuntimeError):
    pass


class SkillExecutor:
    def __init__(
        self,
        *,
        catalog: SkillCatalog,
        runtime: SessionRuntime,
        conversation: Conversation,
        registry: ToolRegistry,
        tool_context: ToolContext,
        confirm_callback: ConfirmCallback,
        provider_config: ProviderConfig | None = None,
        provider_configs: Sequence[ProviderConfig] = (),
        agent_limits: AgentLimits | None = None,
        permission_engine: Engine | None = None,
        permission_callback: PermissionCallback | None = None,
        permission_mode: PermissionMode = PermissionMode.DEFAULT,
        provider_factory: ProviderFactory = new_provider,
        prompt_builder: PromptBuilder | None = None,
    ) -> None:
        self._catalog = catalog
        self._runtime = runtime
        self._conversation = conversation
        self._registry = registry
        self._tool_context = tool_context
        self._confirm_callback = confirm_callback
        self._provider_config = provider_config
        self._provider_configs = tuple(provider_configs)
        self._agent_limits = agent_limits or AgentLimits()
        self._permission_engine = permission_engine
        self._permission_callback = permission_callback
        self._permission_mode = permission_mode
        self._provider_factory = provider_factory
        self._prompt_builder = prompt_builder

    async def execute_command(self, name: str, args: str, ui: CommandUI) -> None:
        skill = self._latest_skill(name)
        if skill.meta.mode == SkillMode.FORK:
            summary = await self.execute_fork(skill, args)
            ui.append_assistant_message(summary)
            return
        trigger = self.activate_inline(skill, args)
        display = f"/{skill.meta.name}" + (f" {args.strip()}" if args.strip() else "")
        ui.send_user_message(
            trigger,
            display_label=display,
            mode=AgentMode.AGENT,
            permission_mode=None,
        )

    def activate_inline(self, skill: Skill, args: str) -> str:
        rendered = render_skill_body(skill, args)
        self._runtime.active_skills.activate(
            skill.meta.name,
            rendered,
            skill.meta.allowed_tools,
        )
        return _inline_trigger(skill, args)

    async def execute_fork(self, skill: Skill, args: str) -> str:
        provider_cfg = self._select_provider(skill)
        child_runtime = new_session_runtime(
            self._tool_context.workspace,
            effective_context_window(provider_cfg),
        )
        rendered = render_skill_body(skill, args)
        child_runtime.active_skills.activate(skill.meta.name, rendered, skill.meta.allowed_tools)
        child_conversation = Conversation.from_items(self._child_history(skill))
        child_registry = self._child_registry(skill)
        child_executor = ToolExecutor(
            child_registry,
            self._tool_context,
            self._confirm_callback,
            self._permission_engine,
            self._permission_callback,
            self._permission_mode,
        )
        system_prompt = self._build_prompt(provider_cfg, child_runtime)
        provider = self._provider_factory(provider_cfg, system_prompt)
        loop = AgentLoop(
            provider,
            child_conversation,
            child_registry,
            child_executor,
            self._agent_limits,
            runtime=child_runtime,
            system_prompt_builder=lambda: self._build_prompt(provider_cfg, child_runtime),
        )
        final_reply = ""
        stop_reason: AgentStopReason | None = None
        error_text = ""
        request = AgentRunRequest(
            _fork_request(skill, args), AgentMode.AGENT, self._permission_mode
        )
        async for event in loop.run(request):
            if event.type == AgentEventType.ASSISTANT_MESSAGE and event.text:
                final_reply = event.text
            elif event.type == AgentEventType.ERROR and event.error is not None:
                error_text = str(event.error)
            elif event.type == AgentEventType.STOPPED:
                stop_reason = event.stop_reason
        if final_reply:
            return final_reply
        if error_text:
            return f"Skill '{skill.meta.name}' failed: {error_text}"
        if stop_reason is not None:
            return f"Skill '{skill.meta.name}' finished with stop reason: {stop_reason.value}"
        return f"Skill '{skill.meta.name}' finished without a model summary."

    def _latest_skill(self, name: str) -> Skill:
        skill = self._catalog.get_latest(name)
        if skill is None:
            raise SkillDependencyError(f"Unknown Skill: {name}")
        return skill

    def _select_provider(self, skill: Skill) -> ProviderConfig:
        if skill.meta.model:
            requested = skill.meta.model.casefold()
            for cfg in self._provider_configs:
                if cfg.name.casefold() == requested or cfg.model.casefold() == requested:
                    return cfg
            raise SkillDependencyError(
                f"Skill '{skill.meta.name}' requested unavailable model '{skill.meta.model}'."
            )
        if self._provider_config is None:
            raise SkillDependencyError(f"Skill '{skill.meta.name}' requires an active provider.")
        return self._provider_config

    def _child_history(self, skill: Skill) -> tuple[ConversationItem, ...]:
        items = self._conversation.items()
        if skill.meta.context == SkillContext.NONE:
            return ()
        if skill.meta.context == SkillContext.RECENT:
            messages = [item for item in items if isinstance(item, ChatMessage)]
            return tuple(messages[-5:])
        return tuple(items)

    def _child_registry(self, skill: Skill) -> ToolRegistry:
        if not skill.meta.allowed_tools:
            return self._registry
        return self._registry.filtered_by_names(skill.meta.allowed_tools)

    def _build_prompt(self, provider_cfg: ProviderConfig, runtime: SessionRuntime) -> str:
        if self._prompt_builder is None:
            return ""
        return self._prompt_builder(provider_cfg, runtime)


def _inline_trigger(skill: Skill, args: str) -> str:
    args = args.strip()
    if args:
        return f"Run active Skill '{skill.meta.name}' for this request: {args}"
    return f"Run active Skill '{skill.meta.name}'."


def _fork_request(skill: Skill, args: str) -> str:
    args = args.strip()
    if args:
        return (
            f"Run fork Skill '{skill.meta.name}' for this request, "
            f"then return a concise summary: {args}"
        )
    return f"Run fork Skill '{skill.meta.name}', then return a concise summary."

