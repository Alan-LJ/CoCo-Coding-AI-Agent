from __future__ import annotations

import asyncio
import os
import sys
from contextlib import AsyncExitStack, suppress
from dataclasses import dataclass
from typing import Any, TextIO

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.types import Implementation

from coco_code.mcp.config import McpConfig, ServerConfig
from coco_code.mcp.tool import McpTool, adapt_tool
from coco_code.tools.base import Tool

STARTUP_TIMEOUT_SECONDS = 30.0
CLOSE_TIMEOUT_SECONDS = 5.0


@dataclass
class ManagedSession:
    server_name: str
    session: ClientSession
    stack: AsyncExitStack


@dataclass
class _ConnectedServer:
    managed: ManagedSession
    tools: list[McpTool]


class McpManager:
    def __init__(
        self,
        config: McpConfig,
        version: str,
        *,
        stderr: TextIO = sys.stderr,
    ) -> None:
        self._config = config
        self._version = version
        self._stderr = stderr
        self._sessions: dict[str, ManagedSession] = {}
        self._tools: list[McpTool] = []
        self._started = False
        self._closed = False

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        if not self._config.servers:
            return
        results = await asyncio.gather(
            *(self._start_one(name, server) for name, server in self._config.servers.items()),
            return_exceptions=True,
        )
        seen: set[str] = set()
        for result in results:
            if isinstance(result, BaseException) or result is None:
                continue
            self._sessions[result.managed.server_name] = result.managed
            for tool in result.tools:
                if tool.full_name in seen:
                    print(
                        f"[mcp] warn: skip tool {tool.full_name}: duplicate name", file=self._stderr
                    )
                    continue
                seen.add(tool.full_name)
                self._tools.append(tool)
        self._tools.sort(key=lambda tool: (tool.server_name, tool.remote_name))

    def tools(self) -> list[Tool]:
        return list(self._tools)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if not self._sessions:
            return

        async def close_session(session: ManagedSession) -> None:
            with suppress(Exception):
                await session.stack.aclose()

        try:
            async with asyncio.timeout(CLOSE_TIMEOUT_SECONDS):
                await asyncio.gather(*(close_session(s) for s in self._sessions.values()))
        except TimeoutError:
            print(
                f"[mcp] warn: close timeout after {CLOSE_TIMEOUT_SECONDS:g}s; "
                "some sessions may still be closing",
                file=self._stderr,
            )

    async def _start_one(self, name: str, server: ServerConfig) -> _ConnectedServer | None:
        try:
            async with asyncio.timeout(STARTUP_TIMEOUT_SECONDS):
                return await connect_server(server, self._version, self._stderr)
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            print(
                f"[mcp] warn: connect server {name} timeout after {STARTUP_TIMEOUT_SECONDS:g}s",
                file=self._stderr,
            )
        except Exception as exc:
            print(f"[mcp] warn: connect server {name} failed: {exc}", file=self._stderr)
        return None


async def connect_server(
    config: ServerConfig,
    version: str,
    stderr: TextIO = sys.stderr,
) -> _ConnectedServer:
    if config.type == "stdio":
        return await connect_stdio(config, version, stderr)
    return await connect_http(config, version, stderr)


async def connect_stdio(
    config: ServerConfig,
    version: str,
    stderr: TextIO = sys.stderr,
) -> _ConnectedServer:
    stack = AsyncExitStack()
    await stack.__aenter__()
    try:
        params = StdioServerParameters(
            command=config.command,
            args=list(config.args),
            env=merge_env(config.env),
        )
        read_stream, write_stream = await stack.enter_async_context(
            stdio_client(params, errlog=stderr)
        )
        session = await _enter_session(stack, read_stream, write_stream, version)
        tools = await _list_and_adapt(config.name, session, stderr)
        return _ConnectedServer(ManagedSession(config.name, session, stack), tools)
    except Exception:
        await stack.aclose()
        raise


async def connect_http(
    config: ServerConfig,
    version: str,
    stderr: TextIO = sys.stderr,
) -> _ConnectedServer:
    stack = AsyncExitStack()
    await stack.__aenter__()
    try:
        client = httpx.AsyncClient(
            headers=config.headers,
            timeout=httpx.Timeout(STARTUP_TIMEOUT_SECONDS),
            follow_redirects=True,
        )
        await stack.enter_async_context(client)
        streams = await stack.enter_async_context(
            streamable_http_client(config.url, http_client=client)
        )
        read_stream, write_stream = streams[0], streams[1]
        session = await _enter_session(stack, read_stream, write_stream, version)
        tools = await _list_and_adapt(config.name, session, stderr)
        return _ConnectedServer(ManagedSession(config.name, session, stack), tools)
    except Exception:
        await stack.aclose()
        raise


def merge_env(extra: dict[str, str]) -> dict[str, str]:
    merged = dict(os.environ)
    merged.update(extra)
    return merged


async def _enter_session(
    stack: AsyncExitStack,
    read_stream: Any,
    write_stream: Any,
    version: str,
) -> ClientSession:
    session = ClientSession(
        read_stream,
        write_stream,
        client_info=Implementation(name="coco-code", version=version),
    )
    entered = await stack.enter_async_context(session)
    await entered.initialize()
    return entered


async def _list_and_adapt(
    server_name: str,
    session: ClientSession,
    stderr: TextIO,
) -> list[McpTool]:
    listed = await session.list_tools()
    tools: list[McpTool] = []
    for remote_tool in listed.tools:
        tool = adapt_tool(server_name, remote_tool, session, stderr=stderr)
        if tool is not None:
            tools.append(tool)
    return tools
