from __future__ import annotations

from collections.abc import Sequence

from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from coco_code.agent.types import AgentMode, AgentProgress, AgentStopReason
from coco_code.config import ProviderConfig
from coco_code.permission import Mode as PermissionMode
from coco_code.tools.base import ToolCall, ToolResult, ToolSpec
from coco_code.tools.safety import summarize_params


def user_block(text: str) -> Panel:
    return Panel(Text(text, style="bright_white"), title="You", border_style="cyan")


def assistant_markdown(reply: str) -> Panel:
    return Panel(Markdown(reply or "(empty)"), title="CoCo Code", border_style="green")


def error_block(error: Exception | str) -> Panel:
    return Panel(Text(str(error), style="bold red"), title="Error", border_style="red")


def notice_block(message: str) -> Panel:
    return Panel(Text(message, style="cyan"), title="Notice", border_style="cyan")


def tool_call_block(call: ToolCall, spec: ToolSpec | None = None) -> Panel:
    title = f"Tool: {call.name}"
    text = Text()
    text.append("The model requested a tool call.\n", style="bold yellow")
    if spec is not None:
        text.append(f"Purpose: {spec.description}\n", style="white")
        text.append(f"Confirmation policy: {spec.confirmation.value}\n", style="dim")
        text.append(_tool_metadata_line(spec), style="dim")
        text.append("\n")
    text.append(f"Arguments: {summarize_params(call.arguments)}", style="white")
    return Panel(text, title=title, border_style="yellow")


def tool_confirm_block(call: ToolCall, spec: ToolSpec) -> Panel:
    text = Text()
    text.append("Waiting for user confirmation before execution.\n", style="bold yellow")
    text.append(f"Tool: {call.name}\n", style="white")
    text.append(f"Risk: {spec.description}\n", style="red")
    text.append(_tool_metadata_line(spec), style="dim")
    text.append("\n")
    text.append(f"Arguments: {summarize_params(call.arguments)}", style="white")
    return Panel(text, title="Confirm Tool", border_style="red")


def tool_permission_block(call: ToolCall, spec: ToolSpec, reason: str) -> Panel:
    text = Text()
    text.append("This tool needs permission before execution.\n", style="bold yellow")
    text.append(f"Tool: {call.name}\n", style="white")
    text.append(f"Reason: {reason}\n", style="red")
    text.append(_tool_metadata_line(spec), style="dim")
    text.append("\n")
    text.append(f"Arguments: {summarize_params(call.arguments)}", style="white")
    return Panel(text, title="Permission Required", border_style="red")


def tool_result_block(result: ToolResult) -> Panel:
    style = "green" if result.ok else "red"
    text = Text()
    text.append(result.summary, style=f"bold {style}")
    text.append(f"\nElapsed: {result.elapsed_ms}ms", style="dim")
    if result.truncated:
        text.append("\nOutput was truncated.", style="yellow")
    if result.error:
        text.append(f"\nError: {result.error}", style="red")
    output = _tool_result_output(result)
    if output:
        text.append("\nOutput:\n", style="dim")
        text.append(output, style="white")
    return Panel(text, title=f"Tool Result: {result.tool_name}", border_style=style)


def tool_batch_block(
    batch_index: int | None,
    batch_total: int | None,
    calls: Sequence[ToolCall],
    concurrent: bool = False,
) -> Panel:
    text = Text()
    mode = "concurrent" if concurrent else "serial"
    text.append(f"Tool batch: {mode}\n", style="bold yellow")
    if batch_index is not None and batch_total is not None:
        text.append(f"Batch: {batch_index}/{batch_total}\n", style="dim")
    for call in calls:
        text.append(f"- {call.name}: {summarize_params(call.arguments)}\n", style="white")
    return Panel(text, title="Tool Batch", border_style="yellow")


def agent_stop_block(reason: AgentStopReason | str, detail: str = "") -> Panel:
    text = Text()
    text.append(f"Stop reason: {reason}", style="bold cyan")
    if detail:
        text.append(f"\n{detail}", style="white")
    return Panel(text, title="Agent Stopped", border_style="cyan")


