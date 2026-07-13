from __future__ import annotations

import fnmatch
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from coco_code.worktree.git import _resolve_head_sha_from_fs, _run_git
from coco_code.worktree.manager import Worktree
from coco_code.worktree.slug import flat_slug, validate_slug

if TYPE_CHECKING:
    from coco_code.worktree.manager import Manager


async def create_worktree(
    manager: Manager,
    name: str,
    base_ref: str = "HEAD",
    manual: bool = False,
) -> Worktree:
    validate_slug(name)
    async with manager.lock:
        if name in manager.active:
            raise ValueError(f"worktree 已存在: {name}")
        flat = flat_slug(name)
        wt_path = manager.worktree_dir / flat
        branch = f"worktree-{flat}"
        if wt_path.exists():
            head = _resolve_head_sha_from_fs(wt_path) or ""
            worktree = Worktree(
                name=name,
                path=str(wt_path.resolve(strict=False)),
                branch=branch,
                based_on=base_ref,
                head_commit=head,
                created=datetime.fromtimestamp(wt_path.stat().st_mtime),
                manual=manual,
            )
            manager.active[name] = worktree
            return worktree
        try:
            await _run_git(
                manager.repo_root,
                "worktree",
                "add",
                "-B",
                branch,
                str(wt_path),
                base_ref,
            )
        except Exception:
            shutil.rmtree(wt_path, ignore_errors=True)
            raise

        await _perform_post_creation_setup(manager.repo_root, wt_path, manager.symlink_dirs)
        head = await _run_git(wt_path, "rev-parse", "HEAD")
        worktree = Worktree(
            name=name,
            path=str(wt_path.resolve(strict=False)),
            branch=branch,
            based_on=base_ref,
            head_commit=head,
            created=datetime.now(),
            manual=manual,
        )
        manager.active[name] = worktree
        return worktree


async def _perform_post_creation_setup(
    repo_root: str | Path,
    wt_path: str | Path,
    symlink_dirs: list[str],
) -> None:
    steps = (
        ("config", lambda: _copy_local_configs(repo_root, wt_path)),
        ("hooks", lambda: _setup_git_hooks(repo_root, wt_path)),
        ("symlink", lambda: _symlink_large_dirs(repo_root, wt_path, symlink_dirs)),
        ("include", lambda: _copy_included_ignored(repo_root, wt_path)),
    )
    for label, step in steps:
        try:
            result = step()
            if hasattr(result, "__await__"):
                await result
        except Exception as exc:
            print(f"worktree: setup {label}: {exc}", file=sys.stderr)


def _copy_local_configs(repo_root: str | Path, wt_path: str | Path) -> None:
    root = Path(repo_root)
    target_root = Path(wt_path)
    for relative in (".coco-code/config.yaml", ".coco-code/settings.local.yaml"):
        src = root / relative
        dst = target_root / relative
        if src.exists() and not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)


async def _setup_git_hooks(repo_root: str | Path, wt_path: str | Path) -> None:
    root = Path(repo_root)
    hooks_path = root / ".husky"
    value = str(hooks_path.resolve(strict=False)) if hooks_path.exists() else ""
    if not value:
        try:
            configured = await _run_git(root, "config", "--get", "core.hooksPath")
        except Exception:
            configured = ""
        if configured:
            configured_path = Path(configured)
            if not configured_path.is_absolute():
                configured_path = root / configured_path
            value = str(configured_path.resolve(strict=False))
    if value:
        await _run_git(wt_path, "config", "core.hooksPath", value)


def _symlink_large_dirs(
    repo_root: str | Path, wt_path: str | Path, symlink_dirs: list[str]
) -> None:
    root = Path(repo_root)
    target_root = Path(wt_path)
    for name in symlink_dirs:
        src = root / name
        dst = target_root / name
        if src.exists() and not dst.exists():
            dst.symlink_to(src, target_is_directory=src.is_dir())


async def _copy_included_ignored(repo_root: str | Path, wt_path: str | Path) -> None:
    root = Path(repo_root)
    patterns = _read_worktree_include(root)
    if not patterns:
        return
    ignored = await _list_ignored_files(root)
    target_root = Path(wt_path)
    for relative in ignored:
        if not any(fnmatch.fnmatch(relative, pattern) for pattern in patterns):
            continue
        src = root / relative
        dst = target_root / relative
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        elif src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)


def _read_worktree_include(repo_root: Path) -> list[str]:
    path = repo_root / ".worktreeinclude"
    if not path.exists():
        return []
    patterns: list[str] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            patterns.append(stripped)
    return patterns


async def _list_ignored_files(repo_root: Path) -> list[str]:
    output = await _run_git(repo_root, "ls-files", "--others", "--ignored", "--exclude-standard")
    return [line.strip() for line in output.splitlines() if line.strip()]
