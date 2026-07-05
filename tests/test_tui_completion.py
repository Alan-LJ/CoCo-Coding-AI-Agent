from __future__ import annotations

from coco_code.command import build_default_registry
from coco_code.tui.complete import CompletionMenu


def test_completion_hides_for_non_slash() -> None:
    menu = CompletionMenu()
    menu.update("hello", build_default_registry())
    assert menu.active is False


def test_completion_lists_slash_commands() -> None:
    menu = CompletionMenu()
    menu.update("/", build_default_registry())
    assert menu.active is True
    assert len(menu.items) == 10


def test_completion_filters_by_prefix_and_alias() -> None:
    menu = CompletionMenu()
    menu.update("/s", build_default_registry())
    assert [item.name for item in menu.items] == ["session", "status"]


def test_single_completion() -> None:
    menu = CompletionMenu()
    menu.update("/rev", build_default_registry())
    assert menu.single_completion() == "/review "


def test_move_and_select() -> None:
    menu = CompletionMenu()
    menu.update("/s", build_default_registry())
    assert menu.selected().name == "session"
    menu.move_down()
    assert menu.selected().name == "status"
    menu.move_up()
    assert menu.selected().name == "session"


def test_render_marks_selected() -> None:
    menu = CompletionMenu()
    menu.update("/s", build_default_registry())
    output = menu.render(80)
    assert "> /session" in output
    assert "/status" in output
