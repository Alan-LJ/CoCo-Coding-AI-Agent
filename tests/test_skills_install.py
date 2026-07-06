from __future__ import annotations

import asyncio
import base64
from pathlib import Path

import pytest

from coco_code.skills.install import (
    MAX_FILE_BYTES,
    SkillInstallError,
    install_from_url,
    parse_skill_url,
)


class FakeResponse:
    def __init__(self, *, content: bytes = b"", json_data=None) -> None:
        self.content = content
        self._json_data = json_data

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._json_data


class FakeClient:
    def __init__(self, responses: dict[str, FakeResponse]) -> None:
        self.responses = responses
        self.urls: list[str] = []

    async def get(self, url: str) -> FakeResponse:
        self.urls.append(url)
        try:
            return self.responses[url]
        except KeyError as exc:
            raise AssertionError(f"unexpected URL: {url}") from exc


def skill_bytes(name: str = "installed") -> bytes:
    return f"---\nname: {name}\ndescription: Installed skill\n---\nBody\n".encode()


def skill_text(name: str = "installed") -> str:
    return skill_bytes(name).decode()


def test_parse_skill_url_supported_forms() -> None:
    skills_sh = parse_skill_url("https://www.skills.sh/anthropics/skills/frontend-design")
    assert skills_sh.kind == "skills_sh"
    assert skills_sh.path == "anthropics/skills/frontend-design"
    assert parse_skill_url("https://skills.sh/example").kind == "skills_sh"
    raw = parse_skill_url("https://raw.githubusercontent.com/o/r/main/path/SKILL.md")
    assert raw.kind == "github_raw"
    assert raw.owner == "o"
    tree = parse_skill_url("https://github.com/o/r/tree/main/skills/demo")
    assert tree.kind == "github_tree"
    assert tree.path == "skills/demo"


def test_parse_skill_url_rejects_unsupported_host() -> None:
    with pytest.raises(SkillInstallError):
        parse_skill_url("https://example.com/skill")


def test_install_raw_skill(tmp_path: Path) -> None:
    async def run() -> None:
        url = "https://raw.githubusercontent.com/o/r/main/SKILL.md"
        client = FakeClient({url: FakeResponse(content=skill_bytes("raw-skill"))})

        result = await install_from_url(url, tmp_path, http_client=client)

        assert result.name == "raw-skill"
        assert (tmp_path / "raw-skill" / "SKILL.md").is_file()
        assert result.file_count == 1

    asyncio.run(run())


def test_install_github_tree_uses_contents_api(tmp_path: Path) -> None:
    async def run() -> None:
        url = "https://github.com/o/r/tree/main/skills/demo"
        api_url = "https://api.github.com/repos/o/r/contents/skills/demo?ref=main"
        content = base64.b64encode(skill_bytes("tree-skill")).decode()
        client = FakeClient(
            {
                api_url: FakeResponse(
                    json_data=[
                        {
                            "type": "file",
                            "name": "SKILL.md",
                            "content": content,
                            "encoding": "base64",
                        }
                    ]
                )
            }
        )

        result = await install_from_url(url, tmp_path, http_client=client)

        assert result.name == "tree-skill"
        assert client.urls == [api_url]

    asyncio.run(run())


def test_install_skills_sh_uses_detail_api_file_tree(tmp_path: Path) -> None:
    async def run() -> None:
        url = "https://www.skills.sh/anthropics/skills/frontend-design"
        api_url = "https://skills.sh/api/v1/skills/anthropics/skills/frontend-design"
        client = FakeClient(
            {
                api_url: FakeResponse(
                    json_data={
                        "files": [
                            {"path": "SKILL.md", "contents": skill_text("frontend-design")},
                            {"path": "examples/demo.txt", "contents": "example"},
                        ]
                    }
                )
            }
        )

        result = await install_from_url(url, tmp_path, http_client=client)

        assert result.name == "frontend-design"
        assert (tmp_path / "frontend-design" / "SKILL.md").is_file()
        assert (tmp_path / "frontend-design" / "examples" / "demo.txt").read_text() == "example"
        assert result.file_count == 2
        assert client.urls == [api_url]

    asyncio.run(run())


def test_install_skills_sh_falls_back_to_github_skill_folder(tmp_path: Path) -> None:
    async def run() -> None:
        url = "https://www.skills.sh/anthropics/skills/frontend-design"
        api_url = "https://skills.sh/api/v1/skills/anthropics/skills/frontend-design"
        github_url = "https://api.github.com/repos/anthropics/skills/contents/skills/frontend-design"
        content = base64.b64encode(skill_bytes("frontend-design")).decode()
        client = FakeClient(
            {
                api_url: FakeResponse(json_data={"files": None}),
                github_url: FakeResponse(
                    json_data=[
                        {
                            "type": "file",
                            "name": "SKILL.md",
                            "content": content,
                            "encoding": "base64",
                        }
                    ]
                ),
            }
        )

        result = await install_from_url(url, tmp_path, http_client=client)

        assert result.name == "frontend-design"
        assert client.urls == [api_url, github_url]

    asyncio.run(run())


def test_install_skills_sh_rejects_unsafe_snapshot_path(tmp_path: Path) -> None:
    async def run() -> None:
        url = "https://www.skills.sh/anthropics/skills/frontend-design"
        api_url = "https://skills.sh/api/v1/skills/anthropics/skills/frontend-design"
        client = FakeClient(
            {
                api_url: FakeResponse(
                    json_data={
                        "files": [
                            {"path": "SKILL.md", "contents": skill_text("frontend-design")},
                            {"path": "../escape.txt", "contents": "bad"},
                        ]
                    }
                )
            }
        )

        with pytest.raises(SkillInstallError, match="unsafe path"):
            await install_from_url(url, tmp_path, http_client=client)

        assert not any(path.name.startswith(".skill-install-") for path in tmp_path.iterdir())

    asyncio.run(run())


def test_install_rejects_missing_skill_md_and_cleans_staging(tmp_path: Path) -> None:
    async def run() -> None:
        url = "https://raw.githubusercontent.com/o/r/main/README.md"
        client = FakeClient({url: FakeResponse(content=b"not a skill")})

        with pytest.raises(SkillInstallError):
            await install_from_url(url, tmp_path, http_client=client)

        assert not any(path.name.startswith(".skill-install-") for path in tmp_path.iterdir())

    asyncio.run(run())


def test_install_rejects_oversized_file(tmp_path: Path) -> None:
    async def run() -> None:
        url = "https://raw.githubusercontent.com/o/r/main/SKILL.md"
        client = FakeClient({url: FakeResponse(content=b"x" * (MAX_FILE_BYTES + 1))})

        with pytest.raises(SkillInstallError):
            await install_from_url(url, tmp_path, http_client=client)

    asyncio.run(run())


def test_install_rejects_existing_target(tmp_path: Path) -> None:
    async def run() -> None:
        (tmp_path / "installed").mkdir()
        url = "https://raw.githubusercontent.com/o/r/main/SKILL.md"
        client = FakeClient({url: FakeResponse(content=skill_bytes("installed"))})

        with pytest.raises(SkillInstallError, match="already installed"):
            await install_from_url(url, tmp_path, http_client=client)

    asyncio.run(run())
