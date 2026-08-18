
from __future__ import annotations

from coco_code.commands.handlers.clear import CLEAR_COMMAND
from coco_code.commands.handlers.compact import COMPACT_COMMAND
from coco_code.commands.handlers.help import HELP_COMMAND
from coco_code.commands.handlers.mcp import MCP_COMMAND
from coco_code.commands.handlers.memory import MEMORY_COMMAND
from coco_code.commands.handlers.model import MODEL_COMMAND
from coco_code.commands.handlers.permission import PERMISSION_COMMAND
from coco_code.commands.handlers.plan import PLAN_COMMAND
from coco_code.commands.handlers.sandbox import SANDBOX_COMMAND
from coco_code.commands.handlers.session import SESSION_COMMAND
from coco_code.commands.handlers.skill import SKILL_COMMAND
from coco_code.commands.handlers.rewind import REWIND_COMMAND
from coco_code.commands.handlers.status import STATUS_COMMAND
from coco_code.commands.registry import CommandRegistry


ALL_COMMANDS = [
    HELP_COMMAND,
    COMPACT_COMMAND,
    CLEAR_COMMAND,
    PLAN_COMMAND,
    SESSION_COMMAND,
    MCP_COMMAND,
    MEMORY_COMMAND,
    MODEL_COMMAND,
    PERMISSION_COMMAND,
    SANDBOX_COMMAND,
    REWIND_COMMAND,
    STATUS_COMMAND,
    SKILL_COMMAND,
]


def register_all_commands(registry: CommandRegistry) -> None:
    for cmd in ALL_COMMANDS:
        registry.register_sync(cmd)
