from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from coco_code.worktree import Manager
from coco_code.worktree import git as git_helpers
from coco_code.worktree.git import (
    _has_unpushed_commits,
    _has_worktree_changes,
    _resolve_head_sha_from_fs,
    _run_git,
)


def init_repo(path: Path) -> str:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    (path / "README.md").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=CoCo",
            "-c",
            "user.email=coco@example.test",
            "commit",
            "-m",
            "init",
        ],
        cwd=path,
        check=True,
        capture_output=True,
    )
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_run_git_disables_interactive_prompts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured = {}

    class FakeProc:
        returncode = 0

        async def communicate(self):
            return b"ok\n", b""

    async def fake_create_subprocess_exec(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    result = asyncio.run(_run_git(tmp_path, "status"))

    assert result == "ok"
    assert captured["args"] == ("git", "status")
    assert captured["kwargs"]["cwd"] == str(tmp_path)
    assert captured["kwargs"]["env"]["GIT_TERMINAL_PROMPT"] == "0"
    assert captured["kwargs"]["env"]["GIT_ASKPASS"] == ""
    assert captured["kwargs"]["stdin"] is asyncio.subprocess.DEVNULL


def test_has_worktree_changes_detects_status_and_new_commits(tmp_path: Path) -> None:
    async def run() -> None:
        head = init_repo(tmp_path)
        manager = Manager(tmp_path)
        wt = await manager.create("alice", "HEAD", manual=True)
        wt_path = Path(wt.path)

        assert await _has_worktree_changes(wt_path, head) is False

        (wt_path / "README.md").write_text("changed\n", encoding="utf-8")
        assert await _has_worktree_changes(wt_path, head) is True

        subprocess.run(["git", "checkout", "--", "README.md"], cwd=wt_path, check=True)
        (wt_path / "new.txt").write_text("new\n", encoding="utf-8")
        subprocess.run(["git", "add", "new.txt"], cwd=wt_path, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=CoCo",
                "-c",
                "user.email=coco@example.test",
                "commit",
                "-m",
                "new",
            ],
            cwd=wt_path,
            check=True,
            capture_output=True,
        )
        assert await _has_worktree_changes(wt_path, head) is True

    asyncio.run(run())


def test_has_worktree_changes_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def boom(*_args, **_kwargs):
        raise RuntimeError("git failed")

    monkeypatch.setattr(git_helpers, "_run_git", boom)
    assert asyncio.run(_has_worktree_changes(tmp_path, "HEAD")) is True


def test_resolve_head_sha_from_fs_reads_real_worktree(tmp_path: Path) -> None:
    async def run() -> None:
        head = init_repo(tmp_path)
        manager = Manager(tmp_path)
        wt = await manager.create("alice", "HEAD", manual=True)
        assert _resolve_head_sha_from_fs(wt.path) == head

    asyncio.run(run())


def test_has_unpushed_commits_uses_remote_reachability(tmp_path: Path) -> None:
    async def run() -> None:
        head = init_repo(tmp_path)
        manager = Manager(tmp_path)
        wt = await manager.create("alice", "HEAD", manual=True)
        wt_path = Path(wt.path)
        subprocess.run(
            ["git", "update-ref", "refs/remotes/origin/main", head],
            cwd=tmp_path,
            check=True,
        )

        assert await _has_unpushed_commits(wt_path) is False

        (wt_path / "new.txt").write_text("new\n", encoding="utf-8")
        subprocess.run(["git", "add", "new.txt"], cwd=wt_path, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=CoCo",
                "-c",
                "user.email=coco@example.test",
                "commit",
                "-m",
                "new",
            ],
            cwd=wt_path,
            check=True,
            capture_output=True,
        )
        assert await _has_unpushed_commits(wt_path) is True

    asyncio.run(run())
