"""Deterministic post-edit verification for the agent loop.

The verifier deliberately does not ask the model how to validate its own work.
Explicit project commands take precedence; otherwise a small set of
high-confidence test commands is discovered from root-level project files.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path


CODE_SUFFIXES = {
    ".c", ".cc", ".cpp", ".cs", ".go", ".h", ".hpp", ".java", ".js",
    ".jsx", ".kt", ".kts", ".php", ".py", ".rb", ".rs", ".scala",
    ".svelte", ".swift", ".ts", ".tsx", ".vue",
}

CODE_MANIFESTS = {
    "cargo.toml", "go.mod", "package.json", "pom.xml", "pyproject.toml",
    "requirements.txt", "setup.cfg", "setup.py",
}


@dataclass
class VerificationConfig:
    enabled: bool = True
    auto_discover: bool = True
    commands: list[str] = field(default_factory=list)
    timeout_seconds: int = 300
    max_fix_attempts: int = 2
    fail_fast: bool = True
    output_limit: int = 12_000
    # Internal merge marker: distinguishes an absent YAML section from an
    # explicitly configured section whose values happen to equal defaults.
    configured: bool = False


@dataclass(frozen=True)
class VerificationCommand:
    name: str
    command: str
    source: str


@dataclass(frozen=True)
class VerificationCommandResult:
    name: str
    command: str
    exit_code: int | None
    output: str
    elapsed: float
    timed_out: bool = False

    @property
    def passed(self) -> bool:
        return not self.timed_out and self.exit_code == 0


@dataclass
class VerificationReport:
    status: str
    changed_files: list[str]
    commands: list[VerificationCommand]
    results: list[VerificationCommandResult] = field(default_factory=list)
    reason: str = ""

    @property
    def passed(self) -> bool:
        return self.status == "passed"

    @property
    def skipped(self) -> bool:
        return self.status == "skipped"

    def format(self) -> str:
        if self.skipped:
            return f"Automatic verification skipped: {self.reason}"

        lines = [
            "Automatic verification " + ("passed." if self.passed else "failed."),
            "Changed files: " + ", ".join(self.changed_files),
        ]
        for result in self.results:
            state = "PASS" if result.passed else "FAIL"
            if result.timed_out:
                detail = "timed out"
            else:
                detail = f"exit code {result.exit_code}"
            lines.append(
                f"\n[{state}] {result.name}: {result.command} "
                f"({detail}, {result.elapsed:.2f}s)"
            )
            if result.output:
                lines.append(result.output)
        return "\n".join(lines)


def has_code_changes(changed_files: set[str] | list[str]) -> bool:
    """Return whether automatic discovery should run for these writes."""
    for raw_path in changed_files:
        path = Path(raw_path)
        if path.suffix.lower() in CODE_SUFFIXES:
            return True
        if path.name.lower() in CODE_MANIFESTS:
            return True
    return False


def _python_command() -> str:
    if os.name == "nt":
        executable = subprocess.list2cmdline([sys.executable])
    else:
        import shlex
        executable = shlex.quote(sys.executable)
    return f"{executable} -m pytest -q"


def _node_runner(root: Path) -> str:
    if (root / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (root / "yarn.lock").exists():
        return "yarn"
    return "npm"


def discover_commands(work_dir: str | Path) -> list[VerificationCommand]:
    """Discover conservative, root-level test commands without installing anything."""
    root = Path(work_dir)
    commands: list[VerificationCommand] = []

    pyproject = root / "pyproject.toml"
    pytest_signal = (
        (root / "pytest.ini").exists()
        or (root / "tests").is_dir()
        or any(root.glob("test_*.py"))
    )
    if pyproject.exists() and not pytest_signal:
        try:
            pytest_signal = "pytest" in pyproject.read_text(encoding="utf-8").lower()
        except OSError:
            pass
    if pytest_signal:
        commands.append(VerificationCommand("pytest", _python_command(), "auto"))

    package_json = root / "package.json"
    if package_json.exists():
        try:
            package = json.loads(package_json.read_text(encoding="utf-8"))
            scripts = package.get("scripts", {})
            runner = _node_runner(root)
            for script_name in ("typecheck", "check", "test", "build"):
                if isinstance(scripts, dict) and scripts.get(script_name):
                    separator = " run" if runner == "npm" else ""
                    commands.append(VerificationCommand(
                        f"{runner}:{script_name}",
                        f"{runner}{separator} {script_name}",
                        "auto",
                    ))
        except (OSError, json.JSONDecodeError):
            pass

    if (root / "Cargo.toml").exists():
        commands.append(VerificationCommand("cargo-test", "cargo test --quiet", "auto"))
    if (root / "go.mod").exists():
        commands.append(VerificationCommand("go-test", "go test ./...", "auto"))
    if any(root.glob("*.sln")) or any(root.glob("*.csproj")):
        commands.append(VerificationCommand("dotnet-test", "dotnet test --nologo", "auto"))
    if (root / "mvnw.cmd").exists():
        commands.append(VerificationCommand("maven-test", ".\\mvnw.cmd -q test", "auto"))
    elif (root / "mvnw").exists():
        commands.append(VerificationCommand("maven-test", "./mvnw -q test", "auto"))
    elif (root / "pom.xml").exists():
        commands.append(VerificationCommand("maven-test", "mvn -q test", "auto"))
    if (root / "gradlew.bat").exists():
        commands.append(VerificationCommand("gradle-test", ".\\gradlew.bat test", "auto"))
    elif (root / "gradlew").exists():
        commands.append(VerificationCommand("gradle-test", "./gradlew test", "auto"))

    return commands


def resolve_commands(
    config: VerificationConfig,
    work_dir: str | Path,
) -> list[VerificationCommand]:
    if config.commands:
        return [
            VerificationCommand(f"configured-{index}", command, "configured")
            for index, command in enumerate(config.commands, start=1)
        ]
    if config.auto_discover:
        return discover_commands(work_dir)
    return []


def _truncate_output(output: str, limit: int) -> str:
    if len(output) <= limit:
        return output
    omitted = len(output) - limit
    return f"... [{omitted} characters omitted; showing tail] ...\n{output[-limit:]}"


async def _run_command(
    spec: VerificationCommand,
    work_dir: str | Path,
    timeout: int,
    output_limit: int,
) -> VerificationCommandResult:
    start = time.monotonic()
    env = dict(os.environ)
    env.setdefault("CI", "true")
    env.setdefault("NO_COLOR", "1")
    try:
        proc = await asyncio.create_subprocess_shell(
            spec.command,
            cwd=str(work_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return VerificationCommandResult(
                spec.name,
                spec.command,
                None,
                f"Command timed out after {timeout}s",
                time.monotonic() - start,
                timed_out=True,
            )
    except Exception as exc:
        return VerificationCommandResult(
            spec.name,
            spec.command,
            None,
            f"Failed to start command: {exc}",
            time.monotonic() - start,
        )

    output = stdout.decode(errors="replace").rstrip() if stdout else ""
    return VerificationCommandResult(
        spec.name,
        spec.command,
        proc.returncode,
        _truncate_output(output, output_limit),
        time.monotonic() - start,
    )


async def run_verification(
    config: VerificationConfig,
    work_dir: str | Path,
    changed_files: set[str] | list[str],
) -> VerificationReport:
    files = sorted(str(path) for path in changed_files)
    if not config.enabled:
        return VerificationReport("skipped", files, [], reason="disabled by configuration")
    if not files:
        return VerificationReport("skipped", files, [], reason="no successful file writes")
    if not config.commands and not has_code_changes(files):
        return VerificationReport("skipped", files, [], reason="only non-code files changed")

    commands = resolve_commands(config, work_dir)
    if not commands:
        return VerificationReport(
            "skipped", files, [], reason="no configured or high-confidence command was found"
        )

    results: list[VerificationCommandResult] = []
    for command in commands:
        result = await _run_command(
            command,
            work_dir,
            config.timeout_seconds,
            config.output_limit,
        )
        results.append(result)
        if not result.passed and config.fail_fast:
            break

    status = "passed" if all(result.passed for result in results) else "failed"
    return VerificationReport(status, files, commands, results)


def build_failure_reminder(report: VerificationReport, attempts_left: int) -> str:
    return (
        "<automatic-verification-failure>\n"
        "The deterministic post-edit verification gate failed. Inspect the output, "
        "fix the implementation, and finish only after verification passes. "
        f"Automatic repair attempts remaining after this turn: {attempts_left}.\n\n"
        f"{report.format()}\n"
        "</automatic-verification-failure>"
    )
