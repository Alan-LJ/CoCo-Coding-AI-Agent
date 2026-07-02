from __future__ import annotations

import asyncio
from dataclasses import replace
from time import monotonic
from typing import Any

from coco_code.tools.base import (
    ConfirmationPolicy,
    ConfirmCallback,
    ToolCall,
    ToolContext,
    ToolResult,
    ToolSpec,
)
from coco_code.tools.registry import ToolRegistry, ToolRegistryError


class ToolExecutionError(RuntimeError):
    pass


class ToolExecutor:
    def __init__(
        self,
        registry: ToolRegistry,
        context: ToolContext,
        confirm: ConfirmCallback,
    ) -> None:
        self._registry = registry
        self._context = context
        self._confirm = confirm

    async def execute(self, call: ToolCall) -> ToolResult:
        started = monotonic()
        try:
            tool = self._registry.get(call.name)
            spec = tool.spec
        except ToolRegistryError as exc:
            return error_result(call, str(exc), _elapsed_ms(started))

        validation_error = validate_tool_params(call.arguments, spec)
        if validation_error is not None:
            return error_result(call, validation_error, _elapsed_ms(started))

        if spec.confirmation == ConfirmationPolicy.REQUIRED:
            try:
                approved = await asyncio.wait_for(
                    self._confirm(call, spec),
                    timeout=self._context.confirm_timeout_seconds,
                )
            except asyncio.CancelledError:
                raise
            except TimeoutError:
                return error_result(call, "工具确认超时，已取消执行。", _elapsed_ms(started))
            except Exception as exc:
                return error_result(call, f"工具确认失败：{exc}", _elapsed_ms(started))
            if not approved:
                return rejected_result(call, spec, _elapsed_ms(started))

        try:
            result = await asyncio.wait_for(
                tool.run(call.arguments, self._context),
                timeout=self._context.timeout_seconds,
            )
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            return error_result(call, "工具执行超时。", _elapsed_ms(started))
        except Exception as exc:
            return error_result(call, str(exc), _elapsed_ms(started))
        return replace(result, tool_call_id=call.id)


def validate_tool_params(arguments: dict[str, Any], spec: ToolSpec) -> str | None:
    schema = spec.parameters_schema
    required = set(schema.get("required", []))
    missing = sorted(required - arguments.keys())
    if missing:
        return f"工具参数缺少必填字段：{', '.join(missing)}。"

    properties = schema.get("properties", {})
    if schema.get("additionalProperties") is False:
        extra = sorted(set(arguments) - set(properties))
        if extra:
            return f"工具参数包含未知字段：{', '.join(extra)}。"

    for name, value in arguments.items():
        expected = properties.get(name, {}).get("type")
        if expected is None:
            continue
        if expected == "string" and not isinstance(value, str):
            return f"工具参数 `{name}` 必须是字符串。"
        if expected == "boolean" and not isinstance(value, bool):
            return f"工具参数 `{name}` 必须是布尔值。"
        if expected == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
            return f"工具参数 `{name}` 必须是整数。"
        if expected == "number" and (
            not isinstance(value, int | float) or isinstance(value, bool)
        ):
            return f"工具参数 `{name}` 必须是数字。"
    return None


def rejected_result(call: ToolCall, spec: ToolSpec, elapsed_ms: int = 0) -> ToolResult:
    return ToolResult(
        tool_call_id=call.id,
        tool_name=spec.name,
        ok=False,
        summary="用户拒绝执行该工具。",
        data={"rejected": True},
        error="用户拒绝执行。",
        elapsed_ms=elapsed_ms,
    )


def error_result(call: ToolCall, message: str, elapsed_ms: int = 0) -> ToolResult:
    return ToolResult(
        tool_call_id=call.id,
        tool_name=call.name,
        ok=False,
        summary=message,
        data={},
        error=message,
        elapsed_ms=elapsed_ms,
    )


def _elapsed_ms(started: float) -> int:
    return int((monotonic() - started) * 1000)