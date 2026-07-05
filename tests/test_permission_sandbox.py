from __future__ import annotations

from pathlib import Path

import pytest

from coco_code.permission.engine import Engine
from coco_code.permission.sandbox import eval_symlinks_or_ancestor, resolve_root, sandbox_ok


def test_sandbox_accepts_inside_and_uncreated_descendants(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    engine = Engine(root=str(root.resolve()))

    assert resolve_root(root) == root.resolve()
    assert sandbox_ok(engine, "src/app.py") is True
    assert sandbox_ok(engine, "src/new/deep/file.txt") is True
    assert eval_symlinks_or_ancestor(root / "src" / "new.txt") == root / "src" / "new.txt"


def test_sandbox_rejects_parent_and_absolute_outside_paths(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    engine = Engine(root=str(root.resolve()))

    assert sandbox_ok(engine, "../outside.txt") is False
    assert sandbox_ok(engine, str(outside)) is False


def test_sandbox_resolves_symlinks_before_prefix_check(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    link = root / "link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink unavailable on this platform: {exc}")

    engine = Engine(root=str(root.resolve()))
    assert sandbox_ok(engine, "link/secret.txt") is False
