from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from coco_code.conversation import (
    AssistantToolCallItem,
    AssistantToolCallsItem,
    ConversationItem,
    ToolResultItem,
)
from coco_code.session.codec import SessionEntry, entry_to_items, parse_entry
from coco_code.session.paths import SessionPaths


@dataclass(frozen=True)
class SessionLoadResult:
    items: tuple[ConversationItem, ...]
    loaded_count: int
    skipped_bad_lines: int
    truncated: bool
    last_timestamp: int | None


def load_session(paths: SessionPaths | Path) -> SessionLoadResult:
    jsonl_path = (
        paths.jsonl_path if isinstance(paths, SessionPaths) else paths / "conversation.jsonl"
    )
    entries: list[SessionEntry] = []
    skipped = 0
    compact_index = -1
    last_timestamp: int | None = None
    try:
        with jsonl_path.open("r", encoding="utf-8", errors="replace") as file:
            for line in file:
                try:
                    entry = parse_entry(line)
                except Exception:
                    skipped += 1
                    continue
                entries.append(entry)
                if entry.ts:
                    last_timestamp = entry.ts
                if entry.type == "compact":
                    compact_index = len(entries) - 1
    except OSError:
        return SessionLoadResult((), 0, skipped, False, None)

    items: list[ConversationItem] = []
    for entry in entries[compact_index + 1 :]:
        items.extend(entry_to_items(entry))
    truncated_items = _truncate_orphaned_tool_calls(items)
    return SessionLoadResult(
        items=tuple(truncated_items),
        loaded_count=len(truncated_items),
        skipped_bad_lines=skipped,
        truncated=len(truncated_items) != len(items),
        last_timestamp=last_timestamp,
    )


def _truncate_orphaned_tool_calls(items: list[ConversationItem]) -> list[ConversationItem]:
    if not items:
        return []
    last = items[-1]
    if isinstance(last, AssistantToolCallItem | AssistantToolCallsItem):
        return items[:-1]
    for index in range(len(items) - 1, -1, -1):
        item = items[index]
        if isinstance(item, AssistantToolCallItem | AssistantToolCallsItem):
            expected = _call_ids(item)
            following = items[index + 1 :]
            seen = {
                result.result.tool_call_id
                for result in following
                if isinstance(result, ToolResultItem)
            }
            if not expected.issubset(seen):
                return items[:index]
            return items
    return items


def _call_ids(item: AssistantToolCallItem | AssistantToolCallsItem) -> set[str]:
    if isinstance(item, AssistantToolCallItem):
        return {item.call.id}
    return {call.id for call in item.calls}
