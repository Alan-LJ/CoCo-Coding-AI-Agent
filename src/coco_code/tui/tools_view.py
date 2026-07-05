from __future__ import annotations

from rich.panel import Panel
from rich.text import Text

from coco_code.tools.base import ConfirmationPolicy, ToolSpec
from coco_code.tools.registry import ToolRegistry


def tool_list_block(registry: ToolRegistry) -> Panel:
    specs = sorted(registry.list_specs(), key=lambda spec: spec.name.casefold())
    text = Text()
    if not specs:
        text.append("No tools registered.", style="yellow")
    for spec in specs:
        text.append(spec.name, style="bold cyan")
        text.append(f"  {spec.category.value}", style="dim")
        text.append(
            "  read-only" if spec.read_only else "  execute",
            style="green" if spec.read_only else "yellow",
        )
        if spec.destructive:
            text.append("  destructive", style="red")
        if spec.confirmation == ConfirmationPolicy.REQUIRED:
            text.append("  confirm", style="red")
        text.append("\n")
        text.append(f"  {spec.description}\n", style="white")
    return Panel(text, title="Available Tools", border_style="cyan")


def tool_summary(spec: ToolSpec) -> str:
    mode = "read-only" if spec.read_only else "execute"
    confirm = "confirm" if spec.confirmation == ConfirmationPolicy.REQUIRED else "no-confirm"
    return f"{spec.name} · {spec.category.value} · {mode} · {confirm}"
