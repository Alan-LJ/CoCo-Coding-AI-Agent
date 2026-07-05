from __future__ import annotations

import asyncio
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from threading import Lock
from time import monotonic
from typing import Any, Protocol, TextIO

from mcp.types import TextContent

from coco_code.tools.base import (
    ConfirmationPolicy,
    ToolCategory,
    ToolContext,
    ToolParams,
    ToolResult,
    ToolSpec,
)

CALL_TIMEOUT_SECONDS = 30.0
OUTER_EXECUTOR_TIMEOUT_SECONDS = 31.0
TOOL_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")

_warned_non_text: set[str] = set()
_warn_lock = Lock()


class McpCaller(Protocol):
    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any: ...


@dataclass
class McpTool:
    full_name: str
    server_name: str
    remote_name: str
    description: str
    parameters_schema: dict[str, Any]
    read_only: bool
    caller: McpCaller
    stderr: TextIO = sys.stderr

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.full_name,
            description=self.description,
            parameters_schema=self.parameters_schema,
            confirmation=(
                ConfirmationPolicy.NEVER if self.read_only else ConfirmationPolicy.REQUIRED
            ),
            category=ToolCategory.GENERAL,
            read_only=self.read_only,
            destructive=False,
            typical_scenarios=(f"MCP server: {self.server_name}",),
            timeout_seconds=OUTER_EXECUTOR_TIMEOUT_SECONDS,
        )

    async def run(self, params: ToolParams, context: ToolContext) -> ToolResult:  # noqa: ARG002
        started = monotonic()
        try:
            async with asyncio.timeout(CALL_TIMEOUT_SECONDS):
                result = await self.caller.call_tool(self.remote_name, params or None)
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            return self._error_result(
                "MCP tool call timed out after 30s.",
                started,
                data={"timeout": True},
            )
        except Exception as exc:
            return self._error_result(f"MCP tool call failed: {exc}", started)

        text, non_text_count = _collect_text(result)
        if non_text_count:
            await _warn_non_text_once(self.full_name, non_text_count, self.stderr)
        is_error = bool(_get_attr(result, "is_error", "isError", default=False))
        if is_error:
            message = text or "MCP tool returned an error."
            return self._error_result(message, started, data={"content": text})
        return ToolResult(
            tool_call_id="",
            tool_name=self.full_name,
            ok=True,
            summary=_summary(text),
            data={"content": text},
            error=None,
            elapsed_ms=_elapsed_ms(started),
        )

    def _error_result(
        self,
        message: str,
        started: float,
        *,
        data: dict[str, Any] | None = None,
    ) -> ToolResult:
        return ToolResult(
            tool_call_id="",
            tool_name=self.full_name,
            ok=False,
            summary=message,
            data=data or {},
            error=message,
            elapsed_ms=_elapsed_ms(started),
        )


def adapt_tool(
    server_name: str,
    remote_tool: Any,
    caller: McpCaller,
    *,
    stderr: TextIO = sys.stderr,
) -> McpTool | None:
    remote_name = str(_get_attr(remote_tool, "name", default="") or "")
    if not remote_name:
        print(f"[mcp] warn: skip tool from server {server_name}: missing name", file=stderr)
        return None
    full_name = tool_full_name(server_name, remote_name)
    if not TOOL_NAME_RE.fullmatch(full_name):
        print(f"[mcp] warn: skip tool {full_name}: name contains illegal characters", file=stderr)
        return None
    description = str(_get_attr(remote_tool, "description", default="") or "")
    if not description:
        description = f"MCP tool {remote_name} from server {server_name}"
    return McpTool(
        full_name=full_name,
        server_name=server_name,
        remote_name=remote_name,
        description=description,
        parameters_schema=normalize_input_schema(
            _get_attr(remote_tool, "input_schema", "inputSchema", default=None)
        ),
        read_only=remote_read_only(remote_tool),
        caller=caller,
        stderr=stderr,
    )


def tool_full_name(server_name: str, remote_name: str) -> str:
    return f"mcp__{server_name}__{remote_name}"


def normalize_input_schema(raw_schema: Any) -> dict[str, Any]:
    if isinstance(raw_schema, dict):
        return dict(raw_schema) or {"type": "object", "properties": {}}
    if hasattr(raw_schema, "model_dump"):
        dumped = raw_schema.model_dump(by_alias=True, exclude_none=True)
        if isinstance(dumped, dict):
            return dumped or {"type": "object", "properties": {}}
    if isinstance(raw_schema, Mapping):
        return dict(raw_schema) or {"type": "object", "properties": {}}
    return {"type": "object", "properties": {}}


def remote_read_only(remote_tool: Any) -> bool:
    annotations = _get_attr(remote_tool, "annotations", default=None)
    if annotations is None:
        return False
    if isinstance(annotations, dict):
        return annotations.get("readOnlyHint") is True or annotations.get("read_only_hint") is True
    return bool(_get_attr(annotations, "read_only_hint", "readOnlyHint", default=False) is True)


def _collect_text(result: Any) -> tuple[str, int]:
    texts: list[str] = []
    non_text_count = 0
    for block in getattr(result, "content", []) or []:
        if isinstance(block, TextContent):
            texts.append(block.text)
            continue
        block_type = _get_attr(block, "type", default=None)
        text = _get_attr(block, "text", default=None)
        if block_type == "text" and isinstance(text, str):
            texts.append(text)
            continue
        non_text_count += 1
    return "\n".join(texts), non_text_count


async def _warn_non_text_once(full_name: str, count: int, stderr: TextIO) -> None:
    with _warn_lock:
        if full_name in _warned_non_text:
            return
        _warned_non_text.add(full_name)
    plural = "block" if count == 1 else "blocks"
    print(
        f"[mcp] warn: tool {full_name} returned {count} non-text content {plural}; dropped",
        file=stderr,
    )


def _get_attr(obj: Any, *names: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        for name in names:
            if name in obj:
                return obj[name]
        return default
    for name in names:
        if hasattr(obj, name):
            return getattr(obj, name)
    return default


def _summary(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return "MCP tool completed."
    first_line = stripped.splitlines()[0]
    if len(first_line) > 160:
        return first_line[:157] + "..."
    return first_line


def _elapsed_ms(started: float) -> int:
    return int((monotonic() - started) * 1000)
