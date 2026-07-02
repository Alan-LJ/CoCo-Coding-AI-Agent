from __future__ import annotations

from types import SimpleNamespace

from coco_code.config import ProviderConfig
from coco_code.conversation import AssistantToolCallItem, ChatMessage, ToolResultItem
from coco_code.llm import StreamEventType
from coco_code.llm.anthropic_provider import AnthropicProvider, AnthropicToolAccumulator
from coco_code.llm.openai_provider import (
    OpenAIProvider,
    _accumulate_openai_tool_calls,
    _openai_tool_event,
)
from coco_code.tools import ToolCall, ToolResult, create_default_registry


def test_openai_request_includes_tools_and_tool_history() -> None:
    cfg = ProviderConfig(name="OpenAI", protocol="openai", model="gpt-test")
    provider = OpenAIProvider(cfg, "secret", "system", client=object())
    call = ToolCall("call-1", "ReadFile", {"path": "a.py"}, '{"path":"a.py"}')
    result = ToolResult("call-1", "ReadFile", True, "ok", {"content": "hello"}, None, 1)
    messages = provider._request_messages(
        [ChatMessage("user", "read"), AssistantToolCallItem(call), ToolResultItem(result)]
    )
    assert messages[1] == {"role": "user", "content": "read"}
    assert messages[2]["tool_calls"][0]["function"]["name"] == "ReadFile"
    assert messages[3]["role"] == "tool"
    assert messages[3]["tool_call_id"] == "call-1"
    assert create_default_registry().to_openai_tools()[0]["type"] == "function"


def test_openai_stream_accumulates_tool_call_fragments() -> None:
    accumulator: dict[int, dict[str, str]] = {}
    first = SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(
                    tool_calls=[
                        SimpleNamespace(
                            index=0,
                            id="call-1",
                            function=SimpleNamespace(name="ReadFile", arguments='{"pa'),
                        )
                    ]
                )
            )
        ]
    )
    second = SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(
                    tool_calls=[
                        SimpleNamespace(
                            index=0,
                            id=None,
                            function=SimpleNamespace(name=None, arguments='th":"a.py"}'),
                        )
                    ]
                )
            )
        ]
    )
    assert _accumulate_openai_tool_calls(first, accumulator) is True
    assert _accumulate_openai_tool_calls(second, accumulator) is True
    event = _openai_tool_event(accumulator)
    assert event.type == StreamEventType.TOOL_CALL
    assert event.tool_call == ToolCall("call-1", "ReadFile", {"path": "a.py"}, '{"path":"a.py"}')


def test_openai_invalid_tool_arguments_returns_error_event() -> None:
    event = _openai_tool_event({0: {"id": "call-1", "name": "ReadFile", "arguments": "{"}})
    assert event.type == StreamEventType.ERROR


def test_anthropic_request_includes_tools_and_tool_history() -> None:
    cfg = ProviderConfig(name="Claude", protocol="anthropic", model="claude-test")
    provider = AnthropicProvider(cfg, "secret", "system", client=object())
    call = ToolCall("call-1", "ReadFile", {"path": "a.py"}, '{"path":"a.py"}')
    result = ToolResult("call-1", "ReadFile", False, "failed", {}, "boom", 1)
    params = provider._request_params(
        [ChatMessage("user", "read"), AssistantToolCallItem(call), ToolResultItem(result)],
        create_default_registry(),
    )
    assert params["tools"][0]["input_schema"]["type"] == "object"
    assert params["messages"][1]["content"][0]["type"] == "tool_use"
    assert params["messages"][2]["content"][0]["type"] == "tool_result"
    assert params["messages"][2]["content"][0]["is_error"] is True


