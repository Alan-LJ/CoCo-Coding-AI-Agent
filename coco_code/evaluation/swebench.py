"""SWE-bench-Live inference and grading orchestration.

This module deliberately has no dependency on the SWE-bench package. CoCo Code
inference and the official grading harness normally live in separate virtual
environments, so the integration boundary is the prediction JSONL file.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from coco_code.evaluation.trajectory import analyze_trajectory


@dataclass(frozen=True)
class InferenceConfig:
    instance_id: str
    problem_statement: str
    work_dir: Path
    output_dir: Path
    model_name: str
    timeout_seconds: int = 3600
    coco_code_python: str = sys.executable


@dataclass
class InferenceResult:
    instance_id: str
    model_name_or_path: str
    status: str
    model_patch: str
    duration_ms: int
    exit_code: int
    stop_reason: str = ""
    num_turns: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    usage_is_estimated: bool = False
    compact_count: int = 0
    compactions: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    artifact_dir: str = ""

    def prediction(self) -> dict[str, str]:
        return {
            "instance_id": self.instance_id,
            "model_name_or_path": self.model_name_or_path,
            "model_patch": self.model_patch,
        }


@dataclass(frozen=True)
class HarnessConfig:
    harness_dir: Path
    predictions_path: Path
    run_id: str
    dataset_name: str = "SWE-bench-Live/SWE-bench-Live"
    split: str = "lite"
    namespace: str = "starryzhang"
    max_workers: int = 1
    timeout_seconds: int = 7200
    harness_python: str = sys.executable
    instance_ids: tuple[str, ...] = ()


def instance_slug(instance_id: str) -> str:
    """Return a filesystem-safe, readable instance identifier."""
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")
    return "".join(c if c in allowed else "_" for c in instance_id)


def build_coco_code_command(config: InferenceConfig) -> list[str]:
    return [
        config.coco_code_python,
        "-m",
        "coco_code",
        "--mode",
        "bypassPermissions",
        "-p",
        config.problem_statement,
        "--output-format",
        "stream-json",
    ]


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _run_to_files(
    command: Sequence[str],
    *,
    cwd: Path,
    stdout_path: Path,
    stderr_path: Path,
    timeout_seconds: int,
) -> tuple[int, bool]:
    """Run a command without buffering an unbounded agent trajectory in RAM."""
    with stdout_path.open("w", encoding="utf-8", newline="\n") as stdout_file, (
        stderr_path.open("w", encoding="utf-8", newline="\n")
    ) as stderr_file:
        try:
            completed = subprocess.run(
                list(command),
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=stdout_file,
                stderr=stderr_file,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds,
                check=False,
            )
            return completed.returncode, False
        except subprocess.TimeoutExpired:
            stderr_file.write(
                f"\nCommand timed out after {timeout_seconds} seconds.\n"
            )
            return 124, True


def _parse_trajectory(path: Path) -> dict[str, Any]:
    state: dict[str, Any] = {
        "result_seen": False,
        "stop_reason": "",
        "num_turns": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "usage_is_estimated": False,
        "compact_count": 0,
        "compactions": [],
        "tool_calls": [],
        "errors": [],
    }

    if not path.exists():
        state["errors"].append("trajectory file was not created")
        return state

    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            state["errors"].append(f"invalid NDJSON at line {line_number}")
            continue

        event_type = event.get("type")
        if event_type == "compact":
            state["compact_count"] += 1
            state["compactions"].append(
                {
                    "before_tokens": int(event.get("before_tokens", 0) or 0),
                    "summary": str(event.get("summary", "")),
                    "keep_message_count": int(event.get("keep_message_count", 0) or 0),
                }
            )
        elif event_type == "tool_use":
            state["tool_calls"].append(
                {
                    "name": event.get("tool_name", ""),
                    "tool_id": event.get("tool_id", ""),
                    "args": event.get("args", {}),
                }
            )
        elif event_type == "error":
            state["errors"].append(str(event.get("message", "unknown agent error")))
        elif event_type == "result":
            state["result_seen"] = True
            state["stop_reason"] = str(event.get("stop_reason", ""))
            state["num_turns"] = int(event.get("num_turns", 0) or 0)
            usage = event.get("usage") or {}
            state["input_tokens"] = int(usage.get("input_tokens", 0) or 0)
            state["output_tokens"] = int(usage.get("output_tokens", 0) or 0)
            state["usage_is_estimated"] = bool(usage.get("is_estimated", False))
            if event.get("tool_calls"):
                state["tool_calls"] = list(event["tool_calls"])

    return state


def _git_patch(work_dir: Path) -> tuple[str, str | None]:
    try:
        completed = subprocess.run(
            ["git", "--no-pager", "diff", "HEAD", "--text"],
            cwd=work_dir,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return "", f"failed to export git diff: {exc}"

    if completed.returncode != 0:
        detail = completed.stderr.strip() or f"git exited with {completed.returncode}"
        return "", f"failed to export git diff: {detail}"
    return completed.stdout, None


def write_predictions_jsonl(results: Iterable[InferenceResult], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as output:
        for result in results:
            output.write(json.dumps(result.prediction(), ensure_ascii=False) + "\n")


def run_inference(
    config: InferenceConfig,
    *,
    command: Sequence[str] | None = None,
) -> InferenceResult:
    work_dir = config.work_dir.resolve()
    if not work_dir.is_dir():
        raise ValueError(f"work directory does not exist: {work_dir}")
    if not (work_dir / ".git").exists():
        raise ValueError(f"work directory is not a git checkout: {work_dir}")
    if config.timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")

    artifact_dir = config.output_dir.resolve() / instance_slug(config.instance_id)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    trajectory_path = artifact_dir / "trajectory.jsonl"
    stderr_path = artifact_dir / "agent.stderr.log"

    actual_command = list(command) if command is not None else build_coco_code_command(config)
    _write_json(
        artifact_dir / "run-config.json",
        {
            "instance_id": config.instance_id,
            "model_name": config.model_name,
            "work_dir": str(work_dir),
            "timeout_seconds": config.timeout_seconds,
            # Persist the executable shape, but not the full prompt or environment secrets.
            "command": ["<problem_statement>" if arg == config.problem_statement else arg for arg in actual_command],
        },
    )

    started = time.monotonic()
    exit_code, timed_out = _run_to_files(
        actual_command,
        cwd=work_dir,
        stdout_path=trajectory_path,
        stderr_path=stderr_path,
        timeout_seconds=config.timeout_seconds,
    )
    duration_ms = int((time.monotonic() - started) * 1000)

    trajectory = _parse_trajectory(trajectory_path)
    try:
        analysis = analyze_trajectory(trajectory_path)
        _write_json(artifact_dir / "trajectory-analysis.json", analysis.to_dict())
    except (OSError, ValueError) as exc:
        trajectory["errors"].append(f"failed to analyze trajectory: {exc}")
    patch, patch_error = _git_patch(work_dir)
    errors = list(trajectory["errors"])
    if timed_out:
        errors.append(f"agent timed out after {config.timeout_seconds} seconds")
    if patch_error:
        errors.append(patch_error)

    if exit_code != 0 or not trajectory["result_seen"]:
        status = "error"
    elif not patch:
        status = "empty_patch"
    else:
        status = "completed"

    result = InferenceResult(
        instance_id=config.instance_id,
        model_name_or_path=config.model_name,
        status=status,
        model_patch=patch,
        duration_ms=duration_ms,
        exit_code=exit_code,
        stop_reason=trajectory["stop_reason"],
        num_turns=trajectory["num_turns"],
        input_tokens=trajectory["input_tokens"],
        output_tokens=trajectory["output_tokens"],
        usage_is_estimated=trajectory["usage_is_estimated"],
        compact_count=trajectory["compact_count"],
        compactions=trajectory["compactions"],
        tool_calls=trajectory["tool_calls"],
        errors=errors,
        artifact_dir=str(artifact_dir),
    )

    (artifact_dir / "patch.diff").write_text(patch, encoding="utf-8", newline="\n")
    _write_json(artifact_dir / "run-result.json", asdict(result))
    write_predictions_jsonl([result], artifact_dir / "prediction.jsonl")
    return result


def build_harness_command(config: HarnessConfig) -> list[str]:
    if config.max_workers <= 0:
        raise ValueError("max_workers must be positive")
    command = [
        config.harness_python,
        "-m",
        "swebench.harness.run_evaluation",
        "--dataset_name",
        config.dataset_name,
        "--split",
        config.split,
        "--namespace",
        config.namespace,
        "--predictions_path",
        str(config.predictions_path.resolve()),
        "--max_workers",
        str(config.max_workers),
        "--run_id",
        config.run_id,
    ]
    if config.instance_ids:
        command.extend(["--instance_ids", *config.instance_ids])
    return command


def run_harness(config: HarnessConfig, *, log_path: Path | None = None) -> int:
    harness_dir = config.harness_dir.resolve()
    if not harness_dir.is_dir():
        raise ValueError(f"harness directory does not exist: {harness_dir}")
    if not config.predictions_path.is_file():
        raise ValueError(f"predictions file does not exist: {config.predictions_path}")

    target_log = log_path or (harness_dir / f"coco-code.{config.run_id}.log")
    target_log.parent.mkdir(parents=True, exist_ok=True)
    stderr_log = target_log.with_suffix(target_log.suffix + ".stderr")
    exit_code, _ = _run_to_files(
        build_harness_command(config),
        cwd=harness_dir,
        stdout_path=target_log,
        stderr_path=stderr_log,
        timeout_seconds=config.timeout_seconds,
    )
    return exit_code
