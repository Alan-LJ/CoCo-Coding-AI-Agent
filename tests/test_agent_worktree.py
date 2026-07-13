from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path

from coco_code.agent.agent_worktree import _execute_with_worktree, build_worktree_notice
from coco_code.conversation import Conversation
from coco_code.subagent import Definition
from coco_code.tools.ctx import cwd_from_ctx
from coco_code.worktree import AutoCleanupReport, Worktree


class StubManager:
    def __init__(self, path: Path, kept: bool = False) -> None:
        self.path = path
        self.kept = kept
        self.created = []
        self.cleaned = []

    async def create(self, name: str, base_ref: str, manual: bool) -> Worktree:
        self.created.append((name, base_ref, manual))
        return Worktree(
            name,
            str(self.path),
            "worktree-" + name,
            "HEAD",
            "abc",
            datetime.now(),
            False,
        )

    async def auto_cleanup(self, name: str) -> AutoCleanupReport:
        self.cleaned.append(name)
        return AutoCleanupReport(kept=self.kept, path=str(self.path), branch="worktree-" + name)


class StubSubAgent:
    def __init__(self) -> None:
        self.cwd_seen = ""
        self.task_seen = ""

    async def run_to_completion(self, conv, task, *, events=None):  # noqa: ANN001, ARG002
        self.cwd_seen = cwd_from_ctx() or ""
        self.task_seen = task
        return "done"


def test_build_worktree_notice_contains_context() -> None:
    notice = build_worktree_notice("parent", "child")
    assert "<worktree-context>" in notice
    assert "parent" in notice
    assert "child" in notice


def test_execute_with_worktree_sets_cwd_and_cleans(tmp_path: Path) -> None:
    async def run() -> None:
        sub = StubSubAgent()
        manager = StubManager(tmp_path)
        result = await _execute_with_worktree(
            manager,  # type: ignore[arg-type]
            Definition(name="worker", description="worker", isolation="worktree"),
            sub,
            Conversation(),
            "do it",
        )
        assert result == "done"
        assert sub.cwd_seen == str(tmp_path)
        assert "do it" in sub.task_seen
        assert manager.cleaned

    asyncio.run(run())
