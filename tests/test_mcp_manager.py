from __future__ import annotations

import asyncio
import io
from typing import Any

from coco_code.mcp import manager as manager_mod
from coco_code.mcp.config import McpConfig, ServerConfig
from coco_code.mcp.manager import ManagedSession, McpManager, _ConnectedServer
from coco_code.mcp.tool import McpTool


class FakeCaller:
    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:  # noqa: ARG002
        return None


class FakeStack:
    def __init__(self, *, delay: float = 0) -> None:
        self.delay = delay
        self.closed = False

    async def aclose(self) -> None:
        if self.delay:
            await asyncio.sleep(self.delay)
        self.closed = True


class FakeAsyncContext:
    def __init__(self, value: Any) -> None:
        self.value = value

    async def __aenter__(self) -> Any:
        return self.value

    async def __aexit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
        return False


def _tool(server_name: str, remote_name: str = "search") -> McpTool:
    return McpTool(
        full_name=f"mcp__{server_name}__{remote_name}",
        server_name=server_name,
        remote_name=remote_name,
        description="search",
        parameters_schema={"type": "object", "properties": {}},
        read_only=True,
        caller=FakeCaller(),
        stderr=io.StringIO(),
    )


def test_manager_start_skips_failed_servers_and_sorts_tools(monkeypatch) -> None:
    async def run() -> None:
        async def fake_connect(server: ServerConfig, version: str, stderr) -> _ConnectedServer:  # noqa: ARG001, ANN001
            if server.name == "bad":
                raise RuntimeError("boom")
            return _ConnectedServer(
                ManagedSession(server.name, object(), FakeStack()),
                [_tool(server.name, "z")],
            )

        monkeypatch.setattr(manager_mod, "connect_server", fake_connect)
        config = McpConfig(
            servers={
                "b": ServerConfig(name="b", type="stdio", command="b"),
                "bad": ServerConfig(name="bad", type="stdio", command="bad"),
                "a": ServerConfig(name="a", type="stdio", command="a"),
            }
        )
        stderr = io.StringIO()
        manager = McpManager(config, "test", stderr=stderr)

        await manager.start()

        assert [tool.spec.name for tool in manager.tools()] == ["mcp__a__z", "mcp__b__z"]
        assert sorted(manager._sessions) == ["a", "b"]
        assert "connect server bad failed" in stderr.getvalue()

    asyncio.run(run())


def test_manager_start_is_idempotent_and_skips_duplicate_tool_names(monkeypatch) -> None:
    calls = 0

    async def run() -> None:
        nonlocal calls

        async def fake_connect(server: ServerConfig, version: str, stderr) -> _ConnectedServer:  # noqa: ARG001, ANN001
            nonlocal calls
            calls += 1
            return _ConnectedServer(
                ManagedSession(server.name, object(), FakeStack()),
                [_tool(server.name, "same"), _tool(server.name, "same")],
            )

        monkeypatch.setattr(manager_mod, "connect_server", fake_connect)
        manager = McpManager(
            McpConfig(servers={"demo": ServerConfig(name="demo", type="stdio", command="x")}),
            "test",
            stderr=io.StringIO(),
        )

        await manager.start()
        await manager.start()

        assert calls == 1
        assert [tool.spec.name for tool in manager.tools()] == ["mcp__demo__same"]

    asyncio.run(run())


def test_manager_startup_timeout_skips_server(monkeypatch) -> None:
    async def run() -> None:
        async def slow_connect(server: ServerConfig, version: str, stderr) -> _ConnectedServer:  # noqa: ARG001, ANN001
            await asyncio.sleep(1)
            raise AssertionError("unreachable")

        monkeypatch.setattr(manager_mod, "STARTUP_TIMEOUT_SECONDS", 0.01)
        monkeypatch.setattr(manager_mod, "connect_server", slow_connect)
        stderr = io.StringIO()
        manager = McpManager(
            McpConfig(servers={"slow": ServerConfig(name="slow", type="stdio", command="x")}),
            "test",
            stderr=stderr,
        )

        await manager.start()

        assert manager.tools() == []
        assert "connect server slow timeout" in stderr.getvalue()

    asyncio.run(run())


