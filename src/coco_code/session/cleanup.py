from __future__ import annotations

import logging
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from coco_code.session.ids import parse_session_time

LOGGER = logging.getLogger(__name__)


def clean_expired_sessions(workspace: Path, max_age_days: int = 30) -> None:
    sessions_dir = workspace / ".coco-code" / "sessions"
    if not sessions_dir.exists():
        return
    cutoff = datetime.now() - timedelta(days=max_age_days)
    for session_dir in sessions_dir.iterdir():
        if not session_dir.is_dir():
            continue
        created = parse_session_time(session_dir.name)
        if created is None or created >= cutoff:
            continue
        try:
            shutil.rmtree(session_dir)
        except OSError as exc:
            LOGGER.warning("failed to clean expired session %s: %s", session_dir, exc)
