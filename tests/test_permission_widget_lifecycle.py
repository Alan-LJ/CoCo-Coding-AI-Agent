from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from coco_code.agent import PermissionRequest, PermissionResponse
from coco_code.app import CoCoCodeApp


class _TrackedFuture:
    def __init__(self, state: dict[str, Any]) -> None:
        self.state = state
        self.result: PermissionResponse | None = None

    def done(self) -> bool:
        return self.result is not None

    def set_result(self, result: PermissionResponse) -> None:
        assert self.state["widget_removed"]
        assert self.state["input_enabled"]
        self.result = result


class _Widget:
    def __init__(self, state: dict[str, Any]) -> None:
        self.state = state

    async def remove(self) -> None:
        await asyncio.sleep(0)
        self.state["widget_removed"] = True


class _Input:
    def __init__(self, state: dict[str, Any]) -> None:
        self.state = state
        self._disabled = True

    @property
    def disabled(self) -> bool:
        return self._disabled

    @disabled.setter
    def disabled(self, value: bool) -> None:
        self._disabled = value
        self.state["input_enabled"] = not value

    def focus(self) -> None:
        pass


class _AppHarness:
    def __init__(
        self,
        request: PermissionRequest,
        widget: _Widget,
        input_widget: _Input,
    ) -> None:
        self._pending_perm_request = request
        self.widget = widget
        self.input_widget = input_widget

    def query_one(self, selector: str, *_args: Any) -> Any:
        if selector == "#perm-inline":
            return self.widget
        if selector == "#chat-input":
            return self.input_widget
        raise AssertionError(f"Unexpected selector: {selector}")


class _Chat:
    def __init__(self, state: dict[str, Any], stale_widget: _Widget) -> None:
        self.state = state
        self.stale_widget = stale_widget
        self.mounted: Any = None

    def query_one(self, _selector: str, *_args: Any) -> _Widget:
        return self.stale_widget

    async def mount(self, widget: Any) -> None:
        assert self.state["widget_removed"]
        self.mounted = widget

    def scroll_end(self, **_kwargs: Any) -> None:
        pass


class _RequestAppHarness:
    def __init__(self, chat: _Chat, input_widget: _Input) -> None:
        self.chat = chat
        self.input_widget = input_widget
        self._pending_perm_request: PermissionRequest | None = None

    def query_one(self, selector: str, *_args: Any) -> Any:
        if selector == "#chat-area":
            return self.chat
        if selector == "#chat-input":
            return self.input_widget
        raise AssertionError(f"Unexpected selector: {selector}")

    def call_after_refresh(self, *_args: Any, **_kwargs: Any) -> None:
        pass


@pytest.mark.asyncio
async def test_permission_widget_is_removed_before_agent_resumes() -> None:
    state = {"widget_removed": False, "input_enabled": False}
    future = _TrackedFuture(state)
    request = PermissionRequest(
        tool_name="WriteFile",
        description="write web_search.py",
        future=future,  # type: ignore[arg-type]
    )
    app = _AppHarness(request, _Widget(state), _Input(state))
    event = SimpleNamespace(response=PermissionResponse.ALLOW)

    await CoCoCodeApp.on_inline_permission_widget_responded(
        app, event  # type: ignore[arg-type]
    )

    assert app._pending_perm_request is None
    assert future.result is PermissionResponse.ALLOW


@pytest.mark.asyncio
async def test_stale_permission_widget_is_removed_before_next_mount() -> None:
    state = {"widget_removed": False, "input_enabled": True}
    chat = _Chat(state, _Widget(state))
    app = _RequestAppHarness(chat, _Input(state))
    request = PermissionRequest(
        tool_name="WriteFile",
        description="write the next file",
        future=asyncio.get_running_loop().create_future(),
    )

    await CoCoCodeApp._handle_permission_request(
        app, request  # type: ignore[arg-type]
    )

    assert chat.mounted is not None
    assert app._pending_perm_request is request
    assert app.input_widget.disabled is True
