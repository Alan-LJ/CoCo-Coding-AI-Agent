from __future__ import annotations

import asyncio
import io
from types import SimpleNamespace
from typing import Any

from mcp.types import TextContent

from coco_code.mcp import tool as mcp_tool
from coco_code.mcp.tool import McpTool, adapt_tool, tool_full_name
from coco_code.tools import ConfirmationPolicy, ToolContext


class FakeCaller:
    def __init__(
        self,
        result: Any | None = None,
        *,
        exc: Exception | None = None,
        delay: float = 0,
    ) -> None:
        self.result = result
        self.exc = exc
        self.delay = delay
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        self.calls.append((name, arguments))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.exc is not None:
            raise self.exc
        return self.result or SimpleNamespace(content=[], isError=False)


def _remote(
    name: str = "search",
    *,
    description: str = "",
    schema: Any | None = None,
    annotations: Any | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        description=description,
        inputSchema=schema,
        annotations=annotations,
    )


def _tool(
    caller: FakeCaller,
    *,
    name: str = "mcp__demo__search",
    read_only: bool = False,
    stderr: io.StringIO | None = None,
) -> McpTool:
    return McpTool(
        full_name=name,
        server_name="demo",
        remote_name="search",
        description="demo search",
        parameters_schema={"type": "object", "properties": {}},
        read_only=read_only,
        caller=caller,
        stderr=stderr or io.StringIO(),
    )


def test_tool_full_name_and_adapted_metadata() -> None:
    caller = FakeCaller()
    remote = _remote(
        description="",
        schema={"type": "object", "properties": {"q": {"type": "string"}}},
        annotations={"readOnlyHint": True},
    )

    tool = adapt_tool("github", remote, caller, stderr=io.StringIO())

    assert tool is not None
    assert tool.full_name == tool_full_name("github", "search")
    assert tool.description == "MCP tool search from server github"
    assert tool.parameters_schema["properties"]["q"]["type"] == "string"
    assert tool.read_only is True
    assert tool.spec.confirmation == ConfirmationPolicy.NEVER
    assert tool.spec.timeout_seconds == mcp_tool.OUTER_EXECUTOR_TIMEOUT_SECONDS


def test_adapt_tool_skips_missing_or_illegal_names() -> None:
    stderr = io.StringIO()

    assert adapt_tool("demo", _remote(""), FakeCaller(), stderr=stderr) is None
    assert adapt_tool("demo", _remote("bad.name"), FakeCaller(), stderr=stderr) is None

    output = stderr.getvalue()
    assert "missing name" in output
    assert "illegal" in output


def test_adapt_tool_schema_fallback_and_read_only_variants() -> None:
    caller = FakeCaller()

    fallback = adapt_tool(
        "demo",
        _remote(schema=None, annotations=SimpleNamespace(read_only_hint=True)),
        caller,
        stderr=io.StringIO(),
    )
    unsafe = adapt_tool(
        "demo",
        _remote("write", schema="bad", annotations={"readOnlyHint": False}),
        caller,
        stderr=io.StringIO(),
    )

    assert fallback is not None
    assert fallback.parameters_schema == {"type": "object", "properties": {}}
    assert fallback.spec.confirmation == ConfirmationPolicy.NEVER
    assert unsafe is not None
    assert unsafe.parameters_schema == {"type": "object", "properties": {}}
    assert unsafe.spec.confirmation == ConfirmationPolicy.REQUIRED


def test_run_passes_arguments_and_collects_text_content(tmp_path) -> None:
    caller = FakeCaller(
        SimpleNamespace(
            content=[
                TextContent(type="text", text="first"),
                TextContent(type="text", text="second"),
            ],
            isError=False,
        )
    )
    tool = _tool(caller, read_only=True)

    result = asyncio.run(tool.run({"q": "agent"}, ToolContext(workspace=tmp_path)))

    assert caller.calls == [("search", {"q": "agent"})]
    assert result.ok is True
    assert result.summary == "first"
    assert result.data["content"] == "first\nsecond"


def test_run_passes_none_for_empty_arguments(tmp_path) -> None:
    caller = FakeCaller(SimpleNamespace(content=[], isError=False))
    tool = _tool(caller)

    result = asyncio.run(tool.run({}, ToolContext(workspace=tmp_path)))

    assert result.ok is True
    assert caller.calls == [("search", None)]


def test_run_maps_remote_error_to_failed_tool_result(tmp_path) -> None:
    caller = FakeCaller(
        SimpleNamespace(
            content=[TextContent(type="text", text="remote failed")],
            isError=True,
        )
    )
    tool = _tool(caller)

    result = asyncio.run(tool.run({"x": 1}, ToolContext(workspace=tmp_path)))

    assert result.ok is False
    assert result.error == "remote failed"
    assert result.data["content"] == "remote failed"


def test_run_drops_non_text_content_and_warns_once_per_tool(tmp_path) -> None:
    stderr = io.StringIO()
    caller = FakeCaller(
        SimpleNamespace(
            content=[
                SimpleNamespace(type="image", data="base64"),
                TextContent(type="text", text="ok"),
            ],
            isError=False,
        )
    )
    tool = _tool(caller, name="mcp__demo__non_text_once", stderr=stderr)

    first = asyncio.run(tool.run({}, ToolContext(workspace=tmp_path)))
    second = asyncio.run(tool.run({}, ToolContext(workspace=tmp_path)))

    assert first.data["content"] == "ok"
    assert second.data["content"] == "ok"
    assert stderr.getvalue().count("non-text") == 1


def test_run_converts_sdk_exception_to_failed_tool_result(tmp_path) -> None:
    tool = _tool(FakeCaller(exc=RuntimeError("transport down")))

    result = asyncio.run(tool.run({}, ToolContext(workspace=tmp_path)))

    assert result.ok is False
    assert "transport down" in (result.error or "")


def test_run_converts_timeout_to_failed_tool_result(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(mcp_tool, "CALL_TIMEOUT_SECONDS", 0.01)
    tool = _tool(FakeCaller(delay=1))

    result = asyncio.run(tool.run({}, ToolContext(workspace=tmp_path)))

    assert result.ok is False
    assert result.data["timeout"] is True
    assert "timed out" in (result.error or "")
