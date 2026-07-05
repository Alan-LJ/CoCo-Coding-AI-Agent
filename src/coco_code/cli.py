from __future__ import annotations

import sys
from pathlib import Path

from coco_code.agent.runtime import new_session_runtime
from coco_code.config import ConfigError, load, resolve_api_key
from coco_code.instructions import InstructionLoader
from coco_code.mcp import load_config as load_mcp_config
from coco_code.memory import MemoryManager
from coco_code.permission import new_engine
from coco_code.session import SessionWriter, session_paths
from coco_code.tui.app import CoCoCodeApp


def main() -> None:
    _configure_stdio()
    try:
        config = load()
        if len(config.providers) == 1:
            resolve_api_key(config.providers[0])
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        raise SystemExit(1) from None

    root = Path.cwd().resolve()
    engine, engine_error = new_engine(root)
    if engine_error is not None:
        print(f"Permission engine degraded: {engine_error}", file=sys.stderr)
    mcp_config = load_mcp_config(root)

    instruction_text = InstructionLoader(root).load().content
    memory_manager = MemoryManager(root)
    runtime = new_session_runtime(root, context_window=0)
    writer = SessionWriter(session_paths(root, runtime.session.session_id))

    try:
        CoCoCodeApp(
            config,
            cwd=root,
            permission_engine=engine,
            mcp_config=mcp_config,
            runtime=runtime,
            instruction_text=instruction_text,
            memory_manager=memory_manager,
            session_writer=writer,
        ).run()
    except ConfigError as exc:
        print(f"Startup failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from None


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
