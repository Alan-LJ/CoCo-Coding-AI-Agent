from __future__ import annotations

from coco_code.conversation import AssistantToolCallItem, Conversation, ToolResultItem
from coco_code.llm import Message
from coco_code.tools import ToolCall, ToolResult


def test_conversation_stores_tool_call_and_result_items() -> None:
    conversation = Conversation()
    call = ToolCall("call-1", "ReadFile", {"path": "README.md"}, '{"path":"README.md"}')
    result = ToolResult("call-1", "ReadFile", True, "ok", {"content": "hi"}, None, 3)
    conversation.add_user("read")
    conversation.add_tool_call(call)
    conversation.add_tool_result(result)
    conversation.add_assistant("done")
    items = conversation.items()
    assert items[0] == Message(role="user", content="read")
    assert items[1] == AssistantToolCallItem(call)
    assert items[2] == ToolResultItem(result)
    assert items[3] == Message(role="assistant", content="done")


def test_messages_filters_tool_items_for_backward_compatibility() -> None:
    conversation = Conversation()
    conversation.add_user("read")
    conversation.add_tool_call(ToolCall("call-1", "ReadFile", {}, "{}"))
    conversation.add_tool_result(ToolResult("call-1", "ReadFile", True, "ok", {}, None, 0))
    conversation.add_assistant("done")
    assert conversation.messages() == [
        Message(role="user", content="read"),
        Message(role="assistant", content="done"),
    ]


def test_conversation_stores_multiple_tool_calls_as_one_item() -> None:
    from coco_code.conversation import AssistantToolCallsItem

    conversation = Conversation()
    first = ToolCall("call-1", "Glob", {"pattern": "*.py"}, "{}")
    second = ToolCall("call-2", "Grep", {"pattern": "Agent"}, "{}")
    conversation.add_user("inspect")
    conversation.add_tool_calls([first, second])
    items = conversation.items()
    assert isinstance(items[1], AssistantToolCallsItem)
    assert items[1].calls == (first, second)
    assert conversation.messages() == [Message(role="user", content="inspect")]