def test_manager_close_closes_all_sessions(monkeypatch) -> None:  # noqa: ARG001
    async def run() -> None:
        fast = FakeStack()
        other = FakeStack()
        manager = McpManager(McpConfig(), "test")
        manager._sessions = {
            "fast": ManagedSession("fast", object(), fast),
            "other": ManagedSession("other", object(), other),
        }

        await manager.close()
        await manager.close()

        assert fast.closed is True
        assert other.closed is True

    asyncio.run(run())


def test_manager_close_timeout_warns(monkeypatch) -> None:
    async def run() -> None:
        monkeypatch.setattr(manager_mod, "CLOSE_TIMEOUT_SECONDS", 0.01)
        manager = McpManager(McpConfig(), "test", stderr=io.StringIO())
        manager._sessions = {
            "slow": ManagedSession("slow", object(), FakeStack(delay=1)),
        }

        await manager.close()

        assert "close timeout" in manager._stderr.getvalue()

    asyncio.run(run())


def test_connect_stdio_merges_environment_and_discovers_tools(monkeypatch) -> None:
    async def run() -> None:
        captured = {}

        def fake_stdio_client(params, errlog):  # noqa: ANN001, ARG001
            captured["env"] = params.env
            captured["command"] = params.command
            captured["args"] = params.args
            return FakeAsyncContext(("read", "write"))

        async def fake_enter_session(stack, read, write, version):  # noqa: ANN001, ARG001
            assert (read, write, version) == ("read", "write", "test-version")
            return object()

        async def fake_list_and_adapt(server_name, session, stderr):  # noqa: ANN001, ARG001
            return [_tool(server_name, "ok")]

        monkeypatch.setenv("MCP_ENV", "parent")
        monkeypatch.setattr(manager_mod, "stdio_client", fake_stdio_client)
        monkeypatch.setattr(manager_mod, "_enter_session", fake_enter_session)
        monkeypatch.setattr(manager_mod, "_list_and_adapt", fake_list_and_adapt)

        connected = await manager_mod.connect_stdio(
            ServerConfig(
                name="stdio",
                type="stdio",
                command="python",
                args=("server.py",),
                env={"MCP_ENV": "child"},
            ),
            "test-version",
            io.StringIO(),
        )

        assert captured["command"] == "python"
        assert captured["args"] == ["server.py"]
        assert captured["env"]["MCP_ENV"] == "child"
        assert [tool.full_name for tool in connected.tools] == ["mcp__stdio__ok"]

    asyncio.run(run())


def test_connect_http_injects_headers_and_discovers_tools(monkeypatch) -> None:
    async def run() -> None:
        captured = {}

        class FakeAsyncClient:
            def __init__(self, *, headers, timeout, follow_redirects) -> None:  # noqa: ANN001
                captured["headers"] = headers
                captured["timeout"] = timeout
                captured["follow_redirects"] = follow_redirects

            async def __aenter__(self) -> FakeAsyncClient:
                return self

            async def __aexit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
                return False

        def fake_streamable_http_client(url, *, http_client):  # noqa: ANN001
            captured["url"] = url
            captured["client"] = http_client
            return FakeAsyncContext(("read", "write", lambda: "session-id"))

        async def fake_enter_session(stack, read, write, version):  # noqa: ANN001, ARG001
            assert (read, write, version) == ("read", "write", "test-version")
            return object()

        async def fake_list_and_adapt(server_name, session, stderr):  # noqa: ANN001, ARG001
            return [_tool(server_name, "ok")]

        monkeypatch.setattr(manager_mod.httpx, "AsyncClient", FakeAsyncClient)
        monkeypatch.setattr(manager_mod, "streamable_http_client", fake_streamable_http_client)
        monkeypatch.setattr(manager_mod, "_enter_session", fake_enter_session)
        monkeypatch.setattr(manager_mod, "_list_and_adapt", fake_list_and_adapt)

        connected = await manager_mod.connect_http(
            ServerConfig(
                name="http",
                type="http",
                url="https://example.test/mcp",
                headers={"Authorization": "Bearer token"},
            ),
            "test-version",
            io.StringIO(),
        )

        assert captured["url"] == "https://example.test/mcp"
        assert captured["headers"] == {"Authorization": "Bearer token"}
        assert captured["follow_redirects"] is True
        assert [tool.full_name for tool in connected.tools] == ["mcp__http__ok"]

    asyncio.run(run())
