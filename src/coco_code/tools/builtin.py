from __future__ import annotations

import asyncio
import locale
import os
import re
from collections.abc import Iterable
from pathlib import Path
from time import monotonic
from typing import Any

from coco_code.tools.base import (
    ConfirmationPolicy,
    JsonSchema,
    ToolCategory,
    ToolContext,
    ToolParams,
    ToolResult,
    ToolSpec,
)
from coco_code.tools.safety import (
    ToolSafetyError,
    ensure_text_file,
    has_parent_traversal,
    is_ignored_path,
    resolve_workspace_path,
    truncate_text,
)


def _schema(properties: dict[str, JsonSchema], required: list[str]) -> JsonSchema:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _success(
    tool_name: str,
    summary: str,
    data: dict[str, Any],
    *,
    elapsed_ms: int,
    truncated: bool = False,
) -> ToolResult:
    return ToolResult(
        tool_call_id="",
        tool_name=tool_name,
        ok=True,
        summary=summary,
        data=data,
        error=None,
        elapsed_ms=elapsed_ms,
        truncated=truncated,
    )


def _failure(tool_name: str, error: str, *, elapsed_ms: int = 0) -> ToolResult:
    return ToolResult(
        tool_call_id="",
        tool_name=tool_name,
        ok=False,
        summary=error,
        data={},
        error=error,
        elapsed_ms=elapsed_ms,
    )


def _elapsed_ms(started: float) -> int:
    return int((monotonic() - started) * 1000)


def _required_str(params: ToolParams, name: str) -> str:
    value = params.get(name)
    if not isinstance(value, str) or value == "":
        raise ValueError(f"参数 `{name}` 必须是非空字符串。")
    return value


def _optional_bool(params: ToolParams, name: str, default: bool) -> bool:
    value = params.get(name, default)
    if not isinstance(value, bool):
        raise ValueError(f"参数 `{name}` 必须是布尔值。")
    return value


def _optional_int(params: ToolParams, name: str, default: int, maximum: int) -> int:
    value = params.get(name, default)
    if not isinstance(value, int) or value <= 0:
        raise ValueError(f"参数 `{name}` 必须是正整数。")
    if value > maximum:
        raise ValueError(f"参数 `{name}` 不能超过上限 {maximum}。")
    return value


def _optional_float(params: ToolParams, name: str, default: float, maximum: float) -> float:
    value = params.get(name, default)
    if not isinstance(value, int | float) or float(value) <= 0:
        raise ValueError(f"参数 `{name}` 必须是正数。")
    value_float = float(value)
    if value_float > maximum:
        raise ValueError(f"参数 `{name}` 不能超过上限 {maximum}。")
    return value_float


