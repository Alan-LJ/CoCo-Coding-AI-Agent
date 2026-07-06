from __future__ import annotations

import threading
from dataclasses import dataclass


@dataclass(frozen=True)
class ActiveSkillEntry:
    name: str
    rendered_body: str
    allowed_tools: tuple[str, ...] = ()


class ActiveSkills:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: list[ActiveSkillEntry] = []
        self._index: dict[str, int] = {}

    def activate(
        self,
        name: str,
        rendered_body: str,
        allowed_tools: tuple[str, ...] = (),
    ) -> None:
        key = name.casefold()
        entry = ActiveSkillEntry(
            name=name, rendered_body=rendered_body, allowed_tools=allowed_tools
        )
        with self._lock:
            index = self._index.get(key)
            if index is None:
                self._index[key] = len(self._entries)
                self._entries.append(entry)
                return
            self._entries[index] = entry

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._index.clear()

    def snapshot(self) -> tuple[ActiveSkillEntry, ...]:
        with self._lock:
            return tuple(self._entries)

    def allowed_tool_union(self) -> tuple[str, ...]:
        names: dict[str, str] = {}
        with self._lock:
            for entry in self._entries:
                for name in entry.allowed_tools:
                    names.setdefault(name.casefold(), name)
        return tuple(sorted(names.values(), key=str.casefold))
