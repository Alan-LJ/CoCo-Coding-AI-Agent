from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from coco_code.worktree import Manager, WorktreeSession
from coco_code.worktree.session import load_session, save_session


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


def test_session_save_load_and_clear(tmp_path: Path) -> None:
    path = tmp_path / ".coco-code" / "worktree_session.json"
    session = WorktreeSession(
        original_cwd=str(tmp_path),
        worktree_path=str(tmp_path / "wt"),
        worktree_name="wt",
        original_branch="main",
        original_head_commit="abc",
        session_id="sid",
    )
    save_session(path, session)
    assert load_session(path) == session
    save_session(path, None)
    assert path.read_text(encoding="utf-8") == "null"
    assert load_session(path) is None


def test_manager_requires_git_root(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        Manager(tmp_path)


def test_manager_loads_and_clears_missing_session(tmp_path: Path) -> None:
    init_repo(tmp_path)
    path = tmp_path / ".coco-code" / "worktree_session.json"
    save_session(
        path,
        WorktreeSession(
            original_cwd=str(tmp_path),
            worktree_path=str(tmp_path / "missing"),
            worktree_name="missing",
            original_branch="main",
            original_head_commit="abc",
            session_id="sid",
        ),
    )
    manager = Manager(tmp_path)
    assert manager.current_session() is None
    assert path.read_text(encoding="utf-8") == "null"
