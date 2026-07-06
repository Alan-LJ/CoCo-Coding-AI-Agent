from __future__ import annotations

import base64
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote, unquote, urlparse

import httpx

from coco_code.skills.parser import SkillParseError, parse_skill_file
from coco_code.skills.types import Skill, SkillSource

MAX_FILE_BYTES = 1 * 1024 * 1024
MAX_TOTAL_BYTES = 8 * 1024 * 1024
MAX_FILES = 64
MAX_DEPTH = 4


class SkillInstallError(RuntimeError):
    pass


class _SkillsShSnapshotUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class SkillRemoteSource:
    kind: str
    url: str
    owner: str = ""
    repo: str = ""
    ref: str = ""
    path: str = ""


@dataclass(frozen=True)
class InstallResult:
    name: str
    target_dir: Path
    file_count: int
    total_bytes: int


@dataclass
class _DownloadStats:
    file_count: int = 0
    total_bytes: int = 0

    def add_file(self, size: int) -> None:
        if size > MAX_FILE_BYTES:
            raise SkillInstallError("Skill package contains a file larger than 1 MiB.")
        if self.file_count + 1 > MAX_FILES:
            raise SkillInstallError("Skill package contains too many files.")
        if self.total_bytes + size > MAX_TOTAL_BYTES:
            raise SkillInstallError("Skill package is larger than 8 MiB.")
        self.file_count += 1
        self.total_bytes += size


def parse_skill_url(source_url: str) -> SkillRemoteSource:
    parsed = urlparse(source_url)
    host = parsed.netloc.casefold()
    if parsed.scheme not in {"http", "https"}:
        raise SkillInstallError("Skill URL must use http or https.")
    if host == "skills.sh" or host.endswith(".skills.sh"):
        path = "/".join(unquote(part) for part in parsed.path.strip("/").split("/") if part)
        if not path:
            raise SkillInstallError("skills.sh Skill URL must include a skill path.")
        return SkillRemoteSource(kind="skills_sh", url=source_url, path=path)
    if host == "raw.githubusercontent.com":
        parts = [unquote(part) for part in parsed.path.strip("/").split("/") if part]
        if len(parts) < 4:
            raise SkillInstallError("raw.githubusercontent.com Skill URL is incomplete.")
        owner, repo, ref = parts[:3]
        path = "/".join(parts[3:])
        return SkillRemoteSource("github_raw", source_url, owner, repo, ref, path)
    if host == "github.com":
        parts = [unquote(part) for part in parsed.path.strip("/").split("/") if part]
        if len(parts) < 5 or parts[2] != "tree":
            raise SkillInstallError("GitHub Skill URL must point to a repository tree.")
        owner, repo, _, ref = parts[:4]
        path = "/".join(parts[4:])
        return SkillRemoteSource("github_tree", source_url, owner, repo, ref, path)
    raise SkillInstallError(f"Unsupported Skill URL host: {parsed.netloc}")


async def install_from_url(
    source_url: str,
    user_root: Path,
    *,
    http_client: Any | None = None,
) -> InstallResult:
    source = parse_skill_url(source_url)
    user_root.mkdir(parents=True, exist_ok=True)
    staging_parent = user_root
    staging_dir = Path(tempfile.mkdtemp(prefix=".skill-install-", dir=staging_parent))
    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(follow_redirects=True, timeout=60.0)
    try:
        stats = _DownloadStats()
        package_dir = staging_dir / "package"
        package_dir.mkdir()
        if source.kind == "github_tree":
            await _download_github_tree(client, source, package_dir, stats)
        elif source.kind == "skills_sh":
            await _download_skills_sh(client, source, package_dir, stats)
        else:
            content = await _get_bytes(client, source.url)
            stats.add_file(len(content))
            (package_dir / "SKILL.md").write_bytes(content)
        skill = validate_staged_skill(package_dir)
        target_dir = user_root / skill.meta.name
        if target_dir.exists():
            raise SkillInstallError(f"Skill '{skill.meta.name}' is already installed.")
        package_dir.rename(target_dir)
        shutil.rmtree(staging_dir, ignore_errors=True)
        return InstallResult(skill.meta.name, target_dir, stats.file_count, stats.total_bytes)
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise
    finally:
        if owns_client:
            await client.aclose()


def validate_staged_skill(staging_dir: Path) -> Skill:
    entry = staging_dir / "SKILL.md"
    if not entry.is_file():
        raise SkillInstallError("Skill package must contain SKILL.md at its root.")
    try:
        return parse_skill_file(entry, SkillSource.USER, is_directory=True)
    except SkillParseError as exc:
        raise SkillInstallError(f"Invalid SKILL.md: {exc}") from exc


async def _download_github_tree(
    client: Any,
    source: SkillRemoteSource,
    destination: Path,
    stats: _DownloadStats,
) -> None:
    await _download_github_contents(client, source, source.path.strip("/"), destination, stats, 0)


