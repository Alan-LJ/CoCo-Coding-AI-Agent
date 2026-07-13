from __future__ import annotations

import asyncio
import os
import sys
from contextlib import suppress
from dataclasses import replace
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from time import monotonic, time
from typing import Any

from textual import events, on
from textual.app import App, ComposeResult, ScreenStackError
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, OptionList, RichLog, Static, TextArea

from coco_code import __version__
from coco_code.agent import (
    AgentEvent,
    AgentEventType,
    AgentLimits,
    AgentLoop,
    AgentMode,
    AgentProgress,
    AgentRunRequest,
    AgentStopReason,
)
from coco_code.agent.agent_tool import AgentTool
from coco_code.agent.runtime import SessionRuntime, new_session_runtime
from coco_code.command import (
    CommandMemory,
    CommandSession,
    CommandStatus,
    build_default_registry,
    register_skill_commands,
    register_skill_management_command,
)
from coco_code.compact.manager import auto_threshold
from coco_code.compact.recovery import RecoveryState
from coco_code.compact.state import (
    CompactCircuitBreaker,
    ContentReplacementState,
    open_session_context,
)
from coco_code.compact.token import estimate_tokens
from coco_code.config import Config, ConfigError, ProviderConfig, effective_context_window
from coco_code.conversation import ChatMessage, Conversation
from coco_code.hook import DispatchResult, Event, HookEngine
from coco_code.llm import Provider, new_provider
from coco_code.mcp import McpConfig, McpManager
from coco_code.memory import MemoryManager
from coco_code.permission import Mode as PermissionMode
from coco_code.permission import Outcome
from coco_code.permission.engine import Engine
from coco_code.prompt import build_system_prompt, render_banner
from coco_code.session import (
    SessionInfo,
    SessionWriter,
    clean_expired_sessions,
    list_sessions,
    load_session,
    session_paths,
)
from coco_code.skills.catalog import USER_SKILLS_DIR, SkillCatalog
from coco_code.skills.executor import SkillExecutor
from coco_code.skills.render import render_active_skills_block
from coco_code.skills.types import SkillCatalogItem
from coco_code.subagent import Catalog as SubAgentCatalog
from coco_code.subagent import load_catalog as load_subagent_catalog
from coco_code.task import Manager as TaskManager
from coco_code.task import SendMessageTool, TaskGetTool, TaskListTool, TaskStopTool
from coco_code.tools import (
    ConfirmationPolicy,
    ToolCall,
    ToolContext,
    ToolExecutor,
    ToolSpec,
    create_default_registry,
)
from coco_code.tools.base import ConfirmCallback
from coco_code.tools.ctx import with_cwd
from coco_code.tools.executor import PermissionCallback
from coco_code.tools.install_skill import InstallSkillTool
from coco_code.tools.load_skill import LoadSkillTool
from coco_code.tools.registry import ToolRegistry, ToolRegistryError
from coco_code.tui.commands import dispatch_command, format_compact_notice, render_compact_error
from coco_code.tui.complete import CompletionMenu
from coco_code.tui.resume import ResumeSessionScreen
from coco_code.tui.select import ProviderOptionList
from coco_code.tui.tools_view import tool_list_block
from coco_code.tui.view import (
    agent_progress_text,
    agent_stop_block,
    assistant_markdown,
    error_block,
    mode_status_text,
    notice_block,
    tool_batch_block,
    tool_call_block,
    tool_confirm_block,
    tool_permission_block,
    tool_result_block,
    user_block,
)
from coco_code.tui.worktree_adapter import WorktreeAdapter
from coco_code.worktree import Manager as WorktreeManager

DEFAULT_RESPONSE_TIMEOUT_SECONDS = 300.0


class SessionState(StrEnum):
    SELECTING = "selecting"
    IDLE = "idle"
    STREAMING = "streaming"
    RESUMING = "resuming"


class PromptSubmitted(events.Message):
    def __init__(self, text: str) -> None:
        self.text = text
        super().__init__()


class HistoryRequested(events.Message):
    def __init__(self, direction: int) -> None:
        self.direction = direction
        super().__init__()


class PermissionModeRequested(events.Message):
    pass


class CompletionKeyRequested(events.Message):
    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__()


CANCEL_KEYS = {"escape", "ctrl+c"}
CTRL_C_EXIT_WINDOW_SECONDS = 1.5
CTRL_C_DUPLICATE_EVENT_SECONDS = 0.05
FORCE_EXIT_GRACE_SECONDS = 1.0
FORCE_EXIT_RETURN_CODE = 130


class PromptTextArea(TextArea):
    def on_key(self, event: events.Key) -> None:
        handle_key_interrupt = getattr(self.app, "handle_key_interrupt", None)
        if (
            event.key in CANCEL_KEYS
            and callable(handle_key_interrupt)
            and handle_key_interrupt(event.key)
        ):
            event.prevent_default()
            event.stop()
            return
        completion = getattr(self.app, "completion_menu", None)
        completion_active = bool(getattr(completion, "active", False))
        if event.key in {"enter", "tab", "escape", "up", "down"} and (
            completion_active or (event.key == "tab" and self.text.strip().startswith("/"))
        ):
            event.prevent_default()
            event.stop()
            self.post_message(CompletionKeyRequested(event.key))
        elif event.key == "enter":
            event.prevent_default()
            event.stop()
            self.post_message(PromptSubmitted(self.text))
        elif event.key in {"alt+enter", "ctrl+j"}:
            event.prevent_default()
            event.stop()
            self.insert("\n")
        elif event.key == "shift+tab":
            event.prevent_default()
            event.stop()
            self.post_message(PermissionModeRequested())
        elif event.key == "up":
            event.prevent_default()
            event.stop()
            self.post_message(HistoryRequested(-1))
        elif event.key == "down":
            event.prevent_default()
            event.stop()
            self.post_message(HistoryRequested(1))


