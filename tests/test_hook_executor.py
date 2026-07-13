from __future__ import annotations

import sys

from coco_code.hook.event import Event
from coco_code.hook.executor import HookExecutor
from coco_code.hook.rule import (
    HookAction,
    HookRule,
    HttpAction,
    PromptAction,
    ShellAction,
    SubagentAction,
)


def make_rule(action) -> HookRule:
    return HookRule(
        name="test",
        event=Event.PRE_TOOL_USE,
        action=HookAction(type=_action_type(action), value=action),
        timeout_seconds=1.0,
    )


def _action_type(action):
    if isinstance(action, ShellAction):
        return "shell"
    if isinstance(action, PromptAction):
        return "prompt"
    if isinstance(action, HttpAction):
        return "http"
    return "subagent"


async def run_action(action, payload=None, *, blocking=True):
    return await HookExecutor().run(
        make_rule(action),
        payload or {"event": "PreToolUse"},
        blocking=blocking,
    )


def py_command(code: str) -> str:
    return f'"{sys.executable}" -c "{code}"'


def test_run_shell_exit_2_blocks() -> None:
    async def run() -> None:
        outcome = await run_action(
            ShellAction(
                command=py_command("import sys; sys.stderr.write('blocked'); sys.exit(2)")
            )
        )
        assert outcome.blocked is True
        assert outcome.reason == "blocked"

    import asyncio

    asyncio.run(run())


def test_run_shell_exit_0_allows() -> None:
    async def run() -> None:
        outcome = await run_action(ShellAction(command=py_command("raise SystemExit(0)")))
        assert outcome.blocked is False
        assert outcome.error is None

    import asyncio

    asyncio.run(run())


def test_run_shell_exit_1_is_error_not_block() -> None:
    async def run() -> None:
        outcome = await run_action(
            ShellAction(command=py_command("import sys; sys.stderr.write('nope'); sys.exit(1)"))
        )
        assert outcome.blocked is False
        assert outcome.error is not None
        assert "exit 1" in outcome.error

    import asyncio

    asyncio.run(run())


def test_run_shell_stdin_payload_is_sorted_json() -> None:
    async def run() -> None:
        outcome = await run_action(
            ShellAction(
                command=py_command(
                    "import sys; "
                    "data=sys.stdin.read(); "
                    "sys.stdout.write(data); "
                    "sys.exit(2)"
                )
            ),
            {"z": 1, "a": 2},
        )
        assert outcome.reason == '{"a": 2, "z": 1}'

    import asyncio

    asyncio.run(run())


def test_run_shell_timeout_is_error() -> None:
    async def run() -> None:
        executor = HookExecutor()
        rule = make_rule(ShellAction(command=py_command("import time; time.sleep(2)")))
        rule = HookRule(
            name=rule.name,
            event=rule.event,
            action=rule.action,
            timeout_seconds=0.1,
        )
        outcome = await executor.run(rule, {}, blocking=True)
        assert outcome.error is not None
        assert "timeout" in outcome.error

    import asyncio

    asyncio.run(run())


def test_run_prompt_returns_prompt() -> None:
    async def run() -> None:
        outcome = await run_action(PromptAction(text="remember this"))
        assert outcome.prompt == "remember this"

    import asyncio

    asyncio.run(run())


class FakeResponse:
    def __init__(self, status_code: int, text: str) -> None:
        self.status_code = status_code
        self.text = text


class FakeHttpClient:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.requests = []

    async def request(self, method, url, *, content, headers, timeout):
        self.requests.append((method, url, content, headers, timeout))
        return self.response


def test_run_http_blocks_on_decision_block() -> None:
    async def run() -> None:
        client = FakeHttpClient(FakeResponse(200, '{"decision":"block","reason":"x"}'))
        executor = HookExecutor(http_client=client)
        outcome = await executor.run(
            make_rule(HttpAction(url="http://example.test/check")),
            {"event": "PreToolUse"},
            blocking=True,
        )
        assert outcome.blocked is True
        assert outcome.reason == "x"

    import asyncio

    asyncio.run(run())


def test_run_http_5xx_is_error() -> None:
    async def run() -> None:
        client = FakeHttpClient(FakeResponse(500, "boom"))
        executor = HookExecutor(http_client=client)
        outcome = await executor.run(
            make_rule(HttpAction(url="http://example.test/check")),
            {},
            blocking=True,
        )
        assert outcome.error is not None
        assert "http 500" in outcome.error

    import asyncio

    asyncio.run(run())


def test_run_http_body_template() -> None:
    async def run() -> None:
        client = FakeHttpClient(FakeResponse(200, "{}"))
        executor = HookExecutor(http_client=client)
        outcome = await executor.run(
            make_rule(HttpAction(url="http://example.test/check", body="event={event}")),
            {"event": "Stop"},
            blocking=False,
        )
        assert outcome.error is None
        assert client.requests[0][2] == "event=Stop"

    import asyncio

    asyncio.run(run())


def test_run_subagent_logs_placeholder(capsys) -> None:
    async def run() -> None:
        outcome = await run_action(SubagentAction(agent_name="foo", prompt="test"))
        assert outcome.error is None

    import asyncio

    asyncio.run(run())
    assert "not yet implemented" in capsys.readouterr().err
