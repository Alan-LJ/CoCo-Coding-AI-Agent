from __future__ import annotations

from pathlib import Path
from typing import Any


def resolve_root(root: str | Path) -> Path:
    return Path(root).expanduser().resolve(strict=True)


def eval_symlinks_or_ancestor(path: str | Path) -> Path:
    candidate = Path(path).expanduser()
    if candidate.exists():
        return candidate.resolve(strict=True)

    missing_parts: list[str] = []
    probe = candidate
    while not probe.exists():
        missing_parts.append(probe.name)
        parent = probe.parent
        if parent == probe:
            raise FileNotFoundError(str(candidate))
        probe = parent

    resolved = probe.resolve(strict=True)
    for part in reversed(missing_parts):
        resolved = resolved / part
    return resolved


def sandbox_ok(engine: Any, path: str) -> bool:
    try:
        root = Path(str(engine.root)).expanduser().resolve(strict=True)
        raw = str(path or "")
        candidate = Path(raw).expanduser() if raw else root
        if not candidate.is_absolute():
            candidate = root / candidate
        resolved = eval_symlinks_or_ancestor(candidate)
        resolved.relative_to(root)
    except (OSError, RuntimeError, ValueError):
        return False
    return True
