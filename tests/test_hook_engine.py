from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from coco_code.hook.engine import HookEngine
from coco_code.hook.event import Event
from coco_code.hook.executor import ActionOutcome
from coco_code.hook.rule import (
    AtomCondition,
    Condition,
    HookAction,
    HookRule,
    PromptAction,
    ShellAction,
)
from coco_code.permission.matcher import compile_matcher


@dataclass
class Runtime:
    fired_hooks: set[str] = field(default_factory=set)
    tasks: list[asyncio.Task] = field(default_factory=list)

    def track_hook_task(self, task: asyncio.Task) -> None:
        self.tasks.append(task)


class FakeExecutor:
    def __init__(self, outcomes: list[ActionOutcome]) -> None:
        self.outcomes = outcomes
        self.calls: list[str] = []

    async def run(self, rule, payload, *, blocking):
        self.calls.append(rule.name)
        return self.outcomes.pop(0)


def rule(name: str, event: Event, *, only_once=False, async_mode=False, condition=None):
    return HookRule(
        name=name,
        event=event,
        action=HookAction(type="shell", value=ShellAction(command="echo x")),
        condition=condition,
        only_once=only_once,
        async_mode=async_mode,
    )


def test_dispatch_runs_rules_in_order() -> None:
    async def run() -> None:
        executor = FakeExecutor([ActionOutcome(), ActionOutcome()])
        engine = HookEngine(
            [rule("a", Event.STOP), rule("b", Event.STOP)], [], executor=executor
        )
        await engine.dispatch(Event.STOP, {})
        assert executor.calls == ["a", "b"]

    asyncio.run(run())


def test_dispatch_blocking_stops_after_block() -> None:
    async def run() -> None:
        executor = FakeExecutor([ActionOutcome(blocked=True, reason="no"), ActionOutcome()])
        engine = HookEngine(
            [rule("a", Event.PRE_TOOL_USE), rule("b", Event.PRE_TOOL_USE)],
            [],
            executor=executor,
        )
        result = await engine.dispatch(Event.PRE_TOOL_USE, {})
        assert result.blocked is True
        assert result.reason == "no"
        assert result.blocking_hook_name == "a"
        assert executor.calls == ["a"]

    asyncio.run(run())


def test_dispatch_non_blocking_ignores_blocked_outcome() -> None:
    async def run() -> None:
        executor = FakeExecutor([ActionOutcome(blocked=True, reason="no")])
        engine = HookEngine([rule("a", Event.STOP)], [], executor=executor)
        result = await engine.dispatch(Event.STOP, {})
        assert result.blocked is False

    asyncio.run(run())


def test_dispatch_collects_prompt_actions() -> None:
    async def run() -> None:
        executor = FakeExecutor([ActionOutcome(prompt="one"), ActionOutcome(prompt="two")])
        rules = [
            HookRule("a", Event.SESSION_START, HookAction("prompt", PromptAction("one"))),
            HookRule("b", Event.SESSION_START, HookAction("prompt", PromptAction("two"))),
        ]
        engine = HookEngine(rules, [], executor=executor)
        result = await engine.dispatch(Event.SESSION_START, {})
        assert result.injected_prompts == ["one", "two"]

    asyncio.run(run())


def test_only_once_uses_runtime_state_and_can_reset() -> None:
    async def run() -> None:
        runtime = Runtime()
        executor = FakeExecutor([ActionOutcome(), ActionOutcome()])
        engine = HookEngine([rule("once", Event.STOP, only_once=True)], [], executor=executor)
        await engine.dispatch(Event.STOP, {}, runtime)
        await engine.dispatch(Event.STOP, {}, runtime)
        assert executor.calls == ["once"]
        runtime.fired_hooks.clear()
        await engine.dispatch(Event.STOP, {}, runtime)
        assert executor.calls == ["once", "once"]

    asyncio.run(run())


def test_async_rule_is_tracked_and_not_blocking() -> None:
    async def run() -> None:
        runtime = Runtime()
        executor = FakeExecutor([ActionOutcome(blocked=True, reason="no")])
        engine = HookEngine(
            [rule("async", Event.STOP, async_mode=True)], [], executor=executor
        )
        result = await engine.dispatch(Event.STOP, {}, runtime)
        assert result.blocked is False
        assert len(runtime.tasks) == 1
        await runtime.tasks[0]

    asyncio.run(run())


def test_condition_filters_rules() -> None:
    async def run() -> None:
        condition = Condition(
            mode="all_of",
            atoms=(AtomCondition("tool_name", compile_matcher("=WriteFile")),),
        )
        executor = FakeExecutor([ActionOutcome()])
        engine = HookEngine(
            [rule("filtered", Event.PRE_TOOL_USE, condition=condition)], [], executor=executor
        )
        await engine.dispatch(Event.PRE_TOOL_USE, {"tool_name": "Bash"})
        await engine.dispatch(Event.PRE_TOOL_USE, {"tool_name": "WriteFile"})
        assert executor.calls == ["filtered"]

    asyncio.run(run())
