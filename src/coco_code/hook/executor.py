from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from string import Formatter
from typing import Any

import httpx

from coco_code.hook.matcher import get_by_path
from coco_code.hook.rule import (
    HookRule,
    HttpAction,
    PromptAction,
    ShellAction,
    SubagentAction,
)


@dataclass
class ActionOutcome:
    blocked: bool = False
    reason: str = ""
    prompt: str = ""
    error: str | None = None


class HookExecutor:
    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        self._http_client = http_client or httpx.AsyncClient()

    async def run(
        self,
        rule: HookRule,
        payload: Mapping[str, Any],
        *,
        blocking: bool,
    ) -> ActionOutcome:
        action = rule.action.value
        if isinstance(action, ShellAction):
            return await self._run_shell(action, payload, blocking, rule.timeout_seconds)
        if isinstance(action, PromptAction):
            return ActionOutcome(prompt=action.text)
        if isinstance(action, HttpAction):
            return await self._run_http(action, payload, blocking, rule.timeout_seconds)
        if isinstance(action, SubagentAction):
            print(
                f"[hook subagent] not yet implemented, skipped: {action.agent_name}",
                file=sys.stderr,
            )
            return ActionOutcome()
        return ActionOutcome(error=f"unknown action type: {rule.action.type}")

    async def _run_shell(
        self,
        action: ShellAction,
        payload: Mapping[str, Any],
        blocking: bool,
        timeout: float,
    ) -> ActionOutcome:
        try:
            proc = await asyncio.create_subprocess_shell(
                action.command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(_payload_json(payload)), timeout=timeout
                )
            except TimeoutError as exc:
                proc.kill()
                await proc.wait()
                return ActionOutcome(error=f"timeout after {timeout:g}s: {exc}")
        except OSError as exc:
            return ActionOutcome(error=str(exc))

        stdout_text = stdout.decode(errors="replace").rstrip("\n")
        stderr_text = stderr.decode(errors="replace").rstrip("\n")
        if blocking and proc.returncode == 2:
            return ActionOutcome(blocked=True, reason=stderr_text or stdout_text)
        if proc.returncode == 0:
            return ActionOutcome()
        return ActionOutcome(error=f"exit {proc.returncode}: {stderr_text or stdout_text}")

    async def _run_http(
        self,
        action: HttpAction,
        payload: Mapping[str, Any],
        blocking: bool,
        timeout: float,
    ) -> ActionOutcome:
        try:
            body = (
                json.dumps(payload, sort_keys=True, ensure_ascii=False)
                if action.body is None
                else _format_body(action.body, payload)
            )
            response = await self._http_client.request(
                action.method or "POST",
                action.url,
                content=body,
                headers=dict(action.headers),
                timeout=timeout,
            )
        except (httpx.HTTPError, TimeoutError, KeyError, ValueError) as exc:
            return ActionOutcome(error=str(exc))

        if not 200 <= response.status_code < 300:
            return ActionOutcome(error=f"http {response.status_code}: {response.text}")
        if not blocking:
            return ActionOutcome()
        try:
            decoded = json.loads(response.text or "{}")
        except json.JSONDecodeError as exc:
            return ActionOutcome(error=str(exc))
        if isinstance(decoded, dict) and decoded.get("decision") == "block":
            reason = decoded.get("reason")
            return ActionOutcome(blocked=True, reason=str(reason or "blocked by hook"))
        return ActionOutcome()


class _PayloadFormatter(Formatter):
    def get_value(self, key: Any, args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
        if isinstance(key, str):
            return get_by_path(kwargs["payload"], key)
        return super().get_value(key, args, kwargs)


def _format_body(template: str, payload: Mapping[str, Any]) -> str:
    return _PayloadFormatter().format(template, payload=payload)


def _payload_json(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