async def _create_command_process(command: str, context: ToolContext) -> asyncio.subprocess.Process:
    if os.name == "nt":
        return await asyncio.create_subprocess_exec(
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command,
            cwd=context.workspace,
            env=_safe_command_env(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    return await asyncio.create_subprocess_shell(
        command,
        cwd=context.workspace,
        env=_safe_command_env(),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )


def _command_error_message(returncode: int, stdout: str, stderr: str) -> str:
    detail = stderr.strip() or stdout.strip()
    if detail:
        detail, _ = truncate_text(detail, 1000)
        return f"命令退出码 {returncode}：{detail}"
    return f"命令退出码 {returncode}。"


def _relative_path(path: Path, workspace: Path) -> str:
    return path.resolve(strict=False).relative_to(workspace.resolve(strict=False)).as_posix()


class ReadFileTool:
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="ReadFile",
            description="读取工作区内指定 UTF-8 文本文件内容。",
            parameters_schema=_schema(
                {
                    "path": {"type": "string", "description": "工作区内文件路径。"},
                    "max_chars": {"type": "integer", "minimum": 1},
                },
                ["path"],
            ),
            confirmation=ConfirmationPolicy.NEVER,
            category=ToolCategory.FILE,
            read_only=True,
            destructive=False,
            typical_scenarios=("查看文件内容", "读取配置"),
            aliases=("read_file",),
        )

    async def run(self, params: ToolParams, context: ToolContext) -> ToolResult:
        started = monotonic()
        try:
            path = resolve_workspace_path(context.workspace, _required_str(params, "path"))
            max_chars = _optional_int(
                params, "max_chars", context.max_output_chars, context.max_output_chars
            )
            content = ensure_text_file(path)
            output, truncated = truncate_text(content, max_chars)
            return _success(
                self.spec.name,
                f"已读取文件 {_relative_path(path, context.workspace)}。",
                {
                    "path": _relative_path(path, context.workspace),
                    "content": output,
                    "size_chars": len(content),
                    "truncated": truncated,
                },
                elapsed_ms=_elapsed_ms(started),
                truncated=truncated,
            )
        except (OSError, ToolSafetyError, ValueError) as exc:
            return _failure(self.spec.name, str(exc), elapsed_ms=_elapsed_ms(started))


class WriteFileTool:
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="WriteFile",
            description="向工作区内指定路径写入 UTF-8 文本，可创建或覆盖文件。",
            parameters_schema=_schema(
                {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "overwrite": {"type": "boolean"},
                },
                ["path", "content"],
            ),
            confirmation=ConfirmationPolicy.REQUIRED,
            category=ToolCategory.FILE,
            read_only=False,
            destructive=False,
            typical_scenarios=("创建新文件", "覆盖写入"),
            aliases=("write_file",),
        )

    async def run(self, params: ToolParams, context: ToolContext) -> ToolResult:
        started = monotonic()
        try:
            path = resolve_workspace_path(context.workspace, _required_str(params, "path"))
            content = _required_str(params, "content")
            overwrite = _optional_bool(params, "overwrite", False)
            if path.exists() and not path.is_file():
                raise ToolSafetyError(f"目标不是文件：{path}")
            if path.exists() and not overwrite:
                raise ToolSafetyError("目标文件已存在，未设置 overwrite=true。")
            path.parent.mkdir(parents=True, exist_ok=True)
            existed = path.exists()
            path.write_text(content, encoding="utf-8")
            return _success(
                self.spec.name,
                f"已写入文件 {_relative_path(path, context.workspace)}。",
                {
                    "path": _relative_path(path, context.workspace),
                    "chars_written": len(content),
                    "overwrote": existed,
                },
                elapsed_ms=_elapsed_ms(started),
            )
        except (OSError, ToolSafetyError, ValueError) as exc:
            return _failure(self.spec.name, str(exc), elapsed_ms=_elapsed_ms(started))


class EditFileTool:
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="EditFile",
            description="在工作区文本文件中执行原文唯一匹配替换。",
            parameters_schema=_schema(
                {
                    "path": {"type": "string"},
                    "old_text": {"type": "string"},
                    "new_text": {"type": "string"},
                },
                ["path", "old_text", "new_text"],
            ),
            confirmation=ConfirmationPolicy.REQUIRED,
            category=ToolCategory.FILE,
            read_only=False,
            destructive=False,
            typical_scenarios=("精确修改文件某几行", "节省 token"),
            aliases=("edit_file",),
        )

    async def run(self, params: ToolParams, context: ToolContext) -> ToolResult:
        started = monotonic()
        try:
            path = resolve_workspace_path(context.workspace, _required_str(params, "path"))
            old_text = _required_str(params, "old_text")
            new_text = params.get("new_text")
            if not isinstance(new_text, str):
                raise ValueError("参数 `new_text` 必须是字符串。")
            content = ensure_text_file(path)
            count = content.count(old_text)
            if count != 1:
                raise ToolSafetyError(f"旧文本出现 {count} 次，必须恰好出现一次才允许替换。")
            updated = content.replace(old_text, new_text, 1)
            path.write_text(updated, encoding="utf-8")
            return _success(
                self.spec.name,
                f"已修改文件 {_relative_path(path, context.workspace)}。",
                {
                    "path": _relative_path(path, context.workspace),
                    "old_chars": len(old_text),
                    "new_chars": len(new_text),
                },
                elapsed_ms=_elapsed_ms(started),
            )
        except (OSError, ToolSafetyError, ValueError) as exc:
            return _failure(self.spec.name, str(exc), elapsed_ms=_elapsed_ms(started))


