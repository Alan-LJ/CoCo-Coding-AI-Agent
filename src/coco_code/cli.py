from __future__ import annotations

import sys

from coco_code.config import ConfigError, load, resolve_api_key
from coco_code.tui.app import CoCoCodeApp


def main() -> None:
    _configure_stdio()
    try:
        config = load()
        if len(config.providers) == 1:
            resolve_api_key(config.providers[0])
    except ConfigError as exc:
        print(f"配置错误：{exc}", file=sys.stderr)
        raise SystemExit(1) from None

    try:
        CoCoCodeApp(config).run()
    except ConfigError as exc:
        print(f"启动失败：{exc}", file=sys.stderr)
        raise SystemExit(1) from None


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")