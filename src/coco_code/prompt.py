from __future__ import annotations

from pathlib import Path

from coco_code.config import ProviderConfig

CAT_BANNER = r"""
 /\_/\\
( o.o )
 > ^ <
"""

SYSTEM_PROMPT = """You are CoCo Code, a terminal AI coding assistant.

Capabilities:
- You can hold multi-turn conversations and request tool calls when workspace info is needed.
- You can read files, write files, edit code, search the workspace, and run shell commands.
- High-risk actions are governed by the configured permission and confirmation system.
- Use tool results as evidence. If ok=false, adjust your approach or explain the blocker.
- Keep file paths inside the current workspace unless explicitly allowed by the environment.
- Prefer dedicated tools for read, write, edit, glob, and grep tasks.
- Use Bash for build, test, install, and other commands.

Modes:
- agent: default mode, all available tools may be used subject to permissions.
- plan: read-only planning mode.
- do: execution mode for carrying out an approved plan.

Answer concisely and accurately."""


def build_system_prompt(
    cwd: Path,
    provider: ProviderConfig,
    instructions: str = "",
    memory: str = "",
    skills_catalog: str = "",
    active_skills: str = "",
    hook_reminders: str = "",
) -> str:
    parts = [
        SYSTEM_PROMPT,
        "",
        "Runtime Environment:",
        f"- Current working directory: {cwd}",
        f"- Current provider: {provider.name}",
        f"- Current protocol: {provider.protocol}",
        f"- Current model: {provider.model}",
    ]
    skills_catalog = skills_catalog.strip()
    if skills_catalog:
        parts.extend(["", skills_catalog])
    active_skills = active_skills.strip()
    if active_skills:
        parts.extend(["", active_skills])
    hook_reminders = hook_reminders.strip()
    if hook_reminders:
        parts.extend(["", "Hook Reminders:", hook_reminders])
    memory = memory.strip()
    if memory:
        parts.extend(
            [
                "",
                "Long-term Memory Index:",
                (
                    "The following content is a memory index. "
                    "Read referenced memory files when full details are needed."
                ),
                memory,
            ]
        )
    instructions = instructions.strip()
    if instructions:
        parts.extend(
            [
                "",
                "Project Instructions:",
                (
                    "Follow these project and user instructions when they do not conflict "
                    "with core safety and tool boundaries."
                ),
                instructions,
            ]
        )
    return "\n".join(parts)


def render_banner(version: str, cwd: Path, provider: ProviderConfig) -> str:
    return "\n".join(
        [
            CAT_BANNER.strip("\n"),
            f"CoCo Code v{version}",
            f"Provider: {provider.name} ({provider.protocol})",
            f"Model: {provider.model}",
            f"CWD: {cwd}",
        ]
    )
