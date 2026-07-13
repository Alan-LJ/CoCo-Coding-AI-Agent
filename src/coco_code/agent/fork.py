from __future__ import annotations

from collections.abc import Sequence

from coco_code.conversation import (
    AssistantToolCallItem,
    AssistantToolCallsItem,
    ChatMessage,
    ConversationItem,
    ToolResultItem,
)
from coco_code.tools.base import ToolCall, ToolResult

FORK_BOILERPLATE_TAG = "<fork_boilerplate>"

FORK_BOILERPLATE = (
    f"{FORK_BOILERPLATE_TAG}\n"
    "You are running as a forked CoCo Code SubAgent. You have inherited the "
    "parent conversation for context, but your runtime state is isolated from "
    "the parent. Complete the delegated task autonomously and return a concise "
    "final result for the parent Agent.\n"
    "</fork_boilerplate>"
)


def fork_prompt(task_text: str) -> str:
    return f"{FORK_BOILERPLATE}\n\nDelegated task:\n{task_text.strip()}"


def build_forked_messages(
    parent_msgs: Sequence[ConversationItem],
    task: str,
) -> list[ConversationItem]:
    items = list(parent_msgs)
    items.extend(_dangling_tool_results(items))
    items.append(ChatMessage(role="user", content=fork_prompt(task)))
    return items


build_forked_items = build_forked_messages


def is_fork_context(items: Sequence[ConversationItem]) -> bool:
    return any(
        isinstance(item, ChatMessage) and FORK_BOILERPLATE_TAG in item.content
        for item in items
    )


def _dangling_tool_results(items: Sequence[ConversationItem]) -> list[ToolResultItem]:
    calls: dict[str, ToolCall] = {}
    results: set[str] = set()
    for item in items:
        if isinstance(item, AssistantToolCallItem):
            calls[item.call.id] = item.call
        elif isinstance(item, AssistantToolCallsItem):
            for call in item.calls:
                calls[call.id] = call
        elif isinstance(item, ToolResultItem):
            results.add(item.result.tool_call_id)
    dangling = [call for call_id, call in calls.items() if call_id not in results]
    return [
        ToolResultItem(
            ToolResult(
                tool_call_id=call.id,
                tool_name=call.name,
                ok=False,
                summary="[forked, skipped]",
                data={"forked": True, "skipped": True},
                error="[forked, skipped]",
                elapsed_ms=0,
            )
        )
        for call in dangling
    ]
