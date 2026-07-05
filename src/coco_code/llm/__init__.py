from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from coco_code.config import ProviderConfig, resolve_api_key
from coco_code.conversation import ChatMessage, ConversationItem, Message, Role
from coco_code.tools.base import ToolCall
from coco_code.tools.registry import ToolRegistry


class StreamEventType(StrEnum):
    TEXT_DELTA = "text_delta"
    THINKING_DELTA = "thinking_delta"
    TOOL_CALL = "tool_call"
    DONE = "done"
    ERROR = "error"


EventType = StreamEventType | str


class PromptTooLongError(RuntimeError):
    pass


@dataclass(frozen=True)
class StreamEvent:
    type: EventType
    text: str = ""
    tool_call: ToolCall | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    error: Exception | None = None
    usage: dict[str, int] | None = None


class Provider(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def model(self) -> str: ...

    @property
    def protocol(self) -> str: ...

    def stream(
        self,
        messages: list[ConversationItem],
        tools: ToolRegistry | None = None,
    ) -> AsyncIterator[StreamEvent]: ...


def new_provider(cfg: ProviderConfig, system_prompt: str) -> Provider:
    api_key = resolve_api_key(cfg)
    if cfg.protocol == "anthropic":
        from coco_code.llm.anthropic_provider import AnthropicProvider

        return AnthropicProvider(cfg, api_key, system_prompt)

    from coco_code.llm.openai_provider import OpenAICompatProvider, OpenAIProvider

    if cfg.protocol == "openai":
        return OpenAIProvider(cfg, api_key, system_prompt)
    return OpenAICompatProvider(cfg, api_key, system_prompt)


__all__ = [
    "ChatMessage",
    "ConversationItem",
    "EventType",
    "Message",
    "PromptTooLongError",
    "Provider",
    "Role",
    "StreamEvent",
    "StreamEventType",
    "new_provider",
]