async def _download_github_contents(
    client: Any,
    source: SkillRemoteSource,
    remote_path: str,
    local_dir: Path,
    stats: _DownloadStats,
    depth: int,
) -> None:
    if depth > MAX_DEPTH:
        raise SkillInstallError("Skill package directory depth exceeds the limit.")
    api_path = quote(remote_path, safe="/")
    url = f"https://api.github.com/repos/{source.owner}/{source.repo}/contents/{api_path}"
    if source.ref:
        url = f"{url}?ref={quote(source.ref)}"
    data = await _get_json(client, url)
    entries = data if isinstance(data, list) else [data]
    for entry in entries:
        if not isinstance(entry, dict):
            raise SkillInstallError("GitHub API returned an invalid entry.")
        entry_type = str(entry.get("type", ""))
        name = str(entry.get("name", ""))
        if not name:
            raise SkillInstallError("GitHub API returned an entry without a name.")
        _validate_relative_path(name)
        if entry_type == "dir":
            next_dir = local_dir / name
            next_dir.mkdir(parents=True, exist_ok=True)
            child_path = str(entry.get("path") or f"{remote_path}/{name}").strip("/")
            await _download_github_contents(client, source, child_path, next_dir, stats, depth + 1)
        elif entry_type == "file":
            content = await _github_file_bytes(client, entry)
            stats.add_file(len(content))
            (local_dir / name).write_bytes(content)
        else:
            raise SkillInstallError(f"Unsupported GitHub entry type in Skill package: {entry_type}")


async def _download_skills_sh(
    client: Any,
    source: SkillRemoteSource,
    destination: Path,
    stats: _DownloadStats,
) -> None:
    try:
        await _download_skills_sh_snapshot(client, source, destination, stats)
        return
    except _SkillsShSnapshotUnavailable:
        fallback = _github_skill_folder_from_skills_sh(source)
        if fallback is None:
            raise SkillInstallError(
                "skills.sh did not provide a downloadable Skill snapshot for this URL."
            ) from None
        await _download_github_tree(client, fallback, destination, stats)


async def _download_skills_sh_snapshot(
    client: Any,
    source: SkillRemoteSource,
    destination: Path,
    stats: _DownloadStats,
) -> None:
    skill_id = source.path.strip("/")
    api_url = f"https://skills.sh/api/v1/skills/{quote(skill_id, safe='/')}"
    try:
        data = await _get_json(client, api_url)
    except httpx.HTTPError as exc:
        raise _SkillsShSnapshotUnavailable from exc
    if not isinstance(data, dict):
        raise _SkillsShSnapshotUnavailable
    files = data.get("files")
    if files is None:
        raise _SkillsShSnapshotUnavailable
    if not isinstance(files, list) or not files:
        raise SkillInstallError("skills.sh Skill snapshot did not include any files.")

    seen_paths: set[str] = set()
    for entry in files:
        if not isinstance(entry, dict):
            raise SkillInstallError("skills.sh Skill snapshot contains an invalid file entry.")
        path_value = entry.get("path")
        contents = entry.get("contents")
        if not isinstance(path_value, str) or not path_value.strip():
            raise SkillInstallError("skills.sh Skill snapshot contains a file without a path.")
        if not isinstance(contents, str):
            raise SkillInstallError("skills.sh Skill snapshot contains a non-text file.")
        normalized_path = _normalized_relative_path(path_value)
        if normalized_path in seen_paths:
            raise SkillInstallError("skills.sh Skill snapshot contains duplicate file paths.")
        seen_paths.add(normalized_path)
        encoded = contents.encode("utf-8")
        stats.add_file(len(encoded))
        _write_package_file(destination, normalized_path, encoded)


def _github_skill_folder_from_skills_sh(source: SkillRemoteSource) -> SkillRemoteSource | None:
    parts = [part for part in source.path.strip("/").split("/") if part]
    if len(parts) != 3:
        return None
    owner, repo, skill_name = parts
    return SkillRemoteSource(
        kind="github_tree",
        url=source.url,
        owner=owner,
        repo=repo,
        ref="",
        path=f"skills/{skill_name}",
    )


async def _github_file_bytes(client: Any, entry: dict[str, Any]) -> bytes:
    content_value = entry.get("content")
    encoding = entry.get("encoding")
    if isinstance(content_value, str) and encoding == "base64":
        return base64.b64decode(content_value)
    download_url = entry.get("download_url")
    if not isinstance(download_url, str) or not download_url:
        raise SkillInstallError("GitHub file entry does not include downloadable content.")
    return await _get_bytes(client, download_url)


async def _get_json(client: Any, url: str) -> Any:
    response = await client.get(url)
    response.raise_for_status()
    return response.json()


async def _get_bytes(client: Any, url: str) -> bytes:
    response = await client.get(url)
    response.raise_for_status()
    content = response.content
    if not isinstance(content, bytes):
        content = bytes(content)
    return content


def _validate_relative_path(path: str) -> None:
    rel = PurePosixPath(path)
    if rel.is_absolute() or any(part == ".." for part in rel.parts):
        raise SkillInstallError("Skill package contains an unsafe path.")
    if len(rel.parts) > MAX_DEPTH:
        raise SkillInstallError("Skill package directory depth exceeds the limit.")


def _normalized_relative_path(path: str) -> str:
    _validate_relative_path(path)
    rel = PurePosixPath(path)
    if not rel.parts or rel.name in {"", "."}:
        raise SkillInstallError("Skill package contains an invalid path.")
    return rel.as_posix()


def _write_package_file(destination: Path, relative_path: str, content: bytes) -> None:
    target = destination.joinpath(*PurePosixPath(relative_path).parts)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
