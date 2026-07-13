from __future__ import annotations

from dataclasses import fields
from pathlib import Path

import pytest

from coco_code.permission import Mode as PermissionMode
from coco_code.subagent import Source, SubagentParseError, parse_definition, parse_file


def definition_text(frontmatter: str, body: str = "Body\n") -> bytes:
    return f"---\n{frontmatter}\n---\n{body}".encode()


def test_definition_fields() -> None:
    names = {field.name for field in fields(parse_definition(definition_text(
        "name: Demo\ndescription: Demo agent\n"
    ), "demo.md", Source.USER))}
    assert {
        "name",
        "description",
        "tools",
        "disallowed_tools",
        "model",
        "max_turns",
        "permission_mode",
        "dont_ask",
        "background",
        "system_prompt",
        "file_path",
        "source",
        "isolation",
    }.issubset(names)


def test_parse_full_definition() -> None:
    definition = parse_definition(
        definition_text(
            "name: Explore\n"
            "description: Explore code\n"
            "tools: [ReadFile, grep]\n"
            "disallowedTools: [write_file]\n"
            "model: haiku\n"
            "maxTurns: 7\n"
            "permissionMode: plan\n"
            "background: true\n",
            "Prompt body\n",
        ),
        "explore.md",
        Source.PROJECT,
    )
    assert definition.name == "Explore"
    assert definition.tools == ("ReadFile", "grep")
    assert definition.disallowed_tools == ("write_file",)
    assert definition.model == "haiku"
    assert definition.max_turns == 7
    assert definition.permission_mode == PermissionMode.PLAN
    assert definition.background is True
    assert definition.system_prompt == "Prompt body\n"
    assert definition.source == Source.PROJECT


def test_parse_dont_ask_permission_mode() -> None:
    definition = parse_definition(
        definition_text("name: Auto\ndescription: Auto approve\npermissionMode: dontAsk\n"),
        "auto.md",
        Source.USER,
    )
    assert definition.dont_ask is True
    assert definition.permission_mode == PermissionMode.DEFAULT


@pytest.mark.parametrize(
    ("frontmatter", "message"),
    [
        ("description: Missing", "name"),
        ("name: Demo", "description"),
        ("name: bad space\ndescription: x", "name"),
    ],
)
def test_parse_rejects_required_metadata(frontmatter: str, message: str) -> None:
    with pytest.raises(SubagentParseError, match=message):
        parse_definition(definition_text(frontmatter), "bad.md", Source.USER)


def test_parse_invalid_model_and_permission_fallback(capsys: pytest.CaptureFixture[str]) -> None:
    definition = parse_definition(
        definition_text(
            "name: Bad\ndescription: Bad fields\nmodel: gpt-4\npermissionMode: weird\n"
        ),
        "bad.md",
        Source.USER,
    )
    assert definition.model == "inherit"
    assert definition.permission_mode == PermissionMode.DEFAULT
    stderr = capsys.readouterr().err
    assert "unknown model" in stderr
    assert "unknown permissionMode" in stderr


def test_parse_file_reads_utf8_bom(tmp_path: Path) -> None:
    path = tmp_path / "agent.md"
    path.write_bytes(
        ("\ufeff---\nname: Demo\ndescription: Demo agent\n---\nPrompt\n").encode()
    )
    assert parse_file(path, Source.PROJECT).system_prompt == "Prompt\n"


def test_frontmatter_must_close() -> None:
    with pytest.raises(SubagentParseError):
        parse_definition(b"---\nname: nope\nbody", "bad.md", Source.USER)


def test_parse_isolation_worktree() -> None:
    definition = parse_definition(
        definition_text("name: Worker\ndescription: Worker\nisolation: worktree\n"),
        "worker.md",
        Source.USER,
    )
    assert definition.isolation == "worktree"


def test_parse_invalid_isolation_fallback(capsys: pytest.CaptureFixture[str]) -> None:
    definition = parse_definition(
        definition_text("name: Bad\ndescription: Bad\nisolation: nope\n"),
        "bad.md",
        Source.USER,
    )
    assert definition.isolation == ""
    assert "unknown isolation" in capsys.readouterr().err