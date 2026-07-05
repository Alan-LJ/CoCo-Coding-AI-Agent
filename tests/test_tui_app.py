from __future__ import annotations

import asyncio
from pathlib import Path

from coco_code.config import Config, ProviderConfig
from coco_code.tui.app import CoCoCodeApp, PromptTextArea, SessionState


def test_single_provider_app_mounts_headless() -> None:
    async def run() -> None:
        provider = ProviderConfig(
            name="Fake OpenAI",
            protocol="openai",
            model="fake-model",
            api_key="secret-key",
        )
        app = CoCoCodeApp(Config(providers=[provider]), cwd=Path("P:/AI/CoCo Code_Agent"))
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.state == SessionState.IDLE
            assert app.active_cfg == provider
            assert app.query_one("#input", PromptTextArea).disabled is False

    asyncio.run(run())


def test_multi_provider_selection_mounts_headless() -> None:
    async def run() -> None:
        providers = [
            ProviderConfig(
                name="Fake Claude",
                protocol="anthropic",
                model="claude-fake",
                api_key="secret-key",
            ),
            ProviderConfig(
                name="Fake OpenAI",
                protocol="openai",
                model="openai-fake",
                api_key="secret-key",
            ),
        ]
        app = CoCoCodeApp(Config(providers=providers), cwd=Path("P:/AI/CoCo Code_Agent"))
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.state == SessionState.SELECTING
            assert app.query_one("#input", PromptTextArea).disabled is True
            await pilot.press("enter")
            await pilot.pause()
            assert app.state == SessionState.IDLE
            assert app.active_cfg in providers
            assert app.query_one("#input", PromptTextArea).disabled is False

    asyncio.run(run())


def test_parse_agent_request_modes() -> None:
    from coco_code.agent import AgentMode
    from coco_code.tui.app import parse_agent_request

    assert parse_agent_request("hello").mode == AgentMode.AGENT
    plan = parse_agent_request("/plan inspect")
    assert plan.mode == AgentMode.PLAN
    assert plan.text == "inspect"
    do = parse_agent_request("/do execute")
    assert do.mode == AgentMode.DO
    assert do.text == "execute"


def test_slash_help_and_unknown_do_not_add_conversation(tmp_path: Path) -> None:
    from coco_code.tui.commands import dispatch_command

    async def run() -> None:
        provider = ProviderConfig(
            name="Fake OpenAI",
            protocol="openai",
            model="fake-model",
            api_key="secret-key",
        )
        app = CoCoCodeApp(Config(providers=[provider]), cwd=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert await dispatch_command(app, "/help") is True
            assert await dispatch_command(app, "/foobar") is True
            assert app.conversation.items() == []

    asyncio.run(run())


def test_slash_plan_without_args_is_local(tmp_path: Path) -> None:
    from coco_code.agent import AgentMode
    from coco_code.permission import Mode as PermissionMode
    from coco_code.tui.commands import dispatch_command

    async def run() -> None:
        provider = ProviderConfig(
            name="Fake OpenAI",
            protocol="openai",
            model="fake-model",
            api_key="secret-key",
        )
        app = CoCoCodeApp(Config(providers=[provider]), cwd=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert await dispatch_command(app, "/PLAN") is True
            assert app.agent_mode == AgentMode.PLAN
            assert app.permission_mode == PermissionMode.PLAN
            assert app.conversation.items() == []

    asyncio.run(run())


def test_slash_review_sends_preset_prompt(tmp_path: Path) -> None:
    from coco_code.llm import StreamEvent, StreamEventType
    from coco_code.tui.commands import dispatch_command

    class FakeProvider:
        name = "fake"
        model = "fake-model"
        protocol = "openai"

        def __init__(self) -> None:
            self.calls = 0
            self.messages_seen = []

        async def stream(self, messages, tools=None):  # noqa: ARG002
            self.calls += 1
            self.messages_seen.append(messages)
            yield StreamEvent(type=StreamEventType.DONE)

    async def wait_until_idle(app: CoCoCodeApp) -> None:
        for _ in range(50):
            await asyncio.sleep(0.02)
            if app.state == SessionState.IDLE:
                return
        raise AssertionError("app did not return to idle")

    async def run() -> None:
        provider = ProviderConfig(
            name="Fake OpenAI",
            protocol="openai",
            model="fake-model",
            api_key="secret-key",
        )
        fake = FakeProvider()
        app = CoCoCodeApp(Config(providers=[provider]), cwd=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.provider = fake
            assert await dispatch_command(app, "/review") is True
            await wait_until_idle(app)
            assert fake.calls == 1
            first_message = fake.messages_seen[0][0]
            assert first_message.role == "user"
            assert "/review" not in first_message.content
            assert "review" in first_message.content.lower()

    asyncio.run(run())
