from __future__ import annotations

from coco_code.command.types import ParsedCommand


def parse_command(text: str) -> ParsedCommand:
    stripped = text.strip()
    if not stripped or not stripped.startswith("/"):
        return ParsedCommand(is_command=False, raw=stripped)

    body = stripped[1:]
    if not body:
        return ParsedCommand(is_command=True, raw=stripped)

    parts = body.split(maxsplit=1)
    name = parts[0].strip().lower()
    args = parts[1].strip() if len(parts) > 1 else ""
    return ParsedCommand(is_command=True, name=name, args=args, raw=stripped)
