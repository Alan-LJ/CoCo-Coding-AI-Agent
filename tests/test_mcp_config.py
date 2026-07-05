from __future__ import annotations

import io
import re
from pathlib import Path

import yaml

from coco_code.mcp import config as mcp_config
from coco_code.mcp.config import default_mcp_config_paths, load_config


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _use_home(monkeypatch, home: Path) -> None:
    monkeypatch.setattr(mcp_config.Path, "home", staticmethod(lambda: home))


def test_default_mcp_config_paths_use_user_and_project_layers(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    _use_home(monkeypatch, home)

    user_path, project_path = default_mcp_config_paths(tmp_path)

    assert user_path == home / ".coco-code" / "mcp.yaml"
    assert project_path == tmp_path / ".coco-code" / "mcp.yaml"


def test_missing_configs_load_empty(tmp_path: Path, monkeypatch) -> None:
    _use_home(monkeypatch, tmp_path / "home")

    config = load_config(tmp_path)

    assert config.servers == {}


def test_project_server_overrides_user_server_without_field_merge(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "home"
    root = tmp_path / "project"
    monkeypatch.setenv("USER_TOKEN", "user-secret")
    monkeypatch.setenv("PROJECT_TOKEN", "project-secret")
    _use_home(monkeypatch, home)
    _write(
        home / ".coco-code" / "mcp.yaml",
        """
mcp_servers:
  shared:
    type: stdio
    command: user-command
    args: ["user"]
    env:
      TOKEN: "${USER_TOKEN}"
      USER_ONLY: keep
  user_only:
    type: http
    url: https://user.example/mcp
""",
    )
    _write(
        root / ".coco-code" / "mcp.yaml",
        """
mcp_servers:
  shared:
    type: stdio
    command: project-command
    args: ["${NOT_EXPANDED_IN_ARGS}"]
    env:
      TOKEN: "${PROJECT_TOKEN}"
""",
    )

    config = load_config(root)

    assert sorted(config.servers) == ["shared", "user_only"]
    shared = config.servers["shared"]
    assert shared.command == "project-command"
    assert shared.args == ("${NOT_EXPANDED_IN_ARGS}",)
    assert shared.env == {"TOKEN": "project-secret"}
    assert config.servers["user_only"].url == "https://user.example/mcp"


def test_invalid_yaml_degrades_to_other_layer(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    root = tmp_path / "project"
    _use_home(monkeypatch, home)
    _write(home / ".coco-code" / "mcp.yaml", "mcp_servers: [")
    _write(
        root / ".coco-code" / "mcp.yaml",
        """
mcp_servers:
  ok:
    type: stdio
    command: python
""",
    )
    stderr = io.StringIO()

    config = load_config(root, stderr=stderr)

    assert list(config.servers) == ["ok"]
    assert "failed" in stderr.getvalue()


def test_validate_server_fields_skip_bad_entries(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    _use_home(monkeypatch, home)
    _write(
        tmp_path / ".coco-code" / "mcp.yaml",
        """
mcp_servers:
  valid_stdio:
    type: stdio
    command: python
  valid_http:
    type: http
    url: https://example.test/mcp
  bad_type:
    type: websocket
    url: wss://example.test
  missing_command:
    type: stdio
  missing_url:
    type: http
  bad_args:
    type: stdio
    command: python
    args: ["ok", 1]
  bad_env:
    type: stdio
    command: python
    env: ["TOKEN"]
  bad_headers:
    type: http
    url: https://example.test/mcp
    headers:
      Authorization: 123
""",
    )
    stderr = io.StringIO()

    config = load_config(tmp_path, stderr=stderr)

    assert sorted(config.servers) == ["valid_http", "valid_stdio"]
    assert stderr.getvalue().count("skip server") >= 6


def test_expand_vars_only_in_env_and_headers_without_leaking_values(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "home"
    _use_home(monkeypatch, home)
    monkeypatch.setenv("SECRET_TOKEN", "super-secret-value")
    monkeypatch.delenv("MISSING_TOKEN", raising=False)
    _write(
        tmp_path / ".coco-code" / "mcp.yaml",
        """
mcp_servers:
  api:
    type: http
    url: https://example.test/mcp
    headers:
      Authorization: "Bearer ${SECRET_TOKEN}"
      X-Missing: "${MISSING_TOKEN}"
  runner:
    type: stdio
    command: "${COMMAND_NOT_EXPANDED}"
    args: ["${ARG_NOT_EXPANDED}"]
    env:
      TOKEN: "${SECRET_TOKEN}"
""",
    )
    stderr = io.StringIO()

    config = load_config(tmp_path, stderr=stderr)

    assert config.servers["api"].headers["Authorization"] == "Bearer super-secret-value"
    assert config.servers["api"].headers["X-Missing"] == ""
    assert config.servers["runner"].command == "${COMMAND_NOT_EXPANDED}"
    assert config.servers["runner"].args == ("${ARG_NOT_EXPANDED}",)
    assert config.servers["runner"].env["TOKEN"] == "super-secret-value"
    assert "MISSING_TOKEN" in stderr.getvalue()
    assert "super-secret-value" not in stderr.getvalue()


def test_docs_example_is_parseable_and_does_not_embed_real_tokens(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "home"
    _use_home(monkeypatch, home)
    example = Path("docs/mcp-servers.example.yaml").read_text(encoding="utf-8")
    parsed = yaml.safe_load(example)
    _write(tmp_path / ".coco-code" / "mcp.yaml", example)

    config = load_config(tmp_path, stderr=io.StringIO())

    assert isinstance(parsed.get("mcp_servers"), dict)
    assert sorted(config.servers) == ["context7", "github"]
    assert not re.search(r"(sk-|ghp_|github_pat_)[A-Za-z0-9_-]{12,}", example)
    assert not re.search(r"Bearer [A-Za-z0-9_-]{12,}", example)
