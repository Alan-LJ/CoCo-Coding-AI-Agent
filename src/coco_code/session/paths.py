from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SessionPaths:
    session_id: str
    session_dir: Path
    jsonl_path: Path
    spill_dir: Path


def session_paths(workspace: Path, session_id: str) -> SessionPaths:
    session_dir = workspace / ".mewcode" / "sessions" / session_id
    return SessionPaths(
        session_id=session_id,
        session_dir=session_dir,
        jsonl_path=session_dir / "conversation.jsonl",
        spill_dir=session_dir / "tool-results",
    )
