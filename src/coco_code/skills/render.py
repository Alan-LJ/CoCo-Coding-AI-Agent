from __future__ import annotations

from collections.abc import Sequence

from coco_code.skills.active import ActiveSkillEntry
from coco_code.skills.parser import substitute_arguments
from coco_code.skills.types import Skill


def render_skill_body(skill: Skill, args: str = "") -> str:
    return substitute_arguments(skill.prompt_body, args)


def render_skills_catalog(skills: Sequence[Skill]) -> str:
    if not skills:
        return ""
    lines = [
        "Available Skills:",
        (
            "The following reusable SOPs are available. If the user's request matches one, "
            "call LoadSkill with its name before proceeding."
        ),
        "",
    ]
    for skill in skills:
        lines.append(
            f"- {skill.meta.name}: {skill.meta.description} "
            f"[{skill.source.value}, {skill.meta.mode.value}]"
        )
    return "\n".join(lines)


def render_active_skills_block(entries: Sequence[ActiveSkillEntry]) -> str:
    if not entries:
        return ""
    parts = ["## Active Skills", ""]
    for entry in entries:
        parts.extend([f"### Skill: {entry.name}", "", entry.rendered_body.strip(), ""])
    return "\n".join(parts).rstrip()

