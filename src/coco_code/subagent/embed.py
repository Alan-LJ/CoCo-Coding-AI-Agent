from __future__ import annotations

from importlib.resources import files

from coco_code.subagent.definition import Definition, Source
from coco_code.subagent.parser import parse_definition


def builtin_definitions() -> list[Definition]:
    package = files("coco_code.subagent.builtin")
    definitions: list[Definition] = []
    for resource in sorted(package.iterdir(), key=lambda item: item.name.casefold()):
        if not resource.name.endswith(".md"):
            continue
        definitions.append(
            parse_definition(
                resource.read_bytes(),
                f"builtin:{resource.name}",
                Source.BUILTIN,
            )
        )
    return sorted(definitions, key=lambda definition: definition.name.casefold())
