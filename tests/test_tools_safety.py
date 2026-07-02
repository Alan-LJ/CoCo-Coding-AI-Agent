from __future__ import annotations

import pytest

from coco_code.tools.safety import (
    ToolSafetyError,
    ensure_text_file,
    resolve_workspace_path,
    summarize_params,
    truncate_text,
)


def test_resolve_workspace_path_accepts_inside_path(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    resolved = resolve_workspace_path(workspace, "src/app.py")
    assert resolved == workspace / "src" / "app.py"


def test_resolve_workspace_path_rejects_parent_traversal(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with pytest.raises(ToolSafetyError):
        resolve_workspace_path(workspace, "../outside.txt")


def test_resolve_workspace_path_rejects_absolute_outside_path(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside.txt"
    workspace.mkdir()
    with pytest.raises(ToolSafetyError):
        resolve_workspace_path(workspace, outside)


def test_ensure_text_file_reads_utf8_text(tmp_path) -> None:
    path = tmp_path / "hello.txt"
    path.write_text("你好", encoding="utf-8")
    assert ensure_text_file(path) == "你好"


def test_ensure_text_file_rejects_directory(tmp_path) -> None:
    with pytest.raises(ToolSafetyError):
        ensure_text_file(tmp_path)


def test_ensure_text_file_rejects_binary(tmp_path) -> None:
    path = tmp_path / "binary.bin"
    path.write_bytes(b"abc\x00def")
    with pytest.raises(ToolSafetyError):
        ensure_text_file(path)


def test_truncate_text_marks_truncated() -> None:
    assert truncate_text("abcdef", 3) == ("abc", True)
    assert truncate_text("abc", 3) == ("abc", False)


def test_summarize_params_redacts_sensitive_values() -> None:
    summary = summarize_params({"api_key": "secret", "content": "x" * 200})
    assert "secret" not in summary
    assert "<redacted>" in summary
    assert "200 chars" in summary
