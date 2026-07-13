from __future__ import annotations

import asyncio
import os
from pathlib import Path


async def _run_git(work_dir: str | Path, *args: str) -> str:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_ASKPASS"] = ""
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=str(work_dir),
        env=env,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    out_text = stdout.decode("utf-8", errors="replace").rstrip("\r\n")
    err_text = stderr.decode("utf-8", errors="replace").strip()
    if proc.returncode != 0:
        raise RuntimeError(err_text or out_text or f"git exited with {proc.returncode}")
    return out_text


async def _has_worktree_changes(wt_path: str | Path, base_commit: str) -> bool:
    try:
        status = await _run_git(wt_path, "status", "--porcelain")
        if status.strip():
            return True
        if base_commit:
            count_text = await _run_git(wt_path, "rev-list", "--count", f"{base_commit}..HEAD")
            return int(count_text.strip() or "0") > 0
        return False
    except Exception:
        return True


async def _has_unpushed_commits(wt_path: str | Path) -> bool:
    try:
        output = await _run_git(
            wt_path,
            "rev-list",
            "--max-count=1",
            "HEAD",
            "--not",
            "--remotes",
        )
        return bool(output.strip())
    except Exception:
        return True


def _resolve_head_sha_from_fs(wt_path: str | Path) -> str | None:
    try:
        worktree = Path(wt_path)
        git_marker = worktree / ".git"
        if git_marker.is_file():
            raw = git_marker.read_text(encoding="utf-8", errors="replace").strip()
            if not raw.startswith("gitdir:"):
                return None
            git_dir = Path(raw.removeprefix("gitdir:").strip())
            if not git_dir.is_absolute():
                git_dir = (worktree / git_dir).resolve(strict=False)
        elif git_marker.is_dir():
            git_dir = git_marker.resolve(strict=False)
        else:
            return None

        common_dir = git_dir
        common_file = git_dir / "commondir"
        if common_file.exists():
            common_raw = common_file.read_text(encoding="utf-8", errors="replace").strip()
            common_dir = Path(common_raw)
            if not common_dir.is_absolute():
                common_dir = (git_dir / common_dir).resolve(strict=False)

        head = (git_dir / "HEAD").read_text(encoding="utf-8", errors="replace").strip()
        if not head.startswith("ref:"):
            return head if _looks_like_sha(head) else None
        ref = head.removeprefix("ref:").strip()
        for root in (git_dir, common_dir):
            ref_file = root / ref
            if ref_file.exists():
                value = ref_file.read_text(encoding="utf-8", errors="replace").strip()
                return value if _looks_like_sha(value) else None
        packed = common_dir / "packed-refs"
        if packed.exists():
            for line in packed.read_text(encoding="utf-8", errors="replace").splitlines():
                if not line or line.startswith(("#", "^")):
                    continue
                parts = line.split()
                if len(parts) == 2 and parts[1] == ref and _looks_like_sha(parts[0]):
                    return parts[0]
    except OSError:
        return None
    return None


def _looks_like_sha(value: str) -> bool:
    return len(value) in {40, 64} and all(ch in "0123456789abcdefABCDEF" for ch in value)
