from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from coco_code.compact.constants import (
    ESTIMATE_CHARS_PER_TOKEN,
    RECOVERY_FILE_LIMIT,
    RECOVERY_TOKENS_PER_FILE,
)
from coco_code.tools.base import ToolSpec
from coco_code.tools.registry import ToolRegistry

BOUNDARY_NOTICE = (
    "边界提示：早期详细消息和工具输出已经被压缩。摘要只用于定位和保持连续性；"
    "需要文件、命令输出或工具结果细节时，必须重新读取摘要中列出的本地文件或项目文件，"
    "不要根据摘要脑补代码、数据或完整输出。"
)


@dataclass(frozen=True)
class FileReadRecord:
    path: str
    content: str
    timestamp: datetime


class RecoveryState:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._files: dict[str, FileReadRecord] = {}
        self._order: dict[str, int] = {}
        self._next_order = 0

    async def record_file(self, path: str | Path, content: str) -> None:
        key = str(Path(path).resolve(strict=False))
        async with self._lock:
            self._next_order += 1
            self._order[key] = self._next_order
            self._files[key] = FileReadRecord(
                path=key,
                content=content,
                timestamp=datetime.now(UTC),
            )

    async def snapshot(self) -> list[FileReadRecord]:
        async with self._lock:
            return sorted(
                list(self._files.values()),
                key=lambda record: (record.timestamp, self._order.get(record.path, 0)),
                reverse=True,
            )


async def build_recovery_attachment(
    recovery: RecoveryState,
    tools: ToolRegistry,
) -> str:
    records = await recovery.snapshot()
    file_blocks = "\n\n".join(render_file_block(record) for record in records[:RECOVERY_FILE_LIMIT])
    if not file_blocks:
        file_blocks = "无。"
    return (
        "## 最近读过的文件\n"
        f"{file_blocks}\n\n"
        "## 当前可用工具\n"
        f"{render_tools_block(tools.list_specs())}\n\n"
        "## 边界提示\n"
        f"{BOUNDARY_NOTICE}"
    )


def render_file_block(record: FileReadRecord) -> str:
    content = record.content
    char_limit = int(RECOVERY_TOKENS_PER_FILE * ESTIMATE_CHARS_PER_TOKEN)
    truncated = len(content) > char_limit
    if truncated:
        content = content[:char_limit] + "\n(content truncated)"
    return f"### {record.path}\n{content}"


def render_tools_block(specs: list[ToolSpec]) -> str:
    if not specs:
        return "无。"
    lines: list[str] = []
    for spec in specs:
        schema = json.dumps(spec.parameters_schema, ensure_ascii=False, sort_keys=True)
        lines.append(f"- {spec.name}: {spec.description}; input_schema={schema}")
    return "\n".join(lines)