class ConfirmToolScreen(ModalScreen[bool]):
    CSS = """
    ConfirmToolScreen {
        align: center middle;
    }

    #confirm-dialog {
        width: 80%;
        height: auto;
        max-height: 80%;
        border: round red;
        padding: 1 2;
        background: $surface;
    }

    #confirm-body {
        height: auto;
    }

    #confirm-actions {
        height: auto;
    }

    #confirm-actions Button {
        margin: 0 1;
    }
    """

    BINDINGS = [
        ("escape", "reject", "Reject"),
    ]

    def __init__(self, call: ToolCall, spec: ToolSpec) -> None:
        super().__init__()
        self.call = call
        self.spec = spec

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-dialog"):
            yield Static(tool_confirm_block(self.call, self.spec), id="confirm-body")
            with Horizontal(id="confirm-actions"):
                yield Button("Approve", id="approve", variant="success")
                yield Button("Reject", id="reject", variant="error")

    @on(Button.Pressed)
    def button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "approve")

    def action_reject(self) -> None:
        self.dismiss(False)


class PermissionToolScreen(ModalScreen[Outcome]):
    CSS = """
    PermissionToolScreen {
        align: center middle;
    }

    #permission-dialog {
        width: 84%;
        height: auto;
        max-height: 85%;
        border: round red;
        padding: 1 2;
        background: $surface;
    }

    #permission-body {
        height: auto;
    }

    #permission-actions {
        height: auto;
    }

    #permission-actions Button {
        margin: 0 1;
    }
    """

    BINDINGS = [
        ("escape", "reject", "Reject"),
    ]

    def __init__(self, call: ToolCall, spec: ToolSpec, reason: str) -> None:
        super().__init__()
        self.call = call
        self.spec = spec
        self.reason = reason

    def compose(self) -> ComposeResult:
        with Vertical(id="permission-dialog"):
            yield Static(
                tool_permission_block(self.call, self.spec, self.reason), id="permission-body"
            )
            with Horizontal(id="permission-actions"):
                yield Button("Allow once", id="allow-once", variant="success")
                yield Button("Always allow", id="allow-forever", variant="primary")
                yield Button("Reject", id="deny-once", variant="error")

    @on(Button.Pressed)
    def button_pressed(self, event: Button.Pressed) -> None:
        outcomes = {
            "allow-once": Outcome.ALLOW_ONCE,
            "allow-forever": Outcome.ALLOW_FOREVER,
            "deny-once": Outcome.DENY_ONCE,
        }
        self.dismiss(outcomes.get(event.button.id or "", Outcome.DENY_ONCE))

    def action_reject(self) -> None:
        self.dismiss(Outcome.DENY_ONCE)


