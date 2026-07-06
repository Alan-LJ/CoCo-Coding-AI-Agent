from __future__ import annotations

from coco_code.skills.active import ActiveSkills


def test_active_skills_preserve_order_and_update_existing() -> None:
    active = ActiveSkills()
    active.activate("alpha", "one", ("ReadFile",))
    active.activate("beta", "two", ("Grep",))
    active.activate("alpha", "updated", ("Bash",))

    snapshot = active.snapshot()
    assert [entry.name for entry in snapshot] == ["alpha", "beta"]
    assert snapshot[0].rendered_body == "updated"
    assert active.allowed_tool_union() == ("Bash", "Grep")


def test_active_skills_clear() -> None:
    active = ActiveSkills()
    active.activate("alpha", "one", ("ReadFile",))
    active.clear()

    assert active.snapshot() == ()
    assert active.allowed_tool_union() == ()
