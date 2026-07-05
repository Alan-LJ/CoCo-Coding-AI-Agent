from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Sequence
from typing import Any, cast

from coco_code.config import ProviderConfig
from coco_code.conversation import (
    AssistantToolCallItem,
    AssistantToolCallsItem,
    ChatMessage,
    ConversationItem,
    ToolResultItem,
)
from coco_code.llm import PromptTooLongError, StreamEvent, StreamEventType
from coco_code.tools.base import ToolCall, ToolResult
from coco_code.tools.registry import ToolRegistry


class _BaseOpenAIProvider:
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
            from openai import AsyncOpenAI

            kwargs: dict[str, Any] = {"api_key": api_key}
            if cfg.base_url:
                kwargs["base_url"] = cfg.base_url
            client = AsyncOpenAI(**kwargs)
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
            create = cast(Any, self._client.chat.completions.create)
            kwargs: dict[str, Any] = {
                "model": self._cfg.model,
                "messages": self._request_messages(messages),
                "stream": True,
                "stream_options": {"include_usage": True},
            }
            if tools is not None:
                kwargs["tools"] = tools.to_openai_tools()
            stream = await create(**kwargs)
            accumulator: dict[int, dict[str, str]] = {}
            for_pending_tool = False
            async for chunk in stream:
                usage = openai_chunk_usage(chunk)
                if usage is not None:
                    yield StreamEvent(type="usage", usage=usage)
                text = openai_chunk_text(chunk)
                if text:
                    yield StreamEvent(type=StreamEventType.TEXT_DELTA, text=text)
                if _accumulate_openai_tool_calls(chunk, accumulator):
                    for_pending_tool = True
                if openai_finish_reason(chunk) == "tool_calls":
                    yield _openai_tool_calls_event(accumulator)
                    return
            if for_pending_tool:
                yield _openai_tool_calls_event(accumulator)
                return
            yield StreamEvent(type=StreamEventType.DONE)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            yield StreamEvent(type=StreamEventType.ERROR, error=wrap_prompt_too_long(exc))

    def _request_messages(self, messages: list[ConversationItem]) -> list[Any]:
        return [{"role": "system", "content": self._system_prompt}] + [
            openai_message_from_item(item) for item in messages
        ]


class OpenAIProvider(_BaseOpenAIProvider):
    pass


class OpenAICompatProvider(_BaseOpenAIProvider):
    pass


def openai_message_from_item(item: ConversationItem) -> dict[str, Any]:
    if isinstance(item, ChatMessage):
        return {"role": item.role, "content": item.content}
    if isinstance(item, AssistantToolCallItem):
        return _assistant_tool_calls_message((item.call,))
    if isinstance(item, AssistantToolCallsItem):
        return _assistant_tool_calls_message(item.calls)
    if isinstance(item, ToolResultItem):
        return {
            "role": "tool",
            "tool_call_id": item.result.tool_call_id,
            "content": json.dumps(tool_result_payload(item.result), ensure_ascii=False),
        }
    raise TypeError(f"不支持的会话项：{type(item)!r}")


def _assistant_tool_calls_message(calls: Sequence[ToolCall]) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": call.raw_arguments
                    or json.dumps(call.arguments, ensure_ascii=False),
                },
            }
            for call in calls
        ],
    }


def tool_result_payload(result: ToolResult) -> dict[str, Any]:
    return {
        "ok": result.ok,
        "tool_name": result.tool_name,
        "summary": result.summary,
        "data": result.data,
        "error": result.error,
        "elapsed_ms": result.elapsed_ms,
        "truncated": result.truncated,
    }


def openai_chunk_text(chunk: Any) -> str:
    choices = getattr(chunk, "choices", None)
    if not choices:
        return ""
    delta = getattr(choices[0], "delta", None)
    content = getattr(delta, "content", "")
    return content or ""


def openai_chunk_usage(chunk: Any) -> dict[str, int] | None:
    usage = getattr(chunk, "usage", None)
    if usage is None:
        return None
    return {
        "input_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
        "output_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
        "cache_read": _nested_usage_int(usage, "prompt_tokens_details", "cached_tokens"),
        "cache_write": 0,
    }


def openai_finish_reason(chunk: Any) -> str | None:
    choices = getattr(chunk, "choices", None)
    if not choices:
        return None
    return getattr(choices[0], "finish_reason", None)


def wrap_prompt_too_long(exc: Exception) -> Exception:
    if not is_prompt_too_long_error(exc):
        return exc
    wrapped = PromptTooLongError(str(exc) or "Prompt is too long.")
    wrapped.__cause__ = exc
    return wrapped


def is_prompt_too_long_error(exc: Exception) -> bool:
    code = str(getattr(exc, "code", "") or getattr(exc, "type", "")).casefold()
    message = str(exc).casefold()
    return any(
        marker in f"{code} {message}"
        for marker in (
            "context_length_exceeded",
            "prompt_too_long",
            "prompt is too long",
            "context length",
            "maximum context",
            "too many tokens",
        )
    )


def _nested_usage_int(usage: Any, attr: str, nested: str) -> int:
    details = getattr(usage, attr, None)
    if details is None:
        return 0
    if isinstance(details, dict):
        return int(details.get(nested, 0) or 0)
    return int(getattr(details, nested, 0) or 0)


def _accumulate_openai_tool_calls(chunk: Any, accumulator: dict[int, dict[str, str]]) -> bool:
    choices = getattr(chunk, "choices", None)
    if not choices:
        return False
    delta = getattr(choices[0], "delta", None)
    tool_calls = getattr(delta, "tool_calls", None) or []
    changed = False
    for fallback_index, tool_call in enumerate(tool_calls):
        index = getattr(tool_call, "index", fallback_index)
        state = accumulator.setdefault(index, {"id": "", "name": "", "arguments": ""})
        tool_id = getattr(tool_call, "id", None)
        if tool_id:
            state["id"] = tool_id
        function = getattr(tool_call, "function", None)
        if function is not None:
            name = getattr(function, "name", None)
            arguments = getattr(function, "arguments", None)
            if name:
                state["name"] = name
            if arguments:
                state["arguments"] += arguments
        changed = True
    return changed


def _openai_tool_event(accumulator: dict[int, dict[str, str]]) -> StreamEvent:
    return _openai_tool_calls_event(accumulator)


def _openai_tool_calls_event(accumulator: dict[int, dict[str, str]]) -> StreamEvent:
    if not accumulator:
        return StreamEvent(type=StreamEventType.ERROR, error=ValueError("OpenAI 工具调用为空。"))
    calls: list[ToolCall] = []
    for index in sorted(accumulator):
        state = accumulator[index]
        raw_arguments = state.get("arguments", "") or "{}"
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
                id=state.get("id") or f"tool_call_{index}",
                name=state.get("name") or "",
                arguments=arguments,
                raw_arguments=raw_arguments,
            )
        )
    return StreamEvent(
        type=StreamEventType.TOOL_CALL,
        tool_call=calls[0],
        tool_calls=tuple(calls),
    )
