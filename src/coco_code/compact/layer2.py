from __future__ import annotations

import math
from typing import TYPE_CHECKING

from coco_code.compact.constants import (
    PTL_DROP_PERCENTAGE,
    PTL_RETRY_LIMIT,
    RECENT_KEEP_ITEMS,
    RECENT_KEEP_TOKENS,
)
from coco_code.compact.recovery import build_recovery_attachment
from coco_code.compact.summary_prompt import (
    build_summary_prompt,
    extract_summary,
    validate_summary,
)
from coco_code.compact.token import conversation_bytes
from coco_code.conversation import (
    ChatMessage,
    ConversationItem,
    ToolResultItem,
)
from coco_code.llm import PromptTooLongError, Provider, StreamEventType

if TYPE_CHECKING:
    from coco_code.compact.manager import ManageInput


class CompactError(RuntimeError):
    pass


async def auto_compact(input: ManageInput) -> list[ConversationItem]:
    try:
        items = await run_summary(input)
    except Exception:
        await input.runtime.circuit_breaker.record_failure()
        raise
    await input.runtime.circuit_breaker.record_success()
    return items


async def force_compact(input: ManageInput) -> list[ConversationItem]:
    return await run_summary(input)


async def run_summary(input: ManageInput) -> list[ConversationItem]:
    items = input.conversation.items()
    tail = pick_recent_tail(items)
    older_count = max(0, len(items) - len(tail))
    summary_source = items[:older_count] or items
    summary = await ptl_retry(input.provider, summary_source)
    recovery = await build_recovery_attachment(input.runtime.recovery, input.tools)
    merged = ChatMessage(role="user", content=f"{summary}\n\n{recovery}")
    new_items: list[ConversationItem] = [merged]
    if tail and isinstance(tail[0], ChatMessage) and tail[0].role == "user":
        new_items.append(
            ChatMessage(role="assistant", content="我会基于压缩摘要和近期原文继续推进。")
        )
    new_items.extend(tail)
    return new_items


async def summarize_once(provider: Provider, items: list[ConversationItem]) -> str:
    text_parts: list[str] = []
    async for event in provider.stream(build_summary_prompt(items), tools=None):
        if event.type == StreamEventType.TEXT_DELTA or event.type == "text_delta":
            text_parts.append(event.text)
        elif event.type == StreamEventType.TOOL_CALL or event.type == "tool_call":
            raise CompactError("Summary provider attempted to call a tool.")
        elif event.type == StreamEventType.ERROR or event.type == "error":
            if event.error is not None:
                raise event.error
            raise CompactError("Summary provider returned an unknown error.")
        elif event.type == StreamEventType.DONE or event.type == "done":
            break
    summary = extract_summary("".join(text_parts))
    if not validate_summary(summary):
        raise CompactError("Summary is empty or missing required sections.")
    return summary


async def ptl_retry(provider: Provider, items: list[ConversationItem]) -> str:
    groups = group_by_user_turn(items)
    if not groups:
        groups = [items]
    remaining = [group for group in groups if group]
    attempt = 0
    last_error: PromptTooLongError | None = None
    while remaining:
        try:
            return await summarize_once(provider, _flatten(remaining))
        except PromptTooLongError as exc:
            last_error = exc
            attempt += 1
            drop = (
                1
                if attempt <= PTL_RETRY_LIMIT
                else max(1, math.ceil(len(remaining) * PTL_DROP_PERCENTAGE))
            )
            remaining = remaining[min(drop, len(remaining)) :]
    if last_error is not None:
        raise last_error
    raise CompactError("No conversation items remain for summary.")


def pick_recent_tail(items: list[ConversationItem]) -> list[ConversationItem]:
    if not items:
        return []
    total_bytes = 0
    start = len(items)
    while start > 0 and (
        len(items) - start < RECENT_KEEP_ITEMS or total_bytes / 3.5 < RECENT_KEEP_TOKENS
    ):
        start -= 1
        total_bytes += conversation_bytes([items[start]])
    start = _expand_start_to_tool_boundary(items, start)
    return list(items[start:])


def group_by_user_turn(items: list[ConversationItem]) -> list[list[ConversationItem]]:
    groups: list[list[ConversationItem]] = []
    current: list[ConversationItem] = []
    for item in items:
        if isinstance(item, ChatMessage) and item.role == "user" and current:
            groups.append(current)
            current = [item]
        else:
            current.append(item)
    if current:
        groups.append(current)
    return groups


def _expand_start_to_tool_boundary(items: list[ConversationItem], start: int) -> int:
    while start > 0 and isinstance(items[start], ToolResultItem):
        start -= 1
    return start


def _flatten(groups: list[list[ConversationItem]]) -> list[ConversationItem]:
    return [item for group in groups for item in group]
