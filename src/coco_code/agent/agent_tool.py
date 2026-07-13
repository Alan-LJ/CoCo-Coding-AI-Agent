from __future__ import annotations

import asyncio
import secrets
from collections.abc import Callable, Sequence
from dataclasses import replace
from time import monotonic
from typing import Any

from coco_code.agent.agent_worktree import _execute_with_worktree
from coco_code.agent.fork import build_forked_messages, is_fork_context
from coco_code.agent.runner import LoopSubAgent, ProviderFactory
from coco_code.agent.runtime import SessionRuntime
from coco_code.agent.types import AgentLimits
from coco_code.config import ProviderConfig
from coco_code.conversation import Conversation
from coco_code.hook import HookEngine
from coco_code.llm import new_provider
from coco_code.permission import Mode as PermissionMode
from coco_code.permission.engine import Engine
from coco_code.subagent import Catalog, Definition
from coco_code.task import Manager
from coco_code.tools.base import (
    ConfirmationPolicy,
    ConfirmCallback,
    ToolCategory,
    ToolContext,
    ToolParams,
    ToolResult,
    ToolSpec,
)
from coco_code.tools.executor import PermissionCallback
from coco_code.tools.filter import FilterParams, apply_agent_tool_filter
from coco_code.tools.registry import ToolRegistry, ToolRegistryError

ProviderConfigGetter = Callable[[], ProviderConfig | None]
ProviderConfigsGetter = Callable[[], Sequence[ProviderConfig]]
ConversationGetter = Callable[[], Conversation]
RuntimeGetter = Callable[[], SessionRuntime]
PermissionModeGetter = Callable[[], PermissionMode]
PromptBuilder = Callable[[ProviderConfig, SessionRuntime], str]
BackgroundEnabled = bool | Callable[[], bool]
AUTO_BACKGROUND_SECONDS = 120.0


