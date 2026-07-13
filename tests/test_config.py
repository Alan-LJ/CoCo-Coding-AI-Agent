from __future__ import annotations

from pathlib import Path

import pytest

from coco_code.config import ConfigError, ProviderConfig, load, merge_raw, resolve_api_key


def write_config(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_provider_model_can_be_instantiated() -> None:
    provider = ProviderConfig(name="Claude", protocol="anthropic", model="claude-test")
    assert provider.name == "Claude"
    assert provider.thinking is False


def test_load_file_path(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    write_config(
        config_path,
        """
providers:
  - name: Claude
    protocol: anthropic
    model: claude-test
""",
    )
    config = load(path=config_path)
    assert config.providers[0].name == "Claude"
    assert config.enable_subagent_background is True


def test_load_subagent_background_flag(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    write_config(
        config_path,
        """
enableSubAgentBackground: false
providers:
  - name: Claude
    protocol: anthropic
    model: claude-test
""",
    )
    config = load(path=config_path)
    assert config.enable_subagent_background is False


def test_missing_layers_are_allowed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    cwd = tmp_path / "project"
    monkeypatch.setattr(Path, "home", lambda: home)
    write_config(
        cwd / ".coco-code" / "config.yaml",
        """
providers:
  - name: OpenAI
    protocol: openai
    model: gpt-test
""",
    )
    config = load(cwd=cwd)
    assert config.providers[0].name == "OpenAI"


def test_three_layer_provider_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    cwd = tmp_path / "project"
    monkeypatch.setattr(Path, "home", lambda: home)
    write_config(
        home / ".coco-code" / "config.yaml",
        """
providers:
  - name: Global
    protocol: anthropic
    model: global-model
""",
    )
    write_config(
        cwd / ".coco-code" / "config.yaml",
        """
providers:
  - name: Project
    protocol: openai
    model: project-model
""",
    )
    write_config(
        cwd / ".coco-code" / "config.local.yaml",
        """
providers:
  - name: Local
    protocol: openai-compat
    model: local-model
""",
    )
    config = load(cwd=cwd)
    assert config.providers == [
        ProviderConfig(name="Local", protocol="openai-compat", model="local-model")
    ]


def test_merge_raw_replaces_providers() -> None:
    merged = merge_raw(
        {"providers": [{"name": "old"}], "nested": {"a": 1}},
        {"providers": [{"name": "new"}], "nested": {"b": 2}},
    )
    assert merged == {"providers": [{"name": "new"}], "nested": {"a": 1, "b": 2}}


@pytest.mark.parametrize(
    ("content", "needle"),
    [
        ("", "providers"),
        ("providers: []", "providers"),
        ("providers:\n  - protocol: anthropic\n    model: x", "name"),
        ("providers:\n  - name: x\n    protocol: bad\n    model: x", "protocol"),
        ("providers:\n  - name: x\n    protocol: anthropic", "model"),
        (
            "providers:\n  - name: x\n    protocol: anthropic\n    model: x\n    thinking: maybe",
            "thinking",
        ),
    ],
)
def test_invalid_config_has_clear_error(tmp_path: Path, content: str, needle: str) -> None:
    config_path = tmp_path / "config.yaml"
    write_config(config_path, content)
    with pytest.raises(ConfigError, match=needle):
        load(path=config_path)


def test_invalid_yaml_is_config_error(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    write_config(config_path, "providers: [")
    with pytest.raises(ConfigError, match="YAML"):
        load(path=config_path)


def test_resolve_api_key_prefers_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-secret")
    provider = ProviderConfig(
        name="Claude",
        protocol="anthropic",
        model="claude-test",
        api_key="config-secret",
    )
    assert resolve_api_key(provider) == "config-secret"


def test_resolve_api_key_falls_back_to_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "env-secret")
    provider = ProviderConfig(name="OpenAI", protocol="openai-compat", model="gpt-test")
    assert resolve_api_key(provider) == "env-secret"


def test_missing_api_key_error_does_not_leak_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    provider = ProviderConfig(name="Claude", protocol="anthropic", model="claude-test")
    with pytest.raises(ConfigError) as exc_info:
        resolve_api_key(provider)
    message = str(exc_info.value)
    assert "ANTHROPIC_API_KEY" in message
    assert "secret" not in message
