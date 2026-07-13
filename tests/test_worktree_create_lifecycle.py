from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from coco_code.worktree import ExitAction, ExitOptions, Manager, WorktreeHasChangesError


def init_repo(path: Path) -> None:
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


def test_create_enter_exit_remove(tmp_path: Path) -> None:
    async def run() -> None:
        init_repo(tmp_path)
        manager = Manager(tmp_path)
        wt = await manager.create("team/alice", "HEAD", manual=True)
        assert Path(wt.path).exists()
        assert Path(wt.path).name == "team+alice"
        assert wt.branch == "worktree-team+alice"

        session = await manager.enter("team/alice")
        assert session.worktree_path == wt.path
        assert Path.cwd() != Path(wt.path)

        await manager.exit("team/alice", ExitAction.REMOVE, ExitOptions(discard_changes=True))
        assert not Path(wt.path).exists()
        assert manager.current_session() is None

    asyncio.run(run())


def test_remove_protects_changes(tmp_path: Path) -> None:
    async def run() -> None:
        init_repo(tmp_path)
        manager = Manager(tmp_path)
        wt = await manager.create("alice", "HEAD", manual=True)
        (Path(wt.path) / "README.md").write_text("changed\n", encoding="utf-8")
        with pytest.raises(WorktreeHasChangesError):
            await manager.remove("alice", ExitOptions())
        assert Path(wt.path).exists()
        await manager.remove("alice", ExitOptions(discard_changes=True))
        assert not Path(wt.path).exists()

    asyncio.run(run())
