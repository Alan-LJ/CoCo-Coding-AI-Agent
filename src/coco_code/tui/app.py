from __future__ import annotations

import asyncio
from enum import StrEnum
from pathlib import Path
from time import monotonic
from typing import Any

from textual import events, on
from textual.app import App, ComposeResult
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
from coco_code.config import Config, ConfigError, ProviderConfig
from coco_code.conversation import Conversation
from coco_code.llm import Provider, new_provider
from coco_code.prompt import build_system_prompt, render_banner
from coco_code.tools import (
    ConfirmationPolicy,
    ToolCall,
    ToolContext,
    ToolExecutor,
    ToolSpec,
    create_default_registry,
)
from coco_code.tools.base import ConfirmCallback
from coco_code.tools.registry import ToolRegistry, ToolRegistryError
from coco_code.tui.select import ProviderOptionList
from coco_code.tui.view import (
    agent_progress_text,
    agent_stop_block,
    assistant_markdown,
    error_block,
    mode_status_text,
    tool_batch_block,
    tool_call_block,
    tool_confirm_block,
    tool_result_block,
    user_block,
)

DEFAULT_RESPONSE_TIMEOUT_SECONDS = 300.0


class SessionState(StrEnum):
    SELECTING = "selecting"
    IDLE = "idle"
    STREAMING = "streaming"


class PromptSubmitted(events.Message):
    def __init__(self, text: str) -> None:
        self.text = text
        super().__init__()


class HistoryRequested(events.Message):
    def __init__(self, direction: int) -> None:
        self.direction = direction
        super().__init__()


