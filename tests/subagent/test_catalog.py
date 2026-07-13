from __future__ import annotations

from pathlib import Path

from coco_code.subagent import Source
from coco_code.subagent.catalog import Catalog, load_catalog
from coco_code.subagent.embed import builtin_definitions


def write_agent(root: Path, name: str, marker: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{name}.md").write_text(
        f"---\nname: {name}\ndescription: {marker}\n---\n{marker}\n",
        encoding="utf-8",
    )


def test_builtin() -> None:
    names = {definition.name for definition in builtin_definitions()}
    assert {"general-purpose", "Explore", "Plan"}.issubset(names)


def test_load_catalog_uses_coco_code_agents_dirs(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    monkeypatch.setattr(Path, "home", lambda: home)
    write_agent(home / ".coco-code" / "agents", "Explore", "user explore")
    write_agent(project / ".coco-code" / "agents", "Explore", "project explore")

    catalog = load_catalog(project)

    definition = catalog.resolve("explore")
    assert definition is not None
    assert definition.source == Source.PROJECT
    assert definition.description == "project explore"


def test_load_catalog_falls_back_to_user_then_builtin(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    monkeypatch.setattr(Path, "home", lambda: home)
    write_agent(home / ".coco-code" / "agents", "Explore", "user explore")

    catalog = load_catalog(project)
    assert catalog.resolve("Explore").source == Source.USER

    empty_home = tmp_path / "empty-home"
    monkeypatch.setattr(Path, "home", lambda: empty_home)
    catalog = load_catalog(project)
    assert catalog.resolve("Explore").source == Source.BUILTIN


def test_catalog_fork_definition() -> None:
    definition = Catalog().fork_definition()
    assert definition.is_fork() is True


def test_bad_user_definition_is_skipped(tmp_path: Path, monkeypatch, capsys) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    monkeypatch.setattr(Path, "home", lambda: home)
    write_agent(home / ".coco-code" / "agents", "Good", "good")
    (home / ".coco-code" / "agents" / "bad.md").write_text(
        "---\nname: bad\n",
        encoding="utf-8",
    )
    catalog = load_catalog(project)
    assert catalog.resolve("Good") is not None
    assert catalog.resolve("bad") is None
    assert "skipping" in capsys.readouterr().err
