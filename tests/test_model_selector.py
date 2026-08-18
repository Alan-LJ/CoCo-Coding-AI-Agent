from __future__ import annotations

import pytest

from coco_code.app import CoCoCodeApp
from coco_code.config import ProviderConfig


def _providers() -> list[ProviderConfig]:
    return [
        ProviderConfig(
            name="kimi-official",
            protocol="openai-compat",
            base_url="https://api.moonshot.cn/v1",
            model="kimi-k3",
            api_key="test",
        ),
        ProviderConfig(
            name="deepseek-official",
            protocol="openai-compat",
            base_url="https://api.deepseek.com",
            model="deepseek-v4-flash",
            api_key="test",
        ),
    ]


@pytest.mark.asyncio
async def test_model_selector_queues_change_while_streaming() -> None:
    providers = _providers()
    app = CoCoCodeApp(providers=providers)

    async with app.run_test(size=(120, 40)) as pilot:
        app._selected_provider = providers[0]
        app._model_select_ready = True
        app._streaming = True

        selector = app.query_one("#model-select")
        selector.value = providers[1].name
        await pilot.pause()

        assert app._pending_provider is providers[1]
        assert "下轮生效" in str(app.query_one("#model-label").render())


@pytest.mark.asyncio
async def test_provider_auth_error_is_visible_and_picker_keeps_focus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing_env = "COCO_CODE_TEST_MISSING_API_KEY"
    monkeypatch.delenv(missing_env, raising=False)
    providers = _providers()
    providers[0].api_key = ""
    providers[0].api_key_env = missing_env
    app = CoCoCodeApp(providers=providers)

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("enter")
        await pilot.pause()

        error = app.query_one("#provider-error")
        assert error.display is True
        assert missing_env in str(error.render())
        assert app.query_one("#provider-list").has_focus
