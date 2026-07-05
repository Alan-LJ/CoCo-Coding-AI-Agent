from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Any

from coco_code.config import ProviderConfig
from coco_code.conversation import (
    AssistantToolCallItem,
    AssistantToolCallsItem,
    ChatMessage,
    ConversationItem,
    ToolResultItem,
)
from coco_code.llm import PromptTooLongError, StreamEvent, StreamEventType
from coco_code.llm.openai_provider import tool_result_payload
from coco_code.tools.base import ToolCall
from coco_code.tools.registry import ToolRegistry

DEFAULT_MAX_TOKENS = 4096
DEFAULT_THINKING_BUDGET = 1024


class AnthropicProvider:
    def __init__(
        self,
        cfg: ProviderConfig,
        api_key: str,
        system_prompt: str,
        client: Any | None = None,
    ) -> None:
        self._cfg = cfg
        self._system_prompt = system_prompt
        if client is None:
            from anthropic import AsyncAnthropic

            kwargs: dict[str, Any] = {"api_key": api_key}
            if cfg.base_url:
                kwargs["base_url"] = cfg.base_url
            client = AsyncAnthropic(**kwargs)
        self._client = client

    @property
    def name(self) -> str:
        return self._cfg.name

    @property
    def model(self) -> str:
        return self._cfg.model

    @property
    def protocol(self) -> str:
        return self._cfg.protocol

    async def stream(
        self,
        messages: list[ConversationItem],
        tools: ToolRegistry | None = None,
    ) -> AsyncIterator[StreamEvent]:
        try:
            accumulator = AnthropicToolAccumulator()
            pending_tool_event: StreamEvent | None = None
            params = self._request_params(messages, tools)
            async with self._client.messages.stream(**params) as stream:
                async for event in stream:
                    usage = anthropic_event_usage(event)
                    if usage is not None:
                        yield StreamEvent(type="usage", usage=usage)
                    tool_event = accumulator.process(event)
                    if tool_event is not None:
                        pending_tool_event = tool_event
                    mapped = map_anthropic_event(event)
                    if mapped is not None:
                        yield mapped
            if pending_tool_event is not None:
                yield pending_tool_event
                return
            yield StreamEvent(type=StreamEventType.DONE)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            yield StreamEvent(type=StreamEventType.ERROR, error=wrap_prompt_too_long(exc))

    def _request_params(
        self,
        messages: list[ConversationItem],
        tools: ToolRegistry | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "model": self._cfg.model,
            "system": self._system_prompt,
            "messages": [anthropic_message_from_item(item) for item in messages],
            "max_tokens": DEFAULT_MAX_TOKENS,
        }
        if tools is not None:
            params["tools"] = tools.to_anthropic_tools()
        if self._cfg.thinking:
            params["thinking"] = {
                "type": "enabled",
                "budget_tokens": DEFAULT_THINKING_BUDGET,
            }
        return params


@dataclass
class _AnthropicToolState:
    id: str = ""
    name: str = ""
    raw: str = ""


class AnthropicToolAccumulator:
    def __init__(self) -> None:
        self._states: dict[int, _AnthropicToolState] = {}
        self._order: list[int] = []
        self._current_index = 0

    def process(self, event: Any) -> StreamEvent | None:
        event_type = getattr(event, "type", "")
        index = int(getattr(event, "index", self._current_index) or 0)
        if event_type == "content_block_start":
            block = getattr(event, "content_block", None)
            if getattr(block, "type", "") == "tool_use":
                self._current_index = index
                start_state = self._states.setdefault(index, _AnthropicToolState())
                if index not in self._order:
                    self._order.append(index)
                start_state.id = getattr(block, "id", "") or start_state.id
                start_state.name = getattr(block, "name", "") or start_state.name
                input_value = getattr(block, "input", None)
                if input_value:
                    start_state.raw = json.dumps(input_value, ensure_ascii=False)
            return None

        if event_type == "input_json":
            json_state = self._states.setdefault(index, _AnthropicToolState())
            if index not in self._order:
                self._order.append(index)
            snapshot = getattr(event, "snapshot", None)
            partial = getattr(event, "partial_json", None)
            if snapshot is not None:
                json_state.raw = snapshot
            elif partial:
                json_state.raw += partial
            return None

        if event_type == "content_block_delta":
            delta = getattr(event, "delta", None)
            delta_type = getattr(delta, "type", "")
            if delta_type in {"input_json_delta", "input_json"}:
                delta_state = self._states.setdefault(index, _AnthropicToolState())
                if index not in self._order:
                    self._order.append(index)
                partial = getattr(delta, "partial_json", "") or getattr(delta, "text", "")
                if partial is not None:
                    delta_state.raw += str(partial)
            return None

        if event_type == "content_block_stop":
            block = getattr(event, "content_block", None)
            stop_state = self._states.get(index)
            if stop_state is None and (self._states or block is not None):
                stop_state = self._states.setdefault(index, _AnthropicToolState())
                if index not in self._order:
                    self._order.append(index)
            if stop_state is not None and getattr(block, "type", "") == "tool_use":
                stop_state.id = getattr(block, "id", stop_state.id) or stop_state.id
                stop_state.name = getattr(block, "name", stop_state.name) or stop_state.name
                input_value = getattr(block, "input", None)
                if isinstance(input_value, dict):
                    stop_state.raw = json.dumps(input_value, ensure_ascii=False)
            if self._states:
                return self._tool_event()
        return None

    def _tool_event(self) -> StreamEvent:
        calls: list[ToolCall] = []
        for fallback_index, index in enumerate(self._order):
            state = self._states[index]
            raw_arguments = state.raw or "{}"
            try:
                arguments = json.loads(raw_arguments)
            except json.JSONDecodeError as exc:
                return StreamEvent(type=StreamEventType.ERROR, error=exc)
            if not isinstance(arguments, dict):
                return StreamEvent(
                    type=StreamEventType.ERROR,
                    error=ValueError("工具参数必须是 JSON object。"),
                )
            calls.append(
                ToolCall(
                    id=state.id or f"tool_use_{fallback_index}",
                    name=state.name,
                    arguments=arguments,
                    raw_arguments=raw_arguments,
                )
            )
        return StreamEvent(
            type=StreamEventType.TOOL_CALL,
            tool_call=calls[0] if calls else None,
            tool_calls=tuple(calls),
        )


