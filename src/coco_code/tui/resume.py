from __future__ import annotations

from datetime import datetime

from textual import events, on
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import OptionList, Static

from coco_code.session import SessionInfo


class ResumeSessionScreen(ModalScreen[SessionInfo | None]):
    CSS = """
    ResumeSessionScreen {
        align: center middle;
    }

    #resume-dialog {
        width: 88%;
        height: auto;
        max-height: 85%;
        border: round cyan;
        padding: 1 2;
        background: $surface;
    }

    #resume-list {
        height: auto;
        max-height: 20;
    }
    """

    BINDINGS = [("escape", "new_session", "New session")]

    def __init__(self, sessions: list[SessionInfo]) -> None:
        super().__init__()
        self.sessions = sessions
        self.filtered = sessions
        self.search = ""

    def compose(self) -> ComposeResult:
        with Vertical(id="resume-dialog"):
            yield Static(self._title_text(), id="resume-title")
            yield OptionList(*self._labels(), id="resume-list")

    @on(OptionList.OptionSelected)
    def option_selected(self, event: OptionList.OptionSelected) -> None:
        index = getattr(event, "option_index", None)
        if index is None:
            index = getattr(event, "index", None)
        index = int(index or 0)
        if index == 0:
            self.dismiss(None)
            return
        if 0 < index <= len(self.filtered):
            self.dismiss(self.filtered[index - 1])

    def on_key(self, event: events.Key) -> None:
        if event.key == "backspace" and self.search:
            event.prevent_default()
            event.stop()
            self.search = self.search[:-1]
            self._refresh_options()
        elif len(event.character or "") == 1 and event.character and event.character.isprintable():
            event.prevent_default()
            event.stop()
            self.search += event.character
            self._refresh_options()

    def action_new_session(self) -> None:
        self.dismiss(None)

    def _refresh_options(self) -> None:
        query = self.search.casefold().strip()
        self.filtered = [
            info for info in self.sessions if not query or query in info.title.casefold()
        ]
        self.query_one("#resume-title", Static).update(self._title_text())
        option_list = self.query_one("#resume-list", OptionList)
        option_list.clear_options()
        option_list.add_options(self._labels())

    def _labels(self) -> list[str]:
        return ["New session"] + [session_label(info) for info in self.filtered]

    def _title_text(self) -> str:
        suffix = f" | search: {self.search}" if self.search else ""
        return f"Resume a recent session{suffix}"


def session_label(info: SessionInfo) -> str:
    return (
        f"{info.title} - {relative_time(info.modified_at)} - "
        f"{info.model} - {info.message_count} msgs - {_format_size(info.size_bytes)}"
    )


def relative_time(moment: datetime) -> str:
    seconds = max(0, int((datetime.now() - moment).total_seconds()))
    if seconds < 60:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} min ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} hours ago"
    days = hours // 24
    return f"{days} days ago"


def _format_size(size: int) -> str:
    if size < 1024:
        return f"{size}B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f}KB"
    return f"{size / 1024 / 1024:.1f}MB"
