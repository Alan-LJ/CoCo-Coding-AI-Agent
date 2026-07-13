from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class WorktreeSession:
    original_cwd: str
    worktree_path: str
    worktree_name: str
    original_branch: str
    original_head_commit: str
    session_id: str
    hook_based: bool = False

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> WorktreeSession:
        return cls(**json.loads(raw))


def load_session(path: Path) -> WorktreeSession | None:
    if not path.exists():
        return None
    raw = path.read_text(encoding="utf-8").strip()
    if not raw or raw == "null":
        return None
    return WorktreeSession.from_json(raw)


def save_session(path: Path, session: WorktreeSession | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = "null" if session is None else session.to_json()
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(raw, encoding="utf-8")
    os.replace(tmp, path)


def clear_session(path: Path) -> None:
    save_session(path, None)
