from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from coco_code.session.codec import parse_entry
from coco_code.session.ids import parse_session_time


@dataclass(frozen=True)
class SessionInfo:
    session_id: str
    title: str
    modified_at: datetime
    model: str
    message_count: int
    size_bytes: int
    session_dir: Path


def list_sessions(workspace: Path) -> list[SessionInfo]:
    sessions_dir = workspace / ".coco-code" / "sessions"
    if not sessions_dir.exists():
        return []
    infos: list[SessionInfo] = []
    for session_dir in sessions_dir.iterdir():
        if not session_dir.is_dir():
            continue
        if parse_session_time(session_dir.name) is None:
            continue
        jsonl_path = session_dir / "conversation.jsonl"
        if not jsonl_path.exists():
            continue
        info = _scan_session(session_dir, jsonl_path)
        if info is not None:
            infos.append(info)
    return sorted(infos, key=lambda item: item.modified_at, reverse=True)


def _scan_session(session_dir: Path, jsonl_path: Path) -> SessionInfo | None:
    title = "Untitled session"
    model = "unknown"
    message_count = 0
    try:
        with jsonl_path.open("r", encoding="utf-8", errors="replace") as file:
            for line in file:
                try:
                    entry = parse_entry(line)
                except Exception:
                    continue
                if entry.type == "compact":
                    continue
                if entry.role in {"user", "assistant", "tool"}:
                    message_count += 1
                if entry.model and model == "unknown":
                    model = entry.model
                if entry.role == "user" and entry.content and title == "Untitled session":
                    title = _truncate_title(entry.content)
    except OSError:
        return None
    if message_count == 0:
        return None
    stat = jsonl_path.stat()
    return SessionInfo(
        session_id=session_dir.name,
        title=title,
        modified_at=datetime.fromtimestamp(stat.st_mtime),
        model=model,
        message_count=message_count,
        size_bytes=stat.st_size,
        session_dir=session_dir,
    )


def _truncate_title(text: str, limit: int = 50) -> str:
    clean = " ".join(text.split())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 3] + "..."
