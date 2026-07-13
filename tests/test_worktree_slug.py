from __future__ import annotations

import pytest

from coco_code.worktree import flat_slug, validate_slug


@pytest.mark.parametrize("name", ["alice", "team/alice", "v1.0", "a_b", "a-b"])
def test_validate_slug_accepts_safe_names(name: str) -> None:
    validate_slug(name)


@pytest.mark.parametrize("name", ["", "." * 65, "..", "./x", "a//b", "/x", "a/", "a b", "a;b"])
def test_validate_slug_rejects_unsafe_names(name: str) -> None:
    with pytest.raises(ValueError):
        validate_slug(name)


def test_flat_slug_replaces_slashes() -> None:
    assert flat_slug("team/alice") == "team+alice"
