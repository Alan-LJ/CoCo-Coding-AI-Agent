from __future__ import annotations

from coco_code.permission import Decision
from coco_code.permission.rule import Rule, RuleSet, match_pattern, parse_rule


def test_parse_rule_accepts_tool_with_or_without_pattern() -> None:
    rule, ok = parse_rule("Bash(git *)")
    assert ok is True
    assert rule.tool == "Bash"
    assert rule.pattern == "git *"

    rule, ok = parse_rule("Read")
    assert ok is True
    assert rule.tool == "Read"
    assert rule.pattern == ""

    _rule, ok = parse_rule("Bash(git *")
    assert ok is False


def test_match_pattern_supports_command_and_path_globs() -> None:
    assert match_pattern("git *", "git status") is True
    assert match_pattern("git *", "npm install") is False
    assert match_pattern("src/**", "src/a/b.py") is True
    assert match_pattern("src/**", "docs/a.py") is False
    assert match_pattern("", "anything") is True


def test_rule_set_prefers_deny_over_allow_in_same_layer() -> None:
    rules = RuleSet(
        allow=[Rule("Bash", "git *", True)],
        deny=[Rule("Bash", "git status", False)],
    )
    assert rules.match("Bash", "git status") == (Decision.DENY, True)
    assert rules.match("Bash", "git diff") == (Decision.ALLOW, True)
    assert rules.match("Bash", "npm test") == (Decision.ALLOW, False)


def test_rule_set_matches_mcp_tool_globs() -> None:
    rules = RuleSet(
        allow=[Rule("mcp__github__*", "", True)],
        deny=[Rule("mcp__github__delete_issue", "", False)],
    )
    assert rules.match("mcp__github__delete_issue", "") == (Decision.DENY, True)
    assert rules.match("mcp__github__create_issue", "") == (Decision.ALLOW, True)
    assert rules.match("mcp__slack__post_message", "") == (Decision.ALLOW, False)
