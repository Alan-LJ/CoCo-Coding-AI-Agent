from __future__ import annotations

from collections.abc import Callable

from coco_code.command import WorktreeSummary
from coco_code.worktree import ExitAction, ExitOptions, Manager


class WorktreeAdapter:
    def __init__(self, manager: Manager, set_active_cwd: Callable[[str], None]) -> None:
        self._manager = manager
        self._set_active_cwd = set_active_cwd

    async def create(self, name: str) -> tuple[str, str]:
        wt = await self._manager.create(name, "HEAD", manual=True)
        return wt.path, wt.branch

    def list(self) -> list[WorktreeSummary]:
        session = self._manager.current_session()
        active_name = session.worktree_name if session is not None else ""
        return [
            WorktreeSummary(
                name=item.name,
                path=item.path,
                branch=item.branch,
                active=item.name == active_name,
                manual=item.manual,
            )
            for item in self._manager.list()
        ]

    async def enter(self, name: str) -> None:
        session = await self._manager.enter(name)
        self._set_active_cwd(session.worktree_path)

    async def exit(self, action: str, discard: bool) -> bool:
        session = self._manager.current_session()
        if session is None:
            raise ValueError("当前未进入 Worktree")
        report = await self._manager.exit(
            session.worktree_name,
            ExitAction.REMOVE if action == "remove" else ExitAction.KEEP,
            ExitOptions(discard_changes=discard),
        )
        self._set_active_cwd("")
        return report.removed

    async def remove(self, name: str, discard: bool) -> None:
        await self._manager.remove(name, ExitOptions(discard_changes=discard))
        session = self._manager.current_session()
        if session is None or session.worktree_name == name:
            self._set_active_cwd("")