def anthropic_message_from_item(item: ConversationItem) -> dict[str, Any]:
    if isinstance(item, ChatMessage):
        return {"role": item.role, "content": item.content}
    if isinstance(item, AssistantToolCallItem):
        return _assistant_tool_calls_message((item.call,))
    if isinstance(item, AssistantToolCallsItem):
        return _assistant_tool_calls_message(item.calls)
    if isinstance(item, ToolResultItem):
        result = item.result
        return {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": result.tool_call_id,
                    "content": json.dumps(tool_result_payload(result), ensure_ascii=False),
                    "is_error": not result.ok,
                }
            ],
        }
    raise TypeError(f"不支持的会话项：{type(item)!r}")


def _assistant_tool_calls_message(calls: Sequence[ToolCall]) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": [
            {
                "type": "tool_use",
                "id": call.id,
                "name": call.name,
                "input": call.arguments,
            }
            for call in calls
        ],
    }


def map_anthropic_event(event: Any) -> StreamEvent | None:
    event_type = getattr(event, "type", "")
    if event_type == "text":
        text = getattr(event, "text", "")
        return StreamEvent(type=StreamEventType.TEXT_DELTA, text=text) if text else None

    if event_type == "content_block_delta":
        delta = getattr(event, "delta", None)
        delta_type = getattr(delta, "type", "")
        if delta_type == "text_delta":
            text = getattr(delta, "text", "")
            return StreamEvent(type=StreamEventType.TEXT_DELTA, text=text) if text else None
        if "thinking" in delta_type:
            thinking = getattr(delta, "thinking", "") or getattr(delta, "text", "")
            return StreamEvent(type=StreamEventType.THINKING_DELTA, text=thinking)

    if "thinking" in event_type:
        thinking = getattr(event, "thinking", "") or getattr(event, "text", "")
        return StreamEvent(type=StreamEventType.THINKING_DELTA, text=thinking)

    return None


def anthropic_event_usage(event: Any) -> dict[str, int] | None:
    usage = getattr(event, "usage", None)
    if usage is None:
        delta = getattr(event, "delta", None)
        usage = getattr(delta, "usage", None)
    if usage is None:
        message = getattr(event, "message", None)
        usage = getattr(message, "usage", None)
    if usage is None:
        return None
    return {
        "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
        "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
        "cache_read": int(getattr(usage, "cache_read_input_tokens", 0) or 0),
        "cache_write": int(getattr(usage, "cache_creation_input_tokens", 0) or 0),
    }


def wrap_prompt_too_long(exc: Exception) -> Exception:
    if not is_prompt_too_long_error(exc):
        return exc
    wrapped = PromptTooLongError(str(exc) or "Prompt is too long.")
    wrapped.__cause__ = exc
    return wrapped


def is_prompt_too_long_error(exc: Exception) -> bool:
    error_type = str(getattr(exc, "type", "") or getattr(exc, "code", "")).casefold()
    message = str(exc).casefold()
    return any(
        marker in f"{error_type} {message}"
        for marker in (
            "prompt_too_long",
            "prompt is too long",
            "context length",
            "maximum context",
            "too many tokens",
        )
    )
