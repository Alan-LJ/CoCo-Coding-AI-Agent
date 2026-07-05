from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from typing import Any

from coco_code.conversation import (
    AssistantToolCallItem,
    AssistantToolCallsItem,
    ChatMessage,
    ConversationItem,
    ToolResultItem,
)
from coco_code.tools.base import ToolCall, ToolResult


@dataclass(frozen=True)
class SessionEntry:
    role: str | None = None
    content: str | None = None
    tool_calls: tuple[dict[str, Any], ...] = ()
    tool_results: tuple[dict[str, Any], ...] = ()
    ts: int = 0
    model: str | None = None
    type: str | None = None

    def to_json_line(self) -> str:
        data = asdict(self)
        compact = {
            key: value
            for key, value in data.items()
            if value is not None and value != () and value != ""
        }
        return json.dumps(compact, ensure_ascii=False, separators=(",", ":")) + "\n"


def compact_marker(ts: int | None = None) -> SessionEntry:
    return SessionEntry(type="compact", ts=ts or int(time.time()))


def item_to_entry(
    item: ConversationItem,
    *,
    model: str | None = None,
    include_model: bool = False,
    ts: int | None = None,
) -> SessionEntry:
    timestamp = ts or int(time.time())
    model_value = model if include_model else None
    if isinstance(item, ChatMessage):
        return SessionEntry(
            role=item.role,
            content=item.content,
            ts=timestamp,
            model=model_value if item.role == "user" else None,
        )
    if isinstance(item, AssistantToolCallItem):
        return SessionEntry(
            role="assistant",
            tool_calls=(_tool_call_to_dict(item.call),),
            ts=timestamp,
        )
    if isinstance(item, AssistantToolCallsItem):
        return SessionEntry(
            role="assistant",
            tool_calls=tuple(_tool_call_to_dict(call) for call in item.calls),
            ts=timestamp,
        )
    if isinstance(item, ToolResultItem):
        return SessionEntry(
            role="tool",
            tool_results=(_tool_result_to_dict(item.result),),
            ts=timestamp,
        )
    raise TypeError(f"Unsupported conversation item: {type(item)!r}")


def entry_to_items(entry: SessionEntry) -> tuple[ConversationItem, ...]:
    if entry.type == "compact":
        return ()
    if entry.role == "user" or (entry.role == "assistant" and entry.content is not None):
        return (ChatMessage(role=entry.role, content=entry.content or ""),)  # type: ignore[arg-type]
    if entry.role == "assistant" and entry.tool_calls:
        calls = tuple(_tool_call_from_dict(raw) for raw in entry.tool_calls)
        if len(calls) == 1:
            return (AssistantToolCallItem(calls[0]),)
        return (AssistantToolCallsItem(calls),)
    if entry.role == "tool" and entry.tool_results:
        return tuple(ToolResultItem(_tool_result_from_dict(raw)) for raw in entry.tool_results)
    return ()


def parse_entry(raw: str) -> SessionEntry:
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("session entry must be a JSON object")
    return SessionEntry(
        role=_optional_str(data.get("role")),
        content=_optional_str(data.get("content")),
        tool_calls=tuple(_dict_items(data.get("tool_calls"))),
        tool_results=tuple(_dict_items(data.get("tool_results"))),
        ts=_int_value(data.get("ts")),
        model=_optional_str(data.get("model")),
        type=_optional_str(data.get("type")),
    )


def _tool_call_to_dict(call: ToolCall) -> dict[str, Any]:
    return {
        "id": call.id,
        "name": call.name,
        "arguments": call.arguments,
        "raw_arguments": call.raw_arguments,
    }


def _tool_call_from_dict(raw: dict[str, Any]) -> ToolCall:
    arguments = raw.get("arguments")
    return ToolCall(
        id=str(raw.get("id", "")),
        name=str(raw.get("name", "")),
        arguments=arguments if isinstance(arguments, dict) else {},
        raw_arguments=str(raw.get("raw_arguments", "{}")),
    )


def _tool_result_to_dict(result: ToolResult) -> dict[str, Any]:
    return {
        "tool_call_id": result.tool_call_id,
        "tool_name": result.tool_name,
        "ok": result.ok,
        "summary": result.summary,
        "data": result.data,
        "error": result.error,
        "elapsed_ms": result.elapsed_ms,
        "truncated": result.truncated,
    }


def _tool_result_from_dict(raw: dict[str, Any]) -> ToolResult:
    data = raw.get("data")
    return ToolResult(
        tool_call_id=str(raw.get("tool_call_id", "")),
        tool_name=str(raw.get("tool_name", "")),
        ok=bool(raw.get("ok", False)),
        summary=str(raw.get("summary", "")),
        data=data if isinstance(data, dict) else {},
        error=_optional_str(raw.get("error")),
        elapsed_ms=int(raw.get("elapsed_ms", 0) or 0),
        truncated=bool(raw.get("truncated", False)),
    )


def _dict_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _int_value(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
