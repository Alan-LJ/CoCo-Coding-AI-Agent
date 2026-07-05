from __future__ import annotations

import re
import threading
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from coco_code.memory.types import MemoryAction, MemoryLevel, MemoryNote, NoteType

INDEX_FILE = "MEMORY.md"
MAX_INDEX_LINES = 200
MAX_INDEX_BYTES = 25 * 1024


class MemoryStore:
    def __init__(self, root: Path, level: MemoryLevel) -> None:
        self.root = root
        self.level = level
        self._lock = threading.Lock()

    @property
    def index_path(self) -> Path:
        return self.root / INDEX_FILE

    def ensure_dir(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def load_index(self) -> str:
        try:
            return self.index_path.read_text(encoding="utf-8")
        except OSError:
            return ""

    def apply_actions(self, actions: list[MemoryAction]) -> None:
        with self._lock:
            self.ensure_dir()
            index_lines = self._index_lines()
            for action in actions:
                if action.level != self.level:
                    continue
                if action.action == "create":
                    filename = _filename(action)
                    note_type = action.type or NoteType.PROJECT_KNOWLEDGE
                    now = datetime.now(UTC)
                    note = MemoryNote(
                        level=self.level,
                        type=note_type,
                        title=action.title or action.slug or filename,
                        slug=action.slug or _slug_from_title(action.title or filename),
                        content=action.content,
                        path=self.root / filename,
                        created=now,
                        updated=now,
                    )
                    self._write_note(note)
                    index_lines = _upsert_index_line(
                        index_lines, filename, note.type, note.title, note.content
                    )
                elif action.action == "update":
                    filename = _safe_filename(action.filename)
                    if not filename:
                        continue
                    path = self.root / filename
                    old_meta = _read_frontmatter(path)
                    note_type = (
                        action.type
                        or _note_type(old_meta.get("type"))
                        or NoteType.PROJECT_KNOWLEDGE
                    )
                    created = _parse_datetime(old_meta.get("created")) or datetime.now(UTC)
                    updated = datetime.now(UTC)
                    title = action.title or str(old_meta.get("title") or filename)
                    note = MemoryNote(
                        level=self.level,
                        type=note_type,
                        title=title,
                        slug=_slug_from_filename(filename),
                        content=action.content,
                        path=path,
                        created=created,
                        updated=updated,
                    )
                    self._write_note(note)
                    index_lines = _upsert_index_line(
                        index_lines, filename, note.type, note.title, note.content
                    )
                elif action.action == "delete":
                    filename = _safe_filename(action.filename)
                    if not filename:
                        continue
                    with suppress(FileNotFoundError):
                        (self.root / filename).unlink()
                    index_lines = [line for line in index_lines if filename not in line]
            self._write_index(index_lines)

    def _index_lines(self) -> list[str]:
        return [line for line in self.load_index().splitlines() if line.strip()]

    def _write_note(self, note: MemoryNote) -> None:
        self.ensure_dir()
        meta: dict[str, Any] = {
            "type": note.type.value,
            "title": note.title,
            "created": note.created.isoformat(),
            "updated": note.updated.isoformat(),
        }
        frontmatter = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False).strip()
        text = f"---\n{frontmatter}\n---\n{note.content.strip()}\n"
        note.path.write_text(text, encoding="utf-8")

    def _write_index(self, lines: list[str]) -> None:
        limited = _limit_index(lines)
        self.index_path.write_text(
            "\n".join(limited).rstrip() + ("\n" if limited else ""), encoding="utf-8"
        )


def _filename(action: MemoryAction) -> str:
    note_type = action.type or NoteType.PROJECT_KNOWLEDGE
    slug = action.slug or _slug_from_title(action.title or note_type.value)
    return _safe_filename(f"{note_type.value}_{slug}.md") or f"{note_type.value}_note.md"


def _safe_filename(filename: str) -> str:
    name = Path(filename).name
    if not name.endswith(".md"):
        name = f"{name}.md"
    return re.sub(r"[^a-zA-Z0-9_.-]", "_", name)


def _slug_from_title(title: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", title.strip().lower()).strip("_")
    return slug[:60] or "note"


def _slug_from_filename(filename: str) -> str:
    stem = Path(filename).stem
    parts = stem.split("_", 2)
    return parts[-1] if parts else stem


def _upsert_index_line(
    lines: list[str],
    filename: str,
    note_type: NoteType,
    title: str,
    content: str,
) -> list[str]:
    description = " ".join(content.split())[:120] or title
    line = f"- [{note_type.value}] {title} — {description} ({filename})"
    kept = [existing for existing in lines if filename not in existing]
    kept.append(line)
    return kept


def _limit_index(lines: list[str]) -> list[str]:
    limited = lines[-MAX_INDEX_LINES:]
    while len("\n".join(limited).encode("utf-8")) > MAX_INDEX_BYTES and limited:
        limited.pop(0)
    return limited


def _read_frontmatter(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    if not text.startswith("---\n"):
        return {}
    _, rest = text.split("---\n", 1)
    meta_text, _, _body = rest.partition("\n---")
    try:
        data = yaml.safe_load(meta_text) or {}
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _note_type(value: Any) -> NoteType | None:
    try:
        return NoteType(str(value))
    except ValueError:
        return None
