from __future__ import annotations

from datetime import datetime
from pathlib import Path

from coco_code.conversation import Conversation
from coco_code.session import (
    SessionWriter,
    clean_expired_sessions,
    list_sessions,
    load_session,
    new_session_id,
    parse_session_time,
    session_paths,
)
from coco_code.session.codec import compact_marker
from coco_code.tools import ToolCall, ToolResult


def test_session_id_format() -> None:
    session_id = new_session_id(datetime(2026, 6, 1, 14, 30, 22))
    assert session_id.startswith("20260601-143022-")
    assert parse_session_time(session_id) == datetime(2026, 6, 1, 14, 30, 22)


def test_writer_and_loader_roundtrip(tmp_path: Path) -> None:
    paths = session_paths(tmp_path, new_session_id())
    writer = SessionWriter(paths, model="fake-model")
    conv = Conversation(on_append=writer.append_item, on_replace=writer.replace_items)
    conv.add_user("hello")
    conv.add_assistant("hi")
    call = ToolCall("1", "ReadFile", {"path": "a.txt"}, '{"path":"a.txt"}')
    conv.add_tool_call(call)
    conv.add_tool_result(ToolResult("1", "ReadFile", True, "ok", {"content": "x"}, None, 1))
    writer.close()
    lines = paths.jsonl_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 4
    assert '"model":"fake-model"' in lines[0]
    loaded = load_session(paths)
    assert loaded.loaded_count == 4
    assert loaded.skipped_bad_lines == 0


def test_compact_marker_and_bad_line(tmp_path: Path) -> None:
    paths = session_paths(tmp_path, new_session_id())
    paths.session_dir.mkdir(parents=True)
    paths.jsonl_path.write_text(
        '{"role":"user","content":"old","ts":1}\n'
        "{bad json\n"
        + compact_marker(2).to_json_line()
        + '{"role":"user","content":"new","ts":3}\n',
        encoding="utf-8",
    )
    loaded = load_session(paths)
    assert loaded.skipped_bad_lines == 1
    assert loaded.loaded_count == 1
    assert loaded.items[0].content == "new"  # type: ignore[attr-defined]


def test_list_and_cleanup_sessions(tmp_path: Path) -> None:
    old_id = "20260401-120000-dead"
    fresh_id = new_session_id(datetime.now())
    for session_id in (old_id, fresh_id):
        paths = session_paths(tmp_path, session_id)
        paths.session_dir.mkdir(parents=True)
        paths.jsonl_path.write_text(
            '{"role":"user","content":"hello","ts":1,"model":"m"}\n', encoding="utf-8"
        )
    legacy = tmp_path / ".coco-code" / "sessions" / "1717000000-abc12345"
    legacy.mkdir(parents=True)
    infos = list_sessions(tmp_path)
    assert {info.session_id for info in infos} == {old_id, fresh_id}
    clean_expired_sessions(tmp_path, max_age_days=30)
    assert not (tmp_path / ".coco-code" / "sessions" / old_id).exists()
    assert (tmp_path / ".coco-code" / "sessions" / fresh_id).exists()
    assert legacy.exists()
