from __future__ import annotations

from coco_code.tools.filter import (
    ALL_AGENT_DISALLOWED_TOOLS,
    ASYNC_AGENT_ALLOWED_TOOLS,
    CUSTOM_AGENT_DISALLOWED_TOOLS,
    FilterParams,
    apply_agent_tool_filter,
    canonical_tool_name,
    is_mcp_or_skill,
)

ALL_TOOLS = [
    "ReadFile",
    "WriteFile",
    "EditFile",
    "Bash",
    "Glob",
    "Grep",
    "LoadSkill",
    "InstallSkill",
    "Agent",
    "TaskList",
    "SendMessage",
    "mcp__demo__lookup",
]


def test_constants() -> None:
    assert ALL_AGENT_DISALLOWED_TOOLS == ["Agent"]
    assert CUSTOM_AGENT_DISALLOWED_TOOLS == []
    assert "Bash" in ASYNC_AGENT_ALLOWED_TOOLS


def test_default_filter_removes_agent_tool() -> None:
    assert apply_agent_tool_filter(FilterParams(all=ALL_TOOLS)) == [
        name for name in ALL_TOOLS if name != "Agent"
    ]


def test_background_filter_intersects_allowed_set_and_keeps_mcp() -> None:
    names = apply_agent_tool_filter(FilterParams(all=ALL_TOOLS, background=True))
    assert "Agent" not in names
    assert "TaskList" not in names
    assert "SendMessage" not in names
    assert "mcp__demo__lookup" in names
    assert "ReadFile" in names


def test_disallowed_and_allowed_use_aliases() -> None:
    names = apply_agent_tool_filter(
        FilterParams(
            all=ALL_TOOLS,
            allowed=["read_file", "grep", "bash"],
            disallowed=["run_command"],
        )
    )
    assert names == ["ReadFile", "Grep"]


def test_canonical_tool_name_maps_aliases() -> None:
    assert canonical_tool_name("write_file") == "WriteFile"
    assert canonical_tool_name("Bash") == "Bash"


def test_is_mcp_or_skill() -> None:
    assert is_mcp_or_skill("mcp__demo__lookup") is True
    assert is_mcp_or_skill("LoadSkill") is True
    assert is_mcp_or_skill("ReadFile") is False
