"""Offline analysis of CoCo Code stream-json evaluation trajectories."""

from __future__ import annotations

import hashlib
import json
import re
import shlex
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


_WRITE_TOOLS = {"EditFile", "WriteFile"}
_DEDICATED_TOOL_COMMANDS = {
    "cat",
    "egrep",
    "fgrep",
    "find",
    "grep",
    "head",
    "ls",
    "rg",
    "sed",
    "tail",
}


@dataclass
class TrajectoryAnalysis:
    trajectory_path: str
    invalid_line_count: int = 0
    event_counts: dict[str, int] = field(default_factory=dict)
    tool_counts: dict[str, int] = field(default_factory=dict)
    tool_error_count: int = 0
    tool_errors: list[dict[str, Any]] = field(default_factory=list)
    exact_repeat_tool_calls: int = 0
    repeated_read_ranges: int = 0
    edit_count: int = 0
    edit_reversal_count: int = 0
    edit_records: list[dict[str, Any]] = field(default_factory=list)
    bash_command_count: int = 0
    bash_command_counts: list[dict[str, Any]] = field(default_factory=list)
    bash_dedicated_tool_violations: int = 0
    bash_violation_commands: list[str] = field(default_factory=list)
    test_run_count: int = 0
    test_target_counts: dict[str, int] = field(default_factory=dict)
    usage_event_count: int = 0
    nonzero_usage_event_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    usage_is_estimated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:12]


