from __future__ import annotations

from pathlib import Path

from coco_code.permission import Category, Decision, Mode, mode_fallback, new_engine
from coco_code.permission.engine import Engine
from coco_code.permission.rule import Rule, RuleSet
from coco_code.tools import ConfirmationPolicy, ToolCall, ToolSpec, create_default_registry


def tool_spec(name: str):
    return create_default_registry().get(name).spec


def test_mode_fallback_matrix() -> None:
    assert mode_fallback(Mode.DEFAULT, Category.READ) == Decision.ALLOW
    assert mode_fallback(Mode.DEFAULT, Category.WRITE) == Decision.ASK
    assert mode_fallback(Mode.DEFAULT, Category.EXEC) == Decision.ASK
    assert mode_fallback(Mode.ACCEPT_EDITS, Category.WRITE) == Decision.ALLOW
    assert mode_fallback(Mode.ACCEPT_EDITS, Category.EXEC) == Decision.ASK
    assert mode_fallback(Mode.BYPASS, Category.WRITE) == Decision.ALLOW
    assert mode_fallback(Mode.BYPASS, Category.EXEC) == Decision.ALLOW


def test_engine_pipeline_blacklist_and_sandbox_short_circuit(tmp_path: Path) -> None:
    engine = Engine(root=str(tmp_path.resolve()))

    decision, reason = engine.check(
        Mode.BYPASS,
        ToolCall("1", "Bash", {"command": "rm -rf /"}, "{}"),
        tool_spec("Bash"),
    )
    assert decision == Decision.DENY
    assert "blacklist" in reason

    decision, reason = engine.check(
        Mode.BYPASS,
        ToolCall("2", "WriteFile", {"path": "../escape.txt", "content": "x"}, "{}"),
        tool_spec("WriteFile"),
    )
    assert decision == Decision.DENY
    assert "outside" in reason


def test_engine_rule_layers_prefer_local_over_project_over_user(tmp_path: Path) -> None:
    engine = Engine(
        root=str(tmp_path.resolve()),
        user=RuleSet(allow=[Rule("Bash", "git *", True)]),
        project=RuleSet(allow=[Rule("Bash", "git status", True)]),
        local=RuleSet(deny=[Rule("Bash", "git status", False)]),
    )
    decision, reason = engine.check(
        Mode.BYPASS,
        ToolCall("1", "Bash", {"command": "git status"}, "{}"),
        tool_spec("Bash"),
    )
    assert decision == Decision.DENY
    assert "local deny" in reason


def test_engine_defaults_read_to_allow_and_write_to_ask(tmp_path: Path) -> None:
    engine = Engine(root=str(tmp_path.resolve()))
    read_decision, _reason = engine.check(
        Mode.DEFAULT,
        ToolCall("1", "ReadFile", {"path": "notes.txt"}, "{}"),
        tool_spec("ReadFile"),
    )
    write_decision, reason = engine.check(
        Mode.DEFAULT,
        ToolCall("2", "WriteFile", {"path": "notes.txt", "content": "x"}, "{}"),
        tool_spec("WriteFile"),
    )
    assert read_decision == Decision.ALLOW
    assert write_decision == Decision.ASK
    assert "requires approval" in reason


def test_new_engine_loads_settings_and_start_mode_from_nearest_layer(tmp_path: Path) -> None:
    settings_dir = tmp_path / ".coco-code"
    settings_dir.mkdir()
    (settings_dir / "settings.yaml").write_text(
        "default_mode: plan\npermissions:\n  allow:\n    - 'Bash(git *)'\n",
        encoding="utf-8",
    )
    (settings_dir / "settings.local.yaml").write_text(
        "default_mode: bypassPermissions\n", encoding="utf-8"
    )

    engine, error = new_engine(tmp_path)
    assert error is None
    assert engine.start_mode == Mode.BYPASS
    decision, _reason = engine.check(
        Mode.DEFAULT,
        ToolCall("1", "Bash", {"command": "git status"}, "{}"),
        tool_spec("Bash"),
    )
    assert decision == Decision.ALLOW


def mcp_tool_spec(name: str, *, read_only: bool) -> ToolSpec:
    return ToolSpec(
        name=name,
        description="mcp tool",
        parameters_schema={"type": "object", "properties": {}},
        confirmation=ConfirmationPolicy.NEVER if read_only else ConfirmationPolicy.REQUIRED,
        read_only=read_only,
    )


def test_engine_mcp_rules_support_exact_and_glob_names(tmp_path: Path) -> None:
    engine = Engine(
        root=str(tmp_path.resolve()),
        user=RuleSet(allow=[Rule("mcp__github__*", "", True)]),
        local=RuleSet(deny=[Rule("mcp__github__delete_issue", "", False)]),
    )

    denied, denied_reason = engine.check(
        Mode.BYPASS,
        ToolCall("1", "mcp__github__delete_issue", {}, "{}"),
        mcp_tool_spec("mcp__github__delete_issue", read_only=False),
    )
    allowed, _allowed_reason = engine.check(
        Mode.DEFAULT,
        ToolCall("2", "mcp__github__create_issue", {}, "{}"),
        mcp_tool_spec("mcp__github__create_issue", read_only=False),
    )

    assert denied == Decision.DENY
    assert "local deny" in denied_reason
    assert allowed == Decision.ALLOW


def test_engine_mcp_read_only_and_exec_mode_fallbacks(tmp_path: Path) -> None:
    engine = Engine(root=str(tmp_path.resolve()))
    read_call = ToolCall(
        "1",
        "mcp__github__list_issues",
        {"command": "rm -rf /", "path": "../outside.txt"},
        "{}",
    )
    write_call = ToolCall(
        "2",
        "mcp__github__create_issue",
        {"command": "rm -rf /", "path": "../outside.txt"},
        "{}",
    )

    read_decision, _read_reason = engine.check(
        Mode.DEFAULT,
        read_call,
        mcp_tool_spec("mcp__github__list_issues", read_only=True),
    )
    default_decision, default_reason = engine.check(
        Mode.DEFAULT,
        write_call,
        mcp_tool_spec("mcp__github__create_issue", read_only=False),
    )
    accept_edits_decision, _accept_reason = engine.check(
        Mode.ACCEPT_EDITS,
        write_call,
        mcp_tool_spec("mcp__github__create_issue", read_only=False),
    )
    bypass_decision, _bypass_reason = engine.check(
        Mode.BYPASS,
        write_call,
        mcp_tool_spec("mcp__github__create_issue", read_only=False),
    )

    assert read_decision == Decision.ALLOW
    assert default_decision == Decision.ASK
    assert "requires approval" in default_reason
    assert accept_edits_decision == Decision.ASK
    assert bypass_decision == Decision.ALLOW
