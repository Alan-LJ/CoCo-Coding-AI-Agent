"""Docker-backed inference for SWE-bench-Live instances.

Inference deliberately runs in a disposable copy of the official task image.
The resulting patch is later graded by the official harness in a second,
clean container.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from coco_code.evaluation.swebench import _run_to_files, instance_slug


@dataclass(frozen=True)
class DockerInferenceConfig:
    instance_id: str
    image: str
    problem_file: Path
    coco_code_source: Path
    config_file: Path
    output_dir: Path
    model_name: str
    env_file: Path | None = None
    python_bin: str = "/usr/bin/python3.11"
    timeout_seconds: int = 3600
    bootstrap_timeout_seconds: int = 1200
    cpus: float = 8.0
    memory: str = "20g"
    docker_bin: str = "docker"


@dataclass(frozen=True)
class DockerInferenceResult:
    instance_id: str
    status: str
    exit_code: int
    duration_ms: int
    container_name: str
    artifact_dir: str
    stdout_log: str
    stderr_log: str
    inner_result: dict[str, Any] | None = None


def _mount(source: Path, target: str, *, readonly: bool = False) -> str:
    value = f"type=bind,source={source.resolve()},target={target}"
    if readonly:
        value += ",readonly"
    return value


def _host_identity() -> tuple[int, int]:
    """Return the WSL/Linux owner for bind-mounted result files."""
    getuid = getattr(os, "getuid", None)
    getgid = getattr(os, "getgid", None)
    return (
        int(getuid()) if getuid is not None else 0,
        int(getgid()) if getgid is not None else 0,
    )


def build_container_script(
    config: DockerInferenceConfig,
    *,
    host_uid: int,
    host_gid: int,
) -> str:
    """Build the bootstrap script executed inside the disposable container."""
    quote = shlex.quote
    python_bin = quote(config.python_bin)
    instance_id = quote(config.instance_id)
    model_name = quote(config.model_name)
    timeout = str(config.timeout_seconds)

    # The provider config is copied outside /testbed so credentials can never
    # appear in the submitted git patch. Its contents are not embedded here.
    return "\n".join(
        [
            "set -euo pipefail",
            f"cleanup() {{ chown -R {host_uid}:{host_gid} /results 2>/dev/null || true; }}",
            "trap cleanup EXIT",
            "test -d /testbed/.git",
            "cd /testbed",
            "git config --global --add safe.directory /testbed",
            "git rev-parse --verify HEAD >/dev/null",
            "mkdir -p /root/.coco-code",
            "cp /tmp/coco-code-eval-config.yaml /root/.coco-code/config.yaml",
            "chmod 600 /root/.coco-code/config.yaml",
            "if [ -f /tmp/coco-code-eval.env ]; then",
            "  while IFS='=' read -r key value; do",
            "    case \"$key\" in",
            "      OPENAI_API_KEY|ANTHROPIC_API_KEY) export \"$key=$value\" ;;",
            "    esac",
            "  done < /tmp/coco-code-eval.env",
            "fi",
            "rm -rf /opt/coco-code-venv",
            f"if ! {python_bin} -m venv /opt/coco-code-venv; then",
            "  rm -rf /opt/coco-code-venv",
            "  apt-get update",
            "  DEBIAN_FRONTEND=noninteractive apt-get install -y python3.11-venv",
            f"  {python_bin} -m venv /opt/coco-code-venv",
            "fi",
            "/opt/coco-code-venv/bin/python -m pip install --disable-pip-version-check --upgrade pip",
            "/opt/coco-code-venv/bin/python -m pip install --disable-pip-version-check /opt/coco-code-src",
            "/opt/coco-code-venv/bin/coco-code-swebench infer \\",
            f"  --instance-id {instance_id} \\",
            "  --problem-file /tmp/coco-code-problem.txt \\",
            "  --work-dir /testbed \\",
            "  --output-dir /results \\",
            f"  --model-name {model_name} \\",
            f"  --timeout-seconds {timeout}",
        ]
    )


def build_docker_inference_command(
    config: DockerInferenceConfig,
    *,
    container_name: str,
    host_uid: int | None = None,
    host_gid: int | None = None,
) -> list[str]:
    """Build a Docker command without reading or serializing any secret."""
    if host_uid is None or host_gid is None:
        detected_uid, detected_gid = _host_identity()
        host_uid = detected_uid if host_uid is None else host_uid
        host_gid = detected_gid if host_gid is None else host_gid

    command = [
        config.docker_bin,
        "run",
        "--rm",
        "--name",
        container_name,
        "--cpus",
        str(config.cpus),
        "--memory",
        config.memory,
        "--mount",
        _mount(config.coco_code_source, "/opt/coco-code-src", readonly=True),
        "--mount",
        _mount(config.problem_file, "/tmp/coco-code-problem.txt", readonly=True),
        "--mount",
        _mount(config.config_file, "/tmp/coco-code-eval-config.yaml", readonly=True),
        "--mount",
        _mount(config.output_dir, "/results"),
    ]
    if config.env_file is not None:
        command.extend(
            [
                "--mount",
                _mount(config.env_file, "/tmp/coco-code-eval.env", readonly=True),
            ]
        )
    command.extend(
        [
            config.image,
            "/bin/bash",
            "-lc",
            build_container_script(
                config,
                host_uid=host_uid,
                host_gid=host_gid,
            ),
        ]
    )
    return command


def _validate_config(config: DockerInferenceConfig) -> None:
    if not config.instance_id.strip():
        raise ValueError("instance_id must not be empty")
    if not config.image.strip():
        raise ValueError("image must not be empty")
    if not config.problem_file.is_file():
        raise ValueError(f"problem file does not exist: {config.problem_file}")
    if not config.coco_code_source.is_dir():
        raise ValueError(f"CoCo Code source directory does not exist: {config.coco_code_source}")
    if not (config.coco_code_source / "pyproject.toml").is_file():
        raise ValueError(
            f"CoCo Code source directory has no pyproject.toml: {config.coco_code_source}"
        )
    if not config.config_file.is_file():
        raise ValueError(f"CoCo Code config file does not exist: {config.config_file}")
    if config.env_file is not None and not config.env_file.is_file():
        raise ValueError(f"environment file does not exist: {config.env_file}")
    if config.timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    if config.bootstrap_timeout_seconds <= 0:
        raise ValueError("bootstrap_timeout_seconds must be positive")
    if config.cpus <= 0:
        raise ValueError("cpus must be positive")


def run_docker_inference(
    config: DockerInferenceConfig,
    *,
    command: Sequence[str] | None = None,
) -> DockerInferenceResult:
    """Run CoCo Code in a disposable task image and retain host-side artifacts."""
    _validate_config(config)
    output_dir = config.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    slug = instance_slug(config.instance_id)
    container_name = f"coco-code-sweb-{slug.lower()[:32]}-{uuid.uuid4().hex[:8]}"
    stdout_log = output_dir / f"docker-{slug}.stdout.log"
    stderr_log = output_dir / f"docker-{slug}.stderr.log"
    actual_command = (
        list(command)
        if command is not None
        else build_docker_inference_command(config, container_name=container_name)
    )

    started = time.monotonic()
    exit_code, timed_out = _run_to_files(
        actual_command,
        cwd=output_dir,
        stdout_path=stdout_log,
        stderr_path=stderr_log,
        timeout_seconds=config.timeout_seconds + config.bootstrap_timeout_seconds,
    )
    if timed_out and command is None:
        # Killing an attached Docker CLI does not reliably stop its container.
        # Force removal preserves the disposable-container isolation contract.
        subprocess.run(
            [config.docker_bin, "rm", "-f", container_name],
            cwd=output_dir,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=60,
            check=False,
        )
    duration_ms = int((time.monotonic() - started) * 1000)

    artifact_dir = output_dir / slug
    result_path = artifact_dir / "run-result.json"
    inner_result: dict[str, Any] | None = None
    if result_path.is_file():
        try:
            loaded = json.loads(result_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                inner_result = loaded
        except (OSError, json.JSONDecodeError):
            inner_result = None

    if timed_out:
        status = "timeout"
    elif exit_code != 0:
        status = "error"
    elif inner_result is None:
        status = "error"
    else:
        status = str(inner_result.get("status", "error"))

    return DockerInferenceResult(
        instance_id=config.instance_id,
        status=status,
        exit_code=exit_code,
        duration_ms=duration_ms,
        container_name=container_name,
        artifact_dir=str(artifact_dir),
        stdout_log=str(stdout_log),
        stderr_log=str(stderr_log),
        inner_result=inner_result,
    )