def _canonical_args(args: dict[str, Any]) -> str:
    return json.dumps(args, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _normalise_command(command: str) -> str:
    return " ".join(command.split())


def _leading_executable(segment: str) -> str:
    first_pipeline_segment = segment.split("|", maxsplit=1)[0].strip()
    try:
        tokens = shlex.split(first_pipeline_segment)
    except ValueError:
        tokens = first_pipeline_segment.split()
    for token in tokens:
        if re.match(r"^[A-Za-z_]\w*=", token):
            continue
        if token in {"env", "sudo"}:
            continue
        return token.rsplit("/", maxsplit=1)[-1]
    return ""


def _dedicated_tool_violation(command: str) -> bool:
    for segment in re.split(r"&&|;", command):
        if _leading_executable(segment) in _DEDICATED_TOOL_COMMANDS:
            return True
    return False


def _pytest_target(command: str) -> str | None:
    for segment in re.split(r"&&|;", command):
        first_pipeline_segment = segment.split("|", maxsplit=1)[0].strip()
        try:
            tokens = shlex.split(first_pipeline_segment)
        except ValueError:
            tokens = first_pipeline_segment.split()
        pytest_index: int | None = None
        for index, token in enumerate(tokens):
            executable = token.rsplit("/", maxsplit=1)[-1]
            if executable == "pytest":
                pytest_index = index
                break
            if token == "-m" and index + 1 < len(tokens):
                if tokens[index + 1] == "pytest":
                    pytest_index = index + 1
                    break
        if pytest_index is None:
            continue
        for token in tokens[pytest_index + 1 :]:
            if token.startswith("-") or token in {"2>&1"}:
                continue
            return token
        return "<all>"
    return None


def _load_events(path: Path) -> tuple[list[dict[str, Any]], int]:
    events: list[dict[str, Any]] = []
    invalid_lines = 0
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not raw_line.strip():
            continue
        try:
            event = json.loads(raw_line)
        except json.JSONDecodeError:
            invalid_lines += 1
            continue
        if isinstance(event, dict):
            events.append(event)
        else:
            invalid_lines += 1
    return events, invalid_lines


def analyze_trajectory(path: Path) -> TrajectoryAnalysis:
    trajectory_path = path.resolve()
    if not trajectory_path.is_file():
        raise ValueError(f"trajectory file does not exist: {trajectory_path}")

    events, invalid_lines = _load_events(trajectory_path)
    event_counts: Counter[str] = Counter()
    tool_counts: Counter[str] = Counter()
    signature_counts: Counter[tuple[int, str, str]] = Counter()
    read_counts: Counter[tuple[int, str, int, int]] = Counter()
    bash_counts: Counter[str] = Counter()
    test_targets: Counter[str] = Counter()
    pending: dict[str, dict[str, Any]] = {}
    last_edit_by_file: dict[str, tuple[str, str]] = {}
    edit_records: list[dict[str, Any]] = []
    tool_errors: list[dict[str, Any]] = []
    violation_commands: list[str] = []
    workspace_revision = 0
    edit_reversals = 0
    usage_events = 0
    nonzero_usage_events = 0
    input_tokens = 0
    output_tokens = 0
    usage_is_estimated = False

    for event in events:
        event_type = str(event.get("type", "unknown"))
        event_counts[event_type] += 1

        if event_type == "usage":
            usage_events += 1
            current_input = int(event.get("input_tokens", 0) or 0)
            current_output = int(event.get("output_tokens", 0) or 0)
            if current_input or current_output:
                nonzero_usage_events += 1
            input_tokens = current_input
            output_tokens = current_output
            usage_is_estimated = bool(event.get("is_estimated", False))
            continue

        if event_type == "result":
            usage = event.get("usage") or {}
            input_tokens = int(usage.get("input_tokens", input_tokens) or 0)
            output_tokens = int(usage.get("output_tokens", output_tokens) or 0)
            usage_is_estimated = bool(
                usage.get("is_estimated", usage_is_estimated)
            )
            continue

        if event_type == "tool_use":
            tool_name = str(event.get("tool_name", "unknown"))
            tool_id = str(event.get("tool_id", ""))
            args = event.get("args") or {}
            if not isinstance(args, dict):
                args = {"value": args}
            tool_counts[tool_name] += 1
            signature_counts[
                (workspace_revision, tool_name, _canonical_args(args))
            ] += 1
            pending[tool_id] = {
                "tool_name": tool_name,
                "args": args,
                "revision": workspace_revision,
            }

            if tool_name == "ReadFile":
                read_counts[
                    (
                        workspace_revision,
                        str(args.get("file_path", "")),
                        int(args.get("offset", 0) or 0),
                        int(args.get("limit", 2000) or 2000),
                    )
                ] += 1
            elif tool_name == "Bash":
                command = _normalise_command(str(args.get("command", "")))
                bash_counts[command] += 1
                if _dedicated_tool_violation(command):
                    violation_commands.append(command[:300])
                target = _pytest_target(command)
                if target is not None:
                    test_targets[target] += 1
            continue

        if event_type != "tool_result":
            continue

        tool_id = str(event.get("tool_id", ""))
        tool_name = str(event.get("tool_name", "unknown"))
        is_error = bool(event.get("is_error", False))
        call = pending.get(tool_id)
        if is_error:
            tool_errors.append(
                {
                    "tool_name": tool_name,
                    "tool_id": tool_id,
                    "output": str(event.get("output", ""))[:500],
                }
            )
            continue
        if call is None or call["tool_name"] not in _WRITE_TOOLS:
            continue

        args = call["args"]
        if call["tool_name"] == "EditFile":
            file_path = str(args.get("file_path", ""))
            old_string = str(args.get("old_string", ""))
            new_string = str(args.get("new_string", ""))
            previous = last_edit_by_file.get(file_path)
            reverses_previous = bool(
                previous
                and old_string == previous[1]
                and new_string == previous[0]
            )
            if reverses_previous:
                edit_reversals += 1
            edit_records.append(
                {
                    "file_path": file_path,
                    "old_hash": _stable_hash(old_string),
                    "new_hash": _stable_hash(new_string),
                    "old_chars": len(old_string),
                    "new_chars": len(new_string),
                    "reverses_previous": reverses_previous,
                }
            )
            last_edit_by_file[file_path] = (old_string, new_string)
        workspace_revision += 1

    exact_repeats = sum(max(count - 1, 0) for count in signature_counts.values())
    repeated_reads = sum(max(count - 1, 0) for count in read_counts.values())
    bash_command_counts = [
        {"count": count, "command": command[:300]}
        for command, count in bash_counts.most_common()
    ]

    return TrajectoryAnalysis(
        trajectory_path=str(trajectory_path),
        invalid_line_count=invalid_lines,
        event_counts=dict(event_counts.most_common()),
        tool_counts=dict(tool_counts.most_common()),
        tool_error_count=len(tool_errors),
        tool_errors=tool_errors,
        exact_repeat_tool_calls=exact_repeats,
        repeated_read_ranges=repeated_reads,
        edit_count=len(edit_records),
        edit_reversal_count=edit_reversals,
        edit_records=edit_records,
        bash_command_count=sum(bash_counts.values()),
        bash_command_counts=bash_command_counts,
        bash_dedicated_tool_violations=len(violation_commands),
        bash_violation_commands=violation_commands,
        test_run_count=sum(test_targets.values()),
        test_target_counts=dict(test_targets.most_common()),
        usage_event_count=usage_events,
        nonzero_usage_event_count=nonzero_usage_events,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        usage_is_estimated=usage_is_estimated,
    )
