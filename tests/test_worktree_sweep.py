from __future__ import annotations

import asyncio
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from coco_code.worktree import Manager
from coco_code.worktree.sweep import EPHEMERAL_PATTERN, random_agent_name


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
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(["git", "update-ref", "refs/remotes/origin/main", head], cwd=path, check=True)
    return head


def test_random_agent_name_matches_ephemeral_pattern() -> None:
    assert EPHEMERAL_PATTERN.fullmatch(random_agent_name())


def test_sweep_removes_only_stale_clean_ephemeral_worktrees(tmp_path: Path) -> None:
    async def run() -> None:
        init_repo(tmp_path)
        manager = Manager(tmp_path)
        old_clean = await manager.create("agent-a1234567", "HEAD", manual=False)
        old_dirty = await manager.create("agent-a7654321", "HEAD", manual=False)
        manual = await manager.create("manual", "HEAD", manual=True)
        (Path(old_dirty.path) / "dirty.txt").write_text("dirty\n", encoding="utf-8")

        old_time = (datetime.now() - timedelta(days=2)).timestamp()
        for item in (old_clean, old_dirty, manual):
            Path(item.path).touch()
            import os

            os.utime(item.path, (old_time, old_time))

        removed = await manager.sweep_stale(datetime.now() - timedelta(days=1))

        assert removed == ["agent-a1234567"]
        assert not Path(old_clean.path).exists()
        assert Path(old_dirty.path).exists()
        assert Path(manual.path).exists()

    asyncio.run(run())


def test_sweep_skips_current_session(tmp_path: Path) -> None:
    async def run() -> None:
        init_repo(tmp_path)
        manager = Manager(tmp_path)
        wt = await manager.create("agent-a2222222", "HEAD", manual=False)
        await manager.enter("agent-a2222222")
        old_time = (datetime.now() - timedelta(days=2)).timestamp()
        import os

        os.utime(wt.path, (old_time, old_time))

        removed = await manager.sweep_stale(datetime.now() - timedelta(days=1))

        assert removed == []
        assert Path(wt.path).exists()

    asyncio.run(run())


def test_sweep_skips_unpushed_local_commits(tmp_path: Path) -> None:
    async def run() -> None:
        init_repo(tmp_path)
        manager = Manager(tmp_path)
        wt = await manager.create("agent-a3333333", "HEAD", manual=False)
        wt_path = Path(wt.path)
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
        old_time = (datetime.now() - timedelta(days=2)).timestamp()
        import os

        os.utime(wt.path, (old_time, old_time))

        removed = await manager.sweep_stale(datetime.now() - timedelta(days=1))

        assert removed == []
        assert wt_path.exists()

    asyncio.run(run())
