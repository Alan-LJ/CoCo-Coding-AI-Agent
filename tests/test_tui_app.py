from __future__ import annotations

import asyncio
from contextlib import suppress
from pathlib import Path

from coco_code.config import Config, ProviderConfig
from coco_code.llm import StreamEvent, StreamEventType
from coco_code.tools import ConfirmationPolicy, ToolCall, ToolSpec
from coco_code.tui.app import CoCoCodeApp, ConfirmToolScreen, PromptTextArea, SessionState
from coco_code.tui.resume import ResumeSessionScreen


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


def test_startup_resume_new_session_does_not_trigger_provider_selection(tmp_path: Path) -> None:
    async def run() -> None:
        session_dir = tmp_path / ".mewcode" / "sessions" / "20260705-120000-abcd"
        session_dir.mkdir(parents=True)
        (session_dir / "conversation.jsonl").write_text(
            '{"role":"user","content":"old session","ts":1,"model":"m"}\n',
            encoding="utf-8",
        )
        provider = ProviderConfig(
            name="Fake OpenAI",
            protocol="openai",
            model="fake-model",
            api_key="secret-key",
        )
        app = CoCoCodeApp(Config(providers=[provider]), cwd=tmp_path)
        async with app.run_test() as pilot:
            for _ in range(50):
                await pilot.pause(0.02)
                if isinstance(app.screen, ResumeSessionScreen):
                    break
            assert isinstance(app.screen, ResumeSessionScreen)

            await pilot.press("enter")
            await pilot.pause()

            assert app.state == SessionState.IDLE
            assert app.active_cfg == provider
            assert app.query_one("#input", PromptTextArea).disabled is False

    asyncio.run(run())


def test_escape_closes_idle_prompt(tmp_path: Path) -> None:
    async def run() -> None:
        provider = ProviderConfig(
            name="Fake OpenAI",
            protocol="openai",
            model="fake-model",
            api_key="secret-key",
        )
        app = CoCoCodeApp(Config(providers=[provider]), cwd=tmp_path, show_startup_resume=False)
        quit_requested = False

        def fake_request_quit(*, force: bool = False) -> None:  # noqa: FBT001, FBT002
            nonlocal quit_requested
            assert force is False
            quit_requested = True

        app.request_quit = fake_request_quit  # type: ignore[method-assign]
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.state == SessionState.IDLE

            await pilot.press("escape")
            await pilot.pause()

            assert quit_requested is True

    asyncio.run(run())


def test_ctrl_c_requires_second_press_to_close_idle_prompt(tmp_path: Path) -> None:
    async def run() -> None:
        provider = ProviderConfig(
            name="Fake OpenAI",
            protocol="openai",
            model="fake-model",
            api_key="secret-key",
        )
        app = CoCoCodeApp(Config(providers=[provider]), cwd=tmp_path, show_startup_resume=False)
        quit_requested = False

        def fake_request_quit(*, force: bool = False) -> None:  # noqa: FBT001, FBT002
            nonlocal quit_requested
            assert force is True
            quit_requested = True

        app.request_quit = fake_request_quit  # type: ignore[method-assign]
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.state == SessionState.IDLE

            await pilot.press("ctrl+c")
            await pilot.pause(0.1)

            assert quit_requested is False
            assert app.state == SessionState.IDLE
            assert app.query_one("#input", PromptTextArea).disabled is False

            await pilot.press("ctrl+c")
            await pilot.pause()

            assert quit_requested is True

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


class CancelAwareProvider:
    name = "fake"
    model = "fake-model"
    protocol = "openai"

    def __init__(self) -> None:
        self.calls = 0
        self.cancelled = False

    async def stream(self, messages, tools=None):  # noqa: ARG002
        self.calls += 1
        try:
            yield StreamEvent(type=StreamEventType.TEXT_DELTA, text="partial")
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            self.cancelled = True
            raise


class QuickProvider:
    name = "fake"
    model = "fake-model"
    protocol = "openai"

    def __init__(self) -> None:
        self.calls = 0

    async def stream(self, messages, tools=None):  # noqa: ARG002
        self.calls += 1
        yield StreamEvent(type=StreamEventType.TEXT_DELTA, text="ok")
        yield StreamEvent(type=StreamEventType.DONE)


