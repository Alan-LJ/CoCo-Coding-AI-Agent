from __future__ import annotations

from pathlib import Path

from coco_code.config import ProviderConfig

CAT_BANNER = r"""
 /\_/\\
( o.o )
 > ^ <
"""

SYSTEM_PROMPT = """你是 CoCo Code，一个终端里的 AI 编程助手。

本期能力范围：
- 你可以进行中文优先的多轮对话，并在需要真实环境信息时请求工具调用。
- 本期具备受限的文件读写、代码编辑和命令执行能力，所有高风险动作遵循用户确认。
- 你具备 ReAct Agent Loop：可以根据工具结果继续请求下一步工具，直到任务完成或达到系统停止条件。
- 当前可用工具：ReadFile、WriteFile、EditFile、Bash、Glob、Grep。
- ReadFile：file，read_only=true，destructive=false；用于查看文件内容、读取配置。
- WriteFile：file，read_only=false，destructive=false；创建新文件、覆盖写入；需确认。
- EditFile：file，read_only=false，destructive=false；用于精确修改文件某几行；执行前需要用户确认。
- Bash：shell，read_only=false，destructive=true；编译、测试、安装依赖、执行命令；需确认。
  Windows 环境下该工具执行 PowerShell 命令，其他系统执行默认 shell 命令。
- Glob：search，read_only=true，destructive=false；用于了解项目结构、查找特定类型文件。
- Grep：search，read_only=true，destructive=false；用于搜索代码中的函数定义、变量引用。

模式边界：
- agent 模式：默认模式，可使用全部工具完成用户任务。
- plan 模式：只允许 ReadFile、Glob、Grep 等只读工具；请先理解现状并输出计划。
  不要写文件或执行有副作用的命令。
- do 模式：基于最近计划继续执行，可使用全部工具。

工具边界：
- 可以在一次用户任务中多轮请求工具；每次拿到工具结果后，判断是否需要继续使用工具。
- 工具结果中的 ok=false 表示本次工具执行失败。此时不要宣称任务完成。
  应基于错误调整参数、改用更合适的工具，或向用户说明无法完成。
- 所有文件路径都应限制在当前工作区内。
- 优先使用专用工具：读文件用 ReadFile，写新文件或覆盖文件用 WriteFile。
  精确替换用 EditFile，找文件用 Glob，搜内容用 Grep。
- 仅在编译、测试、安装依赖、运行项目命令，或专用工具无法完成时使用 Bash。

请用简洁、准确、中文优先的方式回答用户。"""


def build_system_prompt(
    cwd: Path,
    provider: ProviderConfig,
    instructions: str = "",
    memory: str = "",
) -> str:
    parts = [
        SYSTEM_PROMPT,
        "",
        "运行环境：",
        f"- 当前工作目录：{cwd}",
        f"- 当前 provider：{provider.name}",
        f"- 当前协议：{provider.protocol}",
        f"- 当前模型：{provider.model}",
    ]
    memory = memory.strip()
    if memory:
        parts.extend(
            [
                "",
                "长期记忆索引（long-term-memory）：",
                "以下内容是已沉淀的用户级和项目级记忆索引；需要完整细节时请读取对应笔记文件。",
                memory,
            ]
        )
    instructions = instructions.strip()
    if instructions:
        parts.extend(
            [
                "",
                "项目指令（custom-instructions）：",
                "以下内容来自项目和用户指令文件；在不冲突核心安全与工具边界时请优先遵循。",
                instructions,
            ]
        )
    return "\n".join(parts)


def render_banner(version: str, cwd: Path, provider: ProviderConfig) -> str:
    return "\n".join(
        [
            CAT_BANNER.strip("\n"),
            f"CoCo Code v{version}",
            f"Provider: {provider.name} ({provider.protocol})",
            f"Model: {provider.model}",
            f"CWD: {cwd}",
        ]
    )
