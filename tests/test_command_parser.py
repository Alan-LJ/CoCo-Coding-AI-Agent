from __future__ import annotations

from coco_code.command import parse_command


def test_parse_non_commands() -> None:
    assert parse_command("").is_command is False
    assert parse_command("   ").is_command is False
    assert parse_command("hello").is_command is False


def test_parse_command_name_case_insensitive() -> None:
    parsed = parse_command("  /HELP  ")
    assert parsed.is_command is True
    assert parsed.name == "help"
    assert parsed.args == ""


def test_parse_command_args_preserved() -> None:
    parsed = parse_command("/plan inspect this")
    assert parsed.is_command is True
    assert parsed.name == "plan"
    assert parsed.args == "inspect this"


def test_parse_empty_slash_command() -> None:
    parsed = parse_command("/")
    assert parsed.is_command is True
    assert parsed.name == ""