async def _wait_for_state(app: CoCoCodeApp, state: SessionState) -> None:
    for _ in range(50):
        await asyncio.sleep(0.02)
        if app.state == state:
            return
    raise AssertionError(f"app did not reach {state}")


def test_escape_cancels_streaming_and_allows_next_prompt(tmp_path: Path) -> None:
    async def run() -> None:
        provider = ProviderConfig(
            name="Fake OpenAI",
            protocol="openai",
            model="fake-model",
            api_key="secret-key",
        )
        hanging = CancelAwareProvider()
        app = CoCoCodeApp(Config(providers=[provider]), cwd=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.provider = hanging
            app.submit_user_text("hang")
            await _wait_for_state(app, SessionState.STREAMING)
            assert app.query_one("#input", PromptTextArea).disabled is True

            await pilot.press("escape")
            await _wait_for_state(app, SessionState.IDLE)

            assert hanging.cancelled is True
            assert app.stream_task is None
            assert app.query_one("#input", PromptTextArea).disabled is False

            quick = QuickProvider()
            app.provider = quick
            app.submit_user_text("next")
            await _wait_for_state(app, SessionState.IDLE)
            assert quick.calls == 1

    asyncio.run(run())


def test_ctrl_c_cancels_streaming_and_allows_next_prompt(tmp_path: Path) -> None:
    async def run() -> None:
        provider = ProviderConfig(
            name="Fake OpenAI",
            protocol="openai",
            model="fake-model",
            api_key="secret-key",
        )
        hanging = CancelAwareProvider()
        app = CoCoCodeApp(Config(providers=[provider]), cwd=tmp_path)
        quit_requested = False

        def fake_request_quit(*, force: bool = False) -> None:  # noqa: FBT001, FBT002
            nonlocal quit_requested
            assert force is True
            quit_requested = True

        app.request_quit = fake_request_quit  # type: ignore[method-assign]
        async with app.run_test() as pilot:
            await pilot.pause()
            app.provider = hanging
            app.submit_user_text("hang")
            await _wait_for_state(app, SessionState.STREAMING)
            assert app.query_one("#input", PromptTextArea).disabled is True

            await pilot.press("ctrl+c")
            await _wait_for_state(app, SessionState.IDLE)

            assert quit_requested is False
            assert hanging.cancelled is True
            assert app.stream_task is None
            assert app.query_one("#input", PromptTextArea).disabled is False

            quick = QuickProvider()
            app.provider = quick
            app.submit_user_text("next")
            await _wait_for_state(app, SessionState.IDLE)
            assert quick.calls == 1

    asyncio.run(run())

def test_ctrl_c_cancels_first_then_second_ctrl_c_quits(monkeypatch, tmp_path: Path) -> None:
    import coco_code.tui.app as app_module

    provider = ProviderConfig(
        name="Fake OpenAI",
        protocol="openai",
        model="fake-model",
        api_key="secret-key",
    )
    clock = iter([100.0, 100.2])
    app = CoCoCodeApp(Config(providers=[provider]), cwd=tmp_path)
    app.state = SessionState.STREAMING
    quit_requested = False
    cancel_called = False

    def fake_monotonic() -> float:
        return next(clock)

    def fake_request_quit(*, force: bool = False) -> None:  # noqa: FBT001, FBT002
        nonlocal quit_requested
        assert force is True
        quit_requested = True

    def fake_cancel_current_turn() -> bool:
        nonlocal cancel_called
        cancel_called = True
        return True

    monkeypatch.setattr(app_module, "monotonic", fake_monotonic)
    app.request_quit = fake_request_quit  # type: ignore[method-assign]
    app.cancel_current_turn = fake_cancel_current_turn  # type: ignore[method-assign]
    app.show_message = lambda text: None  # type: ignore[method-assign]

    assert app.handle_key_interrupt("ctrl+c") is True
    assert cancel_called is True
    assert quit_requested is False

    assert app.handle_key_interrupt("ctrl+c") is True
    assert quit_requested is True


class SlowCancelProvider:
    name = "fake"
    model = "fake-model"
    protocol = "openai"

    def __init__(self) -> None:
        self.calls = 0
        self.cancelled = False
        self.cleanup_started = asyncio.Event()
        self.release_cleanup = asyncio.Event()

    async def stream(self, messages, tools=None):  # noqa: ARG002
        self.calls += 1
        try:
            yield StreamEvent(type=StreamEventType.TEXT_DELTA, text="partial")
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            self.cancelled = True
            self.cleanup_started.set()
            await self.release_cleanup.wait()
            raise


def test_escape_recovers_before_slow_cancelled_turn_exits(tmp_path: Path) -> None:
    async def run() -> None:
        provider = ProviderConfig(
            name="Fake OpenAI",
            protocol="openai",
            model="fake-model",
            api_key="secret-key",
        )
        hanging = SlowCancelProvider()
        app = CoCoCodeApp(Config(providers=[provider]), cwd=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.provider = hanging
            app.submit_user_text("hang")
            await _wait_for_state(app, SessionState.STREAMING)
            old_task = app.stream_task
            assert old_task is not None

            await pilot.press("escape")
            await _wait_for_state(app, SessionState.IDLE)

            assert app.stream_task is None
            assert app.query_one("#input", PromptTextArea).disabled is False

            quick = QuickProvider()
            app.provider = quick
            app.submit_user_text("next")
            await _wait_for_state(app, SessionState.IDLE)
            assert quick.calls == 1

            await asyncio.wait_for(hanging.cleanup_started.wait(), timeout=1)
            hanging.release_cleanup.set()
            with suppress(asyncio.CancelledError):
                await asyncio.wait_for(old_task, timeout=1)

    asyncio.run(run())



def test_force_quit_schedules_hard_exit_fallback(monkeypatch, tmp_path: Path) -> None:
    async def run() -> None:
        provider = ProviderConfig(
            name="Fake OpenAI",
            protocol="openai",
            model="fake-model",
            api_key="secret-key",
        )
        app = CoCoCodeApp(Config(providers=[provider]), cwd=tmp_path)
        exited = False
        forced = False

        def fake_exit() -> None:
            nonlocal exited
            exited = True

        def fake_force_exit_now() -> None:
            nonlocal forced
            forced = True

        monkeypatch.setattr(app, "exit", fake_exit)
        monkeypatch.setattr(app, "_force_exit_now", fake_force_exit_now)

        app.request_quit(force=True)

        assert exited is True
        assert app._force_exit_handle is not None

        await asyncio.sleep(1.1)

        assert forced is True

    asyncio.run(run())


async def _wait_for_confirm_screen(app: CoCoCodeApp) -> None:
    for _ in range(50):
        await asyncio.sleep(0.02)
        if isinstance(app.screen, ConfirmToolScreen):
            return
    raise AssertionError("confirmation screen did not open")


def test_dismiss_active_confirmation_rejects_modal(tmp_path: Path) -> None:
    async def run() -> None:
        provider = ProviderConfig(
            name="Fake OpenAI",
            protocol="openai",
            model="fake-model",
            api_key="secret-key",
        )
        call = ToolCall(
            "call-1",
            "WriteFile",
            {"path": "created.txt", "content": "no"},
            '{"path":"created.txt","content":"no"}',
        )
        spec = ToolSpec(
            name="WriteFile",
            description="Write a file",
            parameters_schema={"type": "object", "properties": {}},
            confirmation=ConfirmationPolicy.REQUIRED,
        )
        app = CoCoCodeApp(Config(providers=[provider]), cwd=tmp_path)
        confirmation_result: bool | None = None

        def resolve_confirmation(approved: bool | None) -> None:
            nonlocal confirmation_result
            confirmation_result = approved

        async with app.run_test() as pilot:
            await pilot.pause()
            app.push_screen(ConfirmToolScreen(call, spec), callback=resolve_confirmation)
            await _wait_for_confirm_screen(app)

            app.dismiss_active_confirmation()
            await pilot.pause()

            assert confirmation_result is False
            assert not isinstance(app.screen, ConfirmToolScreen)

    asyncio.run(run())
















