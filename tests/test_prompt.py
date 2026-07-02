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
    assert "当前工作目录" in prompt
    assert "claude-test" in prompt
    assert "工具调用" in prompt
    assert "文件读写" in prompt
    assert "代码编辑" in prompt
    assert "ReAct Agent Loop" in prompt
    assert "只支持“请求一次工具" not in prompt
    assert "不要继续请求第二个工具" not in prompt
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
