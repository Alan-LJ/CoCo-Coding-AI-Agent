from __future__ import annotations

import asyncio
from types import SimpleNamespace

from coco_code.config import ProviderConfig
from coco_code.llm import Message, StreamEvent
from coco_code.llm.anthropic_provider import AnthropicProvider, map_anthropic_event
from coco_code.llm.openai_provider import OpenAIProvider, openai_chunk_text
from coco_code.tui.stream import consume_provider_stream


def test_anthropic_text_event_maps_to_text_delta() -> None:
    event = SimpleNamespace(type="text", text="hello")
    assert map_anthropic_event(event) == StreamEvent(type="text_delta", text="hello")


def test_anthropic_thinking_delta_does_not_become_text() -> None:
    event = SimpleNamespace(
        type="content_block_delta",
        delta=SimpleNamespace(type="thinking_delta", thinking="hidden"),
    )
    assert map_anthropic_event(event) == StreamEvent(type="thinking_delta", text="hidden")


def test_anthropic_request_includes_system_and_thinking() -> None:
    cfg = ProviderConfig(
        name="Claude",
        protocol="anthropic",
        model="claude-test",
        thinking=True,
    )
    provider = AnthropicProvider(cfg, "secret", "system prompt", client=object())
    params = provider._request_params([Message(role="user", content="hi")])
    assert params["system"] == "system prompt"
    assert params["messages"] == [{"role": "user", "content": "hi"}]
    assert params["thinking"]["type"] == "enabled"


def test_openai_chunk_text_reads_delta_content() -> None:
    chunk = SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content="hello"))],
    )
    assert openai_chunk_text(chunk) == "hello"


def test_openai_chunk_text_ignores_empty_choices() -> None:
    assert openai_chunk_text(SimpleNamespace(choices=[])) == ""


def test_openai_request_starts_with_system_prompt() -> None:
    cfg = ProviderConfig(name="OpenAI", protocol="openai", model="gpt-test")
    provider = OpenAIProvider(cfg, "secret", "system prompt", client=object())
    assert provider._request_messages([Message(role="user", content="hi")]) == [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "hi"},
    ]


def test_consume_stream_discards_thinking_and_returns_text() -> None:
    class FakeProvider:
        name = "fake"
        model = "fake-model"
        protocol = "fake"

        async def stream(self, messages: list[Message]):  # noqa: ARG002
            yield StreamEvent(type="text_delta", text="A")
            yield StreamEvent(type="thinking_delta", text="hidden")
            yield StreamEvent(type="text_delta", text="B")
            yield StreamEvent(type="done")

    seen: list[str] = []

    async def on_text(text: str) -> None:
        seen.append(text)

    result = asyncio.run(consume_provider_stream(FakeProvider(), [], on_text))
    assert result.reply == "AB"
    assert seen == ["A", "B"]


def test_consume_stream_returns_partial_reply_on_error() -> None:
    class FakeProvider:
        name = "fake"
        model = "fake-model"
        protocol = "fake"

        async def stream(self, messages: list[Message]):  # noqa: ARG002
            yield StreamEvent(type="text_delta", text="partial")
            yield StreamEvent(type="error", error=RuntimeError("boom"))

    async def on_text(text: str) -> None:
        assert text == "partial"

    result = asyncio.run(consume_provider_stream(FakeProvider(), [], on_text))
    assert result.reply == "partial"
    assert isinstance(result.error, RuntimeError)
