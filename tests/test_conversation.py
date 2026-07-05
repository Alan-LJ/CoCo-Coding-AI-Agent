from __future__ import annotations

from coco_code.conversation import Conversation
from coco_code.llm import Message


def test_conversation_appends_messages_in_order() -> None:
    conversation = Conversation()
    conversation.add_user("你好")
    conversation.add_assistant("你好，我是 CoCo Code")
    assert conversation.messages() == [
        Message(role="user", content="你好"),
        Message(role="assistant", content="你好，我是 CoCo Code"),
    ]


def test_messages_returns_copy() -> None:
    conversation = Conversation()
    conversation.add_user("hello")
    messages = conversation.messages()
    messages.append(Message(role="assistant", content="changed"))
    assert len(conversation.messages()) == 1


def test_clear_removes_history() -> None:
    conversation = Conversation()
    conversation.add_user("hello")
    conversation.clear()
    assert conversation.messages() == []


def test_callbacks_fire_for_append_and_replace() -> None:
    appended = []
    replaced = []
    conversation = Conversation(
        on_append=appended.append, on_replace=lambda items: replaced.append(list(items))
    )
    conversation.add_user("hello")
    conversation.add_assistant("hi")
    conversation.replace_items(conversation.items())
    assert len(appended) == 2
    assert len(replaced) == 1


def test_from_items_initializes_without_callbacks_firing() -> None:
    appended = []
    original = Conversation()
    original.add_user("hello")
    restored = Conversation.from_items(original.items(), on_append=appended.append)
    assert restored.messages() == original.messages()
    assert appended == []
