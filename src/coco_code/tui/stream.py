from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import cast

from coco_code.conversation import ConversationItem, Message
from coco_code.llm import Provider, StreamEventType
from coco_code.tools.base import ToolCall
from coco_code.tools.registry import ToolRegistry


@dataclass(frozen=True)
class StreamResult:
    reply: str
    error: Exception | None = None
    tool_call: ToolCall | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    blocked_by_second_tool_call: bool = False

    @property
    def ok(self) -> bool:
        return self.error is None


TextCallback = Callable[[str], Awaitable[None]]


async def consume_provider_stream(
    provider: Provider,
    messages: list[ConversationItem] | list[Message],
    on_text: TextCallback,
    tools: ToolRegistry | None = None,
    *,
    allow_tool_call: bool = True,
) -> StreamResult:
    reply_parts: list[str] = []
    stream_messages = cast(list[ConversationItem], messages)
    stream = (
        provider.stream(stream_messages)
        if tools is None
        else provider.stream(stream_messages, tools=tools)
    )
    async for event in stream:
        if event.type == StreamEventType.TEXT_DELTA or event.type == "text_delta":
            reply_parts.append(event.text)
            await on_text(event.text)
        elif event.type == StreamEventType.THINKING_DELTA or event.type == "thinking_delta":
            continue
        elif event.type == StreamEventType.TOOL_CALL or event.type == "tool_call":
            calls = event.tool_calls or ((event.tool_call,) if event.tool_call is not None else ())
            return StreamResult(
                reply="".join(reply_parts),
                tool_call=calls[0] if calls else None,
                tool_calls=calls,
                blocked_by_second_tool_call=not allow_tool_call,
            )
        elif event.type == StreamEventType.ERROR or event.type == "error":
            return StreamResult(reply="".join(reply_parts), error=event.error)
        elif event.type == StreamEventType.DONE or event.type == "done":
            break
    return StreamResult(reply="".join(reply_parts))