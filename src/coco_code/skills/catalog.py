from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from coco_code.skills.parser import SkillParseError, parse_skill_file
from coco_code.skills.render import render_skills_catalog
from coco_code.skills.types import Skill, SkillSource, SkillValidationIssue
from coco_code.tools.registry import ToolRegistry, ToolRegistryError

BUILTIN_SKILLS_DIR = Path(__file__).parent / "builtin"
USER_SKILLS_DIR = Path.home() / ".coco-code" / "skills"
PROJECT_SKILLS_DIR = Path(".coco-code") / "skills"


@dataclass(frozen=True)
class SkillRoot:
    path: Path
    source: SkillSource


class SkillCatalog:
    def __init__(
        self,
        workspace: Path,
        *,
        builtin_dir: Path = BUILTIN_SKILLS_DIR,
        user_dir: Path = USER_SKILLS_DIR,
        project_dir: Path | None = None,
        stderr: TextIO = sys.stderr,
    ) -> None:
        self.workspace = workspace
        self.builtin_dir = builtin_dir
        self.user_dir = user_dir
        self.project_dir = project_dir or workspace / PROJECT_SKILLS_DIR
        self._stderr = stderr
        self._skills: dict[str, Skill] = {}
        self._cache: dict[str, Skill] = {}

    @classmethod
    def load(cls, workspace: Path, *, stderr: TextIO = sys.stderr) -> SkillCatalog:
        catalog = cls(workspace, stderr=stderr)
        catalog.reload()
        return catalog

    def reload(self) -> None:
        loaded: dict[str, Skill] = {}
        for root in self._roots():
            for skill in self._scan_root(root):
                loaded[skill.meta.name.casefold()] = skill
        self._skills = dict(sorted(loaded.items(), key=lambda item: item[0]))
        self._cache.update(self._skills)

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name.casefold())

    def get_latest(self, name: str) -> Skill | None:
        key = name.casefold()
        skill = self._skills.get(key)
        if skill is None:
            return None
        try:
            latest = parse_skill_file(
                skill.entry_path,
                skill.source,
                is_directory=skill.is_directory,
            )
        except SkillParseError as exc:
            print(
                f"[skills] warn: keep cached Skill '{skill.meta.name}' after reload failure: {exc}",
                file=self._stderr,
            )
            return self._cache.get(key, skill)
        self._skills[key] = latest
        self._cache[key] = latest
        return latest

    def list(self) -> tuple[Skill, ...]:
        return tuple(self._skills[key] for key in sorted(self._skills))

    def catalog_text(self) -> str:
        return render_skills_catalog(self.list())

    def validate_tools(self, registry: ToolRegistry) -> tuple[SkillValidationIssue, ...]:
        issues: list[SkillValidationIssue] = []
        for skill in self.list():
            for tool_name in skill.meta.allowed_tools:
                try:
                    registry.get(tool_name)
                except ToolRegistryError:
                    issues.append(
                        SkillValidationIssue(
                            skill_name=skill.meta.name,
                            tool_name=tool_name,
                            message=(
                                f"Skill '{skill.meta.name}' references unknown "
                                f"tool '{tool_name}'."
                            ),
                        )
                    )
        return tuple(issues)

    def remove_invalid(self, issues: tuple[SkillValidationIssue, ...]) -> None:
        invalid = {issue.skill_name.casefold() for issue in issues}
        for key in invalid:
            self._skills.pop(key, None)

    def _roots(self) -> tuple[SkillRoot, ...]:
        return (
            SkillRoot(self.builtin_dir, SkillSource.BUILTIN),
            SkillRoot(self.user_dir, SkillSource.USER),
            SkillRoot(self.project_dir, SkillSource.PROJECT),
        )

    def _scan_root(self, root: SkillRoot) -> tuple[Skill, ...]:
        path = root.path
        if not self._safe_path_check(path, root.source, "is_dir", path.is_dir):
            return ()
        try:
            children = sorted(path.iterdir(), key=lambda item: item.name.casefold())
        except OSError as exc:
            self._warn_inaccessible(root.source, path, "list directory", exc)
            return ()

        skills: list[Skill] = []
        for child in children:
            if self._safe_path_check(child, root.source, "is_dir", child.is_dir):
                entry = child / "SKILL.md"
                if self._safe_path_check(entry, root.source, "exists", entry.exists):
                    parsed = self._parse_or_warn(entry, root.source, is_directory=True)
                    if parsed is not None:
                        skills.append(parsed)
                continue
            if child.suffix.lower() == ".md" and self._safe_path_check(
                child, root.source, "is_file", child.is_file
            ):
                parsed = self._parse_or_warn(child, root.source, is_directory=False)
                if parsed is not None:
                    skills.append(parsed)
        return tuple(skills)

    def _safe_path_check(
        self,
        path: Path,
        source: SkillSource,
        operation: str,
        check: Callable[[], bool],
    ) -> bool:
        try:
            return check()
        except OSError as exc:
            self._warn_inaccessible(source, path, operation, exc)
            return False

    def _warn_inaccessible(
        self,
        source: SkillSource,
        path: Path,
        operation: str,
        exc: OSError,
    ) -> None:
        print(
            f"[skills] warn: skipping {source.value} Skill path {path}: "
            f"cannot {operation}: {exc}",
            file=self._stderr,
        )

    def _parse_or_warn(
        self,
        path: Path,
        source: SkillSource,
        *,
        is_directory: bool,
    ) -> Skill | None:
        try:
            return parse_skill_file(path, source, is_directory=is_directory)
        except SkillParseError as exc:
            print(
                f"[skills] warn: skipping {source.value} Skill at {path}: {exc}", file=self._stderr
            )
            return None
