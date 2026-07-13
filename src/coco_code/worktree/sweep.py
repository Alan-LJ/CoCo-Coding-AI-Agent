from __future__ import annotations

import re
import secrets
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from coco_code.worktree.git import (
    _has_unpushed_commits,
    _has_worktree_changes,
    _resolve_head_sha_from_fs,
)
from coco_code.worktree.lifecycle import _remove_active_unlocked
from coco_code.worktree.manager import Worktree

if TYPE_CHECKING:
    from coco_code.worktree.manager import Manager

EPHEMERAL_PATTERN = re.compile(r"^agent-a[0-9a-f]{7}$")


def random_agent_name() -> str:
    return "agent-a" + secrets.token_hex(4)[:7]


async def sweep_stale_worktrees(manager: Manager, cutoff: datetime) -> list[str]:
    removed: list[str] = []
    session = manager.current_session()
    async with manager.lock:
        if not manager.worktree_dir.exists():
            return removed
        for path in manager.worktree_dir.iterdir():
            if not path.is_dir() or not EPHEMERAL_PATTERN.fullmatch(path.name):
                continue
            resolved = str(path.resolve(strict=False))
            if session is not None and Path(session.worktree_path).resolve(strict=False) == Path(
                resolved
            ):
                continue
            if datetime.fromtimestamp(path.stat().st_mtime) > cutoff:
                continue
            if await _has_worktree_changes(path, "HEAD"):
                continue
            if await _has_unpushed_commits(path):
                continue
            wt = manager.active.get(path.name)
            if wt is None:
                head = _resolve_head_sha_from_fs(path) or ""
                wt = Worktree(
                    name=path.name,
                    path=resolved,
                    branch=f"worktree-{path.name}",
                    based_on=head or "HEAD",
                    head_commit=head,
                    created=datetime.fromtimestamp(path.stat().st_mtime),
                    manual=False,
                )
                manager.active[path.name] = wt
            await _remove_active_unlocked(manager, wt)
            removed.append(path.name)
    return removed