class AgentTool:
    def __init__(
        self,
        *,
        catalog: Catalog,
        manager: Manager,
        registry: ToolRegistry,
        tool_context: ToolContext,
        confirm_callback: ConfirmCallback,
        provider_config_getter: ProviderConfigGetter,
        provider_configs_getter: ProviderConfigsGetter,
        conversation_getter: ConversationGetter,
        runtime_getter: RuntimeGetter,
        permission_mode_getter: PermissionModeGetter,
        prompt_builder: PromptBuilder,
        agent_limits: AgentLimits,
        permission_engine: Engine | None = None,
        permission_callback: PermissionCallback | None = None,
        provider_factory: ProviderFactory = new_provider,
        hook_engine: HookEngine | None = None,
        background_enabled: BackgroundEnabled = True,
        auto_background_seconds: float = AUTO_BACKGROUND_SECONDS,
        worktree_mgr: Any | None = None,
    ) -> None:
        self._catalog = catalog
        self._manager = manager
        self._registry = registry
        self._tool_context = tool_context
        self._confirm_callback = confirm_callback
        self._provider_config_getter = provider_config_getter
        self._provider_configs_getter = provider_configs_getter
        self._conversation_getter = conversation_getter
        self._runtime_getter = runtime_getter
        self._permission_mode_getter = permission_mode_getter
        self._prompt_builder = prompt_builder
        self._agent_limits = agent_limits
        self._permission_engine = permission_engine
        self._permission_callback = permission_callback
        self._provider_factory = provider_factory
        self._hook_engine = hook_engine
        self._background_enabled = background_enabled
        self._auto_background_seconds = auto_background_seconds
        self._worktree_mgr = worktree_mgr

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="Agent",
            description=(
                "Delegate a task to an isolated CoCo Code SubAgent. Use type='defined' "
                "for a role loaded from .coco-code/agents or type='fork' to inherit "
                "the current conversation in a background-only fork."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "prompt": {"type": "string"},
                    "type": {"type": "string"},
                    "subagent_type": {"type": "string"},
                    "description": {"type": "string"},
                    "model": {"type": "string"},
                    "run_in_background": {"type": "boolean"},
                    "name": {"type": "string"},
                },
                "required": ["prompt"],
                "additionalProperties": False,
            },
            confirmation=ConfirmationPolicy.NEVER,
            category=ToolCategory.GENERAL,
            read_only=False,
            destructive=False,
            typical_scenarios=(
                "Parallel research or implementation subtask",
                "Role-specific analysis with a clean context",
                "Forked background task that needs parent conversation context",
            ),
        )

    async def run(self, params: ToolParams, context: ToolContext) -> ToolResult:  # noqa: ARG002
        started = monotonic()
        prompt = params.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            return _failure(self.spec.name, "Agent parameter `prompt` must be a string.", started)
        kind = _text_param(params, "type", "defined").casefold()
        if kind in {"fork", "forked"}:
            return await self._run_fork(params, prompt.strip(), started)
        if kind not in {"defined", "definition", "role", "subagent"}:
            return _failure(self.spec.name, f"Unknown Agent type: {kind}", started)
        return await self._run_defined(params, prompt.strip(), started)

    async def _run_defined(
        self,
        params: ToolParams,
        prompt: str,
        started: float,
    ) -> ToolResult:
        definition_name = _text_param(params, "subagent_type", "general-purpose")
        definition = self._catalog.resolve(definition_name)
        if definition is None:
            return _failure(
                self.spec.name,
                f"Unknown SubAgent definition: {definition_name}",
                started,
            )
        background = bool(params.get("run_in_background", False)) or definition.background
        if definition.isolation == "worktree":
            background = False
        if background and not self._is_background_enabled():
            return _failure(self.spec.name, "SubAgent background tasks are disabled.", started)
        try:
            provider_cfg = self._select_provider(
                _text_param(params, "model", definition.model),
                definition.name,
            )
            runner = self._defined_runner(definition, provider_cfg, background)
        except ValueError as exc:
            return _failure(self.spec.name, str(exc), started)

        conv = Conversation()
        if background:
            task_id = await self._manager.launch(
                runner,
                conv,
                _task_name(params, definition.name),
                prompt,
            )
            return _success(
                self.spec.name,
                f"SubAgent task {task_id} launched.",
                {
                    "task_id": task_id,
                    "status": "async_launched",
                    "subagent_type": definition.name,
                },
                started,
            )

        return await self._run_foreground_defined(
            params,
            definition,
            runner,
            conv,
            prompt,
            started,
        )

    async def _run_foreground_defined(
        self,
        params: ToolParams,
        definition: Definition,
        runner: LoopSubAgent,
        conv: Conversation,
        prompt: str,
        started: float,
    ) -> ToolResult:
        if definition.isolation == "worktree":
            if self._worktree_mgr is None:
                return _failure(self.spec.name, "worktree manager not configured", started)
            try:
                result = await _execute_with_worktree(
                    self._worktree_mgr,
                    definition,
                    runner,
                    conv,
                    prompt,
                )
            except Exception as exc:
                return _failure(self.spec.name, f"SubAgent failed: {exc}", started)
            return _success(
                self.spec.name,
                "SubAgent completed.",
                {"status": "completed", "subagent_type": definition.name, "result": result},
                started,
            )
        auto_timeout = self._auto_background_seconds
        if auto_timeout <= 0 or not self._is_background_enabled():
            try:
                result = await runner.run_to_completion(conv, prompt)
            except Exception as exc:
                return _failure(self.spec.name, f"SubAgent failed: {exc}", started)
            return _success(
                self.spec.name,
                "SubAgent completed.",
                {"status": "completed", "subagent_type": definition.name, "result": result},
                started,
            )

        handle = asyncio.create_task(runner.run_to_completion(conv, prompt))
        try:
            result = await asyncio.wait_for(asyncio.shield(handle), timeout=auto_timeout)
        except TimeoutError:
            task_id = await self._manager.adopt_running(
                runner,
                conv,
                _task_name(params, definition.name),
                prompt,
                handle,
            )
            return _success(
                self.spec.name,
                f"SubAgent task {task_id} moved to background after timeout.",
                {
                    "task_id": task_id,
                    "status": "timed_out_to_background",
                    "subagent_type": definition.name,
                },
                started,
            )
        except Exception as exc:
            return _failure(self.spec.name, f"SubAgent failed: {exc}", started)
        return _success(
            self.spec.name,
            "SubAgent completed.",
            {"status": "completed", "subagent_type": definition.name, "result": result},
            started,
        )

    async def _run_fork(
        self,
        params: ToolParams,
        prompt: str,
        started: float,
    ) -> ToolResult:
        if not self._is_background_enabled():
            return _failure(self.spec.name, "Fork SubAgents require background tasks.", started)
        parent = self._conversation_getter()
        parent_items = parent.items()
        if is_fork_context(parent_items):
            return _failure(self.spec.name, "Fork SubAgents cannot create nested forks.", started)
        definition = self._catalog.fork_definition()
        try:
            provider_cfg = self._select_provider(
                _text_param(params, "model", definition.model),
                definition.name,
            )
            runner = self._fork_runner(definition, provider_cfg)
        except ValueError as exc:
            return _failure(self.spec.name, str(exc), started)
        task_id = await self._manager.launch(
            runner,
            Conversation.from_items(build_forked_messages(parent_items, prompt)),
            _task_name(params, "fork"),
            prompt,
            run_text="",
        )
        return _success(
            self.spec.name,
            f"Fork SubAgent task {task_id} launched.",
            {"task_id": task_id, "status": "async_launched", "type": "fork"},
            started,
        )

    def _defined_runner(
        self,
        definition: Definition,
        provider_cfg: ProviderConfig,
        background: bool,
    ) -> LoopSubAgent:
        permission_mode = (
            PermissionMode.BYPASS if definition.dont_ask else definition.permission_mode
        )
        return LoopSubAgent(
            provider_cfg=provider_cfg,
            registry=self._child_registry(definition, background, inherit_parent_tools=False),
            tool_context=self._tool_context,
            confirm_callback=self._confirm_callback,
            prompt_builder=lambda _cfg, _runtime: definition.system_prompt,
            agent_limits=self._limits_for(definition),
            permission_mode=permission_mode,
            provider_factory=self._provider_factory,
            permission_engine=self._permission_engine,
            permission_callback=self._permission_callback,
            hook_engine=self._hook_engine,
        )

    def _fork_runner(
        self,
        definition: Definition,
        provider_cfg: ProviderConfig,
    ) -> LoopSubAgent:
        return LoopSubAgent(
            provider_cfg=provider_cfg,
            registry=self._child_registry(definition, True, inherit_parent_tools=True),
            tool_context=self._tool_context,
            confirm_callback=self._confirm_callback,
            prompt_builder=self._prompt_builder,
            agent_limits=self._limits_for(definition),
            permission_mode=self._permission_mode_getter(),
            provider_factory=self._provider_factory,
            permission_engine=self._permission_engine,
            permission_callback=self._permission_callback,
            hook_engine=self._hook_engine,
        )

    def _limits_for(self, definition: Definition) -> AgentLimits:
        if definition.max_turns <= 0:
            return self._agent_limits
        return replace(self._agent_limits, max_iterations=definition.max_turns)

    def _child_registry(
        self,
        definition: Definition,
        background: bool,
        *,
        inherit_parent_tools: bool,
    ) -> ToolRegistry:
        all_names = list(self._registry.names())
        if inherit_parent_tools:
            active_allowed = self._runtime_getter().active_skills.allowed_tool_union()
            if active_allowed:
                all_names = [name for name in active_allowed if self._has_tool(name)]
        names = apply_agent_tool_filter(
            FilterParams(
                all=all_names,
                source=int(definition.source),
                background=background,
                allowed=list(definition.tools),
                disallowed=list(definition.disallowed_tools),
            )
        )
        return self._registry_by_names(names)

    def _registry_by_names(self, names: Sequence[str]) -> ToolRegistry:
        registry = ToolRegistry()
        seen: set[str] = set()
        for name in names:
            try:
                tool = self._registry.get(name)
            except ToolRegistryError:
                continue
            canonical = tool.spec.name
            if canonical in seen:
                continue
            registry.register(tool)
            seen.add(canonical)
        return registry

    def _has_tool(self, name: str) -> bool:
        try:
            self._registry.get(name)
        except ToolRegistryError:
            return False
        return True

    def _select_provider(self, requested: str, agent_name: str) -> ProviderConfig:
        requested = requested.strip()
        if not requested or requested.casefold() == "inherit":
            active = self._provider_config_getter()
            if active is None:
                raise ValueError(f"SubAgent '{agent_name}' requires an active provider.")
            return active
        configs = tuple(self._provider_configs_getter())
        wanted = requested.casefold()
        for cfg in configs:
            if cfg.name.casefold() == wanted or cfg.model.casefold() == wanted:
                return cfg
        if wanted in {"haiku", "sonnet", "opus"}:
            for cfg in configs:
                if wanted in cfg.name.casefold() or wanted in cfg.model.casefold():
                    return cfg
        for cfg in configs:
            if wanted in cfg.name.casefold() or wanted in cfg.model.casefold():
                return cfg
        raise ValueError(f"SubAgent '{agent_name}' requested unavailable model '{requested}'.")

    def _is_background_enabled(self) -> bool:
        if callable(self._background_enabled):
            return bool(self._background_enabled())
        return bool(self._background_enabled)


def _text_param(params: ToolParams, name: str, default: str) -> str:
    value = params.get(name, default)
    return value.strip() if isinstance(value, str) else default


def _task_name(params: ToolParams, default: str) -> str:
    name = _text_param(params, "name", "")
    if name:
        return name
    return f"{default}-{secrets.token_hex(2)}"


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
