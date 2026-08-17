
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from coco_code.conversation import (
    ConversationManager,
    Message,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
)


def _serialize_conversation(conv: ConversationManager) -> dict[str, Any]:
    messages: list[dict[str, Any]] = []
    for msg in conv.history:
        entry: dict[str, Any] = {"role": msg.role, "content": msg.content}
        if msg.tool_uses:
            entry["tool_uses"] = [
                {
                    "tool_use_id": tu.tool_use_id,
                    "tool_name": tu.tool_name,
                    "arguments": tu.arguments,
                }
                for tu in msg.tool_uses
            ]
        if msg.tool_results:
            entry["tool_results"] = [
                {
                    "tool_use_id": tr.tool_use_id,
                    "content": tr.content,
                    "is_error": tr.is_error,
                }
                for tr in msg.tool_results
            ]
        if msg.thinking_blocks:
            entry["thinking_blocks"] = [
                {
                    "thinking": block.thinking,
                    "signature": block.signature,
                }
                for block in msg.thinking_blocks
            ]
        messages.append(entry)
    return {
        "messages": messages,
        "env_injected": conv.env_injected,
        "ltm_injected": conv.ltm_injected,
        "last_input_tokens": conv.last_input_tokens,
        "baseline_tokens": conv.baseline_tokens,
        "anchor_count": conv.anchor_count,
    }


def _deserialize_conversation(
    data: list[dict[str, Any]] | dict[str, Any],
) -> ConversationManager:
    conv = ConversationManager()
    if isinstance(data, dict):
        messages = data.get("messages", [])
    else:
        messages = data
    for entry in messages:
        tool_uses = [
            ToolUseBlock(
                tool_use_id=tu["tool_use_id"],
                tool_name=tu["tool_name"],
                arguments=tu["arguments"],
            )
            for tu in entry.get("tool_uses", [])
        ]
        tool_results = [
            ToolResultBlock(
                tool_use_id=tr["tool_use_id"],
                content=tr["content"],
                is_error=tr.get("is_error", False),
            )
            for tr in entry.get("tool_results", [])
        ]
        thinking_blocks = [
            ThinkingBlock(
                thinking=block["thinking"],
                signature=block["signature"],
            )
            for block in entry.get("thinking_blocks", [])
        ]
        msg = Message(
            role=entry["role"],
            content=entry.get("content", ""),
            tool_uses=tool_uses,
            tool_results=tool_results,
            thinking_blocks=thinking_blocks,
        )
        conv.history.append(msg)
    if isinstance(data, dict):
        conv.env_injected = bool(data.get("env_injected", False))
        conv.ltm_injected = bool(data.get("ltm_injected", False))
        conv.last_input_tokens = int(data.get("last_input_tokens", 0) or 0)
        conv.baseline_tokens = int(data.get("baseline_tokens", 0) or 0)
        conv.anchor_count = int(data.get("anchor_count", 0) or 0)
    else:
        conv.env_injected = True
        conv.ltm_injected = True
    return conv


def save_transcript(
    team_name: str,
    agent_id: str,
    conversation: ConversationManager,
) -> Path:
    from coco_code.teams.models import resolve_team_dir

    transcript_dir = resolve_team_dir(team_name) / "transcripts"
    transcript_dir.mkdir(parents=True, exist_ok=True)
    path = transcript_dir / f"{agent_id}.json"
    data = _serialize_conversation(conversation)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_transcript(
    team_name: str,
    agent_id: str,
) -> ConversationManager | None:
    from coco_code.teams.models import resolve_team_dir

    path = resolve_team_dir(team_name) / "transcripts" / f"{agent_id}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return _deserialize_conversation(data)
