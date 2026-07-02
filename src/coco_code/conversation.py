from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from coco_code.tools.base import ToolCall, ToolResult

Role = Literal["user", "assistant"]


@dataclass(frozen=True)
class ChatMessage:
    role: Role
    content: str


@dataclass(frozen=True)
class AssistantToolCallItem:
    call: ToolCall


@dataclass(frozen=True)
class AssistantToolCallsItem:
    calls: tuple[ToolCall, ...]


@dataclass(frozen=True)
class ToolResultItem:
    result: ToolResult


ConversationItem = ChatMessage | AssistantToolCallItem | AssistantToolCallsItem | ToolResultItem
Message = ChatMessage


class Conversation:
    def __init__(self) -> None:
        self._items: list[ConversationItem] = []

    def add_user(self, text: str) -> None:
        self._items.append(ChatMessage(role="user", content=text))

    def add_assistant(self, text: str) -> None:
        self._items.append(ChatMessage(role="assistant", content=text))

    def add_tool_call(self, call: ToolCall) -> None:
        self._items.append(AssistantToolCallItem(call=call))

    def add_tool_calls(self, calls: Sequence[ToolCall]) -> None:
        call_items = tuple(calls)
        if not call_items:
            return
        if len(call_items) == 1:
            self.add_tool_call(call_items[0])
            return
        self._items.append(AssistantToolCallsItem(calls=call_items))

    def add_tool_result(self, result: ToolResult) -> None:
        self._items.append(ToolResultItem(result=result))

    def messages(self) -> list[Message]:
        return [item for item in self._items if isinstance(item, ChatMessage)]

    def items(self) -> list[ConversationItem]:
        return list(self._items)

    def clear(self) -> None:
        self._items.clear()