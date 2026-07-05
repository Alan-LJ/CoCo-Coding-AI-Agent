from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import replace
from time import monotonic
from typing import Any

from coco_code.permission import Decision, Mode, Outcome
from coco_code.permission.engine import Engine
from coco_code.tools.base import (
    ConfirmationPolicy,
    ConfirmCallback,
    ToolCall,
    ToolContext,
    ToolResult,
    ToolSpec,
)
from coco_code.tools.registry import ToolRegistry, ToolRegistryError

PermissionCallback = Callable[[ToolCall, ToolSpec, str], Awaitable[Outcome]]


class ToolExecutionError(RuntimeError):
    pass


class ToolExecutor:
    def __init__(
        self,
        registry: ToolRegistry,
        context: ToolContext,
        confirm: ConfirmCallback,
        permission_engine: Engine | None = None,
        permission_confirm: PermissionCallback | None = None,
        default_permission_mode: Mode = Mode.DEFAULT,
    ) -> None:
        self._registry = registry
        self._context = context
        self._confirm = confirm
        self._permission_engine = permission_engine
        self._permission_confirm = permission_confirm
        self._default_permission_mode = default_permission_mode

    async def execute(self, call: ToolCall, permission_mode: Mode | None = None) -> ToolResult:
        started = monotonic()
        try:
            tool = self._registry.get(call.name)
            spec = tool.spec
        except ToolRegistryError as exc:
            return error_result(call, str(exc), _elapsed_ms(started))

        validation_error = validate_tool_params(call.arguments, spec)
        if validation_error is not None:
            return error_result(call, validation_error, _elapsed_ms(started))

        if self._permission_engine is not None:
            permission_result = await self._check_permission(
                call,
                spec,
                permission_mode or self._default_permission_mode,
                started,
            )
            if permission_result is not None:
                return permission_result
        elif spec.confirmation == ConfirmationPolicy.REQUIRED:
            confirmation_result = await self._check_legacy_confirmation(call, spec, started)
            if confirmation_result is not None:
                return confirmation_result

        try:
            timeout = spec.timeout_seconds or self._context.timeout_seconds
            result = await asyncio.wait_for(
                tool.run(call.arguments, self._context),
                timeout=timeout,
            )
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            return error_result(call, "Tool execution timed out.", _elapsed_ms(started))
        except Exception as exc:
            return error_result(call, str(exc), _elapsed_ms(started))
        return replace(result, tool_call_id=call.id)

    async def _check_permission(
        self,
        call: ToolCall,
        spec: ToolSpec,
        mode: Mode,
        started: float,
    ) -> ToolResult | None:
        assert self._permission_engine is not None
        decision, reason = self._permission_engine.check(mode, call, spec)
        if decision == Decision.ALLOW:
            return None
        if decision == Decision.DENY:
            return permission_denied_result(call, spec, reason, _elapsed_ms(started))

        try:
            outcome = await asyncio.wait_for(
                self._request_permission(call, spec, reason),
                timeout=self._context.confirm_timeout_seconds,
            )
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            return error_result(
                call,
                "Permission confirmation timed out; tool execution was cancelled.",
                _elapsed_ms(started),
            )
        except Exception as exc:
            return error_result(
                call, f"Permission confirmation failed: {exc}", _elapsed_ms(started)
            )

        if outcome == Outcome.DENY_ONCE:
            return rejected_result(call, spec, _elapsed_ms(started))
        if outcome == Outcome.ALLOW_FOREVER:
            with suppress(Exception):
                self._permission_engine.persist_local_allow(call)
        return None

    async def _request_permission(
        self,
        call: ToolCall,
        spec: ToolSpec,
        reason: str,
    ) -> Outcome:
        if self._permission_confirm is not None:
            return await self._permission_confirm(call, spec, reason)
        approved = await self._confirm(call, spec)
        return Outcome.ALLOW_ONCE if approved else Outcome.DENY_ONCE

    async def _check_legacy_confirmation(
        self,
        call: ToolCall,
        spec: ToolSpec,
        started: float,
    ) -> ToolResult | None:
        try:
            approved = await asyncio.wait_for(
                self._confirm(call, spec),
                timeout=self._context.confirm_timeout_seconds,
            )
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            return error_result(
                call,
                "Tool confirmation timed out; execution was cancelled.",
                _elapsed_ms(started),
            )
        except Exception as exc:
            return error_result(call, f"Tool confirmation failed: {exc}", _elapsed_ms(started))
        if not approved:
            return rejected_result(call, spec, _elapsed_ms(started))
        return None


def validate_tool_params(arguments: dict[str, Any], spec: ToolSpec) -> str | None:
    schema = spec.parameters_schema
    required = set(schema.get("required", []))
    missing = sorted(required - arguments.keys())
    if missing:
        return f"Tool parameters missing required fields: {', '.join(missing)}."

    properties = schema.get("properties", {})
    if schema.get("additionalProperties") is False:
        extra = sorted(set(arguments) - set(properties))
        if extra:
            return f"Tool parameters contain unknown fields: {', '.join(extra)}."

    for name, value in arguments.items():
        expected = properties.get(name, {}).get("type")
        if expected is None:
            continue
        if expected == "string" and not isinstance(value, str):
            return f"Tool parameter `{name}` must be a string."
        if expected == "boolean" and not isinstance(value, bool):
            return f"Tool parameter `{name}` must be a boolean."
        if expected == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
            return f"Tool parameter `{name}` must be an integer."
        if expected == "number" and (not isinstance(value, int | float) or isinstance(value, bool)):
            return f"Tool parameter `{name}` must be a number."
    return None


def rejected_result(call: ToolCall, spec: ToolSpec, elapsed_ms: int = 0) -> ToolResult:
    return ToolResult(
        tool_call_id=call.id,
        tool_name=spec.name,
        ok=False,
        summary="User rejected this tool call.",
        data={"rejected": True},
        error="User rejected tool execution.",
        elapsed_ms=elapsed_ms,
    )


def permission_denied_result(
    call: ToolCall,
    spec: ToolSpec,
    reason: str,
    elapsed_ms: int = 0,
) -> ToolResult:
    return ToolResult(
        tool_call_id=call.id,
        tool_name=spec.name,
        ok=False,
        summary=reason,
        data={"permission_denied": True},
        error=reason,
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
