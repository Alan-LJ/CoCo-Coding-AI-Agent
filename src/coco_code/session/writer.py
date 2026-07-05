from __future__ import annotations

import os
import threading
from collections.abc import Sequence
from types import TracebackType

from coco_code.conversation import ConversationItem
from coco_code.session.codec import compact_marker, item_to_entry
from coco_code.session.paths import SessionPaths


class SessionWriter:
    def __init__(self, paths: SessionPaths, model: str | None = None) -> None:
        self.paths = paths
        self.model = model
        self._lock = threading.Lock()
        self._closed = False
        self.paths.session_dir.mkdir(parents=True, exist_ok=True)
        self.paths.spill_dir.mkdir(parents=True, exist_ok=True)
        self._wrote_model = (
            self.paths.jsonl_path.exists() and self.paths.jsonl_path.stat().st_size > 0
        )
        self._file = self.paths.jsonl_path.open("ab")

    @classmethod
    def open_existing(cls, paths: SessionPaths, model: str | None = None) -> SessionWriter:
        if not paths.session_dir.exists():
            raise FileNotFoundError(paths.session_dir)
        return cls(paths, model=model)

    def append_item(self, item: ConversationItem) -> None:
        include_model = not self._wrote_model
        entry = item_to_entry(item, model=self.model, include_model=include_model)
        if include_model and entry.model is not None:
            self._wrote_model = True
        self._write_line(entry.to_json_line())

    def replace_items(self, items: Sequence[ConversationItem]) -> None:
        with self._lock:
            self._write_line_locked(compact_marker().to_json_line())
            for item in items:
                entry = item_to_entry(item, model=self.model, include_model=False)
                self._write_line_locked(entry.to_json_line())
            self._flush_locked()

    def write_compact_marker(self) -> None:
        self._write_line(compact_marker().to_json_line())

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._file.flush()
            self._file.close()
            self._closed = True

    def __enter__(self) -> SessionWriter:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def _write_line(self, line: str) -> None:
        with self._lock:
            self._write_line_locked(line)
            self._flush_locked()

    def _write_line_locked(self, line: str) -> None:
        if self._closed:
            raise ValueError("session writer is closed")
        self._file.write(line.encode("utf-8"))

    def _flush_locked(self) -> None:
        self._file.flush()
        os.fsync(self._file.fileno())


def null_append(item: ConversationItem) -> None:
    return None
