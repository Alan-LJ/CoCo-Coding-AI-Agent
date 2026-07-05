from __future__ import annotations

from pathlib import Path

from coco_code.instructions import InstructionLoader


def test_three_layer_priority(tmp_path: Path) -> None:
    project = tmp_path / "project"
    home = tmp_path / "home"
    (project / ".mewcode").mkdir(parents=True)
    (home / ".mewcode").mkdir(parents=True)
    (project / "MEWCODE.md").write_text("project-root", encoding="utf-8")
    (project / ".mewcode" / "MEWCODE.md").write_text("project-config", encoding="utf-8")
    (home / ".mewcode" / "MEWCODE.md").write_text("user", encoding="utf-8")
    result = InstructionLoader(project, user_home=home).load().content
    assert result.index("project-root") < result.index("project-config") < result.index("user")


def test_include_expands_and_detects_cycle(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "MEWCODE.md").write_text("A\n@include b.md", encoding="utf-8")
    (project / "b.md").write_text("B\n@include MEWCODE.md", encoding="utf-8")
    result = InstructionLoader(project).load().content
    assert "A" in result
    assert "B" in result
    assert "检测到环路" in result


def test_include_depth_and_boundary_and_binary(tmp_path: Path) -> None:
    project = tmp_path / "project"
    outside = tmp_path / "outside.md"
    project.mkdir()
    outside.write_text("outside", encoding="utf-8")
    (project / "MEWCODE.md").write_text(
        "@include child1.md\n@include ../outside.md\n@include bin.dat", encoding="utf-8"
    )
    for index in range(1, 7):
        next_name = f"child{index + 1}.md" if index < 6 else "leaf.md"
        (project / f"child{index}.md").write_text(f"@include {next_name}", encoding="utf-8")
    (project / "leaf.md").write_text("leaf", encoding="utf-8")
    (project / "bin.dat").write_bytes(b"abc\x00def")
    result = InstructionLoader(project).load().content
    assert "超过最大嵌套深度" in result
    assert "路径超出允许范围" in result
    assert "二进制文件" in result
