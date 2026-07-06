from __future__ import annotations

import pytest

from coco_code.tools import ConfirmationPolicy, ToolCategory, ToolSpec, create_default_registry
from coco_code.tools.base import ToolContext, ToolParams, ToolResult
from coco_code.tools.registry import ToolRegistry, ToolRegistryError


class DummyTool:
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="dummy",
            description="dummy tool",
            parameters_schema={
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
            confirmation=ConfirmationPolicy.NEVER,
        )

    async def run(self, params: ToolParams, context: ToolContext) -> ToolResult:  # noqa: ARG002
        return ToolResult("", "dummy", True, "ok", {}, None, 0)


def test_default_registry_contains_six_core_tools() -> None:
    registry = create_default_registry()
    names = {spec.name for spec in registry.list_specs()}
    assert names == {"ReadFile", "WriteFile", "EditFile", "Bash", "Glob", "Grep"}


def test_default_registry_confirmation_policies() -> None:
    registry = create_default_registry()
    policies = {spec.name: spec.confirmation for spec in registry.list_specs()}
    assert policies["ReadFile"] == ConfirmationPolicy.NEVER
    assert policies["Glob"] == ConfirmationPolicy.NEVER
    assert policies["Grep"] == ConfirmationPolicy.NEVER
    assert policies["WriteFile"] == ConfirmationPolicy.REQUIRED
    assert policies["EditFile"] == ConfirmationPolicy.REQUIRED
    assert policies["Bash"] == ConfirmationPolicy.REQUIRED


def test_default_registry_tool_metadata_matches_permission_table() -> None:
    registry = create_default_registry()
    specs = {spec.name: spec for spec in registry.list_specs()}
    expected = {
        "ReadFile": (ToolCategory.FILE, True, False),
        "WriteFile": (ToolCategory.FILE, False, False),
        "EditFile": (ToolCategory.FILE, False, False),
        "Bash": (ToolCategory.SHELL, False, True),
        "Glob": (ToolCategory.SEARCH, True, False),
        "Grep": (ToolCategory.SEARCH, True, False),
    }
    for name, (category, read_only, destructive) in expected.items():
        spec = specs[name]
        assert spec.category == category
        assert spec.read_only is read_only
        assert spec.destructive is destructive
        assert spec.typical_scenarios
        assert spec.system is False


def test_registry_rejects_duplicate_names() -> None:
    registry = ToolRegistry()
    registry.register(DummyTool())
    with pytest.raises(ToolRegistryError):
        registry.register(DummyTool())


def test_registry_get_unknown_tool_raises() -> None:
    with pytest.raises(ToolRegistryError):
        ToolRegistry().get("missing")


def test_registry_resolves_legacy_aliases_without_exposing_them_to_models() -> None:
    registry = create_default_registry()
    assert registry.get("read_file").spec.name == "ReadFile"
    assert registry.get("write_file").spec.name == "WriteFile"
    assert registry.get("edit_file").spec.name == "EditFile"
    assert registry.get("run_command").spec.name == "Bash"
    assert registry.get("glob_files").spec.name == "Glob"
    assert registry.get("search_code").spec.name == "Grep"
    exposed_names = {spec.name for spec in registry.list_specs()}
    assert "run_command" not in exposed_names
    assert "search_code" not in exposed_names


def test_registry_converts_to_openai_and_anthropic_formats() -> None:
    registry = create_default_registry()
    openai_tools = registry.to_openai_tools()
    anthropic_tools = registry.to_anthropic_tools()
    assert openai_tools[0]["type"] == "function"
    assert "parameters" in openai_tools[0]["function"]
    assert "input_schema" in anthropic_tools[0]
    bash_openai = next(item for item in openai_tools if item["function"]["name"] == "Bash")
    bash_anthropic = next(item for item in anthropic_tools if item["name"] == "Bash")
    assert "category=shell" in bash_openai["function"]["description"]
    assert "read_only=false" in bash_openai["function"]["description"]
    assert "destructive=true" in bash_openai["function"]["description"]
    assert "PowerShell" in bash_openai["function"]["description"]
    assert "category=shell" in bash_anthropic["description"]
    assert "typical_scenarios=" in bash_anthropic["description"]
    assert {item["function"]["name"] for item in openai_tools} == {
        item["name"] for item in anthropic_tools
    }
