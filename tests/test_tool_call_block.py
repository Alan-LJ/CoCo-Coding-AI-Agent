# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com

from __future__ import annotations

from coco_code.app import ReasoningLoopBlock, ToolCallBlock, _format_detail


def test_format_detail_colors_edit_file_diff_lines():
    output = (
        "Updated foo.py with 1 addition and 1 removal\n"
        "   10  unchanged\n"
        "-   11  old line\n"
        "+   11  new line"
    )
    detail = _format_detail("EditFile", {"file_path": "foo.py"}, output)

    assert "[green]" in detail
    assert "new line" in detail
    assert "[red]" in detail
    assert "old line" in detail
    assert "[dim]" in detail


def test_format_detail_escapes_brackets_in_code():
    # Python 类型标注里的方括号不应该被当成 Rich markup 标签解析
    output = "+    1  def foo(x: list[int]) -> dict[str, int]:"
    detail = _format_detail("EditFile", {"file_path": "foo.py"}, output)
    assert "list\\[int]" in detail
    assert "dict\\[str, int]" in detail


def test_edit_file_block_auto_expands_on_success():
    block = ToolCallBlock("EditFile", {"file_path": "foo.py"})
    block.set_result("Updated foo.py with 1 addition and 0 removals\n+    1  hello", False, 0.1)

    assert block._collapsed is False
    assert "hello" in block.render().plain


def test_edit_file_block_stays_collapsed_on_error():
    block = ToolCallBlock("EditFile", {"file_path": "foo.py"})
    block.set_result("Error: old_string not found in file", True, 0.1)
    assert block._collapsed is True


def test_other_tools_still_default_collapsed():
    block = ToolCallBlock("Bash", {"command": "ls"})
    block.set_result("file1\nfile2", False, 0.1)
    assert block._collapsed is True


def test_reasoning_loop_streams_expanded_then_collapses_on_finish():
    block = ReasoningLoopBlock("Thinking")

    block.append_thinking("Inspecting the request. ")
    block.append_thinking("Checking the available tools.")
    block.record_tool_use()

    assert block._collapsed is False
    assert block.body.display is True
    assert "Inspecting the request" in block._thinking_label.render().plain

    block.finish(2.5)

    assert block._collapsed is True
    assert block.body.display is False
    assert "Thought for 2.5s · 1 tool call" in block._header.render().plain

    block.toggle()

    assert block._collapsed is False
    assert block.body.display is True
    assert "Inspecting the request" in block._thinking_label.render().plain


def test_reasoning_loop_cannot_be_collapsed_while_streaming():
    block = ReasoningLoopBlock("Reasoning")
    block.append_thinking("Still working")

    block.toggle()

    assert block._collapsed is False
    assert block.body.display is True
    assert "Still working" in block._thinking_label.render().plain


def test_restored_reasoning_summary_is_collapsed_and_expandable():
    block = ReasoningLoopBlock("Reasoning")
    block.append_thinking("Loaded from the project session.")
    block.record_tool_use()

    block.restore()

    assert block._collapsed is True
    assert block.body.display is False
    assert "Saved reasoning summary" in block._header.render().plain
    assert "1 tool call" in block._header.render().plain

    block.toggle()

    assert block._collapsed is False
    assert block.body.display is True
    assert "Loaded from the project session" in block._thinking_label.render().plain
