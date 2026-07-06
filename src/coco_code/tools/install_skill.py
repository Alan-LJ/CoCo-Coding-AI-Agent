from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from time import monotonic

from coco_code.skills.install import SkillInstallError, install_from_url
from coco_code.tools.base import (
    ConfirmationPolicy,
    ToolCategory,
    ToolContext,
    ToolParams,
    ToolResult,
    ToolSpec,
)

ReloadCallback = Callable[[], Awaitable[None] | None]


class InstallSkillTool:
    def __init__(
        self,
        user_root: Path,
        *,
        reload_callback: ReloadCallback | None = None,
    ) -> None:
        self._user_root = user_root
        self._reload_callback = reload_callback

    def set_reload_callback(self, callback: ReloadCallback | None) -> None:
        self._reload_callback = callback

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="InstallSkill",
            description=(
                "Install a remote Skill into the user Skill directory. Use this whenever the "
                "user asks to install, add, or fetch a Skill from a URL. Pass the original URL "
                "directly; skills.sh pages, raw GitHub SKILL.md URLs, and GitHub tree URLs are "
                "supported, and this tool resolves skills.sh pages into downloadable Skill files."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "source_url": {
                        "type": "string",
                        "description": (
                            "The Skill source URL, for example "
                            "https://www.skills.sh/anthropics/skills/frontend-design."
                        ),
                    }
                },
                "required": ["source_url"],
                "additionalProperties": False,
            },
            confirmation=ConfirmationPolicy.REQUIRED,
            category=ToolCategory.FILE,
            read_only=False,
            destructive=False,
            typical_scenarios=(
                "User says 'install this skill' followed by a skills.sh or GitHub URL.",
                "User wants to add a reusable AI Skill to the local Skill catalog.",
            ),
            aliases=("Installskill", "installskill", "install_skill"),
            system=False,
        )

    async def run(self, params: ToolParams, context: ToolContext) -> ToolResult:  # noqa: ARG002
        started = monotonic()
        source_url = params.get("source_url")
        if not isinstance(source_url, str) or not source_url.strip():
            return _failure(
                self.spec.name, "InstallSkill parameter `source_url` must be a string.", started
            )
        try:
            result = await install_from_url(source_url.strip(), self._user_root)
            if self._reload_callback is not None:
                maybe_awaitable = self._reload_callback()
                if maybe_awaitable is not None:
                    await maybe_awaitable
            return ToolResult(
                tool_call_id="",
                tool_name=self.spec.name,
                ok=True,
                summary=f"Installed Skill '{result.name}'.",
                data={
                    "skill": result.name,
                    "target_dir": str(result.target_dir),
                    "file_count": result.file_count,
                    "total_bytes": result.total_bytes,
                },
                error=None,
                elapsed_ms=_elapsed_ms(started),
            )
        except (OSError, SkillInstallError, ValueError) as exc:
            return _failure(self.spec.name, str(exc), started)


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
