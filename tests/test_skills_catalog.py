from __future__ import annotations

import io
from pathlib import Path

from coco_code.skills.catalog import SkillCatalog
from coco_code.tools import ConfirmationPolicy, ToolSpec
from coco_code.tools.base import ToolContext, ToolParams, ToolResult
from coco_code.tools.registry import ToolRegistry


class NamedTool:
    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self._name,
            description=self._name,
            parameters_schema={"type": "object", "properties": {}},
            confirmation=ConfirmationPolicy.NEVER,
        )

    async def run(self, params: ToolParams, context: ToolContext) -> ToolResult:  # noqa: ARG002
        return ToolResult("", self._name, True, "ok", {}, None, 0)


def write_skill(root: Path, name: str, description: str, body: str = "Body") -> Path:
    path = root / f"{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n{body}\n", encoding="utf-8"
    )
    return path


def test_catalog_priority_project_over_user_over_builtin(tmp_path: Path) -> None:
    builtin = tmp_path / "builtin"
    user = tmp_path / "user"
    project = tmp_path / "project"
    write_skill(builtin, "demo", "builtin")
    write_skill(user, "demo", "user")
    write_skill(project, "demo", "project")
    catalog = SkillCatalog(tmp_path, builtin_dir=builtin, user_dir=user, project_dir=project)

    catalog.reload()

    assert catalog.get("demo").meta.description == "project"


def test_catalog_supports_directory_skills(tmp_path: Path) -> None:
    project = tmp_path / "project"
    skill_dir = project / "demo"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: demo\ndescription: Directory skill\n---\nBody\n",
        encoding="utf-8",
    )
    catalog = SkillCatalog(
        tmp_path, builtin_dir=tmp_path / "none", user_dir=tmp_path / "user", project_dir=project
    )

    catalog.reload()

    skill = catalog.get("demo")
    assert skill is not None
    assert skill.is_directory is True
    assert skill.package_dir == skill_dir


def test_catalog_skips_invalid_skill_and_loads_valid_ones(tmp_path: Path) -> None:
    stderr = io.StringIO()
    project = tmp_path / "project"
    write_skill(project, "valid", "Valid")
    (project / "bad.md").write_text("---\nname: bad\n---\nBody\n", encoding="utf-8")
    catalog = SkillCatalog(
        tmp_path,
        builtin_dir=tmp_path / "none",
        user_dir=tmp_path / "user",
        project_dir=project,
        stderr=stderr,
    )

    catalog.reload()

    assert catalog.get("valid") is not None
    assert catalog.get("bad") is None
    assert "skipping" in stderr.getvalue()


def test_get_latest_hot_reload_and_cached_fallback(tmp_path: Path) -> None:
    stderr = io.StringIO()
    project = tmp_path / "project"
    path = write_skill(project, "demo", "First", body="One")
    catalog = SkillCatalog(
        tmp_path,
        builtin_dir=tmp_path / "none",
        user_dir=tmp_path / "user",
        project_dir=project,
        stderr=stderr,
    )
    catalog.reload()

    path.write_text("---\nname: demo\ndescription: Second\n---\nTwo\n", encoding="utf-8")
    assert catalog.get_latest("demo").meta.description == "Second"

    path.write_text("---\nname: demo\n---\nBroken\n", encoding="utf-8")
    fallback = catalog.get_latest("demo")
    assert fallback.meta.description == "Second"
    assert "cached" in stderr.getvalue()


def test_catalog_validates_allowed_tools(tmp_path: Path) -> None:
    project = tmp_path / "project"
    path = project / "demo.md"
    project.mkdir()
    path.write_text(
        "---\nname: demo\ndescription: Demo\nallowed_tools: [ReadFile, Missing]\n---\nBody\n",
        encoding="utf-8",
    )
    catalog = SkillCatalog(
        tmp_path, builtin_dir=tmp_path / "none", user_dir=tmp_path / "user", project_dir=project
    )
    catalog.reload()
    registry = ToolRegistry()
    registry.register(NamedTool("ReadFile"))

    issues = catalog.validate_tools(registry)

    assert len(issues) == 1
    assert issues[0].tool_name == "Missing"

def test_catalog_skips_inaccessible_directory_skill(monkeypatch, tmp_path: Path) -> None:
    stderr = io.StringIO()
    project = tmp_path / "project"
    write_skill(project, "valid", "Valid")
    blocked_dir = project / "blocked"
    blocked_dir.mkdir()
    blocked_entry = blocked_dir / "SKILL.md"
    original_exists = Path.exists

    def fake_exists(path: Path) -> bool:
        if path == blocked_entry:
            raise PermissionError("denied")
        return original_exists(path)

    monkeypatch.setattr(Path, "exists", fake_exists)
    catalog = SkillCatalog(
        tmp_path,
        builtin_dir=tmp_path / "none",
        user_dir=tmp_path / "user",
        project_dir=project,
        stderr=stderr,
    )

    catalog.reload()

    assert catalog.get("valid") is not None
    assert "cannot exists" in stderr.getvalue()

