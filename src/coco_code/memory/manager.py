from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path

from coco_code.conversation import ConversationItem
from coco_code.llm import Provider, StreamEventType
from coco_code.memory.prompts import MEMORY_UPDATE_PROMPT
from coco_code.memory.store import MAX_INDEX_BYTES, MemoryStore
from coco_code.memory.types import MemoryAction, MemoryLevel, NoteType
from coco_code.session.codec import item_to_entry

LOGGER = logging.getLogger(__name__)


class MemoryManager:
    def __init__(self, project_root: Path, provider: Provider | None = None) -> None:
        self.project_root = project_root
        self.project_store = MemoryStore(
            project_root / ".coco-code" / "memory", MemoryLevel.PROJECT
        )
        self.user_store = MemoryStore(Path.home() / ".coco-code" / "memory", MemoryLevel.USER)
        self.provider = provider
        self._lock = asyncio.Lock()
        self._index_cache = ""

    def load_index_text(self) -> str:
        project = self.project_store.load_index().strip()
        user = self.user_store.load_index().strip()
        parts: list[str] = []
        if project:
            parts.append(f"## 项目级记忆\n{project}")
        if user:
            parts.append(f"## 用户级记忆\n{user}")
        text = "\n\n".join(parts)
        encoded = text.encode("utf-8")
        if len(encoded) > MAX_INDEX_BYTES:
            text = (
                encoded[:MAX_INDEX_BYTES].decode("utf-8", errors="ignore") + "\n(index truncated)"
            )
        self._index_cache = text
        return text

    def set_provider(self, provider: Provider) -> None:
        self.provider = provider

    def list_files(self) -> tuple[str, ...]:
        files: list[str] = []
        for label, root in (
            ("project", self.project_store.root),
            ("user", self.user_store.root),
        ):
            try:
                entries = sorted(path.name for path in root.glob("*.md") if path.is_file())
            except OSError:
                LOGGER.warning("failed to list %s memory files", label, exc_info=True)
                entries = []
            files.extend(f"{label}:{name}" for name in entries)
        return tuple(files)

    async def update_async(self, recent_items: list[ConversationItem]) -> None:
        provider = self.provider
        if provider is None:
            return
        async with self._lock:
            try:
                prompt = self._build_prompt(recent_items)
                raw = await self._collect_json(provider, prompt)
                actions = _parse_actions(raw)
                project_actions = [
                    action for action in actions if action.level == MemoryLevel.PROJECT
                ]
                user_actions = [action for action in actions if action.level == MemoryLevel.USER]
                if project_actions:
                    await asyncio.to_thread(self.project_store.apply_actions, project_actions)
                if user_actions:
                    await asyncio.to_thread(self.user_store.apply_actions, user_actions)
                self.load_index_text()
            except Exception:
                LOGGER.exception("memory update failed")

    def _build_prompt(self, recent_items: list[ConversationItem]) -> str:
        entries = [item_to_entry(item).to_json_line().strip() for item in recent_items]
        return "\n".join(
            [
                MEMORY_UPDATE_PROMPT,
                "",
                "现有索引：",
                self.load_index_text() or "(empty)",
                "",
                "本轮对话 JSONL：",
                "\n".join(entries),
            ]
        )

    async def _collect_json(self, provider: Provider, prompt: str) -> str:
        from coco_code.conversation import ChatMessage

        parts: list[str] = []
        async for event in provider.stream([ChatMessage(role="user", content=prompt)], tools=None):
            if event.type == StreamEventType.TEXT_DELTA or event.type == "text_delta":
                parts.append(event.text)
            elif event.type == StreamEventType.TOOL_CALL or event.type == "tool_call":
                raise RuntimeError("memory update attempted to call a tool")
            elif event.type == StreamEventType.ERROR or event.type == "error":
                if event.error is not None:
                    raise event.error
                raise RuntimeError("memory update provider returned an error")
            elif event.type == StreamEventType.DONE or event.type == "done":
                break
        return "".join(parts)


def _parse_actions(raw: str) -> list[MemoryAction]:
    text = _extract_json(raw)
    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError("memory update must return a JSON array")
    actions: list[MemoryAction] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        action = item.get("action")
        if action not in {"create", "update", "delete"}:
            continue
        try:
            level = MemoryLevel(str(item.get("level")))
        except ValueError:
            continue
        note_type = None
        if item.get("type") is not None:
            try:
                note_type = NoteType(str(item.get("type")))
            except ValueError:
                note_type = None
        actions.append(
            MemoryAction(
                action=action,
                level=level,
                type=note_type,
                title=str(item.get("title") or ""),
                slug=str(item.get("slug") or ""),
                content=str(item.get("content") or ""),
                filename=str(item.get("filename") or ""),
            )
        )
    return actions


def _extract_json(raw: str) -> str:
    stripped = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", stripped, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        return fenced.group(1).strip()
    start = stripped.find("[")
    end = stripped.rfind("]")
    if start >= 0 and end >= start:
        return stripped[start : end + 1]
    return stripped
