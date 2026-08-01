from __future__ import annotations

import json
from pathlib import Path

from coco_code.evaluation.trajectory import analyze_trajectory


def _write_events(path: Path, events: list[dict]) -> None:
    lines = [json.dumps(event, ensure_ascii=False) for event in events]
    lines.insert(3, "not-json")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_analyze_trajectory_detects_repeats_reversals_and_test_runs(
    tmp_path: Path,
) -> None:
    trajectory = tmp_path / "trajectory.jsonl"
    read_args = {"file_path": "/testbed/sh.py", "offset": 889, "limit": 10}
    events = [
        {"type": "usage", "input_tokens": 0, "output_tokens": 0},
        {"type": "tool_use", "tool_name": "ReadFile", "tool_id": "r1", "args": read_args},
        {"type": "tool_result", "tool_name": "ReadFile", "tool_id": "r1", "output": "A", "is_error": False},
        {"type": "tool_use", "tool_name": "ReadFile", "tool_id": "r2", "args": read_args},
        {"type": "tool_result", "tool_name": "ReadFile", "tool_id": "r2", "output": "A", "is_error": False},
        {"type": "tool_use", "tool_name": "EditFile", "tool_id": "e1", "args": {"file_path": "/testbed/sh.py", "old_string": "A", "new_string": "B"}},
        {"type": "tool_result", "tool_name": "EditFile", "tool_id": "e1", "output": "updated", "is_error": False},
        {"type": "tool_use", "tool_name": "ReadFile", "tool_id": "r3", "args": read_args},
        {"type": "tool_result", "tool_name": "ReadFile", "tool_id": "r3", "output": "B", "is_error": False},
        {"type": "tool_use", "tool_name": "EditFile", "tool_id": "e2", "args": {"file_path": "/testbed/sh.py", "old_string": "B", "new_string": "A"}},
        {"type": "tool_result", "tool_name": "EditFile", "tool_id": "e2", "output": "updated", "is_error": False},
        {"type": "tool_use", "tool_name": "Bash", "tool_id": "b1", "args": {"command": "cd /testbed && grep -n return_cmd sh.py"}},
        {"type": "tool_result", "tool_name": "Bash", "tool_id": "b1", "output": "match", "is_error": False},
        {"type": "tool_use", "tool_name": "Bash", "tool_id": "b2", "args": {"command": "cd /testbed && python -m pytest tests/sh_test.py::test_a -q | tail -20"}},
        {"type": "tool_result", "tool_name": "Bash", "tool_id": "b2", "output": "passed", "is_error": False},
        {"type": "tool_use", "tool_name": "Bash", "tool_id": "b3", "args": {"command": "cd /testbed && FLAG=1 python -m pytest tests/sh_test.py::test_a -x"}},
        {"type": "tool_result", "tool_name": "Bash", "tool_id": "b3", "output": "failed", "is_error": True},
        {"type": "usage", "input_tokens": 120, "output_tokens": 30, "is_estimated": True},
        {"type": "result", "usage": {"input_tokens": 120, "output_tokens": 30, "is_estimated": True}},
    ]
    _write_events(trajectory, events)

    analysis = analyze_trajectory(trajectory)

    assert analysis.invalid_line_count == 1
    assert analysis.tool_counts == {"ReadFile": 3, "Bash": 3, "EditFile": 2}
    assert analysis.exact_repeat_tool_calls == 1
    assert analysis.repeated_read_ranges == 1
    assert analysis.edit_count == 2
    assert analysis.edit_reversal_count == 1
    assert analysis.edit_records[-1]["reverses_previous"] is True
    assert analysis.bash_command_count == 3
    assert analysis.bash_dedicated_tool_violations == 1
    assert analysis.test_run_count == 2
    assert analysis.test_target_counts == {"tests/sh_test.py::test_a": 2}
    assert analysis.tool_error_count == 1
    assert analysis.usage_event_count == 2
    assert analysis.nonzero_usage_event_count == 1
    assert analysis.input_tokens == 120
    assert analysis.output_tokens == 30
    assert analysis.usage_is_estimated is True


def test_analyze_trajectory_rejects_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "missing.jsonl"
    try:
        analyze_trajectory(missing)
    except ValueError as exc:
        assert "trajectory file does not exist" in str(exc)
    else:
        raise AssertionError("expected ValueError")
