from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

INSTRUCTION_FILE = "MEWCODE.md"
DEPTH_WARNING = "@include 超过最大嵌套深度，已跳过"
CYCLE_WARNING = "@include 检测到环路，已跳过"
BOUNDARY_WARNING = "@include 路径超出允许范围，已跳过"
BINARY_WARNING = "@include 指向二进制文件，已跳过"
READ_WARNING = "@include 文件无法读取，已跳过"


@dataclass(frozen=True)
class InstructionWarning:
    path: Path
    message: str


@dataclass(frozen=True)
class InstructionLoadResult:
    content: str
    warnings: tuple[InstructionWarning, ...] = ()


@dataclass(frozen=True)
class InstructionLayer:
    name: str
    path: Path
    boundary: Path
    priority: int


class InstructionLoader:
    def __init__(
        self,
        project_root: Path,
        user_home: Path | None = None,
        max_depth: int = 5,
    ) -> None:
        self.project_root = project_root.resolve()
        self.user_home = (user_home or Path.home()).resolve()
        self.max_depth = max_depth

    def load(self) -> InstructionLoadResult:
        layers = self._layers()
        parts: list[str] = []
        warnings: list[InstructionWarning] = []
        for layer in layers:
            if not layer.path.exists():
                continue
            result = self.load_file(
                layer.path,
                layer.boundary,
                depth=1,
                visited=frozenset(),
            )
            if result.content.strip():
                parts.append(f"<!-- {layer.name}: {layer.path} -->\n{result.content.strip()}")
            warnings.extend(result.warnings)
        return InstructionLoadResult(content="\n\n".join(parts), warnings=tuple(warnings))

    def load_file(
        self,
        path: Path,
        boundary: Path,
        depth: int,
        visited: frozenset[Path],
    ) -> InstructionLoadResult:
        display_path = path
        if depth > self.max_depth:
            return self._warn(display_path, f"{DEPTH_WARNING}: {display_path}")

        try:
            resolved = path.resolve()
            resolved_boundary = boundary.resolve()
        except OSError:
            return self._warn(display_path, f"{READ_WARNING}: {display_path}")

        if resolved in visited:
            return self._warn(display_path, f"{CYCLE_WARNING}: {display_path}")
        if not _is_relative_to(resolved, resolved_boundary):
            return self._warn(display_path, f"{BOUNDARY_WARNING}: {display_path}")
        if not resolved.exists():
            return InstructionLoadResult("")

        try:
            raw = resolved.read_bytes()
        except OSError:
            return self._warn(display_path, f"{READ_WARNING}: {display_path}")
        if b"\x00" in raw[:512]:
            return self._warn(display_path, f"{BINARY_WARNING}: {display_path}")

        text = raw.decode("utf-8", errors="replace")
        next_visited = frozenset((*visited, resolved))
        lines: list[str] = []
        warnings: list[InstructionWarning] = []
        for line in text.splitlines():
            include_target = _include_target(line)
            if include_target is None:
                lines.append(line)
                continue
            include_path = resolved.parent / include_target
            included = self.load_file(
                include_path,
                resolved_boundary,
                depth=depth + 1,
                visited=next_visited,
            )
            if included.content:
                lines.append(included.content)
            warnings.extend(included.warnings)
        return InstructionLoadResult(content="\n".join(lines), warnings=tuple(warnings))

    def _layers(self) -> list[InstructionLayer]:
        user_boundary = self.user_home / ".mewcode"
        return [
            InstructionLayer(
                name="project-root",
                path=self.project_root / INSTRUCTION_FILE,
                boundary=self.project_root,
                priority=100,
            ),
            InstructionLayer(
                name="project-config",
                path=self.project_root / ".mewcode" / INSTRUCTION_FILE,
                boundary=self.project_root,
                priority=80,
            ),
            InstructionLayer(
                name="user",
                path=user_boundary / INSTRUCTION_FILE,
                boundary=user_boundary,
                priority=10,
            ),
        ]

    def _warn(self, path: Path, message: str) -> InstructionLoadResult:
        return InstructionLoadResult(
            content=f"<!-- {message} -->",
            warnings=(InstructionWarning(path=path, message=message),),
        )


def _include_target(line: str) -> str | None:
    stripped = line.strip()
    if not stripped.startswith("@include "):
        return None
    if stripped != line:
        return None
    target = stripped.removeprefix("@include ").strip()
    return target or None


def _is_relative_to(path: Path, boundary: Path) -> bool:
    try:
        path.relative_to(boundary)
        return True
    except ValueError:
        return False
