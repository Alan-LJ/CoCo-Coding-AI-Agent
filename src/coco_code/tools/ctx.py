from __future__ import annotations

import contextvars
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

_ctx_cwd: contextvars.ContextVar[str | None] = contextvars.ContextVar("cwd", default=None)


@contextmanager
def with_cwd(directory: str | Path) -> Iterator[None]:
    text = str(directory)
    if not text:
        yield
        return
    token = _ctx_cwd.set(text)
    try:
        yield
    finally:
        _ctx_cwd.reset(token)


def cwd_from_ctx() -> str | None:
    return _ctx_cwd.get()


def resolve_path(path: str | Path) -> str:
    base = Path(_ctx_cwd.get() or Path.cwd())
    text = str(path)
    if not text:
        return str(base)
    candidate = Path(text)
    if candidate.is_absolute():
        return str(candidate)
    return str(base / candidate)


def workspace_from_ctx(fallback: Path) -> Path:
    current = _ctx_cwd.get()
    if not current:
        return fallback
    return Path(current)
