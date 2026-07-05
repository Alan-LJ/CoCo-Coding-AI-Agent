from __future__ import annotations

import json
import math
from dataclasses import asdict, is_dataclass
from typing import Any

from coco_code.compact.constants import ESTIMATE_CHARS_PER_TOKEN
from coco_code.conversation import (
    AssistantToolCallItem,
    AssistantToolCallsItem,
    ChatMessage,
    ConversationItem,
    ToolResultItem,
)


def conversation_bytes(items: list[ConversationItem]) -> int:
    return sum(item_bytes(item) for item in items)


def item_bytes(item: ConversationItem) -> int:
    return len(item_visible_text(item).encode("utf-8"))


def item_visible_text(item: ConversationItem) -> str:
    if isinstance(item, ChatMessage):
        return item.content
    if isinstance(item, AssistantToolCallItem):
        return _json({"tool_call": _to_jsonable(item.call)})
    if isinstance(item, AssistantToolCallsItem):
        return _json({"tool_calls": [_to_jsonable(call) for call in item.calls]})
    if isinstance(item, ToolResultItem):
        return _json({"tool_result": _to_jsonable(item.result)})
    raise TypeError(f"unsupported conversation item: {type(item)!r}")


def estimate_tokens(
    anchor: int,
    items: list[ConversationItem],
    anchor_item_len: int,
) -> int:
    if anchor <= 0 or anchor_item_len < 0 or anchor_item_len > len(items):
        return _bytes_to_tokens(conversation_bytes(items))
    delta = conversation_bytes(items[anchor_item_len:])
    return int(anchor) + _bytes_to_tokens(delta)


def usage_anchor(usage: dict[str, int] | None) -> int:
    if usage is None:
        return 0
    keys = ("input_tokens", "output_tokens", "cache_read", "cache_write")
    return int(sum(int(usage.get(key, 0) or 0) for key in keys))


def _bytes_to_tokens(byte_count: int) -> int:
    return int(math.ceil(byte_count / ESTIMATE_CHARS_PER_TOKEN))


def _to_jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)  # type: ignore[arg-type]
    if isinstance(value, tuple):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    return value


def _json(value: Any) -> str:
    return json.dumps(_to_jsonable(value), ensure_ascii=False, sort_keys=True)
