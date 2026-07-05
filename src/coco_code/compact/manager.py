from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from coco_code.compact.constants import (
    AUTO_SAFETY_MARGIN_TOKENS,
    MANUAL_SAFETY_MARGIN_TOKENS,
    SUMMARY_RESERVE_TOKENS,
)
from coco_code.compact.layer1 import offload_and_snip
from coco_code.compact.layer2 import auto_compact, force_compact
from coco_code.compact.token import estimate_tokens
from coco_code.conversation import Conversation
from coco_code.llm import Provider
from coco_code.tools.registry import ToolRegistry


class TriggerKind(StrEnum):
    AUTO = "auto"
    MANUAL = "manual"
    EMERGENCY = "emergency"


@dataclass
class ManageInput:
    conversation: Conversation
    provider: Provider
    tools: ToolRegistry
    runtime: Any
    trigger: TriggerKind
    estimated_tokens: int


@dataclass(frozen=True)
class ManageOutput:
    before_tokens: int
    after_tokens: int
    offloaded_results: int = 0
    compacted: bool = False


async def manage_context(input: ManageInput) -> ManageOutput:
    before = input.estimated_tokens
    offloaded = 0
    if input.trigger == TriggerKind.MANUAL:
        compacted_items = await force_compact(input)
        input.conversation.replace_items(compacted_items)
        return _output(input, before, offloaded, compacted=True)

    if input.trigger == TriggerKind.EMERGENCY:
        items, offloaded = await offload_and_snip(
            input.conversation.items(),
            input.runtime.replacement,
            input.runtime.session,
        )
        input.conversation.replace_items(items)
        compacted_items = await force_compact(input)
        input.conversation.replace_items(compacted_items)
        return _output(input, before, offloaded, compacted=True)

    items, offloaded = await offload_and_snip(
        input.conversation.items(),
        input.runtime.replacement,
        input.runtime.session,
    )
    input.conversation.replace_items(items)
    after_layer1 = _estimate(input)
    if after_layer1 < auto_threshold(input.runtime.context_window):
        return _output(input, before, offloaded, compacted=False)
    if await input.runtime.circuit_breaker.tripped():
        return _output(input, before, offloaded, compacted=False)
    compacted_items = await auto_compact(input)
    input.conversation.replace_items(compacted_items)
    return _output(input, before, offloaded, compacted=True)


def auto_threshold(context_window: int) -> int:
    return int(context_window) - SUMMARY_RESERVE_TOKENS - AUTO_SAFETY_MARGIN_TOKENS


def manual_threshold(context_window: int) -> int:
    return int(context_window) - SUMMARY_RESERVE_TOKENS - MANUAL_SAFETY_MARGIN_TOKENS


def _output(
    input: ManageInput,
    before: int,
    offloaded: int,
    *,
    compacted: bool,
) -> ManageOutput:
    return ManageOutput(
        before_tokens=before,
        after_tokens=_estimate(input),
        offloaded_results=offloaded,
        compacted=compacted,
    )


def _estimate(input: ManageInput) -> int:
    return estimate_tokens(
        input.runtime.usage_anchor,
        input.conversation.items(),
        input.runtime.anchor_item_len,
    )
