from __future__ import annotations

from collections.abc import Callable
from typing import Any

from coco_code.tools.base import Tool, ToolSpec
from coco_code.tools.builtin import (
    EditFileTool,
    GlobFilesTool,
    ReadFileTool,
    RunCommandTool,
    SearchCodeTool,
    WriteFileTool,
)


class ToolRegistryError(ValueError):
    pass


def describe_tool_for_model(spec: ToolSpec) -> str:
    read_only = str(spec.read_only).lower()
    destructive = str(spec.destructive).lower()
    scenarios = "、".join(spec.typical_scenarios) if spec.typical_scenarios else "未标注"
    return (
        f"{spec.description}\n\n"
        "元信息："
        f"category={spec.category.value}; "
        f"read_only={read_only}; "
        f"destructive={destructive}; "
        f"confirmation={spec.confirmation.value}; "
        f"typical_scenarios={scenarios}."
    )


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._aliases: dict[str, str] = {}

    def register(self, tool: Tool) -> None:
        spec = tool.spec
        name = spec.name
        if name in self._tools or name in self._aliases:
            raise ToolRegistryError(f"工具已注册：{name}")
        for alias in spec.aliases:
            if alias in self._tools or alias in self._aliases:
                raise ToolRegistryError(f"工具别名已注册：{alias}")
        self._tools[name] = tool
        for alias in spec.aliases:
            self._aliases[alias] = name

    def get(self, name: str) -> Tool:
        canonical_name = self._aliases.get(name, name)
        try:
            return self._tools[canonical_name]
        except KeyError as exc:
            raise ToolRegistryError(f"未知工具：{name}") from exc

    def list_specs(self) -> list[ToolSpec]:
        return [tool.spec for tool in self._tools.values()]

    def count(self) -> int:
        return len(self._tools)

    def filtered(self, predicate: Callable[[ToolSpec], bool]) -> ToolRegistry:
        registry = ToolRegistry()
        for tool in self._tools.values():
            if predicate(tool.spec):
                registry.register(tool)
        return registry

    def to_openai_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": describe_tool_for_model(spec),
                    "parameters": spec.parameters_schema,
                },
            }
            for spec in self.list_specs()
        ]

    def to_anthropic_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": spec.name,
                "description": describe_tool_for_model(spec),
                "input_schema": spec.parameters_schema,
            }
            for spec in self.list_specs()
        ]


def create_default_registry() -> ToolRegistry:
    registry = ToolRegistry()
    for tool in (
        ReadFileTool(),
        WriteFileTool(),
        EditFileTool(),
        RunCommandTool(),
        GlobFilesTool(),
        SearchCodeTool(),
    ):
        registry.register(tool)
    return registry
