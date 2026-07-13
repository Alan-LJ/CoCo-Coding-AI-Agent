from __future__ import annotations

from coco_code.command.types import CommandContext, CommandUI


async def handle_worktree(context: CommandContext, ui: CommandUI) -> None:
    accessor = ui.worktree_accessor()
    if accessor is None:
        ui.show_error("Worktree 功能未启用。")
        return
    parts = context.args.split()
    if not parts:
        ui.show_message(_usage())
        return
    command = parts[0].lower()
    args = parts[1:]
    try:
        if command == "create":
            if len(args) != 1:
                ui.show_error("用法: /worktree create <name>")
                return
            path, branch = await accessor.create(args[0])
            ui.show_message(f"Worktree 已创建: {path} (分支 {branch})")
            return
        if command == "list":
            items = accessor.list()
            if not items:
                ui.show_message("没有 Worktree。")
                return
            lines = ["Worktrees:"]
            for item in items:
                flags = []
                if item.active:
                    flags.append("active")
                if item.manual:
                    flags.append("manual")
                suffix = f" [{' '.join(flags)}]" if flags else ""
                lines.append(f"- {item.name}{suffix} {item.path} ({item.branch})")
            ui.show_message("\n".join(lines))
            return
        if command == "enter":
            if len(args) != 1:
                ui.show_error("用法: /worktree enter <name>")
                return
            await accessor.enter(args[0])
            current = next((item for item in accessor.list() if item.name == args[0]), None)
            path = current.path if current is not None else args[0]
            ui.show_message(f"已进入 {args[0]}: {path}")
            return
        if command == "exit":
            remove = "--remove" in args
            discard = "--discard" in args
            removed = await accessor.exit("remove" if remove else "keep", discard)
            ui.show_message("已退出并删除 Worktree。" if removed else "已退出 Worktree。")
            return
        if command == "remove":
            if not args:
                ui.show_error("用法: /worktree remove <name> [--discard]")
                return
            name = args[0]
            discard = "--discard" in args[1:]
            await accessor.remove(name, discard)
            ui.show_message(f"Worktree 已删除: {name}")
            return
    except Exception as exc:
        ui.show_error(str(exc))
        return
    ui.show_error(f"未知 worktree 子命令: {command}")


def _usage() -> str:
    return (
        "用法:\n"
        "/worktree create <name>\n"
        "/worktree list\n"
        "/worktree enter <name>\n"
        "/worktree exit [--remove] [--discard]\n"
        "/worktree remove <name> [--discard]"
    )
