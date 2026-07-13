from __future__ import annotations

from dataclasses import dataclass, field

ALL_AGENT_DISALLOWED_TOOLS: list[str] = ["Agent"]
CUSTOM_AGENT_DISALLOWED_TOOLS: list[str] = []
ASYNC_AGENT_ALLOWED_TOOLS: list[str] = [
    "ReadFile",
    "WriteFile",
    "EditFile",
    "Glob",
    "Grep",
    "Bash",
    "LoadSkill",
    "InstallSkill",
]

_CANONICAL_BY_NORMALIZED = {
    "agent": "Agent",
    "read": "ReadFile",
    "readfile": "ReadFile",
    "readfiletool": "ReadFile",
    "read_file": "ReadFile",
    "write": "WriteFile",
    "writefile": "WriteFile",
    "writefiletool": "WriteFile",
    "write_file": "WriteFile",
    "edit": "EditFile",
    "editfile": "EditFile",
    "editfiletool": "EditFile",
    "edit_file": "EditFile",
    "bash": "Bash",
    "runcommand": "Bash",
    "run_command": "Bash",
    "glob": "Glob",
    "globfiles": "Glob",
    "glob_files": "Glob",
    "grep": "Grep",
    "searchcode": "Grep",
    "search_code": "Grep",
    "loadskill": "LoadSkill",
    "load_skill": "LoadSkill",
    "installskill": "InstallSkill",
    "install_skill": "InstallSkill",
    "tasklist": "TaskList",
    "taskget": "TaskGet",
    "taskstop": "TaskStop",
    "sendmessage": "SendMessage",
}


@dataclass(frozen=True)
class FilterParams:
    all: list[str]
    source: int = 0
    background: bool = False
    allowed: list[str] = field(default_factory=list)
    disallowed: list[str] = field(default_factory=list)


def apply_agent_tool_filter(params: FilterParams) -> list[str]:
    names = list(dict.fromkeys(params.all))
    names = [name for name in names if not _in_set(name, ALL_AGENT_DISALLOWED_TOOLS)]
    if params.source >= 1:
        names = [name for name in names if not _in_set(name, CUSTOM_AGENT_DISALLOWED_TOOLS)]
    if params.background:
        names = [
            name
            for name in names
            if _in_set(name, ASYNC_AGENT_ALLOWED_TOOLS) or is_mcp_or_skill(name)
        ]
    if params.disallowed:
        names = [name for name in names if not _in_set(name, params.disallowed)]
    if params.allowed:
        names = [name for name in names if _in_set(name, params.allowed)]
    return names


def is_mcp_or_skill(name: str) -> bool:
    canonical = canonical_tool_name(name)
    return name.startswith("mcp__") or canonical in {"LoadSkill", "InstallSkill"}


def canonical_tool_name(name: str) -> str:
    normalized = _normalize(name)
    return _CANONICAL_BY_NORMALIZED.get(normalized, name)


def _in_set(name: str, values: list[str] | tuple[str, ...] | set[str]) -> bool:
    target = canonical_tool_name(name)
    return any(canonical_tool_name(value) == target for value in values)


def _normalize(name: str) -> str:
    return "".join(ch for ch in name.strip().casefold() if ch.isalnum() or ch == "_")
