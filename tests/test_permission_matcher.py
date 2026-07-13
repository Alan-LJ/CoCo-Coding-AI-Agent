from __future__ import annotations

import pytest

from coco_code.permission.matcher import compile_matcher, compile_structured_matcher


@pytest.mark.parametrize(
    ("pattern", "candidate", "expected"),
    [
        pytest.param("=git status", "git status", True, id="exact-hit"),
        pytest.param("=git status", "git status -s", False, id="exact-miss"),
        pytest.param("~^npm (install|test)$", "npm install", True, id="regex-hit"),
        pytest.param("~^npm (install|test)$", "npm run dev", False, id="regex-miss"),
        pytest.param("!=foo", "foo", False, id="not-exact-miss"),
        pytest.param("!=foo", "bar", True, id="not-exact-hit"),
        pytest.param("!~^rm", "ls -lh", True, id="not-regex-hit"),
        pytest.param("!~^rm", "rm -rf .", False, id="not-regex-miss"),
        pytest.param("!git *", "npm install", True, id="not-glob-hit"),
        pytest.param("!git *", "git status", False, id="not-glob-miss"),
        pytest.param("src/**", "src/a/b.py", True, id="path-glob-hit"),
        pytest.param("src/**", "docs/a.py", False, id="path-glob-miss"),
    ],
)
def test_compile_matcher_patterns(pattern: str, candidate: str, expected: bool) -> None:
    assert compile_matcher(pattern, path_like=None).match(candidate) is expected


@pytest.mark.parametrize("pattern", ["~[invalid", ""])
def test_compile_matcher_rejects_invalid_patterns(pattern: str) -> None:
    with pytest.raises(ValueError):
        compile_matcher(pattern)


def test_compile_structured_matcher() -> None:
    assert compile_structured_matcher({"type": "exact", "value": "foo"}).match("foo")
    assert compile_structured_matcher({"type": "glob", "value": "*.py"}).match("main.py")
    assert compile_structured_matcher({"type": "regex", "value": "^foo"}).match("foobar")
    matcher = compile_structured_matcher(
        {"type": "not", "inner": {"type": "regex", "value": "^rm"}}
    )
    assert matcher.match("ls -lh") is True
    assert matcher.match("rm -rf .") is False


@pytest.mark.parametrize(
    "raw",
    [
        {"type": "missing", "value": "x"},
        {"type": "not"},
        {"type": "regex", "value": "[bad"},
        {"type": "exact"},
        "exact",
    ],
)
def test_compile_structured_matcher_rejects_invalid(raw) -> None:
    with pytest.raises(ValueError):
        compile_structured_matcher(raw)
