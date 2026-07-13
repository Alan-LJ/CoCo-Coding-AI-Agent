from __future__ import annotations

from coco_code.agent.fork import (
    FORK_BOILERPLATE_TAG,
    build_forked_messages,
    is_fork_context,
)
from coco_code.conversation import (
    AssistantToolCallItem,
    ChatMessage,
    ToolResultItem,
)
from coco_code.tools.base import ToolCall, ToolResult


def test_build_forked_messages_from_empty_parent() -> None:
    items = build_forked_messages([], "read README")

    assert len(items) == 1
    assert isinstance(items[0], ChatMessage)
    assert items[0].role == "user"
    assert FORK_BOILERPLATE_TAG in items[0].content
    assert "read README" in items[0].content


def test_build_forked_messages_preserves_parent_messages() -> None:
    parent = [ChatMessage(role="user", content="parent")]

    items = build_forked_messages(parent, "task")

    assert items[0] == parent[0]
    assert isinstance(items[-1], ChatMessage)
    assert "task" in items[-1].content


def test_build_forked_messages_adds_placeholder_for_dangling_tool_call() -> None:
    call = ToolCall("call-1", "Agent", {"prompt": "fork"}, "{}")
    parent = [AssistantToolCallItem(call)]

    items = build_forked_messages(parent, "task")

    assert isinstance(items[1], ToolResultItem)
    assert items[1].result.tool_call_id == "call-1"
    assert items[1].result.error == "[forked, skipped]"


def test_build_forked_messages_does_not_duplicate_completed_tool_result() -> None:
    call = ToolCall("call-1", "ReadFile", {"path": "a.txt"}, "{}")
    result = ToolResult("call-1", "ReadFile", True, "ok", {}, None, 0)
    parent = [AssistantToolCallItem(call), ToolResultItem(result)]

    items = build_forked_messages(parent, "task")

    assert sum(isinstance(item, ToolResultItem) for item in items) == 1


def test_is_fork_context() -> None:
    assert is_fork_context(build_forked_messages([], "task")) is True
    assert is_fork_context([ChatMessage(role="user", content="plain")]) is False