class PromptTextArea(TextArea):
    def on_key(self, event: events.Key) -> None:
        if event.key == "enter":
            event.prevent_default()
            event.stop()
            self.post_message(PromptSubmitted(self.text))
        elif event.key in {"alt+enter", "ctrl+j"}:
            event.prevent_default()
            event.stop()
            self.insert("\n")
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
        ("escape", "reject", "拒绝"),
    ]

    def __init__(self, call: ToolCall, spec: ToolSpec) -> None:
        super().__init__()
        self.call = call
        self.spec = spec

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-dialog"):
            yield Static(tool_confirm_block(self.call, self.spec), id="confirm-body")
            with Horizontal(id="confirm-actions"):
                yield Button("批准", id="approve", variant="success")
                yield Button("拒绝", id="reject", variant="error")

    @on(Button.Pressed)
    def button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "approve")

    def action_reject(self) -> None:
        self.dismiss(False)


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
        ("ctrl+c", "quit", "Quit"),
    ]

    def __init__(
        self,
        config: Config,
        cwd: Path | None = None,
        tool_registry: ToolRegistry | None = None,
        tool_context: ToolContext | None = None,
        confirm_callback: ConfirmCallback | None = None,
        response_timeout_seconds: float = DEFAULT_RESPONSE_TIMEOUT_SECONDS,
    ) -> None:
        super().__init__()
        self.config = config
        self.cwd = cwd or Path.cwd()
        self.tool_registry = tool_registry or create_default_registry()
        self.tool_context = tool_context or ToolContext(workspace=self.cwd)
        self._confirm_callback = confirm_callback
        self.response_timeout_seconds = response_timeout_seconds
        self.agent_limits = AgentLimits(
            response_timeout_seconds=response_timeout_seconds,
            tool_timeout_seconds=self.tool_context.timeout_seconds,
            confirm_timeout_seconds=self.tool_context.confirm_timeout_seconds,
        )
        self.tool_executor = ToolExecutor(
            self.tool_registry,
            self.tool_context,
            self.confirm_tool_call,
        )
        self.state = SessionState.SELECTING if len(config.providers) > 1 else SessionState.IDLE
        self.active_cfg: ProviderConfig | None = None
        self.provider: Provider | None = None
        self.conversation = Conversation()
        self.input_history: list[str] = []
        self.history_cursor: int | None = None
        self.current_reply = ""
        self.agent_mode = AgentMode.AGENT
        self.current_progress: AgentProgress | None = None
        self.turn_start = 0.0
        self.stream_task: asyncio.Task[None] | None = None
        self.timer: Any | None = None

    def compose(self) -> ComposeResult:
        if len(self.config.providers) > 1:
            yield Static("选择本次会话的 provider：", id="select-title")
            yield ProviderOptionList(self.config.providers)
        yield RichLog(id="history", wrap=True, markup=False)
        yield Static("", id="stream")
        yield PromptTextArea("", id="input")
        yield Static("", id="status")

    def on_mount(self) -> None:
        self.timer = self.set_interval(1.0, self.refresh_streaming, pause=True)
        if len(self.config.providers) == 1:
            self.activate_provider(self.config.providers[0])
        else:
            self.query_one("#input", PromptTextArea).disabled = True
            self.query_one(ProviderOptionList).focus()

    @on(OptionList.OptionSelected)
    def provider_selected(self, event: OptionList.OptionSelected) -> None:
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
    def prompt_submitted(self, event: PromptSubmitted) -> None:
        if self.state != SessionState.IDLE:
            return
        text = event.text.strip()
        if not text:
            return
        if text == "/exit":
            self.request_quit()
            return
        self.submit_user_text(text)

    @on(HistoryRequested)
    def history_requested(self, event: HistoryRequested) -> None:
        if self.state != SessionState.IDLE or not self.input_history:
            return
        if self.history_cursor is None:
            self.history_cursor = len(self.input_history)
        next_cursor = self.history_cursor + event.direction
        self.history_cursor = max(0, min(len(self.input_history) - 1, next_cursor))
        self.query_one("#input", PromptTextArea).text = self.input_history[self.history_cursor]

    def activate_provider(self, provider_cfg: ProviderConfig) -> None:
        try:
            system_prompt = build_system_prompt(self.cwd, provider_cfg)
            self.provider = new_provider(provider_cfg, system_prompt)
        except ConfigError as exc:
            self.query_one("#history", RichLog).write(error_block(exc))
            self.query_one("#input", PromptTextArea).disabled = True
            self.state = SessionState.IDLE
            return

        self.active_cfg = provider_cfg
        history = self.query_one("#history", RichLog)
        history.clear()
        history.write(render_banner(__version__, self.cwd, provider_cfg))
        input_box = self.query_one("#input", PromptTextArea)
        input_box.disabled = False
        input_box.focus()
        self.state = SessionState.IDLE
        self.update_status()

    def submit_user_text(self, text: str) -> None:
        if self.provider is None or self.active_cfg is None:
            return
        request = parse_agent_request(text)
        self.agent_mode = request.mode
        input_box = self.query_one("#input", PromptTextArea)
        input_box.text = ""
        input_box.disabled = True
        self.input_history.append(text)
        self.history_cursor = None
        self.query_one("#history", RichLog).write(user_block(text))
        self.state = SessionState.STREAMING
        self.current_reply = ""
        self.current_progress = None
        self.turn_start = monotonic()
        self.refresh_streaming()
        if self.timer is not None:
            self.timer.resume()
        self.stream_task = asyncio.create_task(self._run_agent_turn(request))

    async def _run_agent_turn(self, request: AgentRunRequest) -> None:
        assert self.provider is not None
        try:
            loop = AgentLoop(
                self.provider,
                self.conversation,
                self.tool_registry,
                self.tool_executor,
                self.agent_limits,
            )
            async for event in loop.run(request):
                await self.handle_agent_event(event)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.query_one("#history", RichLog).write(error_block(exc))
            self.finish_streaming()

    async def handle_agent_event(self, event: AgentEvent) -> None:
        history = self.query_one("#history", RichLog)
        if event.type == AgentEventType.MODE_CHANGED:
            self.agent_mode = event.mode or self.agent_mode
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
                if spec is not None and spec.confirmation == ConfirmationPolicy.REQUIRED:
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
        elif event.type == AgentEventType.ERROR:
            if event.error is not None:
                history.write(error_block(event.error))
        elif event.type == AgentEventType.STOPPED:
            if event.stop_reason is not None and event.stop_reason != AgentStopReason.MODEL_DONE:
                history.write(agent_stop_block(event.stop_reason))
            self.finish_streaming()

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

    def update_status(self) -> None:
        if self.active_cfg is None:
            return
        self.query_one("#status", Static).update(
            mode_status_text(
                self.active_cfg,
                self.agent_mode,
                len(self.conversation.items()),
                self.current_progress,
            )
        )

    def request_quit(self) -> None:
        if self.stream_task is not None and not self.stream_task.done():
            self.stream_task.cancel()
        self.exit()

    async def action_quit(self) -> None:
        self.request_quit()


def parse_agent_request(text: str) -> AgentRunRequest:
    stripped = text.strip()
    if stripped == "/plan":
        return AgentRunRequest("请基于当前会话上下文制定执行计划。", AgentMode.PLAN)
    if stripped.startswith("/plan "):
        return AgentRunRequest(stripped.removeprefix("/plan ").strip(), AgentMode.PLAN)
    if stripped == "/do":
        return AgentRunRequest("请基于最近的计划和当前会话上下文继续执行。", AgentMode.DO)
    if stripped.startswith("/do "):
        return AgentRunRequest(stripped.removeprefix("/do ").strip(), AgentMode.DO)
    return AgentRunRequest(stripped, AgentMode.AGENT)