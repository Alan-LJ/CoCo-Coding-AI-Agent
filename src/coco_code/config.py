from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

ProtocolName = Literal["anthropic", "openai", "openai-compat"]
SUPPORTED_PROTOCOLS: set[str] = {"anthropic", "openai", "openai-compat"}
DEFAULT_ANTHROPIC_CONTEXT_WINDOW = 200_000
DEFAULT_OPENAI_CONTEXT_WINDOW = 128_000


class ConfigError(Exception):
    """配置错误，面向用户展示。"""


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    protocol: ProtocolName
    model: str
    base_url: str | None = None
    api_key: str | None = None
    thinking: bool = False
    context_window: int = 0


@dataclass(frozen=True)
class Config:
    providers: list[ProviderConfig]
    enable_subagent_background: bool = True


def default_config_paths(cwd: Path | None = None) -> list[Path]:
    base = cwd or Path.cwd()
    return [
        Path.home() / ".coco-code" / "config.yaml",
        base / ".coco-code" / "config.yaml",
        base / ".coco-code" / "config.local.yaml",
    ]


def load_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"配置文件 {path} 的 YAML 格式不正确：{exc}") from exc
    except OSError as exc:
        raise ConfigError(f"无法读取配置文件 {path}：{exc}") from exc

    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConfigError(f"配置文件 {path} 顶层必须是映射对象")
    return raw


def merge_raw(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if key == "providers":
            merged[key] = value
            continue
        old = merged.get(key)
        if isinstance(old, dict) and isinstance(value, dict):
            merged[key] = merge_raw(old, value)
        else:
            merged[key] = value
    return merged


def load(path: str | Path | None = None, cwd: Path | None = None) -> Config:
    raw_config: dict[str, Any]
    if path is not None:
        raw_config = load_file(Path(path).expanduser())
    else:
        raw_config = {}
        for config_path in default_config_paths(cwd):
            raw_config = merge_raw(raw_config, load_file(config_path))
    return _parse_config(raw_config)


def resolve_api_key(provider: ProviderConfig) -> str:
    if provider.api_key:
        return provider.api_key

    env_name = "ANTHROPIC_API_KEY" if provider.protocol == "anthropic" else "OPENAI_API_KEY"
    api_key = os.environ.get(env_name)
    if api_key:
        return api_key

    raise ConfigError(
        f"provider '{provider.name}' 缺少 api_key，请在配置中设置或设置环境变量 {env_name}"
    )


def effective_context_window(provider: ProviderConfig) -> int:
    if provider.context_window > 0:
        return provider.context_window
    if provider.protocol == "openai" or provider.protocol == "openai-compat":
        return DEFAULT_OPENAI_CONTEXT_WINDOW
    return DEFAULT_ANTHROPIC_CONTEXT_WINDOW


def _parse_config(raw: dict[str, Any]) -> Config:
    providers_raw = raw.get("providers")
    if not isinstance(providers_raw, list) or not providers_raw:
        raise ConfigError("配置缺少非空 providers 列表")

    providers = [_parse_provider(index, item) for index, item in enumerate(providers_raw)]
    return Config(
        providers=providers,
        enable_subagent_background=_optional_bool(
            raw,
            "enableSubAgentBackground",
            fallback_key="enable_subagent_background",
            default=True,
        ),
    )


def _parse_provider(index: int, raw: Any) -> ProviderConfig:
    if not isinstance(raw, dict):
        raise ConfigError(f"providers[{index}] 必须是映射对象")

    name = _required_str(raw, "name", index)
    protocol_text = _required_str(raw, "protocol", index)
    if protocol_text not in SUPPORTED_PROTOCOLS:
        supported = ", ".join(sorted(SUPPORTED_PROTOCOLS))
        raise ConfigError(f"providers[{index}].protocol 非法：{protocol_text}，支持：{supported}")

    model = _required_str(raw, "model", index)
    base_url = _optional_str(raw, "base_url", index)
    api_key = _optional_str(raw, "api_key", index)
    thinking_raw = raw.get("thinking", False)
    if not isinstance(thinking_raw, bool):
        raise ConfigError(f"providers[{index}].thinking 必须是布尔值")
    context_window = _optional_non_negative_int(raw, "context_window", index)

    return ProviderConfig(
        name=name,
        protocol=protocol_text,  # type: ignore[arg-type]
        model=model,
        base_url=base_url,
        api_key=api_key,
        thinking=thinking_raw,
        context_window=context_window,
    )


def _required_str(raw: dict[str, Any], field: str, index: int) -> str:
    value = raw.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"providers[{index}].{field} 缺失或为空")
    return value.strip()


def _optional_str(raw: dict[str, Any], field: str, index: int) -> str | None:
    value = raw.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConfigError(f"providers[{index}].{field} 必须是字符串")
    value = value.strip()
    return value or None


def _optional_non_negative_int(raw: dict[str, Any], field: str, index: int) -> int:
    value = raw.get(field, 0)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"providers[{index}].{field} 必须是非负整数")
    if value < 0:
        raise ConfigError(f"providers[{index}].{field} 必须是非负整数")
    return value


def _optional_bool(
    raw: dict[str, Any],
    field: str,
    *,
    fallback_key: str | None = None,
    default: bool,
) -> bool:
    value = raw.get(field)
    if value is None and fallback_key is not None:
        value = raw.get(fallback_key)
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ConfigError(f"{field} must be a boolean")
    return value
