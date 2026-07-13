from __future__ import annotations

import builtins
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TextIO

from coco_code.permission import Mode as PermissionMode
from coco_code.subagent.definition import Definition, Source
from coco_code.subagent.embed import builtin_definitions
from coco_code.subagent.parser import SubagentParseError, parse_file

PROJECT_AGENTS_DIR = Path(".coco-code") / "agents"
USER_AGENTS_DIR = Path.home() / ".coco-code" / "agents"


@dataclass
class Catalog:
    _definitions: dict[str, Definition] = field(default_factory=dict)
    _by_source: dict[Source, list[Definition]] = field(default_factory=dict)

    def add_all(self, definitions: list[Definition]) -> None:
        for definition in definitions:
            self.add(definition)

    def add(self, definition: Definition) -> None:
        key = definition.name.casefold()
        current = self._definitions.get(key)
        if current is None or definition.source.priority >= current.source.priority:
            self._definitions[key] = definition
        self._by_source.setdefault(definition.source, []).append(definition)

    def resolve(self, name: str) -> Definition | None:
        return self._definitions.get(name.casefold())

    def list(self) -> list[Definition]:
        return [self._definitions[key] for key in sorted(self._definitions)]

    def list_by_source(self, source: Source) -> builtins.list[Definition]:
        return sorted(
            self._by_source.get(source, []),
            key=lambda definition: definition.name.casefold(),
        )

    def fork_definition(self) -> Definition:
        return Definition(
            name="__fork__",
            description="Fork-based SubAgent",
            model="inherit",
            max_turns=25,
            permission_mode=PermissionMode.DEFAULT,
            source=Source.BUILTIN,
        )


def load_catalog(root: str | Path, *, stderr: TextIO | None = None) -> Catalog:
    stderr = stderr or sys.stderr
    catalog = Catalog()
    catalog.add_all(builtin_definitions())
    catalog.add_all(_load_from_dir(Path.home() / ".coco-code" / "agents", Source.USER, stderr))
    catalog.add_all(_load_from_dir(Path(root) / PROJECT_AGENTS_DIR, Source.PROJECT, stderr))
    return catalog


def _load_from_dir(path: Path, source: Source, stderr: TextIO) -> list[Definition]:
    if not path.exists():
        return []
    if not path.is_dir():
        print(f"[subagent] warn: skipping {source} path {path}: not a directory", file=stderr)
        return []
    definitions: list[Definition] = []
    for child in sorted(path.glob("*.md"), key=lambda item: item.name.casefold()):
        try:
            definitions.append(parse_file(child, source))
        except (OSError, SubagentParseError, ValueError) as exc:
            print(f"[subagent] warn: skipping {source} definition {child}: {exc}", file=stderr)
    return definitions


