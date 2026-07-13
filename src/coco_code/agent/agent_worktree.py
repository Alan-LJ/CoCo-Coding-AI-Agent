from __future__ import annotations

from pathlib import Path
from typing import Any

from coco_code.conversation import Conversation
from coco_code.subagent import Definition
from coco_code.tools.ctx import cwd_from_ctx, with_cwd
from coco_code.worktree import Manager, random_agent_name


def build_worktree_notice(parent_cwd: str, wt_path: str) -> str:
    return (
        "<worktree-context>\n"
        f"父工作目录: {parent_cwd}\n"
        f"当前隔离工作目录: {wt_path}\n"
        "所有相对路径文件操作都会解析到当前隔离工作目录。"
        "\n</worktree-context>"
    )


async def _execute_with_worktree(
    manager: Manager,
    definition: Definition,
    sub_agent: Any,
    sub_conv: Conversation,
    prompt: str,
    events: Any = None,
) -> str:
    name = random_agent_name()
    wt = await manager.create(name, "HEAD", manual=False)
    parent_cwd = cwd_from_ctx() or str(Path.cwd())
    task_text = build_worktree_notice(parent_cwd, wt.path) + "\n\n" + prompt
    with with_cwd(wt.path):
        final_text = await sub_agent.run_to_completion(sub_conv, task_text, events=events)
    report = await manager.auto_cleanup(name)
    if report.kept:
        return (
            final_text.rstrip()
            + f"\n\n[Worktree 保留: {report.path}, 分支 {report.branch}]"
        )
    return final_text
