from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from coco_code.hook.rule import Condition


def get_by_path(payload: Mapping[str, Any], path: str) -> str:
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, Mapping):
            return ""
        if part not in current:
            return ""
        current = current[part]
    return _stringify(current)


def eval_condition(condition: Condition | None, payload: Mapping[str, Any]) -> bool:
    if condition is None:
        return True
    results = [atom.matcher.match(get_by_path(payload, atom.field)) for atom in condition.atoms]
    if condition.mode == "all_of":
        return all(results)
    return any(results)


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict | list):
        return json.dumps(value, sort_keys=True, ensure_ascii=False)
    return str(value)
