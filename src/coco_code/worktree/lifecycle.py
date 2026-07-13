from __future__ import annotations

import asyncio
import os
import secrets
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from coco_code.worktree.git import _has_worktree_changes, _run_git
from coco_code.worktree.session import WorktreeSession, save_session

if TYPE_CHECKING:
    from coco_code.worktree.manager import Manager, Worktree


class ExitAction(StrEnum):
    KEEP = "keep"
    REMOVE = "remove"


@dataclass(frozen=True)
class ExitOptions:
    discard_changes: bool = False


@dataclass(frozen=True)
class ExitReport:
    removed: bool
    path: str
    branch: str


@dataclass(frozen=True)
class AutoCleanupReport:
    kept: bool
    path: str = ""
    branch: str = ""


class WorktreeHasChangesError(Exception):
    """Worktree has uncommitted changes or local commits."""


async def enter_worktree(manager: Manager, name: str) -> WorktreeSession:
    async with manager.lock:
        wt = manager.active.get(name)
        if wt is None:
            raise ValueError(f"worktree 不存在: {name}")
        original_branch = ""
        original_head = ""
        with suppress(Exception):
            original_branch = await _run_git(manager.repo_root, "rev-parse", "--abbrev-ref", "HEAD")
        with suppress(Exception):
            original_head = await _run_git(manager.repo_root, "rev-parse", "HEAD")
        session = WorktreeSession(
            original_cwd=str(Path.cwd()),
            worktree_path=wt.path,
            worktree_name=wt.name,
            original_branch=original_branch,
            original_head_commit=original_head,
            session_id=secrets.token_hex(8),
        )
        manager.set_current_session(session)
        save_session(manager.session_file, session)
        return session


async def exit_worktree(
    manager: Manager,
    name: str,
    action: ExitAction,
    opts: ExitOptions,
) -> ExitReport:
    async with manager.lock:
        session = manager.current_session()
        if session is None or session.worktree_name != name:
            raise ValueError(f"当前未进入 worktree: {name}")
        wt = _require_worktree(manager, name)
        if action == ExitAction.REMOVE and not opts.discard_changes:
            await _ensure_no_changes(wt)
        with suppress(OSError):
            os.chdir(session.original_cwd)
        manager.set_current_session(None)
        save_session(manager.session_file, None)
        if action == ExitAction.REMOVE:
            await _remove_active_unlocked(manager, wt)
        return ExitReport(removed=action == ExitAction.REMOVE, path=wt.path, branch=wt.branch)


async def remove_worktree(manager: Manager, name: str, opts: ExitOptions) -> None:
    async with manager.lock:
        wt = _require_worktree(manager, name)
        if not opts.discard_changes:
            await _ensure_no_changes(wt)
        session = manager.current_session()
        if session is not None and session.worktree_name == name:
            with suppress(OSError):
                os.chdir(session.original_cwd)
            manager.set_current_session(None)
            save_session(manager.session_file, None)
        await _remove_active_unlocked(manager, wt)


async def auto_cleanup_worktree(manager: Manager, name: str) -> AutoCleanupReport:
    async with manager.lock:
        wt = manager.active.get(name)
        if wt is None:
            return AutoCleanupReport(kept=False)
        if wt.manual:
            return AutoCleanupReport(kept=True, path=wt.path, branch=wt.branch)
        if await _has_worktree_changes(wt.path, wt.head_commit):
            return AutoCleanupReport(kept=True, path=wt.path, branch=wt.branch)
        await _remove_active_unlocked(manager, wt)
        return AutoCleanupReport(kept=False)


def _require_worktree(manager: Manager, name: str) -> Worktree:
    wt = manager.active.get(name)
    if wt is None:
        raise ValueError(f"worktree 不存在: {name}")
    return wt


async def _ensure_no_changes(wt: Worktree) -> None:
    if await _has_worktree_changes(wt.path, wt.head_commit):
        raise WorktreeHasChangesError("worktree has uncommitted changes or new commits")


async def _remove_active_unlocked(manager: Manager, wt: Worktree) -> None:
    await _run_git(manager.repo_root, "worktree", "remove", "--force", wt.path)
    await asyncio.sleep(0.1)
    with suppress(Exception):
        await _run_git(manager.repo_root, "branch", "-D", wt.branch)
    manager.active.pop(wt.name, None)
