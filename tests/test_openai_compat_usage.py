from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from coco_code.client import OpenAICompatClient
from coco_code.config import ProviderConfig
from coco_code.conversation import ConversationManager
from coco_code.tools.base import StreamEnd


class _FakeCompletions:
    def __init__(self, chunks: list[Any]) -> None:
        self.chunks = chunks
        self.kwargs: dict[str, Any] = {}

    async def create(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs

        async def stream() -> Any:
            for chunk in self.chunks:
                yield chunk

        return stream()


def _choice_chunk(text: str, finish_reason: str = "stop") -> Any:
    delta = SimpleNamespace(content=text, tool_calls=None)
    choice = SimpleNamespace(delta=delta, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice], usage=None)


def _usage_chunk(prompt: int, completion: int, cached: int = 0) -> Any:
    details = SimpleNamespace(cached_tokens=cached)
    usage = SimpleNamespace(
        prompt_tokens=prompt,
        completion_tokens=completion,
        prompt_tokens_details=details,
    )
    return SimpleNamespace(choices=[], usage=usage)


def _client(chunks: list[Any]) -> OpenAICompatClient:
    config = ProviderConfig(
        name="test",
        protocol="openai-compat",
        base_url="https://example.invalid/v1",
        model="test-model",
        api_key="test-key",
    )
    client = OpenAICompatClient(config)
    completions = _FakeCompletions(chunks)
    client._client = SimpleNamespace(
        chat=SimpleNamespace(completions=completions)
    )
    return client


@pytest.mark.asyncio
async def test_openai_compat_uses_provider_usage_when_present() -> None:
    client = _client([_choice_chunk("done"), _usage_chunk(100, 25, cached=20)])
    conversation = ConversationManager()
    conversation.add_user_message("fix the bug")

    events = [event async for event in client.stream(conversation)]
    ends = [event for event in events if isinstance(event, StreamEnd)]

    assert len(ends) == 1
    assert ends[0].input_tokens == 80
    assert ends[0].cache_read == 20
    assert ends[0].output_tokens == 25
    assert ends[0].usage_is_estimated is False


@pytest.mark.asyncio
async def test_openai_compat_estimates_usage_when_provider_omits_it() -> None:
    client = _client([_choice_chunk("finished response")])
    conversation = ConversationManager()
    conversation.add_user_message("fix the parser and run its tests")

    events = [event async for event in client.stream(conversation)]
    ends = [event for event in events if isinstance(event, StreamEnd)]

    assert len(ends) == 1
    assert ends[0].stop_reason == "end_turn"
    assert ends[0].input_tokens > 0
    assert ends[0].output_tokens > 0
    assert ends[0].usage_is_estimated is True


@pytest.mark.asyncio
async def test_openai_compat_preserves_length_stop_reason_without_usage() -> None:
    client = _client([_choice_chunk("partial", finish_reason="length")])
    conversation = ConversationManager()
    conversation.add_user_message("write a long answer")

    events = [event async for event in client.stream(conversation)]
    end = next(event for event in events if isinstance(event, StreamEnd))

    assert end.stop_reason == "max_tokens"
    assert end.usage_is_estimated is True
