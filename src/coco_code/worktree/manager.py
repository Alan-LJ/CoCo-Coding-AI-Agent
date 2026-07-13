from __future__ import annotations

import asyncio
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from coco_code.worktree.git import _resolve_head_sha_from_fs
from coco_code.worktree.session import WorktreeSession, clear_session, load_session
from coco_code.worktree.slug import flat_slug

DEFAULT_SYMLINK_DIRS = ("node_modules", ".venv", "vendor")


@dataclass(frozen=True)
class Worktree:
    name: str
    path: str
    branch: str
    based_on: str
    head_commit: str
    created: datetime
    manual: bool


class Manager:
    def __init__(self, repo_root: str | Path) -> None:
        self.repo_root = str(Path(repo_root).resolve(strict=False))
        self._verify_repo_root()
        self.worktree_dir = Path(self.repo_root) / ".coco-code" / "worktrees"
        self.session_file = Path(self.repo_root) / ".coco-code" / "worktree_session.json"
        self.symlink_dirs = list(DEFAULT_SYMLINK_DIRS)
        self.lock = asyncio.Lock()
        self.active: dict[str, Worktree] = {}
        self._current_session: WorktreeSession | None = self._load_current_session()
        self.worktree_dir.mkdir(parents=True, exist_ok=True)
        self._scan_existing_worktrees()

    async def create(self, name: str, base_ref: str = "HEAD", manual: bool = False) -> Worktree:
        from coco_code.worktree.create import create_worktree

        return await create_worktree(self, name, base_ref, manual)

    async def enter(self, name: str) -> WorktreeSession:
        from coco_code.worktree.lifecycle import enter_worktree

        return await enter_worktree(self, name)

    async def exit(self, name: str, action, opts):
        from coco_code.worktree.lifecycle import exit_worktree

        return await exit_worktree(self, name, action, opts)

    async def remove(self, name: str, opts) -> None:
        from coco_code.worktree.lifecycle import remove_worktree

        await remove_worktree(self, name, opts)

    async def auto_cleanup(self, name: str):
        from coco_code.worktree.lifecycle import auto_cleanup_worktree

        return await auto_cleanup_worktree(self, name)

    async def sweep_stale(self, cutoff: datetime) -> list[str]:
        from coco_code.worktree.sweep import sweep_stale_worktrees

        return await sweep_stale_worktrees(self, cutoff)

    def list(self) -> list[Worktree]:
        return sorted(self.active.values(), key=lambda item: item.name)

    def get(self, name: str) -> Worktree | None:
        return self.active.get(name)

    def current_session(self) -> WorktreeSession | None:
        return self._current_session

    def set_current_session(self, session: WorktreeSession | None) -> None:
        self._current_session = session

    def _verify_repo_root(self) -> None:
        result = subprocess.run(
            ["git", "-C", self.repo_root, "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise ValueError("not a git repo root")
        actual = Path(result.stdout.strip()).resolve(strict=False)
        expected = Path(self.repo_root).resolve(strict=False)
        if actual != expected:
            raise ValueError("not a git repo root")

    def _load_current_session(self) -> WorktreeSession | None:
        try:
            session = load_session(self.session_file)
        except Exception as exc:
            print(f"worktree: session 文件损坏，已清空: {exc}", file=sys.stderr)
            clear_session(self.session_file)
            return None
        if session is not None and not Path(session.worktree_path).exists():
            print("worktree: session worktree gone, cleared", file=sys.stderr)
            clear_session(self.session_file)
            return None
        return session

    def _scan_existing_worktrees(self) -> None:
        if not self.worktree_dir.exists():
            return
        for path in self.worktree_dir.iterdir():
            if not path.is_dir():
                continue
            name = path.name.replace("+", "/")
            head = _resolve_head_sha_from_fs(path) or ""
            flat = flat_slug(name)
            self.active[name] = Worktree(
                name=name,
                path=str(path.resolve(strict=False)),
                branch=f"worktree-{flat}",
                based_on=head or "HEAD",
                head_commit=head,
                created=datetime.fromtimestamp(path.stat().st_mtime),
                manual=not name.startswith("agent-a"),
            )
