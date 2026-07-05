from __future__ import annotations

import json
import re
from dataclasses import asdict
from pathlib import Path

from coco_code.compact.constants import (
    BATCH_RESULT_LIMIT_BYTES,
    PREVIEW_HEAD_BYTES,
    PREVIEW_HEAD_LINES,
    SINGLE_RESULT_LIMIT_BYTES,
)
from coco_code.compact.state import (
    ContentReplacementState,
    ReplacementDecision,
    SessionContext,
)
from coco_code.compact.token import item_bytes
from coco_code.conversation import (
    AssistantToolCallItem,
    AssistantToolCallsItem,
    ConversationItem,
    ToolResultItem,
)
from coco_code.tools.base import ToolResult


async def offload_and_snip(
    items: list[ConversationItem],
    state: ContentReplacementState,
    session: SessionContext,
) -> tuple[list[ConversationItem], int]:
    new_items = list(items)
    offloaded = 0
    for batch in _tool_result_batches(new_items):
        offloaded += await _process_single_limit(new_items, batch, state, session)
        offloaded += await _process_batch_limit(new_items, batch, state, session)
    return new_items, offloaded


def tool_result_payload_bytes(result: ToolResult) -> int:
    return len(_serialize_result(result).encode("utf-8"))


async def spill_single(session: SessionContext, result: ToolResult) -> Path:
    session.spill_dir.mkdir(parents=True, exist_ok=True)
    path = session.spill_dir / _safe_tool_filename(result.tool_call_id)
    if path.exists():
        return path
    path.write_text(_serialize_result(result), encoding="utf-8")
    return path


def build_preview_result(
    original: ToolResult,
    original_bytes: int,
    spill_path: Path,
) -> ToolResult:
    preview = _head_preview(_serialize_result(original))
    path_text = str(spill_path)
    summary = (
        f"Tool result offloaded; original size: {original_bytes} bytes; "
        f"[saved to] {path_text}. Use 文件读取工具 to inspect details; "
        "不要凭头部预览猜测完整代码或输出。"
    )
    return ToolResult(
        tool_call_id=original.tool_call_id,
        tool_name=original.tool_name,
        ok=original.ok,
        summary=summary,
        data={
            "offloaded": True,
            "path": path_text,
            "original_bytes": original_bytes,
            "head preview": preview,
            "read_hint": "需要细节时使用文件读取工具重新读取；不要凭头部预览猜测。",
        },
        error=original.error,
        elapsed_ms=original.elapsed_ms,
        truncated=True,
    )


async def _process_single_limit(
    items: list[ConversationItem],
    batch: list[int],
    state: ContentReplacementState,
    session: SessionContext,
) -> int:
    offloaded = 0
    for index in batch:
        result = _result_at(items, index)
        if tool_result_payload_bytes(result) <= SINGLE_RESULT_LIMIT_BYTES:
            continue
        replacement = await _replace_result(items, index, state, session)
        if replacement:
            offloaded += 1
    return offloaded


async def _process_batch_limit(
    items: list[ConversationItem],
    batch: list[int],
    state: ContentReplacementState,
    session: SessionContext,
) -> int:
    offloaded = 0
    while _batch_bytes(items, batch) > BATCH_RESULT_LIMIT_BYTES:
        candidates = sorted(
            batch,
            key=lambda index: tool_result_payload_bytes(_result_at(items, index)),
            reverse=True,
        )
        changed = False
        for index in candidates:
            result = _result_at(items, index)
            if result.truncated and result.data.get("offloaded") is True:
                continue
            if await _replace_result(items, index, state, session):
                offloaded += 1
                changed = True
                break
        if not changed:
            break
    return offloaded


async def _replace_result(
    items: list[ConversationItem],
    index: int,
    state: ContentReplacementState,
    session: SessionContext,
) -> bool:
    original = _result_at(items, index)

    async def decide() -> ReplacementDecision:
        try:
            original_bytes = tool_result_payload_bytes(original)
            spill_path = await spill_single(session, original)
            preview = build_preview_result(original, original_bytes, spill_path)
        except OSError:
            return ReplacementDecision(kind="skip")
        return ReplacementDecision(kind="replaced", result=preview)

    replacement = await state.decide_once(original.tool_call_id, original, decide)
    if replacement is original:
        return False
    items[index] = ToolResultItem(result=replacement)
    return True


def _tool_result_batches(items: list[ConversationItem]) -> list[list[int]]:
    batches: list[list[int]] = []
    expected: set[str] = set()
    current: list[int] = []
    for index, item in enumerate(items):
        if isinstance(item, AssistantToolCallItem):
            if current:
                batches.append(current)
            expected = {item.call.id}
            current = []
            continue
        if isinstance(item, AssistantToolCallsItem):
            if current:
                batches.append(current)
            expected = {call.id for call in item.calls}
            current = []
            continue
        if isinstance(item, ToolResultItem) and item.result.tool_call_id in expected:
            current.append(index)
            continue
        if current:
            batches.append(current)
        expected = set()
        current = []
    if current:
        batches.append(current)
    return batches


def _batch_bytes(items: list[ConversationItem], batch: list[int]) -> int:
    return sum(item_bytes(items[index]) for index in batch)


def _result_at(items: list[ConversationItem], index: int) -> ToolResult:
    item = items[index]
    if not isinstance(item, ToolResultItem):
        raise TypeError("expected ToolResultItem")
    return item.result


def _serialize_result(result: ToolResult) -> str:
    return json.dumps(asdict(result), ensure_ascii=False, sort_keys=True, indent=2)


def _head_preview(text: str) -> str:
    lines = text.splitlines()[:PREVIEW_HEAD_LINES]
    preview = "\n".join(lines)
    data = preview.encode("utf-8")
    if len(data) <= PREVIEW_HEAD_BYTES:
        return preview
    return data[:PREVIEW_HEAD_BYTES].decode("utf-8", errors="ignore")


def _safe_tool_filename(tool_call_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", tool_call_id).strip("._")
    return safe or "tool-result"