class RunCommandTool:
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="Bash",
            description=(
                "在工作区内执行一次性 shell 命令，返回退出码和输出。"
                "Windows 环境下执行 PowerShell 命令，其他系统执行默认 shell 命令。"
                "该工具可执行任意 shell 命令，可能产生文件修改、删除、进程启动等副作用。"
            ),
            parameters_schema=_schema(
                {
                    "command": {"type": "string"},
                    "timeout_seconds": {
                        "type": "number",
                        "exclusiveMinimum": 0,
                        "maximum": 10,
                        "description": "命令超时时间，不能超过系统上限；TUI 默认上限 10 秒。",
                    },
                    "max_output_chars": {"type": "integer", "minimum": 1},
                },
                ["command"],
            ),
            confirmation=ConfirmationPolicy.REQUIRED,
            category=ToolCategory.SHELL,
            read_only=False,
            destructive=True,
            typical_scenarios=("编译", "测试", "安装依赖", "执行命令"),
            aliases=("run_command", "bash"),
        )

    async def run(self, params: ToolParams, context: ToolContext) -> ToolResult:
        started = monotonic()
        try:
            command = _required_str(params, "command")
            timeout_seconds = _optional_float(
                params, "timeout_seconds", context.timeout_seconds, context.timeout_seconds
            )
            max_output_chars = _optional_int(
                params,
                "max_output_chars",
                context.max_output_chars,
                context.max_output_chars,
            )
            process = await _create_command_process(command, context)
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    process.communicate(), timeout_seconds
                )
            except TimeoutError:
                process.kill()
                await process.communicate()
                return _failure(
                    self.spec.name,
                    f"命令执行超时（>{timeout_seconds:g}s）。",
                    elapsed_ms=_elapsed_ms(started),
                )

            stdout = _decode_output(stdout_bytes)
            stderr = _decode_output(stderr_bytes)
            stdout, stdout_truncated = truncate_text(stdout, max_output_chars)
            stderr, stderr_truncated = truncate_text(stderr, max_output_chars)
            truncated = stdout_truncated or stderr_truncated
            returncode = process.returncode if process.returncode is not None else -1
            data = {
                "command": command,
                "returncode": returncode,
                "stdout": stdout,
                "stderr": stderr,
                "stdout_truncated": stdout_truncated,
                "stderr_truncated": stderr_truncated,
            }
            if returncode == 0:
                return _success(
                    self.spec.name,
                    f"命令执行完成，退出码 {returncode}。",
                    data,
                    elapsed_ms=_elapsed_ms(started),
                    truncated=truncated,
                )
            return ToolResult(
                tool_call_id="",
                tool_name=self.spec.name,
                ok=False,
                summary=f"命令执行失败，退出码 {returncode}。",
                data=data,
                error=_command_error_message(returncode, stdout, stderr),
                elapsed_ms=_elapsed_ms(started),
                truncated=truncated,
            )
        except (OSError, ValueError) as exc:
            return _failure(self.spec.name, str(exc), elapsed_ms=_elapsed_ms(started))


class GlobFilesTool:
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="Glob",
            description="按 glob 模式查找工作区内文件路径。",
            parameters_schema=_schema(
                {
                    "pattern": {"type": "string"},
                    "max_results": {"type": "integer", "minimum": 1},
                },
                ["pattern"],
            ),
            confirmation=ConfirmationPolicy.NEVER,
            category=ToolCategory.SEARCH,
            read_only=True,
            destructive=False,
            typical_scenarios=("了解项目结构", "查找特定类型文件"),
            aliases=("glob_files", "glob"),
        )

    async def run(self, params: ToolParams, context: ToolContext) -> ToolResult:
        started = monotonic()
        try:
            pattern = _required_str(params, "pattern")
            if Path(pattern).is_absolute() or has_parent_traversal(pattern):
                raise ToolSafetyError("glob 模式必须是工作区内相对路径，且不能包含 `..`。")
            max_results = _optional_int(
                params, "max_results", context.max_search_results, context.max_search_results
            )
            matches: list[str] = []
            for path in sorted(context.workspace.glob(pattern), key=lambda item: item.as_posix()):
                if not path.is_file() or is_ignored_path(path, context.workspace):
                    continue
                matches.append(_relative_path(path, context.workspace))
                if len(matches) >= max_results:
                    break
            total = sum(
                1
                for path in context.workspace.glob(pattern)
                if path.is_file() and not is_ignored_path(path, context.workspace)
            )
            truncated = total > len(matches)
            return _success(
                self.spec.name,
                f"找到 {len(matches)} 个文件。",
                {"pattern": pattern, "matches": matches, "total": total},
                elapsed_ms=_elapsed_ms(started),
                truncated=truncated,
            )
        except (OSError, ToolSafetyError, ValueError) as exc:
            return _failure(self.spec.name, str(exc), elapsed_ms=_elapsed_ms(started))


