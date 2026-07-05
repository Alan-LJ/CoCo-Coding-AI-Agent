from __future__ import annotations

from coco_code import cli
from coco_code.config import Config, ProviderConfig
from coco_code.mcp.config import McpConfig


def test_cli_loads_and_passes_mcp_config(monkeypatch, tmp_path) -> None:
    provider = ProviderConfig(
        name="Fake OpenAI",
        protocol="openai",
        model="fake-model",
        api_key="secret-key",
    )
    config = Config(providers=[provider])
    mcp_config = McpConfig()
    captured = {}

    class FakeApp:
        def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
            captured["args"] = args
            captured["kwargs"] = kwargs

        def run(self) -> None:
            captured["ran"] = True

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "load", lambda: config)
    monkeypatch.setattr(cli, "resolve_api_key", lambda _provider: None)
    monkeypatch.setattr(cli, "new_engine", lambda root: ("engine", None))
    monkeypatch.setattr(cli, "load_mcp_config", lambda root: mcp_config)
    monkeypatch.setattr(cli, "CoCoCodeApp", FakeApp)

    cli.main()

    assert captured["args"] == (config,)
    assert captured["kwargs"]["cwd"] == tmp_path.resolve()
    assert captured["kwargs"]["permission_engine"] == "engine"
    assert captured["kwargs"]["mcp_config"] is mcp_config
    assert captured["ran"] is True
