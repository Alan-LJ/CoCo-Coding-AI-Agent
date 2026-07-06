from __future__ import annotations

from pathlib import Path

from coco_code.config import ProviderConfig
from coco_code.prompt import build_system_prompt, render_banner


def test_system_prompt_contains_environment_and_scope() -> None:
    provider = ProviderConfig(
        name="Claude",
        protocol="anthropic",
        model="claude-test",
        api_key="secret-key",
    )
    prompt = build_system_prompt(Path("P:/AI/CoCo Code_Agent"), provider)
    assert "CoCo Code" in prompt
    assert "Current working directory" in prompt
    assert "claude-test" in prompt
    assert "tool calls" in prompt
    assert "read files" in prompt
    assert "edit code" in prompt
    assert "Modes:" in prompt
    assert "secret-key" not in prompt


def test_banner_contains_version_model_cwd_and_no_key() -> None:
    provider = ProviderConfig(
        name="OpenAI",
        protocol="openai",
        model="gpt-test",
        api_key="secret-key",
    )
    cwd = Path("P:/AI/CoCo Code_Agent")
    banner = render_banner("0.1.0", cwd, provider)
    assert "CoCo Code v0.1.0" in banner
    assert "OpenAI" in banner
    assert "gpt-test" in banner
    assert str(cwd) in banner
    assert "secret-key" not in banner


def test_system_prompt_injects_memory_and_instructions() -> None:
    provider = ProviderConfig(name="OpenAI", protocol="openai", model="gpt-test")
    prompt = build_system_prompt(
        Path("P:/AI/CoCo Code_Agent"),
        provider,
        instructions="Project rules",
        memory="Memory index",
    )
    assert "Long-term Memory Index" in prompt
    assert "Project Instructions" in prompt
    assert "Memory index" in prompt
    assert "Project rules" in prompt
