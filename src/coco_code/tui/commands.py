from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.widgets import RichLog, TextArea

from coco_code.agent import CompactEvent, CompactPhase
from coco_code.command import CommandContext, CommandKind, parse_command
from coco_code.compact.manager import ManageOutput
from coco_code.tui.view import error_block

if TYPE_CHECKING:
    from coco_code.tui.app import CoCoCodeApp


async def dispatch_command(app: CoCoCodeApp, text: str) -> bool:
    parsed = parse_command(text)
    if not parsed.is_command:
        return False
    input_box = app.query_one("#input", TextArea)
    input_box.text = ""
    command = app.command_registry.lookup(parsed.name)
    if command is None:
        app.show_error(f"Unknown command: {parsed.raw or '/'}. Type /help to list commands.")
        return True
    if command.kind in {CommandKind.UI, CommandKind.PROMPT} and not app.is_idle():
        app.show_error("Wait for the current task to finish before running that command.")
        return True
    try:
        await command.handler(CommandContext(parsed), app)
    except Exception as exc:
        app.show_error(str(exc))
    finally:
        app.hide_completion()
    return True


def format_compact_notice(event_or_output: CompactEvent | ManageOutput | Any) -> str:
    if isinstance(event_or_output, ManageOutput):
        return _done_notice(event_or_output.before_tokens, event_or_output.after_tokens)
    event = event_or_output
    phase = getattr(event, "phase", None)
    error = getattr(event, "error", None)
    if phase == CompactPhase.BEFORE_AUTO:
        return "Compacting context..."
    if phase == CompactPhase.BEFORE_EMERGENCY:
        return "Context is over limit; compacting now..."
    if error is not None:
        return f"Compaction failed: {error}"
    if phase in {CompactPhase.AFTER_AUTO, CompactPhase.AFTER_EMERGENCY, CompactPhase.MANUAL_DONE}:
        return _done_notice(int(event.before_tokens), int(event.after_tokens))
    return "Context compaction state updated."


def render_compact_error(app: CoCoCodeApp, error: Exception | str) -> None:
    app.query_one("#history", RichLog).write(error_block(f"Compaction failed: {error}"))


def _done_notice(before: int, after: int) -> str:
    return f"Compacted context: tokens {before} -> {after}"
