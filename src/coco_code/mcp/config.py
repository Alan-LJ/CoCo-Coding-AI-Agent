from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, TextIO

import yaml

ServerType = Literal["stdio", "http"]
_VAR_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


@dataclass(frozen=True)
class ServerConfig:
    name: str
    type: ServerType
    command: str = ""
    args: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class McpConfig:
    servers: dict[str, ServerConfig] = field(default_factory=dict)


def default_mcp_config_paths(root: Path) -> tuple[Path, Path]:
    return Path.home() / ".coco-code" / "mcp.yaml", root / ".coco-code" / "mcp.yaml"


def load_config(root: str | Path, *, stderr: TextIO = sys.stderr) -> McpConfig:
    root_path = Path(root)
    user_path, project_path = default_mcp_config_paths(root_path)
    user = _load_file(user_path, stderr)
    project = _load_file(project_path, stderr)
    merged = _merge_servers(user, project)
    servers: dict[str, ServerConfig] = {}
    for name in sorted(merged):
        config = _validate_server(name, merged[name], stderr)
        if config is not None:
            servers[name] = config
    return McpConfig(servers=servers)


def expand_vars(value: str, *, server_name: str, stderr: TextIO = sys.stderr) -> str:
    undefined: set[str] = set()

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in os.environ:
            undefined.add(name)
            return ""
        return os.environ[name]

    expanded = _VAR_PATTERN.sub(replace, value)
    for name in sorted(undefined):
        print(
            f"[mcp] warn: server {server_name} references undefined env var ${{{name}}}",
            file=stderr,
        )
    return expanded


def _load_file(path: Path, stderr: TextIO) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        print(f"[mcp] warn: load {path} failed: {exc}", file=stderr)
        return {}
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        print(f"[mcp] warn: load {path} failed: top-level value must be a mapping", file=stderr)
        return {}
    servers = raw.get("mcp_servers")
    if servers is None:
        return {}
    if not isinstance(servers, dict):
        print(f"[mcp] warn: load {path} failed: mcp_servers must be a mapping", file=stderr)
        return {}
    valid: dict[str, dict[str, Any]] = {}
    for name, value in servers.items():
        if not isinstance(name, str) or not name.strip():
            print(f"[mcp] warn: skip server with invalid name in {path}", file=stderr)
            continue
        if not isinstance(value, dict):
            print(f"[mcp] warn: skip server {name}: definition must be a mapping", file=stderr)
            continue
        valid[name] = dict(value)
    return valid


def _merge_servers(
    user: dict[str, dict[str, Any]], project: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    merged = dict(user)
    merged.update(project)
    return merged


def _validate_server(name: str, raw: dict[str, Any], stderr: TextIO) -> ServerConfig | None:
    server_type = raw.get("type")
    if server_type not in {"stdio", "http"}:
        _warn_skip(name, "type must be 'stdio' or 'http'", stderr)
        return None

    args = _string_tuple(raw.get("args", ()), name, "args", stderr)
    if args is None:
        return None
    env = _string_map(raw.get("env", {}), name, "env", stderr)
    if env is None:
        return None
    headers = _string_map(raw.get("headers", {}), name, "headers", stderr)
    if headers is None:
        return None

    env = {key: expand_vars(value, server_name=name, stderr=stderr) for key, value in env.items()}
    headers = {
        key: expand_vars(value, server_name=name, stderr=stderr) for key, value in headers.items()
    }

    if server_type == "stdio":
        command = raw.get("command")
        if not isinstance(command, str) or not command.strip():
            _warn_skip(name, "stdio server requires command", stderr)
            return None
        return ServerConfig(
            name=name,
            type="stdio",
            command=command.strip(),
            args=args,
            env=env,
        )

    url = raw.get("url")
    if not isinstance(url, str) or not url.strip():
        _warn_skip(name, "http server requires url", stderr)
        return None
    return ServerConfig(
        name=name,
        type="http",
        url=url.strip(),
        headers=headers,
    )


def _string_tuple(raw: Any, server: str, field_name: str, stderr: TextIO) -> tuple[str, ...] | None:
    if raw is None:
        return ()
    if not isinstance(raw, list | tuple):
        _warn_skip(server, f"{field_name} must be a list of strings", stderr)
        return None
    values: list[str] = []
    for value in raw:
        if not isinstance(value, str):
            _warn_skip(server, f"{field_name} must be a list of strings", stderr)
            return None
        values.append(value)
    return tuple(values)


def _string_map(raw: Any, server: str, field_name: str, stderr: TextIO) -> dict[str, str] | None:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        _warn_skip(server, f"{field_name} must be a mapping of strings", stderr)
        return None
    values: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, str):
            _warn_skip(server, f"{field_name} must be a mapping of strings", stderr)
            return None
        values[key] = value
    return values


def _warn_skip(server: str, reason: str, stderr: TextIO) -> None:
    print(f"[mcp] warn: skip server {server}: {reason}", file=stderr)
