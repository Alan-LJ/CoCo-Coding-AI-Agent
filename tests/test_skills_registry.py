from __future__ import annotations

from coco_code.tools import ConfirmationPolicy, ToolSpec
from coco_code.tools.base import ToolContext, ToolParams, ToolResult
from coco_code.tools.registry import ToolRegistry


class NamedTool:
    def __init__(self, name: str, *, system: bool = False, alias: str | None = None) -> None:
        self._spec = ToolSpec(
            name=name,
            description=name,
            parameters_schema={"type": "object", "properties": {}},
            confirmation=ConfirmationPolicy.NEVER,
            aliases=(alias,) if alias else (),
            system=system,
        )

    @property
    def spec(self) -> ToolSpec:
        return self._spec

    async def run(self, params: ToolParams, context: ToolContext) -> ToolResult:  # noqa: ARG002
        return ToolResult("", self._spec.name, True, "ok", {}, None, 0)


def test_filtered_by_names_preserves_system_tools() -> None:
    registry = ToolRegistry()
    registry.register(NamedTool("ReadFile"))
    registry.register(NamedTool("WriteFile"))
    registry.register(NamedTool("LoadSkill", system=True))

    filtered = registry.filtered_by_names(("ReadFile",))
    names = {spec.name for spec in filtered.list_specs()}

    assert names == {"ReadFile", "LoadSkill"}


def test_filtered_by_names_resolves_aliases() -> None:
    registry = ToolRegistry()
    registry.register(NamedTool("ReadFile", alias="read_file"))

    filtered = registry.filtered_by_names(("read_file",))

    assert filtered.names() == ("ReadFile",)