def test_anthropic_stream_accumulates_input_json_fragments() -> None:
    accumulator = AnthropicToolAccumulator()
    start = SimpleNamespace(
        type="content_block_start",
        content_block=SimpleNamespace(type="tool_use", id="tool-1", name="ReadFile", input={}),
    )
    delta_1 = SimpleNamespace(type="input_json", partial_json='{"path"', snapshot='{"path"')
    delta_2 = SimpleNamespace(
        type="input_json",
        partial_json=':"a.py"}',
        snapshot='{"path":"a.py"}',
    )
    stop = SimpleNamespace(
        type="content_block_stop",
        content_block=SimpleNamespace(type="tool_use"),
    )
    assert accumulator.process(start) is None
    assert accumulator.process(delta_1) is None
    assert accumulator.process(delta_2) is None
    event = accumulator.process(stop)
    assert event is not None
    assert event.type == StreamEventType.TOOL_CALL
    assert event.tool_call == ToolCall("tool-1", "ReadFile", {"path": "a.py"}, '{"path":"a.py"}')


def test_anthropic_invalid_tool_arguments_returns_error_event() -> None:
    accumulator = AnthropicToolAccumulator()
    accumulator.process(
        SimpleNamespace(
            type="content_block_start",
            content_block=SimpleNamespace(type="tool_use", id="tool-1", name="ReadFile", input={}),
        )
    )
    accumulator.process(SimpleNamespace(type="input_json", partial_json="{", snapshot="{"))
    event = accumulator.process(SimpleNamespace(type="content_block_stop", content_block=None))
    assert event is not None
    assert event.type == StreamEventType.ERROR


def test_openai_tool_event_returns_multiple_tool_calls_in_index_order() -> None:
    event = _openai_tool_event(
        {
            1: {"id": "call-2", "name": "Grep", "arguments": '{"pattern":"Agent"}'},
            0: {"id": "call-1", "name": "Glob", "arguments": '{"pattern":"*.py"}'},
        }
    )
    assert event.type == StreamEventType.TOOL_CALL
    assert [call.name for call in event.tool_calls] == ["Glob", "Grep"]
    assert event.tool_call == event.tool_calls[0]


def test_openai_request_replays_multiple_tool_calls_in_one_assistant_message() -> None:
    from coco_code.conversation import AssistantToolCallsItem

    cfg = ProviderConfig(name="OpenAI", protocol="openai", model="gpt-test")
    provider = OpenAIProvider(cfg, "secret", "system", client=object())
    first = ToolCall("call-1", "Glob", {"pattern": "*.py"}, '{"pattern":"*.py"}')
    second = ToolCall("call-2", "Grep", {"pattern": "Agent"}, '{"pattern":"Agent"}')
    messages = provider._request_messages(
        [ChatMessage("user", "inspect"), AssistantToolCallsItem((first, second))]
    )
    tool_calls = messages[2]["tool_calls"]
    assert [item["function"]["name"] for item in tool_calls] == ["Glob", "Grep"]


def test_anthropic_accumulator_returns_multiple_tool_calls() -> None:
    accumulator = AnthropicToolAccumulator()
    accumulator.process(
        SimpleNamespace(
            type="content_block_start",
            index=0,
            content_block=SimpleNamespace(type="tool_use", id="tool-1", name="Glob", input={}),
        )
    )
    accumulator.process(SimpleNamespace(type="input_json", index=0, snapshot='{"pattern":"*.py"}'))
    accumulator.process(SimpleNamespace(type="content_block_stop", index=0, content_block=None))
    accumulator.process(
        SimpleNamespace(
            type="content_block_start",
            index=1,
            content_block=SimpleNamespace(type="tool_use", id="tool-2", name="Grep", input={}),
        )
    )
    accumulator.process(SimpleNamespace(type="input_json", index=1, snapshot='{"pattern":"Agent"}'))
    event = accumulator.process(
        SimpleNamespace(type="content_block_stop", index=1, content_block=None)
    )
    assert event is not None
    assert [call.name for call in event.tool_calls] == ["Glob", "Grep"]


def test_anthropic_request_replays_multiple_tool_calls_in_one_assistant_message() -> None:
    from coco_code.conversation import AssistantToolCallsItem
    from coco_code.llm.anthropic_provider import anthropic_message_from_item

    first = ToolCall("call-1", "Glob", {"pattern": "*.py"}, "{}")
    second = ToolCall("call-2", "Grep", {"pattern": "Agent"}, "{}")
    message = anthropic_message_from_item(AssistantToolCallsItem((first, second)))
    assert [block["name"] for block in message["content"]] == ["Glob", "Grep"]
