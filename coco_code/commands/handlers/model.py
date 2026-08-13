from __future__ import annotations

from coco_code.commands.registry import Command, CommandContext, CommandType


async def handle_model(ctx: CommandContext) -> None:
    providers = ctx.config.get("providers", [])
    selected_getter = ctx.config.get("selected_provider")
    selected = selected_getter() if selected_getter else None

    selector = ctx.args.strip()
    if not selector:
        lines = ["可用模型："]
        for provider in providers:
            marker = "●" if provider is selected else "○"
            lines.append(f"  {marker} {provider.name}: {provider.model}")
        lines.append("使用 /model <名称> 切换，例如 /model deepseek-v4-flash")
        ctx.ui.add_system_message("\n".join(lines))
        return

    switcher = ctx.config.get("switch_provider")
    if switcher is None:
        ctx.ui.add_system_message("当前界面不支持运行时模型切换。")
        return
    result = await switcher(selector)
    ctx.ui.add_system_message(result)


MODEL_COMMAND = Command(
    name="model",
    aliases=["models"],
    description="查看或切换当前模型",
    usage="/model [provider-or-model]",
    type=CommandType.LOCAL_UI,
    handler=handle_model,
)
