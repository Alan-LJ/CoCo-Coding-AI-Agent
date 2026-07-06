from __future__ import annotations

from time import monotonic
from typing import Any

from coco_code.skills.catalog import SkillCatalog
from coco_code.skills.render import render_skill_body
from coco_code.skills.types import Skill
from coco_code.tools.base import (
    ConfirmationPolicy,
    ToolContext,
    ToolParams,
    ToolResult,
    ToolSpec,
)


class LoadSkillTool:
    def __init__(self, catalog: SkillCatalog | None = None, active: Any | None = None) -> None:
        self._catalog = catalog
        self._active = active

    def attach(self, catalog: SkillCatalog, active: Any) -> None:
        self._catalog = catalog
        self._active = active

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="LoadSkill",
            description="Load and activate a reusable Skill SOP by name.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "arguments": {"type": "string"},
                },
                "required": ["name"],
                "additionalProperties": False,
            },
            confirmation=ConfirmationPolicy.NEVER,
            read_only=True,
            destructive=False,
            system=True,
        )

    async def run(self, params: ToolParams, context: ToolContext) -> ToolResult:  # noqa: ARG002
        started = monotonic()
        if self._catalog is None or self._active is None:
            return _failure(self.spec.name, "LoadSkill is not initialized.", started)
        name = params.get("name")
        if not isinstance(name, str) or not name.strip():
            return _failure(self.spec.name, "LoadSkill parameter `name` must be a string.", started)
        args = params.get("arguments", "")
        if not isinstance(args, str):
            return _failure(
                self.spec.name, "LoadSkill parameter `arguments` must be a string.", started
            )
        skill = self._catalog.get_latest(name.strip())
        if skill is None:
            available = ", ".join(skill.meta.name for skill in self._catalog.list()) or "none"
            return _failure(
                self.spec.name, f"Unknown Skill '{name}'. Available Skills: {available}.", started
            )
        return _activate_skill(self.spec.name, skill, args, self._active, started)


def _activate_skill(
    tool_name: str,
    skill: Skill,
    args: str,
    active: Any,
    started: float,
) -> ToolResult:
    rendered = render_skill_body(skill, args)
    active.activate(skill.meta.name, rendered, skill.meta.allowed_tools)
    summary = f"Skill '{skill.meta.name}' activated. SOP pinned to environment context."
    return ToolResult(
        tool_call_id="",
        tool_name=tool_name,
        ok=True,
        summary=summary,
        data={"skill": skill.meta.name},
        error=None,
        elapsed_ms=_elapsed_ms(started),
    )


def _failure(tool_name: str, message: str, started: float) -> ToolResult:
    return ToolResult(
        tool_call_id="",
        tool_name=tool_name,
        ok=False,
        summary=message,
        data={},
        error=message,
        elapsed_ms=_elapsed_ms(started),
    )


def _elapsed_ms(started: float) -> int:
    return int((monotonic() - started) * 1000)
