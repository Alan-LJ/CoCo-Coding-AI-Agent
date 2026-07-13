from __future__ import annotations

from coco_code.worktree.lifecycle import (
    AutoCleanupReport,
    ExitAction,
    ExitOptions,
    ExitReport,
    WorktreeHasChangesError,
)
from coco_code.worktree.manager import Manager, Worktree
from coco_code.worktree.session import WorktreeSession
from coco_code.worktree.slug import flat_slug, validate_slug
from coco_code.worktree.sweep import random_agent_name

__all__ = [
    "AutoCleanupReport",
    "ExitAction",
    "ExitOptions",
    "ExitReport",
    "Manager",
    "Worktree",
    "WorktreeHasChangesError",
    "WorktreeSession",
    "flat_slug",
    "random_agent_name",
    "validate_slug",
]
