from __future__ import annotations

import os
import shlex
import subprocess
import sys

import pytest

from coco_code.agent import Agent, ErrorEvent, HookEvent, LoopComplete, RetryEvent
from coco_code.config import load_config
from coco_code.conversation import ConversationManager
from coco_code.tools import create_default_registry
from coco_code.tools.base import StreamEnd, TextDelta, ToolCallComplete
from coco_code.tools.bash import Bash, Params as BashParams
from coco_code.verification import (
    VerificationConfig,
    discover_commands,
    run_verification,
)
from test_agent import MockLLMClient


def _shell_command(*args: str) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline(list(args))
    return shlex.join(args)


def _content_check_command(path: str, expected: str) -> str:
    code = (
        "from pathlib import Path; "
        f"raise SystemExit(0 if Path({path!r}).read_text() == {expected!r} else 1)"
    )
    return _shell_command(sys.executable, "-c", code)


def test_discover_pytest_from_tests_directory(tmp_path) -> None:
    (tmp_path / "tests").mkdir()
    commands = discover_commands(tmp_path)
    assert [command.name for command in commands] == ["pytest"]
    assert "-m pytest -q" in commands[0].command


@pytest.mark.asyncio
async def test_non_code_change_skips_auto_discovery(tmp_path) -> None:
    (tmp_path / "tests").mkdir()
    report = await run_verification(
        VerificationConfig(enabled=True),
        tmp_path,
        {"README.md"},
    )
    assert report.skipped
    assert "non-code" in report.reason


@pytest.mark.asyncio
async def test_explicit_command_failure_is_structured(tmp_path) -> None:
    command = _shell_command(sys.executable, "-c", "raise SystemExit(7)")
    report = await run_verification(
        VerificationConfig(enabled=True, commands=[command]),
        tmp_path,
        {"README.md"},
    )
    assert report.status == "failed"
    assert report.results[0].exit_code == 7


@pytest.mark.asyncio
async def test_agent_repairs_after_gate_failure(tmp_path) -> None:
    target = tmp_path / "state.py"
    client = MockLLMClient([
        [
            ToolCallComplete(
                "write", "WriteFile", {"file_path": str(target), "content": "bad"}
            ),
            StreamEnd("end_turn", input_tokens=10, output_tokens=10),
        ],
        [TextDelta("Finished."), StreamEnd("end_turn", input_tokens=10, output_tokens=5)],
        [
            ToolCallComplete(
                "fix",
                "EditFile",
                {"file_path": str(target), "old_string": "bad", "new_string": "good"},
            ),
            StreamEnd("end_turn", input_tokens=10, output_tokens=10),
        ],
        [TextDelta("Fixed and verified."), StreamEnd("end_turn", input_tokens=10, output_tokens=5)],
    ])
    agent = Agent(
        client,
        create_default_registry(),
        "anthropic",
        work_dir=str(tmp_path),
        verification_config=VerificationConfig(
            enabled=True,
            commands=[_content_check_command("state.py", "good")],
            max_fix_attempts=2,
        ),
    )
    conversation = ConversationManager()
    conversation.add_user_message("write a correct state")

    events = [event async for event in agent.run(conversation)]

    gate_events = [
        event for event in events
        if isinstance(event, HookEvent) and event.hook_id == "verification-gate"
    ]
    assert [event.success for event in gate_events] == [False, True]
    assert len([event for event in events if isinstance(event, RetryEvent)]) == 1
    assert any(isinstance(event, LoopComplete) for event in events)
    assert not any(isinstance(event, ErrorEvent) for event in events)
    assert target.read_text() == "good"


@pytest.mark.asyncio
async def test_agent_stops_when_fix_budget_is_exhausted(tmp_path) -> None:
    target = tmp_path / "state.py"
    client = MockLLMClient([
        [
            ToolCallComplete(
                "write", "WriteFile", {"file_path": str(target), "content": "bad"}
            ),
            StreamEnd("end_turn", input_tokens=10, output_tokens=10),
        ],
        [TextDelta("Finished."), StreamEnd("end_turn", input_tokens=10, output_tokens=5)],
    ])
    agent = Agent(
        client,
        create_default_registry(),
        "anthropic",
        work_dir=str(tmp_path),
        verification_config=VerificationConfig(
            enabled=True,
            commands=[_content_check_command("state.py", "good")],
            max_fix_attempts=0,
        ),
    )
    conversation = ConversationManager()
    conversation.add_user_message("write state")

    events = [event async for event in agent.run(conversation)]

    assert any(
        isinstance(event, ErrorEvent) and "Automatic verification failed" in event.message
        for event in events
    )
    assert not any(isinstance(event, LoopComplete) for event in events)


@pytest.mark.asyncio
async def test_bash_marks_ordinary_nonzero_exit_as_error() -> None:
    command = _shell_command(sys.executable, "-c", "raise SystemExit(3)")
    result = await Bash().execute(BashParams(command=command))
    assert result.is_error is True
    assert "Exit code 3" in result.output


def test_load_verification_config(tmp_path) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        """
providers:
  - name: test
    protocol: anthropic
    base_url: https://example.test
    model: test-model
verification:
  enabled: false
  auto_discover: false
  commands: [\"python -m pytest -q\"]
  timeout_seconds: 42
  max_fix_attempts: 1
  fail_fast: false
  output_limit: 2048
""".strip(),
        encoding="utf-8",
    )
    config = load_config(config_file)
    assert config.verification.enabled is False
    assert config.verification.commands == ["python -m pytest -q"]
    assert config.verification.timeout_seconds == 42
    assert config.verification.max_fix_attempts == 1
    assert config.verification.fail_fast is False
    assert config.verification.output_limit == 2048
    assert config.verification.configured is True
