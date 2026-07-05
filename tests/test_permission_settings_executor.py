from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from coco_code.permission import Decision, Mode, Outcome, new_engine
from coco_code.permission.engine import Engine
from coco_code.permission.persist import persist_local_allow
from coco_code.permission.settings import (
    SettingsError,
    categorize,
    extract_target,
    friendly_name,
    load_settings,
)
from coco_code.tools import ToolCall, ToolContext, ToolExecutor, create_default_registry


def test_settings_load_missing_and_invalid_yaml(tmp_path: Path) -> None:
    assert load_settings(tmp_path / "missing.yaml").permissions.allow == []
    bad = tmp_path / "bad.yaml"
    bad.write_text("permissions: [", encoding="utf-8")
    with pytest.raises(SettingsError):
        load_settings(bad)


def test_settings_mapping_and_target_extraction() -> None:
    assert friendly_name("WriteFile") == "Write"
    assert categorize("WriteFile", read_only=False).name == "WRITE"
    assert categorize("Bash", read_only=False).name == "EXEC"
    assert extract_target(ToolCall("1", "WriteFile", {"path": "a.txt"}, "{}")) == (
        "a.txt",
        True,
        True,
    )
    assert extract_target(ToolCall("2", "Bash", {"command": "git status"}, "{}")) == (
        "git status",
        False,
        True,
    )


def test_persist_local_allow_writes_exact_rule_and_reloads(tmp_path: Path) -> None:
    engine = Engine(
        root=str(tmp_path.resolve()),
        local_path=str(tmp_path / ".coco-code" / "settings.local.yaml"),
    )
    call = ToolCall("1", "WriteFile", {"path": "always.txt", "content": "ok"}, "{}")

    persist_local_allow(engine, call)
    persist_local_allow(engine, call)

    local_text = Path(engine.local_path).read_text(encoding="utf-8")
    assert local_text.count("Write(always.txt)") == 1

    reloaded, error = new_engine(tmp_path)
    assert error is None
    decision, _reason = reloaded.check(
        Mode.DEFAULT,
        call,
        create_default_registry().get("WriteFile").spec,
    )
    assert decision == Decision.ALLOW


def test_executor_permission_ask_allow_once_executes_write(tmp_path: Path) -> None:
    async def run() -> None:
        registry = create_default_registry()
        engine = Engine(
            root=str(tmp_path.resolve()),
            local_path=str(tmp_path / ".coco-code" / "settings.local.yaml"),
        )
        prompts: list[str] = []

        async def confirm(_call, _spec):
            return False

        async def permission(_call, _spec, reason):
            prompts.append(reason)
            return Outcome.ALLOW_ONCE

        executor = ToolExecutor(
            registry,
            ToolContext(workspace=tmp_path),
            confirm,
            engine,
            permission,
        )
        result = await executor.execute(
            ToolCall("1", "WriteFile", {"path": "created.txt", "content": "ok"}, "{}"),
            Mode.DEFAULT,
        )
        assert result.ok is True
        assert prompts
        assert (tmp_path / "created.txt").read_text(encoding="utf-8") == "ok"
        assert not Path(engine.local_path).exists()

    asyncio.run(run())


def test_executor_permission_deny_does_not_execute(tmp_path: Path) -> None:
    async def run() -> None:
        registry = create_default_registry()
        engine = Engine(root=str(tmp_path.resolve()))

        async def confirm(_call, _spec):
            return True

        async def permission(_call, _spec, _reason):
            raise AssertionError("sandbox deny should not ask")

        executor = ToolExecutor(
            registry,
            ToolContext(workspace=tmp_path),
            confirm,
            engine,
            permission,
        )
        result = await executor.execute(
            ToolCall("1", "WriteFile", {"path": "../escape.txt", "content": "no"}, "{}"),
            Mode.BYPASS,
        )
        assert result.ok is False
        assert result.data["permission_denied"] is True
        assert not (tmp_path.parent / "escape.txt").exists()

    asyncio.run(run())


def test_executor_allow_forever_persists_then_executes(tmp_path: Path) -> None:
    async def run() -> None:
        registry = create_default_registry()
        engine = Engine(
            root=str(tmp_path.resolve()),
            local_path=str(tmp_path / ".coco-code" / "settings.local.yaml"),
        )

        async def confirm(_call, _spec):
            return False

        async def permission(_call, _spec, _reason):
            return Outcome.ALLOW_FOREVER

        executor = ToolExecutor(
            registry,
            ToolContext(workspace=tmp_path),
            confirm,
            engine,
            permission,
        )
        result = await executor.execute(
            ToolCall("1", "WriteFile", {"path": "forever.txt", "content": "yes"}, "{}"),
            Mode.DEFAULT,
        )
        assert result.ok is True
        assert "Write(forever.txt)" in Path(engine.local_path).read_text(encoding="utf-8")

    asyncio.run(run())