class CoCoCodeApp(App[None]):
    CSS = """
    Screen {
        layout: vertical;
    }

    #history {
        height: 1fr;
        border: round $primary;
    }

    #stream {
        min-height: 3;
        max-height: 10;
        border: round yellow;
    }

    #input {
        height: 7;
        border: round $accent;
    }

    #completion {
        height: auto;
        max-height: 8;
        border: round $secondary;
    }

    #status {
        height: 1;
        background: $boost;
    }

    #provider-select {
        height: auto;
        border: round $primary;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel_streaming", "Cancel", show=False, priority=True),
        Binding("ctrl+c", "interrupt", "Interrupt", priority=True),
    ]

    def __init__(
        self,
        config: Config,
        cwd: Path | None = None,
        tool_registry: ToolRegistry | None = None,
        tool_context: ToolContext | None = None,
        confirm_callback: ConfirmCallback | None = None,
        response_timeout_seconds: float = DEFAULT_RESPONSE_TIMEOUT_SECONDS,
        permission_engine: Engine | None = None,
        permission_callback: PermissionCallback | None = None,
        mcp_config: McpConfig | None = None,
        mcp_manager: McpManager | None = None,
        runtime: SessionRuntime | None = None,
        instruction_text: str = "",
        memory_manager: MemoryManager | None = None,
        session_writer: SessionWriter | None = None,
        show_startup_resume: bool = True,
        hook_engine: HookEngine | None = None,
        subagent_catalog: SubAgentCatalog | None = None,
        task_manager: TaskManager | None = None,
        worktree_mgr: WorktreeManager | None = None,
    ) -> None:
        super().__init__()
        self.config = config
        self.cwd = cwd or Path.cwd()
        self.worktree_mgr = worktree_mgr
        self.active_cwd = ""
        session = self.worktree_mgr.current_session() if self.worktree_mgr is not None else None
        if session is not None:
            self.active_cwd = session.worktree_path
        self.runtime = runtime or new_session_runtime(self.cwd, context_window=0)
        self.hook_engine = hook_engine
        self.instruction_text = instruction_text
        self.memory_manager = memory_manager
        self.session_writer = session_writer
        self.show_startup_resume = show_startup_resume
        self._startup_resume_shown = False
        self.tool_registry = tool_registry or create_default_registry()
        self.task_manager = task_manager or TaskManager()
        self.subagent_catalog = subagent_catalog or load_subagent_catalog(self.cwd)
        self.skill_catalog = SkillCatalog.load(self.cwd)
        self._skills_catalog_text = self.skill_catalog.catalog_text()
        self._load_skill_tool = LoadSkillTool(self.skill_catalog, self.runtime.active_skills)
        self._install_skill_tool = InstallSkillTool(
            USER_SKILLS_DIR, reload_callback=self.reload_skills
        )
        for tool in (self._load_skill_tool, self._install_skill_tool):
            try:
                self.tool_registry.get(tool.spec.name)
            except ToolRegistryError:
                self.tool_registry.register(tool)
        self.command_registry = build_default_registry()
        self.skill_executor: SkillExecutor | None = None
        self.completion_menu = CompletionMenu()
        self.tool_context = tool_context or ToolContext(workspace=self.cwd)
        self._confirm_callback = confirm_callback
        self._permission_callback = permission_callback
        self.mcp_config = mcp_config
        self.mcp_manager = mcp_manager
        self.permission_engine = permission_engine
        self.permission_mode = (
            permission_engine.start_mode
            if permission_engine is not None
            else PermissionMode.DEFAULT
        )
        self.response_timeout_seconds = response_timeout_seconds
        self.agent_limits = AgentLimits(
            response_timeout_seconds=response_timeout_seconds,
            tool_timeout_seconds=self.tool_context.timeout_seconds,
            confirm_timeout_seconds=self.tool_context.confirm_timeout_seconds,
        )
        self._agent_tool: AgentTool | None = None
        self._register_subagent_tools()
        self.tool_executor = ToolExecutor(
            self.tool_registry,
            self.tool_context,
            self.confirm_tool_call,
            permission_engine,
            self.confirm_permission_call if permission_engine is not None else None,
            self.permission_mode,
        )
        self.state = SessionState.SELECTING if len(config.providers) > 1 else SessionState.IDLE
        self.active_cfg: ProviderConfig | None = None
        self.provider: Provider | None = None
        self.conversation = Conversation(
            on_append=session_writer.append_item if session_writer is not None else None,
            on_replace=session_writer.replace_items if session_writer is not None else None,
        )
        self.input_history: list[str] = []
        self.history_cursor: int | None = None
        self.current_reply = ""
        self.agent_mode = AgentMode.AGENT
        self.current_progress: AgentProgress | None = None
        self.turn_start = 0.0
        self.stream_task: asyncio.Task[None] | None = None
        self.timer: Any | None = None
        self._closing = False
        self._turn_token = 0
        self._ctrl_c_exit_deadline = 0.0
        self._last_ctrl_c_handled_at = 0.0
        self._detached_turn_tasks: set[asyncio.Task[None]] = set()
        self._mcp_close_task: asyncio.Task[None] | None = None
        self._task_done_consumer_task: asyncio.Task[None] | None = None
        self._force_exit_handle: asyncio.TimerHandle | None = None

    def compose(self) -> ComposeResult:
        if len(self.config.providers) > 1:
            yield Static("Select a provider for this session:", id="select-title")
            yield ProviderOptionList(self.config.providers)
        yield RichLog(id="history", wrap=True, markup=False)
        yield Static("", id="stream")
        yield PromptTextArea("", id="input")
        yield Static("", id="completion")
        yield Static("", id="status")

    def _register_subagent_tools(self) -> None:
        permission_callback = (
            self.confirm_permission_call if self.permission_engine is not None else None
        )
        self._agent_tool = AgentTool(
            catalog=self.subagent_catalog,
            manager=self.task_manager,
            registry=self.tool_registry,
            tool_context=self.tool_context,
            confirm_callback=self.confirm_tool_call,
            provider_config_getter=lambda: self.active_cfg,
            provider_configs_getter=lambda: tuple(self.config.providers),
            conversation_getter=lambda: self.conversation,
            runtime_getter=lambda: self.runtime,
            permission_mode_getter=lambda: self.permission_mode,
            prompt_builder=lambda cfg, runtime: self.build_current_system_prompt(cfg, runtime),
            agent_limits=self.agent_limits,
            permission_engine=self.permission_engine,
            permission_callback=permission_callback,
            hook_engine=self.hook_engine,
            background_enabled=lambda: self.config.enable_subagent_background,
            worktree_mgr=self.worktree_mgr,
        )
        for tool in (
            TaskListTool(self.task_manager),
            TaskGetTool(self.task_manager),
            TaskStopTool(self.task_manager),
            SendMessageTool(self.task_manager),
            self._agent_tool,
        ):
            try:
                self.tool_registry.get(tool.spec.name)
            except ToolRegistryError:
                self.tool_registry.register(tool)

    async def on_mount(self) -> None:
        self.timer = self.set_interval(1.0, self.refresh_streaming, pause=True)
        self._task_done_consumer_task = asyncio.create_task(self._consume_task_done())
        if self.worktree_mgr is not None:
            asyncio.create_task(
                self.worktree_mgr.sweep_stale(datetime.now() - timedelta(hours=24))
            )
        asyncio.create_task(asyncio.to_thread(clean_expired_sessions, self.cwd))
        await self.start_mcp()
        self.setup_skills_after_tools_ready()
        if len(self.config.providers) == 1:
            self.activate_provider(self.config.providers[0])
        else:
            self.query_one("#input", PromptTextArea).disabled = True
            self.query_one(ProviderOptionList).focus()

    async def _consume_task_done(self) -> None:
        queue = self.task_manager.subscribe_done()
        while True:
            task_id = await queue.get()
            task = self.task_manager.get(task_id)
            if task is None:
                continue
            label = task.name or task.id
            status = task.status.value
            if status == "completed":
                detail = f"SubAgent task {label} completed. Use TaskGet for the full result."
                preview = task.result.strip()
                if preview:
                    if len(preview) > 500:
                        preview = preview[:500] + "..."
                    detail = f"{detail}\n{preview}"
            elif status == "failed":
                detail = f"SubAgent task {label} failed: {task.err}"
            else:
                detail = f"SubAgent task {label} {status}."
            self.runtime.append_hook_reminders([detail])
            with suppress(Exception):
                self.query_one("#history", RichLog).write(notice_block(detail))

    async def start_mcp(self) -> None:
        if self.mcp_manager is None:
            if self.mcp_config is None or not self.mcp_config.servers:
                return
            self.mcp_manager = McpManager(self.mcp_config, __version__)
        history = self.query_one("#history", RichLog)
        if self.mcp_config is not None and self.mcp_config.servers:
            history.write(notice_block("Loading MCP tools..."))
        await self.mcp_manager.start()
        for tool in self.mcp_manager.tools():
            try:
                self.tool_registry.register(tool)
            except ToolRegistryError:
                print(
                    f"[mcp] warn: skip registered tool {tool.spec.name}: duplicate name",
                    file=sys.stderr,
                )

    def setup_skills_after_tools_ready(self) -> None:
        self._validate_skill_tools()
        self._skills_catalog_text = self.skill_catalog.catalog_text()
        self._load_skill_tool.attach(self.skill_catalog, self.runtime.active_skills)
        self._install_skill_tool.set_reload_callback(self.reload_skills)
        register_skill_management_command(
            self.command_registry,
            self.skill_catalog,
            self.reload_skills,
        )
        self._register_skill_commands()

    def reload_skills(self) -> None:
        self.skill_catalog.reload()
        self._validate_skill_tools()
        self._skills_catalog_text = self.skill_catalog.catalog_text()
        self._load_skill_tool.attach(self.skill_catalog, self.runtime.active_skills)
        self._register_skill_commands()
        if self.provider is not None and self.active_cfg is not None:
            self.provider.set_system_prompt(self.build_current_system_prompt())

    def _validate_skill_tools(self) -> None:
        issues = self.skill_catalog.validate_tools(self.tool_registry)
        if not issues:
            return
        self.skill_catalog.remove_invalid(issues)
        for issue in issues:
            try:
                self.show_error(issue.message)
            except Exception:
                print(f"[skills] error: {issue.message}", file=sys.stderr)

    def _register_skill_commands(self) -> None:
        self.skill_executor = self._make_skill_executor()
        try:
            register_skill_commands(self.command_registry, self.skill_catalog, self.skill_executor)
        except RuntimeError as exc:
            try:
                self.show_error(str(exc))
            except Exception:
                print(f"[skills] error: {exc}", file=sys.stderr)

    def _make_skill_executor(self) -> SkillExecutor:
        permission_callback = (
            self.confirm_permission_call if self.permission_engine is not None else None
        )
        return SkillExecutor(
            catalog=self.skill_catalog,
            runtime=self.runtime,
            conversation=self.conversation,
            registry=self.tool_registry,
            tool_context=self.tool_context,
            confirm_callback=self.confirm_tool_call,
            provider_config=self.active_cfg,
            provider_configs=self.config.providers,
            agent_limits=self.agent_limits,
            permission_engine=self.permission_engine,
            permission_callback=permission_callback,
            permission_mode=self.permission_mode,
            prompt_builder=self.build_current_system_prompt,
        )

    def build_current_system_prompt(
        self,
        provider_cfg: ProviderConfig | None = None,
        runtime: SessionRuntime | None = None,
    ) -> str:
        cfg = provider_cfg or self.active_cfg
        if cfg is None:
            raise ConfigError("No active provider is available for system prompt construction.")
        runtime = runtime or self.runtime
        memory_text = (
            self.memory_manager.load_index_text() if self.memory_manager is not None else ""
        )
        return build_system_prompt(
            self.cwd,
            cfg,
            instructions=self.instruction_text,
            memory=memory_text,
            skills_catalog=self._skills_catalog_text,
            active_skills=render_active_skills_block(runtime.active_skills.snapshot()),
        )

    async def _dispatch_hook(
        self,
        event: Event,
        payload: dict[str, Any] | None = None,
        runtime: SessionRuntime | None = None,
    ) -> DispatchResult:
        if self.hook_engine is None:
            return DispatchResult()
        active_runtime = runtime or self.runtime
        merged = {
            "event": event.value,
            "session_id": active_runtime.session.session_id,
            "cwd": str(self.cwd),
            "mode": str(self.permission_mode),
        }
        if payload:
            merged.update(payload)
        result = await self.hook_engine.dispatch(event, merged, active_runtime)
        if result.injected_prompts:
            active_runtime.append_hook_reminders(result.injected_prompts)
        return result

    async def _dispatch_session_start(self) -> None:
        await self._dispatch_hook(Event.SESSION_START)

    async def _dispatch_session_end(self) -> None:
        await self._dispatch_hook(Event.SESSION_END)

    async def _dispatch_session_resume(self) -> None:
        await self._dispatch_hook(Event.SESSION_RESUME)

    async def clear_history_with_hooks(self) -> None:
        await self._dispatch_session_end()
        self.runtime.reset_hook_state()
        self.clear_history()
        await self._dispatch_session_start()

    def hook_rules(self):
        return [] if self.hook_engine is None else list(self.hook_engine.rules())

    def hook_sources(self) -> list[str]:
        if self.hook_engine is None:
            return []
        return [str(path) for path in self.hook_engine.sources()]
    @on(OptionList.OptionSelected)
    def provider_selected(self, event: OptionList.OptionSelected) -> None:
        if not isinstance(event.option_list, ProviderOptionList):
            return
        event.stop()
        index = getattr(event, "option_index", None)
        if index is None:
            index = getattr(event, "index", None)
        if index is None:
            index = self.query_one(ProviderOptionList).highlighted or 0
        self.activate_provider(self.config.providers[int(index)])
        selector = self.query_one(ProviderOptionList)
        selector.display = False
        title = self.query_one("#select-title", Static)
        title.display = False

    @on(PromptSubmitted)
    async def prompt_submitted(self, event: PromptSubmitted) -> None:
        if self.state != SessionState.IDLE:
            return
        text = event.text.strip()
        if not text:
            self.hide_completion()
            return
        if await dispatch_command(self, text):
            return
        result = await self._dispatch_hook(
            Event.USER_PROMPT_SUBMIT,
            {
                "prompt": text,
                "mode": str(self.permission_mode),
            },
        )
        if result.blocked:
            self.show_error(f"[hook {result.blocking_hook_name}] {result.reason}")
            input_box = self.query_one("#input", PromptTextArea)
            input_box.text = text
            input_box.focus()
            return
        self.submit_user_text(text)

    @on(CompletionKeyRequested)
    async def completion_key_requested(self, event: CompletionKeyRequested) -> None:
        input_box = self.query_one("#input", PromptTextArea)
        self.sync_completion()
        if event.key == "escape":
            self.hide_completion()
            return
        if event.key == "up":
            self.completion_menu.move_up()
            self.render_completion()
            return
        if event.key == "down":
            self.completion_menu.move_down()
            self.render_completion()
            return
        if event.key == "tab":
            completion = self.completion_menu.single_completion()
            if completion is not None:
                input_box.text = completion
                self.hide_completion()
                return
        if event.key in {"enter", "tab"}:
            selected = self.completion_menu.selected()
            if selected is None:
                self.hide_completion()
                return
            self.hide_completion()
            await dispatch_command(self, f"/{selected.name}")

    @on(TextArea.Changed)
    def input_changed(self, event: TextArea.Changed) -> None:
        if getattr(event.text_area, "id", None) == "input":
            self.sync_completion()

    @on(HistoryRequested)
    def history_requested(self, event: HistoryRequested) -> None:
        if self.state != SessionState.IDLE or not self.input_history:
            return
        if self.history_cursor is None:
            self.history_cursor = len(self.input_history)
        next_cursor = self.history_cursor + event.direction
        self.history_cursor = max(0, min(len(self.input_history) - 1, next_cursor))
        self.query_one("#input", PromptTextArea).text = self.input_history[self.history_cursor]

    @on(PermissionModeRequested)
    def permission_mode_requested(self, event: PermissionModeRequested) -> None:
        event.stop()
        if self.state != SessionState.IDLE:
            return
        self.permission_mode = next_permission_mode(self.permission_mode)
        self.query_one("#history", RichLog).write(
            notice_block(f"Permission mode: {self.permission_mode}")
        )
        self.update_status()

    def activate_provider(self, provider_cfg: ProviderConfig) -> None:
        try:
            system_prompt = self.build_current_system_prompt(provider_cfg)
            self.provider = new_provider(provider_cfg, system_prompt)
            if self.memory_manager is not None:
                self.memory_manager.set_provider(self.provider)
            if self.session_writer is not None:
                self.session_writer.model = provider_cfg.model
        except ConfigError as exc:
            self.query_one("#history", RichLog).write(error_block(exc))
            self.query_one("#input", PromptTextArea).disabled = True
            self.state = SessionState.IDLE
            return

        self.active_cfg = provider_cfg
        self._register_skill_commands()
        self.runtime.context_window = effective_context_window(provider_cfg)
        history = self.query_one("#history", RichLog)
        history.clear()
        history.write(render_banner(__version__, self.cwd, provider_cfg))
        self.show_tools()
        input_box = self.query_one("#input", PromptTextArea)
        input_box.disabled = False
        input_box.focus()
        self.state = SessionState.IDLE
        self.update_status()
        asyncio.create_task(self._dispatch_session_start())
        self._maybe_show_startup_resume()

    def submit_user_text(
        self,
        text: str,
        *,
        display_text: str | None = None,
        mode: AgentMode | None = None,
        permission_mode: PermissionMode | None = None,
    ) -> None:
        self._reset_ctrl_c_exit_sequence()
        if self.provider is None or self.active_cfg is None:
            return
        if mode is None and permission_mode is None:
            request = parse_agent_request(text)
        else:
            request = AgentRunRequest(text, mode or self.agent_mode, permission_mode)
        if request.permission_mode is not None:
            self.permission_mode = request.permission_mode
        request = replace(request, permission_mode=request.permission_mode or self.permission_mode)
        self.agent_mode = request.mode
        input_box = self.query_one("#input", PromptTextArea)
        input_box.text = ""
        input_box.disabled = True
        self.hide_completion()
        self.input_history.append(display_text or text)
        self.history_cursor = None
        self.query_one("#history", RichLog).write(user_block(display_text or text))
        self.state = SessionState.STREAMING
        self.current_reply = ""
        self.current_progress = None
        self.turn_start = monotonic()
        self.refresh_streaming()
        if self.timer is not None:
            self.timer.resume()
        self._turn_token += 1
        turn_token = self._turn_token
        self.stream_task = asyncio.create_task(self._run_agent_turn(request, turn_token))

    async def _run_agent_turn(self, request: AgentRunRequest, turn_token: int) -> None:
        assert self.provider is not None
        try:
            with with_cwd(self._effective_cwd()):
                loop = AgentLoop(
                    self.provider,
                    self.conversation,
                    self.tool_registry,
                    self.tool_executor,
                    self.agent_limits,
                    runtime=self.runtime,
                    memory_manager=self.memory_manager,
                    system_prompt_builder=self.build_current_system_prompt,
                    hook_engine=self.hook_engine,
                )
                async for event in loop.run(request):
                    if not self.is_current_turn(turn_token):
                        return
                    await self.handle_agent_event(event)
        except asyncio.CancelledError:
            if not self._closing and self.is_current_turn(turn_token):
                self.finish_cancelled_turn()
        except Exception as exc:
            if self.is_current_turn(turn_token):
                self.query_one("#history", RichLog).write(error_block(exc))
                self.finish_streaming()

    async def handle_agent_event(self, event: AgentEvent) -> None:
        history = self.query_one("#history", RichLog)
        if event.type == AgentEventType.MODE_CHANGED:
            self.agent_mode = event.mode or self.agent_mode
            if event.permission_mode is not None:
                self.permission_mode = event.permission_mode
            self.update_status()
        elif event.type == AgentEventType.PROGRESS:
            self.current_progress = event.progress
            self.refresh_streaming()
            self.update_status()
        elif event.type == AgentEventType.TEXT_DELTA:
            await self.append_text_delta(event.text)
        elif event.type == AgentEventType.ASSISTANT_MESSAGE:
            if event.text:
                history.write(assistant_markdown(event.text))
            self.current_reply = ""
            self.refresh_streaming()
        elif event.type == AgentEventType.TOOL_CALLS:
            for call in event.tool_calls:
                try:
                    spec = self.tool_registry.get(call.name).spec
                except ToolRegistryError:
                    spec = None
                history.write(tool_call_block(call, spec))
                if (
                    self.permission_engine is None
                    and spec is not None
                    and spec.confirmation == ConfirmationPolicy.REQUIRED
                ):
                    history.write(tool_confirm_block(call, spec))
        elif event.type == AgentEventType.TOOL_BATCH_STARTED:
            history.write(tool_batch_block(None, None, event.tool_calls, len(event.tool_calls) > 1))
        elif event.type == AgentEventType.TOOL_STARTED:
            if self.current_progress is not None and event.tool_call is not None:
                self.current_progress = AgentProgress(
                    iteration=self.current_progress.iteration,
                    max_iterations=self.current_progress.max_iterations,
                    phase="executing_tool",
                    tool_name=event.tool_call.name,
                )
                self.refresh_streaming()
                self.update_status()
        elif event.type == AgentEventType.TOOL_RESULT:
            if event.tool_result is not None:
                history.write(tool_result_block(event.tool_result))
        elif event.type == AgentEventType.COMPACT:
            if event.compact is not None:
                history.write(notice_block(format_compact_notice(event.compact)))
        elif event.type == AgentEventType.ERROR:
            if event.error is not None:
                history.write(error_block(event.error))
        elif event.type == AgentEventType.STOPPED:
            if event.stop_reason is not None and event.stop_reason != AgentStopReason.MODEL_DONE:
                history.write(agent_stop_block(event.stop_reason))
            self.finish_streaming()

    def show_tools(self) -> None:
        self.query_one("#history", RichLog).write(tool_list_block(self.tool_registry))

    def begin_resume(self, *, startup: bool = False) -> None:
        history = self.query_one("#history", RichLog)
        if self.state == SessionState.STREAMING:
            history.write(
                notice_block(
                    "\u8bf7\u7b49\u5f85\u5f53\u524d\u4efb\u52a1\u5b8c\u6210\u540e\u518d\u6062\u590d\u4f1a\u8bdd\u3002"
                )
            )
            return
        if self.state not in {SessionState.IDLE, SessionState.SELECTING}:
            return
        sessions = list_sessions(self.cwd)
        if not sessions:
            if not startup:
                history.write(
                    notice_block(
                        "\u6ca1\u6709\u53ef\u6062\u590d\u7684\u5386\u53f2\u4f1a\u8bdd\u3002"
                    )
                )
            return
        self.state = SessionState.RESUMING

        def resolve(selection: SessionInfo | None) -> None:
            if selection is None:
                self.state = SessionState.IDLE
                self.update_status()
                return
            asyncio.create_task(self._restore_session(selection))

        self.push_screen(ResumeSessionScreen(sessions), callback=resolve)

    def _maybe_show_startup_resume(self) -> None:
        if not self.show_startup_resume or self._startup_resume_shown:
            return
        self._startup_resume_shown = True
        self.call_later(lambda: self.begin_resume(startup=True))

    async def _restore_session(self, info: SessionInfo) -> None:
        await self._dispatch_session_end()
        history = self.query_one("#history", RichLog)
        paths = session_paths(self.cwd, info.session_id)
        restored_runtime = SessionRuntime(
            replacement=ContentReplacementState(),
            recovery=RecoveryState(),
            circuit_breaker=CompactCircuitBreaker(),
            session=open_session_context(self.cwd, info.session_id),
            context_window=self.runtime.context_window,
        )
        loaded = load_session(paths)
        items = list(loaded.items)
        if loaded.last_timestamp is not None and time() - loaded.last_timestamp > 6 * 60 * 60:
            stale_notice = (
                "[\u7cfb\u7edf\u63d0\u793a] "
                "\u672c\u4f1a\u8bdd\u5df2\u6682\u505c\u8d85\u8fc7 6 \u5c0f\u65f6\u3002"
                "\u90e8\u5206\u4e0a\u4e0b\u6587\u53ef\u80fd\u5df2\u8fc7\u65f6\uff0c"
                "\u5982\u9700\u6700\u65b0\u4fe1\u606f\u8bf7\u91cd\u65b0\u8bfb\u53d6\u76f8\u5173\u6587\u4ef6\u3002"
            )
            items.append(ChatMessage(role="user", content=stale_notice))
        if self.provider is not None and estimate_tokens(0, items, 0) >= auto_threshold(
            self.runtime.context_window
        ):
            temp = Conversation.from_items(items)
            loop = AgentLoop(
                self.provider,
                temp,
                self.tool_registry,
                self.tool_executor,
                self.agent_limits,
                runtime=restored_runtime,
                memory_manager=self.memory_manager,
                system_prompt_builder=lambda: self.build_current_system_prompt(
                    runtime=restored_runtime
                ),
                hook_engine=self.hook_engine,
            )
            try:
                await loop.run_force_compact(self.agent_mode)
            except Exception as exc:
                history.write(
                    error_block(f"\u6062\u590d\u4f1a\u8bdd\u538b\u7f29\u5931\u8d25: {exc}")
                )
                self.state = SessionState.IDLE
                return
            items = temp.items()
        if self.session_writer is not None:
            self.session_writer.close()
        writer = SessionWriter.open_existing(
            paths, model=self.active_cfg.model if self.active_cfg else None
        )
        self.session_writer = writer
        self.conversation = Conversation.from_items(
            items,
            on_append=writer.append_item,
            on_replace=writer.replace_items,
        )
        self.runtime = restored_runtime
        self._load_skill_tool.attach(self.skill_catalog, self.runtime.active_skills)
        self._register_skill_commands()
        restored_notice = (
            f"\u5df2\u6062\u590d\u4f1a\u8bdd {info.session_id}\uff0c"
            f"\u5171 {len(items)} \u6761\u6d88\u606f"
        )
        history.write(notice_block(restored_notice))
        self.state = SessionState.IDLE
        await self._dispatch_session_resume()
        self.update_status()

    async def run_manual_compact(self) -> None:
        if self.provider is None or self.active_cfg is None:
            return
        loop = AgentLoop(
            self.provider,
            self.conversation,
            self.tool_registry,
            self.tool_executor,
            self.agent_limits,
            runtime=self.runtime,
            system_prompt_builder=self.build_current_system_prompt,
            hook_engine=self.hook_engine,
        )
        try:
            output = await loop.run_force_compact(self.agent_mode)
        except Exception as exc:
            render_compact_error(self, exc)
            return
        self.query_one("#history", RichLog).write(notice_block(format_compact_notice(output)))
        self.update_status()

    async def confirm_tool_call(self, call: ToolCall, spec: ToolSpec) -> bool:
        if self._confirm_callback is not None:
            return await self._confirm_callback(call, spec)

        loop = asyncio.get_running_loop()
        result: asyncio.Future[bool] = loop.create_future()

        def resolve_confirmation(approved: bool | None) -> None:
            if not result.done():
                result.set_result(bool(approved))

        self.push_screen(ConfirmToolScreen(call, spec), callback=resolve_confirmation)
        return await result

    async def confirm_permission_call(self, call: ToolCall, spec: ToolSpec, reason: str) -> Outcome:
        await self._dispatch_hook(
            Event.NOTIFICATION,
            {"kind": "approval", "detail": call.name},
        )
        if self._permission_callback is not None:
            return await self._permission_callback(call, spec, reason)
        if self._confirm_callback is not None:
            approved = await self._confirm_callback(call, spec)
            return Outcome.ALLOW_ONCE if approved else Outcome.DENY_ONCE

        loop = asyncio.get_running_loop()
        result: asyncio.Future[Outcome] = loop.create_future()

        def resolve_permission(outcome: Outcome | None) -> None:
            if not result.done():
                result.set_result(outcome or Outcome.DENY_ONCE)

        self.push_screen(PermissionToolScreen(call, spec, reason), callback=resolve_permission)
        return await result

    async def append_text_delta(self, text: str) -> None:
        self.current_reply += text
        self.refresh_streaming()

    def refresh_streaming(self) -> None:
        if self.state != SessionState.STREAMING:
            return
        elapsed = int(monotonic() - self.turn_start)
        self.query_one("#stream", Static).update(
            agent_progress_text(self.current_reply, elapsed, self.current_progress)
        )

    def finish_streaming(self) -> None:
        if self.timer is not None:
            self.timer.pause()
        self.query_one("#stream", Static).update("")
        self.state = SessionState.IDLE
        self.current_progress = None
        self.query_one("#input", PromptTextArea).disabled = False
        self.query_one("#input", PromptTextArea).focus()
        self.stream_task = None
        self.update_status()

    def cancel_current_turn(self) -> bool:
        if not self.interaction_needs_recovery():
            return False
        task = self.stream_task
        self._turn_token += 1
        self.dismiss_active_confirmation()
        self.finish_cancelled_turn()
        self.detach_cancelled_turn_state()
        if task is not None and not task.done():
            task.cancel()
            self._track_detached_turn_task(task)
        return True

    def finish_cancelled_turn(self) -> None:
        if self.state == SessionState.STREAMING or self.stream_task is not None:
            self.query_one("#history", RichLog).write(
                agent_stop_block(AgentStopReason.USER_CANCELLED)
            )
        self.finish_streaming()

    def dismiss_active_confirmation(self) -> None:
        try:
            screen = self.screen
        except ScreenStackError:
            return
        if isinstance(screen, ConfirmToolScreen):
            screen.dismiss(False)
        elif isinstance(screen, PermissionToolScreen):
            screen.dismiss(Outcome.DENY_ONCE)

    def detach_cancelled_turn_state(self) -> None:
        old_conversation = self.conversation
        old_conversation.detach_callbacks()
        writer = self.session_writer
        self.conversation = Conversation.from_items(
            old_conversation.items(),
            on_append=writer.append_item if writer is not None else None,
            on_replace=writer.replace_items if writer is not None else None,
        )
        self.runtime = SessionRuntime(
            replacement=self.runtime.replacement,
            recovery=self.runtime.recovery,
            circuit_breaker=self.runtime.circuit_breaker,
            session=self.runtime.session,
            context_window=self.runtime.context_window,
            usage_anchor=self.runtime.usage_anchor,
            anchor_item_len=self.runtime.anchor_item_len,
            turn_count=self.runtime.turn_count,
            memory_update_task=self.runtime.memory_update_task,
            active_skills=self.runtime.active_skills,
            turn_tasks=self.runtime.turn_tasks,
            pending_hook_reminders=list(self.runtime.pending_hook_reminders),
            fired_hooks=set(self.runtime.fired_hooks),
            hook_tasks=self.runtime.hook_tasks,
        )
        self._load_skill_tool.attach(self.skill_catalog, self.runtime.active_skills)
        self._register_skill_commands()

    def interaction_needs_recovery(self) -> bool:
        if self.state == SessionState.STREAMING or self.stream_task is not None:
            return True
        if isinstance(self.screen, ConfirmToolScreen | PermissionToolScreen):
            return True
        if self.active_cfg is not None:
            try:
                return self.query_one("#input", PromptTextArea).disabled
            except Exception:
                return False
        return False

    def is_current_turn(self, turn_token: int) -> bool:
        return turn_token == self._turn_token

    def update_status(self) -> None:
        if self.active_cfg is None:
            return
        self.query_one("#status", Static).update(
            mode_status_text(
                self.active_cfg,
                self.agent_mode,
                len(self.conversation.items()),
                self.current_progress,
                self.permission_mode,
            )
        )

    def show_message(self, text: str) -> None:
        self.query_one("#history", RichLog).write(notice_block(text))

    def show_error(self, text: str) -> None:
        self.query_one("#history", RichLog).write(error_block(text))

    def clear_history(self) -> None:
        self.conversation.replace_items([])
        self.runtime.usage_anchor = 0
        self.runtime.anchor_item_len = 0
        self.clear_active_skills()
        history = self.query_one("#history", RichLog)
        history.clear()
        if self.active_cfg is not None:
            history.write(render_banner(__version__, self.cwd, self.active_cfg))
            self.show_tools()
        self.update_status()

    def clear_active_skills(self) -> None:
        self.runtime.active_skills.clear()
        if self.provider is not None and self.active_cfg is not None:
            self.provider.set_system_prompt(self.build_current_system_prompt())

    def append_assistant_message(self, text: str) -> None:
        if not text:
            return
        self.conversation.add_assistant(text)
        self.query_one("#history", RichLog).write(assistant_markdown(text))
        self.update_status()

    def list_catalog_skills(self) -> tuple[SkillCatalogItem, ...]:
        return tuple(
            SkillCatalogItem(
                name=skill.meta.name,
                description=skill.meta.description,
                source=skill.source,
                mode=skill.meta.mode,
                entry_path=skill.entry_path,
            )
            for skill in self.skill_catalog.list()
        )

    def list_active_skills(self) -> tuple[str, ...]:
        return tuple(entry.name for entry in self.runtime.active_skills.snapshot())

    def send_user_message(
        self,
        text: str,
        *,
        display_label: str | None = None,
        mode: AgentMode | None = None,
        permission_mode: PermissionMode | None = None,
    ) -> None:
        self.submit_user_text(
            text,
            display_text=display_label,
            mode=mode,
            permission_mode=permission_mode,
        )

    def set_agent_mode(self, mode: AgentMode) -> None:
        self.agent_mode = mode

    def set_permission_mode(self, mode: PermissionMode) -> None:
        self.permission_mode = mode
        self.tool_executor._default_permission_mode = mode
        self._register_skill_commands()

    def run_compact(self) -> None:
        asyncio.create_task(self.run_manual_compact())

    def refresh_status(self) -> None:
        self.update_status()

    def quit(self) -> None:
        self.request_quit()

    def show_resume(self) -> None:
        self.begin_resume()

    def status_snapshot(self) -> CommandStatus:
        return CommandStatus(
            model=self.active_cfg.model if self.active_cfg is not None else "",
            agent_mode=self.agent_mode,
            permission_mode=self.permission_mode,
            message_count=len(self.conversation.items()),
            estimated_tokens=estimate_tokens(
                self.runtime.usage_anchor,
                self.conversation.items(),
                self.runtime.anchor_item_len,
            ),
            tool_count=self.tool_registry.count(),
            session_id=self.runtime.session.session_id,
        )

    def session_snapshot(self) -> CommandSession:
        return CommandSession(
            session_id=self.runtime.session.session_id,
            session_path=str(self.runtime.session.session_dir),
            message_count=len(self.conversation.items()),
        )

    def memory_snapshot(self) -> CommandMemory:
        if self.memory_manager is None:
            return CommandMemory(text="")
        return CommandMemory(
            text=self.memory_manager.load_index_text(),
            files=self.memory_manager.list_files(),
        )


    def worktree_accessor(self):
        if self.worktree_mgr is None:
            return None
        return WorktreeAdapter(self.worktree_mgr, self._set_active_cwd)

    def _set_active_cwd(self, cwd: str) -> None:
        self.active_cwd = cwd

    def _effective_cwd(self) -> str:
        return self.active_cwd or str(self.cwd)
    def is_idle(self) -> bool:
        return self.state == SessionState.IDLE

    def sync_completion(self) -> None:
        if self.state != SessionState.IDLE:
            self.hide_completion()
            return
        try:
            input_box = self.query_one("#input", PromptTextArea)
        except Exception:
            return
        self.completion_menu.update(input_box.text, self.command_registry)
        self.render_completion()

    def render_completion(self) -> None:
        try:
            target = self.query_one("#completion", Static)
        except Exception:
            return
        target.update(self.completion_menu.render(self.size.width or 80))

    def hide_completion(self) -> None:
        self.completion_menu.hide()
        self.render_completion()

    def request_quit(self, *, force: bool = False) -> None:
        already_closing = self._closing
        self._closing = True
        self._reset_ctrl_c_exit_sequence()
        self.dismiss_active_confirmation()
        self._cancel_turn_tasks_for_quit()
        if self.session_writer is not None:
            self.session_writer.close()
        close_task = self._mcp_close_task
        if already_closing and close_task is not None and not close_task.done():
            close_task.cancel()
        elif self.mcp_manager is not None and self._mcp_close_task is None:
            self._mcp_close_task = asyncio.create_task(self._close_mcp_best_effort())
        self.exit()
        if force:
            self._schedule_force_exit()

    def _schedule_force_exit(self) -> None:
        if self._force_exit_handle is not None and not self._force_exit_handle.cancelled():
            return
        loop = asyncio.get_running_loop()
        self._force_exit_handle = loop.call_later(
            FORCE_EXIT_GRACE_SECONDS, self._force_exit_now
        )

    def _force_exit_now(self) -> None:
        driver = getattr(self, "_driver", None)
        if driver is not None:
            with suppress(Exception):
                driver.stop_application_mode()
            with suppress(Exception):
                driver.close()
        os._exit(FORCE_EXIT_RETURN_CODE)

    def _cancel_turn_tasks_for_quit(self) -> None:
        self.runtime.cancel_turn_tasks()
        if self.stream_task is not None and not self.stream_task.done():
            self.stream_task.cancel()
        if self._task_done_consumer_task is not None and not self._task_done_consumer_task.done():
            self._task_done_consumer_task.cancel()
        for task in tuple(self._detached_turn_tasks):
            if not task.done():
                task.cancel()

    def _track_detached_turn_task(self, task: asyncio.Task[None]) -> None:
        if task.done():
            self._consume_task_exception(task)
            return
        self._detached_turn_tasks.add(task)
        task.add_done_callback(self._forget_detached_turn_task)

    def _forget_detached_turn_task(self, task: asyncio.Task[None]) -> None:
        self._detached_turn_tasks.discard(task)
        self._consume_task_exception(task)

    def _consume_task_exception(self, task: asyncio.Task[None]) -> None:
        if not task.done():
            return
        with suppress(asyncio.CancelledError, Exception):
            task.exception()

    async def _close_mcp_best_effort(self) -> None:
        manager = self.mcp_manager
        if manager is None:
            return
        try:
            await manager.close()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"[mcp] warn: close failed during app shutdown: {exc}", file=sys.stderr)
        finally:
            if self.mcp_manager is manager:
                self.mcp_manager = None

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action in {"cancel_streaming", "interrupt"}:
            return True
        return True

    async def action_quit(self) -> None:
        self.request_quit()

    async def action_cancel_streaming(self) -> None:
        self.handle_key_interrupt("escape")

    async def action_interrupt(self) -> None:
        self.handle_key_interrupt("ctrl+c")

    def on_key(self, event: events.Key) -> None:
        if event.key in CANCEL_KEYS and self.handle_key_interrupt(event.key):
            event.prevent_default()
            event.stop()

    def handle_key_interrupt(self, key: str) -> bool:
        if key == "escape":
            self._reset_ctrl_c_exit_sequence()
            if isinstance(self.screen, ResumeSessionScreen):
                self.screen.dismiss(None)
                return True
            if self.cancel_current_turn():
                return True
            if self.completion_menu.active:
                self.hide_completion()
                return True
            self.request_quit()
            return True
        if key == "ctrl+c":
            return self._handle_ctrl_c()
        return False

    def _handle_ctrl_c(self) -> bool:
        now = monotonic()
        if now - self._last_ctrl_c_handled_at < CTRL_C_DUPLICATE_EVENT_SECONDS:
            return True
        self._last_ctrl_c_handled_at = now
        if self._ctrl_c_exit_deadline and now <= self._ctrl_c_exit_deadline:
            self._reset_ctrl_c_exit_sequence()
            self.request_quit(force=True)
            return True

        if self._closing:
            self.request_quit(force=True)
            return True

        self._ctrl_c_exit_deadline = now + CTRL_C_EXIT_WINDOW_SECONDS
        if self.cancel_current_turn():
            self.show_message("Press Ctrl+C again to exit.")
            return True
        if self.completion_menu.active:
            self.hide_completion()
        self.show_message("Press Ctrl+C again to exit.")
        return True

    def _reset_ctrl_c_exit_sequence(self) -> None:
        self._ctrl_c_exit_deadline = 0.0


def parse_agent_request(text: str) -> AgentRunRequest:
    stripped = text.strip()
    if stripped == "/plan":
        return AgentRunRequest(
            (
                "Enter plan mode. Analyze and plan only; "
                "do not edit files or run side-effecting actions."
            ),
            AgentMode.PLAN,
            PermissionMode.PLAN,
        )
    if stripped.startswith("/plan "):
        return AgentRunRequest(
            stripped.removeprefix("/plan ").strip(),
            AgentMode.PLAN,
            PermissionMode.PLAN,
        )
    if stripped == "/do":
        return AgentRunRequest(
            "Enter execution mode. Follow the plan and edit files when needed.",
            AgentMode.DO,
            PermissionMode.DEFAULT,
        )
    if stripped.startswith("/do "):
        return AgentRunRequest(
            stripped.removeprefix("/do ").strip(),
            AgentMode.DO,
            PermissionMode.DEFAULT,
        )
    return AgentRunRequest(stripped, AgentMode.AGENT)


def next_permission_mode(mode: PermissionMode) -> PermissionMode:
    return PermissionMode((int(mode) + 1) % len(PermissionMode))
