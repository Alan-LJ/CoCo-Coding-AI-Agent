from __future__ import annotations

from coco_code.hook.matcher import eval_condition, get_by_path
from coco_code.hook.rule import AtomCondition, Condition
from coco_code.permission.matcher import compile_matcher


def test_get_by_path_reads_nested_fields_and_missing_values() -> None:
    payload = {"tool_input": {"path": "src/app.py"}, "missing": None}
    assert get_by_path(payload, "tool_input.path") == "src/app.py"
    assert get_by_path(payload, "tool_input.nope") == ""
    assert get_by_path(payload, "missing.value") == ""


def test_get_by_path_stringifies_stable_values() -> None:
    payload = {
        "ok": False,
        "count": 3,
        "items": ["b", "a"],
        "obj": {"b": 2, "a": 1},
    }
    assert get_by_path(payload, "ok") == "False"
    assert get_by_path(payload, "count") == "3"
    assert get_by_path(payload, "items") == '["b", "a"]'
    assert get_by_path(payload, "obj") == '{"a": 1, "b": 2}'


def test_eval_condition_all_of_any_of_and_none() -> None:
    payload = {"tool_name": "WriteFile", "path": "src/app.py"}
    all_condition = Condition(
        mode="all_of",
        atoms=(
            AtomCondition("tool_name", compile_matcher("=WriteFile")),
            AtomCondition("path", compile_matcher("**/*.py", path_like=True)),
        ),
    )
    any_condition = Condition(
        mode="any_of",
        atoms=(
            AtomCondition("tool_name", compile_matcher("=Bash")),
            AtomCondition("path", compile_matcher("**/*.py", path_like=True)),
        ),
    )
    assert eval_condition(None, payload) is True
    assert eval_condition(all_condition, payload) is True
    assert eval_condition(any_condition, payload) is True
