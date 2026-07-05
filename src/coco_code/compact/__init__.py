from __future__ import annotations

from coco_code.compact.manager import ManageInput, ManageOutput, TriggerKind, manage_context
from coco_code.compact.recovery import FileReadRecord, RecoveryState
from coco_code.compact.state import (
    CompactCircuitBreaker,
    ContentReplacementState,
    ReplacementDecision,
    SessionContext,
    new_session_context,
)

__all__ = [
    "CompactCircuitBreaker",
    "ContentReplacementState",
    "FileReadRecord",
    "ManageInput",
    "ManageOutput",
    "RecoveryState",
    "ReplacementDecision",
    "SessionContext",
    "TriggerKind",
    "manage_context",
    "new_session_context",
]