def second_tool_block(call: ToolCall) -> Panel:
    text = Text()
    text.append(
        "Compatibility boundary: the old stream path blocks a second tool call.\n",
        style="bold yellow",
    )
    text.append(f"The model requested `{call.name}`.", style="white")
    return Panel(text, title="Tool Boundary", border_style="yellow")


def _tool_result_output(result: ToolResult) -> str:
    stdout = result.data.get("stdout")
    stderr = result.data.get("stderr")
    parts: list[str] = []
    if isinstance(stdout, str) and stdout.strip():
        parts.append(f"stdout:\n{stdout.strip()}")
    if isinstance(stderr, str) and stderr.strip():
        parts.append(f"stderr:\n{stderr.strip()}")
    output = "\n".join(parts)
    if len(output) > 2000:
        return output[:2000] + "\n..."
    return output


def _tool_metadata_line(spec: ToolSpec) -> str:
    read_only = str(spec.read_only).lower()
    destructive = str(spec.destructive).lower()
    scenarios = ", ".join(spec.typical_scenarios) if spec.typical_scenarios else "unmarked"
    return (
        f"Metadata: category={spec.category.value}; "
        f"read_only={read_only}; destructive={destructive}; "
        f"typical_scenarios={scenarios}"
    )


def status_text(provider: ProviderConfig, message_count: int) -> Text:
    return mode_status_text(provider, AgentMode.AGENT, message_count, None, PermissionMode.DEFAULT)


def mode_status_text(
    provider: ProviderConfig,
    mode: AgentMode,
    message_count: int,
    progress: AgentProgress | None = None,
    permission_mode: PermissionMode | None = None,
) -> Text:
    perm = permission_mode or _permission_mode_from_agent_mode(mode)
    label, style = _permission_label(perm)
    text = Text.assemble(
        (" Permission ", "bold cyan"),
        (f"[{label}]", style),
        (" | Model ", "dim"),
        (provider.model, "white"),
        (" | Agent ", "dim"),
        (mode.value, "magenta"),
        (" | Messages ", "dim"),
        (str(message_count), "green"),
    )
    if progress is not None:
        text.append(" | Iter ", style="dim")
        text.append(f"{progress.iteration}/{progress.max_iterations}", style="cyan")
        text.append(" | ", style="dim")
        text.append(progress.phase, style="yellow")
        if progress.tool_name:
            text.append(" ", style="dim")
            text.append(progress.tool_name, style="white")
    return text


def agent_progress_text(current_reply: str, elapsed: int, progress: AgentProgress | None) -> Text:
    text = Text()
    if current_reply:
        text.append(current_reply, style="white")
        text.append("\n")
    if progress is not None:
        status = (
            f"Imagining... ({elapsed}s) | "
            f"iter {progress.iteration}/{progress.max_iterations} | {progress.phase}"
        )
        text.append(status, style="italic yellow")
        if progress.tool_name:
            text.append(f" | {progress.tool_name}", style="italic yellow")
    else:
        text.append(f"Imagining... ({elapsed}s)", style="italic yellow")
    return text


def streaming_text(current_reply: str, elapsed: int) -> Text:
    return agent_progress_text(current_reply, elapsed, None)


def _permission_mode_from_agent_mode(mode: AgentMode) -> PermissionMode:
    if mode == AgentMode.PLAN:
        return PermissionMode.PLAN
    return PermissionMode.DEFAULT


def _permission_label(mode: PermissionMode) -> tuple[str, str]:
    if mode == PermissionMode.ACCEPT_EDITS:
        return "ACCEPT EDITS", "bold green"
    if mode == PermissionMode.PLAN:
        return "PLAN", "bold yellow"
    if mode == PermissionMode.BYPASS:
        return "BYPASS", "bold red"
    return "DEFAULT", "bold cyan"
