from __future__ import annotations

from coco_code.__main__ import _compact_notification_payload
from coco_code.agent import CompactNotification
from coco_code.context import CompactBoundary
from coco_code.conversation import Message, ToolResultBlock


def test_compact_notification_payload_includes_retention_evidence() -> None:
    keep = [
        Message(
            role="user",
            content="run the focused regression test",
            tool_results=[ToolResultBlock(tool_use_id="tool-1", content="failed")],
        )
    ]
    event = CompactNotification(
        before_tokens=95_000,
        message="context compacted",
        boundary=CompactBoundary(summary="Target parser.py and preserve its API.", keep=keep),
    )

    payload = _compact_notification_payload(event)

    assert payload["type"] == "compact"
    assert payload["before_tokens"] == 95_000
    assert payload["summary"] == "Target parser.py and preserve its API."
    assert payload["keep_message_count"] == 1
    assert payload["keep_messages"][0]["content"] == "run the focused regression test"
    assert payload["keep_messages"][0]["tool_results"][0]["content"] == "failed"


def test_compact_notification_payload_handles_missing_boundary() -> None:
    event = CompactNotification(before_tokens=10, message="not compacted", boundary=None)
    payload = _compact_notification_payload(event)
    assert payload["summary"] == ""
    assert payload["keep_messages"] == []
