from __future__ import annotations

import asyncio
import os
import sys

from coco_code.tools.base import ToolContext
from coco_code.tools.builtin import (
    EditFileTool,
    GlobFilesTool,
    ReadFileTool,
    RunCommandTool,
    SearchCodeTool,
    WriteFileTool,
)


def context(tmp_path, *, timeout_seconds: float = 2.0) -> ToolContext:
    return ToolContext(
        workspace=tmp_path,
        timeout_seconds=timeout_seconds,
        max_output_chars=20,
        max_search_results=2,
    )


def run_tool(tool, params, tmp_path, *, timeout_seconds: float = 2.0):
    return asyncio.run(tool.run(params, context(tmp_path, timeout_seconds=timeout_seconds)))


def python_command(code: str) -> str:
    if os.name == "nt":
        return f'& "{sys.executable}" -c "{code}"'
    return f'"{sys.executable}" -c "{code}"'


def test_ReadFile_returns_content_and_truncation(tmp_path) -> None:
    path = tmp_path / "hello.txt"
    path.write_text("abcdef", encoding="utf-8")
    result = run_tool(ReadFileTool(), {"path": "hello.txt", "max_chars": 3}, tmp_path)
    assert result.ok is True
    assert result.data["content"] == "abc"
    assert result.truncated is True


def test_ReadFile_rejects_missing_and_binary_files(tmp_path) -> None:
    missing = run_tool(ReadFileTool(), {"path": "missing.txt"}, tmp_path)
    assert missing.ok is False
    path = tmp_path / "binary.bin"
    path.write_bytes(b"\x00\x01")
    binary = run_tool(ReadFileTool(), {"path": "binary.bin"}, tmp_path)
    assert binary.ok is False
    assert "二进制" in (binary.error or "")


def test_WriteFile_creates_and_respects_overwrite(tmp_path) -> None:
    tool = WriteFileTool()
    created = run_tool(tool, {"path": "notes/a.txt", "content": "one"}, tmp_path)
    assert created.ok is True
    assert (tmp_path / "notes" / "a.txt").read_text(encoding="utf-8") == "one"
    rejected = run_tool(tool, {"path": "notes/a.txt", "content": "two"}, tmp_path)
    assert rejected.ok is False
    overwritten = run_tool(
        tool, {"path": "notes/a.txt", "content": "two", "overwrite": True}, tmp_path
    )
    assert overwritten.ok is True
    assert (tmp_path / "notes" / "a.txt").read_text(encoding="utf-8") == "two"


def test_EditFile_only_replaces_unique_match(tmp_path) -> None:
    path = tmp_path / "code.py"
    path.write_text("alpha beta gamma", encoding="utf-8")
    result = run_tool(
        EditFileTool(),
        {"path": "code.py", "old_text": "beta", "new_text": "BETA"},
        tmp_path,
    )
    assert result.ok is True
    assert path.read_text(encoding="utf-8") == "alpha BETA gamma"

    missing = run_tool(
        EditFileTool(),
        {"path": "code.py", "old_text": "missing", "new_text": "x"},
        tmp_path,
    )
    assert missing.ok is False
    assert path.read_text(encoding="utf-8") == "alpha BETA gamma"

    path.write_text("same same", encoding="utf-8")
    multiple = run_tool(
        EditFileTool(),
        {"path": "code.py", "old_text": "same", "new_text": "x"},
        tmp_path,
    )
    assert multiple.ok is False
    assert path.read_text(encoding="utf-8") == "same same"


def test_file_tools_reject_path_traversal(tmp_path) -> None:
    result = run_tool(WriteFileTool(), {"path": "../escape.txt", "content": "no"}, tmp_path)
    assert result.ok is False
    assert not (tmp_path.parent / "escape.txt").exists()


def test_Glob_skips_ignored_dirs_and_truncates(tmp_path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("a", encoding="utf-8")
    (tmp_path / "src" / "b.py").write_text("b", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "hidden.py").write_text("hidden", encoding="utf-8")
    result = run_tool(GlobFilesTool(), {"pattern": "**/*.py", "max_results": 1}, tmp_path)
    assert result.ok is True
    assert result.data["matches"] == ["src/a.py"]
    assert result.truncated is True
    assert "hidden.py" not in result.data["matches"]


def test_Glob_rejects_parent_traversal(tmp_path) -> None:
    result = run_tool(GlobFilesTool(), {"pattern": "../*.py"}, tmp_path)
    assert result.ok is False


def test_Grep_finds_text_and_regex(tmp_path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("class Conversation:\n    pass\n", encoding="utf-8")
    text_result = run_tool(SearchCodeTool(), {"pattern": "Conversation"}, tmp_path)
    assert text_result.ok is True
    assert text_result.data["matches"][0]["path"] == "src/a.py"
    regex_result = run_tool(SearchCodeTool(), {"pattern": "class\\s+\\w+", "regex": True}, tmp_path)
    assert regex_result.ok is True
    assert regex_result.data["total"] == 1


def test_Grep_truncates_results(tmp_path) -> None:
    (tmp_path / "a.txt").write_text("hit\nhit\nhit\n", encoding="utf-8")
    result = run_tool(SearchCodeTool(), {"pattern": "hit", "max_results": 2}, tmp_path)
    assert result.ok is True
    assert len(result.data["matches"]) == 2
    assert result.truncated is True


def test_Bash_returns_stdout_and_exit_code(tmp_path) -> None:
    result = run_tool(
        RunCommandTool(),
        {"command": python_command("print(123)")},
        tmp_path,
    )
    assert result.ok is True
    assert result.data["returncode"] == 0
    assert "123" in result.data["stdout"]


def test_Bash_nonzero_exit_code_is_failure_with_output(tmp_path) -> None:
    result = run_tool(
        RunCommandTool(),
        {"command": "Write-Output bad; exit 7" if os.name == "nt" else "printf bad; exit 7"},
        tmp_path,
    )
    assert result.ok is False
    assert result.data["returncode"] == 7
    assert "bad" in result.data["stdout"]
    assert "退出码 7" in result.summary
    assert "退出码 7" in (result.error or "")


def test_Bash_times_out(tmp_path) -> None:
    result = run_tool(
        RunCommandTool(),
        {"command": python_command("import time; time.sleep(2)")},
        tmp_path,
        timeout_seconds=0.2,
    )
    assert result.ok is False
    assert "超时" in (result.error or "")

