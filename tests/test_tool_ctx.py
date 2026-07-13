from __future__ import annotations

from pathlib import Path

from coco_code.tools.ctx import cwd_from_ctx, resolve_path, with_cwd, workspace_from_ctx


def test_with_cwd_sets_and_resets(tmp_path: Path) -> None:
    assert cwd_from_ctx() is None
    with with_cwd(tmp_path):
        assert cwd_from_ctx() == str(tmp_path)
        assert resolve_path("a.txt") == str(tmp_path / "a.txt")
        assert workspace_from_ctx(Path("fallback")) == tmp_path
    assert cwd_from_ctx() is None


def test_resolve_path_falls_back_to_process_cwd() -> None:
    assert Path(resolve_path("a.txt")).name == "a.txt"


def test_resolve_path_keeps_absolute(tmp_path: Path) -> None:
    target = tmp_path / "a.txt"
    with with_cwd(tmp_path / "other"):
        assert resolve_path(target) == str(target)
