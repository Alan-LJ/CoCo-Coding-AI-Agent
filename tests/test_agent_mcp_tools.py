from __future__ import annotations

from typing import Any

from coco_code.agent import AgentMode
from coco_code.agent.tools import ToolBatcher
from coco_code.mcp.tool import McpTool
from coco_code.tools import ConfirmationPolicy, ToolCall, ToolSpec
from coco_code.tools.registry import ToolRegistry


class FakeCaller:
    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:  # noqa: ARG002
        return None


class SideEffectTool:
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="side_effect",
            description="side effect",
            parameters_schema={"type": "object", "properties": {}},
            confirmation=ConfirmationPolicy.REQUIRED,
            read_only=False,
        )

    async def run(self, params, context):  # noqa: ANN001, ARG002
        raise AssertionError("not executed")


def test_tool_batcher_groups_read_only_mcp_tools_with_read_batch() -> None:
    registry = ToolRegistry()
    registry.register(
        McpTool(
            full_name="mcp__demo__list_items",
            server_name="demo",
            remote_name="list_items",
            description="list items",
            parameters_schema={"type": "object", "properties": {}},
            read_only=True,
            caller=FakeCaller(),
        )
    )
    registry.register(SideEffectTool())
    calls = [
        ToolCall("1", "mcp__demo__list_items", {}, "{}"),
        ToolCall("2", "side_effect", {}, "{}"),
    ]

    batches = ToolBatcher().build_batches(calls, registry, AgentMode.AGENT)

    assert [batch.concurrent for batch in batches] == [True, False]
    assert [batch.calls[0].name for batch in batches] == ["mcp__demo__list_items", "side_effect"]
