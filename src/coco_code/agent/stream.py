from __future__ import annotations

from collections.abc import Awaitable, Callable

from coco_code.agent.types import AgentEvent, AgentEventType, StreamTurnResult
from coco_code.conversation import ConversationItem
from coco_code.llm import Provider, StreamEventType
from coco_code.tools.base import ToolCall
from coco_code.tools.registry import ToolRegistry

AgentEventCallback = Callable[[AgentEvent], Awaitable[None]]


async def collect_stream_turn(
    provider: Provider,
    messages: list[ConversationItem],
    tools: ToolRegistry | None,
    on_event: AgentEventCallback,
) -> StreamTurnResult:
    reply_parts: list[str] = []
    tool_calls: list[ToolCall] = []
    last_usage: dict[str, int] | None = None
    stream = provider.stream(messages, tools=tools)

    async for event in stream:
        if event.usage is not None:
            last_usage = event.usage
            await on_event(AgentEvent(type=AgentEventType.USAGE, usage=event.usage))
        if event.type == StreamEventType.TEXT_DELTA or event.type == "text_delta":
            reply_parts.append(event.text)
            await on_event(AgentEvent(type=AgentEventType.TEXT_DELTA, text=event.text))
        elif event.type == StreamEventType.THINKING_DELTA or event.type == "thinking_delta":
            continue
        elif event.type == StreamEventType.TOOL_CALL or event.type == "tool_call":
            calls = event.tool_calls or ((event.tool_call,) if event.tool_call is not None else ())
            tool_calls.extend(calls)
            if tool_calls:
                return StreamTurnResult(
                    reply="".join(reply_parts),
                    tool_calls=tuple(tool_calls),
                    usage=last_usage,
                )
        elif event.type == StreamEventType.ERROR or event.type == "error":
            return StreamTurnResult(
                reply="".join(reply_parts),
                error=event.error,
                usage=last_usage,
            )
        elif event.type == StreamEventType.DONE or event.type == "done":
            break

    return StreamTurnResult(
        reply="".join(reply_parts),
        tool_calls=tuple(tool_calls),
        usage=last_usage,
    )
