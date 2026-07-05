from __future__ import annotations

from collections.abc import Callable, Sequence
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
AppendCallback = Callable[[ConversationItem], None]
ReplaceCallback = Callable[[Sequence[ConversationItem]], None]


class Conversation:
    def __init__(
        self,
        on_append: AppendCallback | None = None,
        on_replace: ReplaceCallback | None = None,
    ) -> None:
        self._items: list[ConversationItem] = []
        self._on_append = on_append
        self._on_replace = on_replace

    @classmethod
    def from_items(
        cls,
        items: Sequence[ConversationItem],
        on_append: AppendCallback | None = None,
        on_replace: ReplaceCallback | None = None,
    ) -> Conversation:
        conversation = cls(on_append=on_append, on_replace=on_replace)
        conversation._items = list(items)
        return conversation

    def add_user(self, text: str) -> None:
        self._append(ChatMessage(role="user", content=text))

    def add_assistant(self, text: str) -> None:
        self._append(ChatMessage(role="assistant", content=text))

    def add_tool_call(self, call: ToolCall) -> None:
        self._append(AssistantToolCallItem(call=call))

    def add_tool_calls(self, calls: Sequence[ToolCall]) -> None:
        call_items = tuple(calls)
        if not call_items:
            return
        if len(call_items) == 1:
            self.add_tool_call(call_items[0])
            return
        self._append(AssistantToolCallsItem(calls=call_items))

    def add_tool_result(self, result: ToolResult) -> None:
        self._append(ToolResultItem(result=result))

    def messages(self) -> list[Message]:
        return [item for item in self._items if isinstance(item, ChatMessage)]

    def items(self) -> list[ConversationItem]:
        return list(self._items)

    def replace_items(self, items: Sequence[ConversationItem]) -> None:
        self._items = list(items)
        if self._on_replace is not None:
            self._on_replace(list(self._items))

    def clear(self) -> None:
        self._items.clear()

    def _append(self, item: ConversationItem) -> None:
        self._items.append(item)
        if self._on_append is not None:
            self._on_append(item)