class SearchCodeTool:
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="Grep",
            description="在工作区文本文件中搜索文本或正则模式。",
            parameters_schema=_schema(
                {
                    "pattern": {"type": "string"},
                    "path_glob": {"type": "string"},
                    "regex": {"type": "boolean"},
                    "max_results": {"type": "integer", "minimum": 1},
                },
                ["pattern"],
            ),
            confirmation=ConfirmationPolicy.NEVER,
            category=ToolCategory.SEARCH,
            read_only=True,
            destructive=False,
            typical_scenarios=("搜索代码中的函数定义", "搜索变量引用"),
            aliases=("search_code", "grep"),
        )

    async def run(self, params: ToolParams, context: ToolContext) -> ToolResult:
        started = monotonic()
        try:
            pattern = _required_str(params, "pattern")
            path_glob = params.get("path_glob", "**/*")
            if not isinstance(path_glob, str) or path_glob == "":
                raise ValueError("参数 `path_glob` 必须是非空字符串。")
            if Path(path_glob).is_absolute() or has_parent_traversal(path_glob):
                raise ToolSafetyError("搜索范围必须是工作区内相对路径，且不能包含 `..`。")
            regex = _optional_bool(params, "regex", False)
            max_results = _optional_int(
                params, "max_results", context.max_search_results, context.max_search_results
            )
            matcher = re.compile(pattern) if regex else None
            results: list[dict[str, Any]] = []
            total = 0
            for path in _iter_candidate_files(context.workspace, path_glob):
                if is_ignored_path(path, context.workspace):
                    continue
                try:
                    content = ensure_text_file(path)
                except (OSError, ToolSafetyError):
                    continue
                for line_no, line in enumerate(content.splitlines(), start=1):
                    matched = bool(matcher.search(line)) if matcher is not None else pattern in line
                    if not matched:
                        continue
                    total += 1
                    if len(results) < max_results:
                        snippet, snippet_truncated = truncate_text(line, 240)
                        results.append(
                            {
                                "path": _relative_path(path, context.workspace),
                                "line": line_no,
                                "snippet": snippet,
                                "truncated": snippet_truncated,
                            }
                        )
            truncated = total > len(results)
            return _success(
                self.spec.name,
                f"找到 {total} 处匹配。",
                {
                    "pattern": pattern,
                    "path_glob": path_glob,
                    "regex": regex,
                    "matches": results,
                    "total": total,
                },
                elapsed_ms=_elapsed_ms(started),
                truncated=truncated,
            )
        except (OSError, ToolSafetyError, ValueError, re.error) as exc:
            return _failure(self.spec.name, str(exc), elapsed_ms=_elapsed_ms(started))


def _iter_candidate_files(workspace: Path, path_glob: str) -> Iterable[Path]:
    for path in sorted(workspace.glob(path_glob), key=lambda item: item.as_posix()):
        if path.is_file():
            yield path


def _decode_output(data: bytes) -> str:
    for encoding in ("utf-8-sig", locale.getpreferredencoding(False)):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _safe_command_env() -> dict[str, str]:
    allowed_keys = {
        "COMSPEC",
        "HOMEDRIVE",
        "HOMEPATH",
        "LOCALAPPDATA",
        "PATH",
        "PATHEXT",
        "PSMODULEPATH",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "WINDIR",
    }
    return {key: value for key, value in os.environ.items() if key.upper() in allowed_keys}


