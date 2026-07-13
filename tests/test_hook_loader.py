from __future__ import annotations

from pathlib import Path

from coco_code.hook.event import Event
from coco_code.hook.loader import load_hooks


def write_hooks(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_load_hooks_reads_project_file(tmp_path: Path) -> None:
    write_hooks(
        tmp_path / ".coco-code" / "hooks.yaml",
        """
hooks:
  - name: start
    event: SessionStart
    action:
      type: prompt
      text: hi
  - name: stop
    event: Stop
    action:
      type: shell
      command: echo stop
""",
    )

    engine = load_hooks(tmp_path, home=tmp_path / "home")

    rules = engine.rules()
    assert len(rules) == 2
    assert rules[0].event == Event.SESSION_START
    assert len(engine.sources()) == 1


def test_load_hooks_skips_invalid_rules_and_keeps_valid(
    tmp_path: Path, capsys
) -> None:
    write_hooks(
        tmp_path / ".coco-code" / "hooks.yaml",
        """
hooks:
  - name: bad-event
    event: UnknownEvent
    action:
      type: shell
      command: echo x
  - name: bad-action
    event: Stop
    action:
      type: nope
  - name: good
    event: Stop
    action:
      type: prompt
      text: done
""",
    )

    engine = load_hooks(tmp_path, home=tmp_path / "home")

    captured = capsys.readouterr()
    assert 'unknown event "UnknownEvent"' in captured.err
    assert "unknown action type" in captured.err
    assert [rule.name for rule in engine.rules()] == ["good"]


def test_load_hooks_rejects_mixed_condition_modes(tmp_path: Path, capsys) -> None:
    write_hooks(
        tmp_path / ".coco-code" / "hooks.yaml",
        """
hooks:
  - name: mixed
    event: Stop
    if:
      all_of: []
      any_of: []
    action:
      type: shell
      command: echo x
""",
    )

    engine = load_hooks(tmp_path, home=tmp_path / "home")

    captured = capsys.readouterr()
    assert "exactly one" in captured.err
    assert engine.rules() == ()


def test_load_hooks_rejects_async_blocking_event(tmp_path: Path, capsys) -> None:
    write_hooks(
        tmp_path / ".coco-code" / "hooks.yaml",
        """
hooks:
  - name: bad-async
    event: PreToolUse
    async: true
    action:
      type: shell
      command: echo x
""",
    )

    engine = load_hooks(tmp_path, home=tmp_path / "home")

    captured = capsys.readouterr()
    assert "async not allowed for blocking events" in captured.err
    assert engine.rules() == ()


def test_load_hooks_merges_project_and_user_with_duplicate_skip(
    tmp_path: Path, capsys
) -> None:
    home = tmp_path / "home"
    write_hooks(
        tmp_path / ".coco-code" / "hooks.yaml",
        """
hooks:
  - name: same
    event: Stop
    action:
      type: shell
      command: echo project
""",
    )
    write_hooks(
        home / ".coco-code" / "hooks.yaml",
        """
hooks:
  - name: same
    event: Stop
    action:
      type: shell
      command: echo user
  - name: user-only
    event: SessionEnd
    action:
      type: shell
      command: echo user
""",
    )

    engine = load_hooks(tmp_path, home=home)

    captured = capsys.readouterr()
    assert "duplicate name" in captured.err
    assert [rule.name for rule in engine.rules()] == ["same", "user-only"]
    assert len(engine.sources()) == 2


def test_load_hooks_rejects_bad_regex_and_bad_yaml(tmp_path: Path, capsys) -> None:
    write_hooks(
        tmp_path / ".coco-code" / "hooks.yaml",
        """
hooks:
  - name: bad-regex
    event: Stop
    if:
      all_of:
        - field: prompt
          match: { type: regex, value: "[bad" }
    action:
      type: shell
      command: echo x
""",
    )

    engine = load_hooks(tmp_path, home=tmp_path / "home")

    assert engine.rules() == ()
    assert "invalid regex" in capsys.readouterr().err
