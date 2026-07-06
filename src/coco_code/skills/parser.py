from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from coco_code.skills.types import Skill, SkillContext, SkillMeta, SkillMode, SkillSource

SKILL_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]*$")


class SkillParseError(ValueError):
    pass


def split_frontmatter(raw: str) -> tuple[dict[str, Any], str]:
    raw = raw.lstrip("\ufeff")
    lines = raw.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise SkillParseError("Skill file must start with YAML frontmatter delimiter '---'.")

    end_index: int | None = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_index = index
            break
    if end_index is None:
        raise SkillParseError("Skill frontmatter is missing closing '---' delimiter.")

    frontmatter = "".join(lines[1:end_index])
    body = "".join(lines[end_index + 1 :])
    try:
        loaded = yaml.safe_load(frontmatter) if frontmatter.strip() else {}
    except yaml.YAMLError as exc:
        raise SkillParseError(f"Invalid Skill frontmatter YAML: {exc}") from exc
    if not isinstance(loaded, dict):
        raise SkillParseError("Skill frontmatter must be a YAML mapping.")
    return loaded, body


def parse_skill_file(
    path: Path,
    source: SkillSource,
    *,
    is_directory: bool = False,
) -> Skill:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SkillParseError(f"Unable to read Skill file: {exc}") from exc
    metadata, body = split_frontmatter(raw)
    meta = _validate_meta(metadata)
    return Skill(
        meta=meta,
        prompt_body=body,
        entry_path=path,
        package_dir=path.parent if is_directory else path.parent,
        source=source,
        is_directory=is_directory,
    )


def substitute_arguments(prompt_body: str, args: str) -> str:
    if "$ARGUMENTS" in prompt_body:
        return prompt_body.replace("$ARGUMENTS", args)
    if args.strip():
        return f"{prompt_body.rstrip()}\n\n## User Request\n\n{args.strip()}\n"
    return prompt_body


def _validate_meta(raw: dict[str, Any]) -> SkillMeta:
    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        raise SkillParseError("Skill frontmatter requires string field 'name'.")
    name = name.strip()
    if not SKILL_NAME_RE.fullmatch(name):
        raise SkillParseError(
            "Skill name must match ^[a-z][a-z0-9_-]*$ for slash-command compatibility."
        )

    description = raw.get("description")
    if not isinstance(description, str) or not description.strip():
        raise SkillParseError("Skill frontmatter requires string field 'description'.")

    allowed_tools = raw.get("allowed_tools", ())
    if allowed_tools is None:
        allowed_tools = ()
    if not isinstance(allowed_tools, list | tuple) or not all(
        isinstance(item, str) and item.strip() for item in allowed_tools
    ):
        raise SkillParseError("Skill field 'allowed_tools' must be a list of strings.")

    mode_raw = raw.get("mode", SkillMode.INLINE.value)
    if not isinstance(mode_raw, str):
        raise SkillParseError("Skill field 'mode' must be a string.")
    try:
        mode = SkillMode(mode_raw.strip())
    except ValueError as exc:
        raise SkillParseError("Skill field 'mode' must be 'inline' or 'fork'.") from exc

    context_raw = raw.get("context", SkillContext.NONE.value)
    if not isinstance(context_raw, str):
        raise SkillParseError("Skill field 'context' must be a string.")
    try:
        context = SkillContext(context_raw.strip())
    except ValueError as exc:
        raise SkillParseError("Skill field 'context' must be 'none', 'recent', or 'full'.") from exc

    model = raw.get("model")
    if model is not None and (not isinstance(model, str) or not model.strip()):
        raise SkillParseError("Skill field 'model' must be a non-empty string when present.")

    return SkillMeta(
        name=name,
        description=description.strip(),
        allowed_tools=tuple(item.strip() for item in allowed_tools),
        mode=mode,
        context=context,
        model=model.strip() if isinstance(model, str) else None,
    )
