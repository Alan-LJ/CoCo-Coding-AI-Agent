from __future__ import annotations

from pathlib import Path

import pytest

from coco_code.skills.parser import (
    SkillParseError,
    parse_skill_file,
    split_frontmatter,
    substitute_arguments,
)
from coco_code.skills.types import SkillContext, SkillMode, SkillSource


def write_skill(path: Path, frontmatter: str, body: str = "Body") -> Path:
    path.write_text(f"---\n{frontmatter}\n---\n{body}\n", encoding="utf-8")
    return path


def test_parse_valid_skill_file(tmp_path: Path) -> None:
    path = write_skill(
        tmp_path / "skill.md",
        "name: demo\n"
        "description: Demo skill\n"
        "allowed_tools: [ReadFile, Grep]\n"
        "mode: fork\n"
        "context: recent\n"
        "model: custom-model",
    )

    skill = parse_skill_file(path, SkillSource.PROJECT)

    assert skill.meta.name == "demo"
    assert skill.meta.description == "Demo skill"
    assert skill.meta.allowed_tools == ("ReadFile", "Grep")
    assert skill.meta.mode == SkillMode.FORK
    assert skill.meta.context == SkillContext.RECENT
    assert skill.meta.model == "custom-model"
    assert skill.prompt_body == "Body\n"


@pytest.mark.parametrize(
    ("frontmatter", "message"),
    [
        ("description: Missing name", "name"),
        ("name: demo", "description"),
        ("name: Bad\nDescription: nope", "name"),
        ("name: demo\ndescription: Demo\nallowed_tools: ReadFile", "allowed_tools"),
        ("name: demo\ndescription: Demo\nmode: other", "mode"),
        ("name: demo\ndescription: Demo\ncontext: all", "context"),
        ("name: demo\ndescription: Demo\nmodel: []", "model"),
    ],
)
def test_parse_rejects_invalid_metadata(tmp_path: Path, frontmatter: str, message: str) -> None:
    path = write_skill(tmp_path / "skill.md", frontmatter)

    with pytest.raises(SkillParseError, match=message):
        parse_skill_file(path, SkillSource.USER)


def test_split_frontmatter_requires_opening_and_closing_delimiters() -> None:
    with pytest.raises(SkillParseError):
        split_frontmatter("name: nope\n---\nbody")
    with pytest.raises(SkillParseError):
        split_frontmatter("---\nname: nope\nbody")


def test_substitute_arguments_replaces_all_placeholders() -> None:
    assert substitute_arguments("A $ARGUMENTS B $ARGUMENTS", "x") == "A x B x"


def test_substitute_arguments_appends_user_request_when_no_placeholder() -> None:
    rendered = substitute_arguments("Body\n", "please do it")

    assert "Body" in rendered
    assert "## User Request" in rendered
    assert "please do it" in rendered
