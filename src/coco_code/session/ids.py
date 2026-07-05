from __future__ import annotations

import secrets
from datetime import datetime


def new_session_id(now: datetime | None = None) -> str:
    timestamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    return f"{timestamp}-{secrets.token_hex(2)}"


def parse_session_time(session_id: str) -> datetime | None:
    try:
        if len(session_id) != 20 or session_id[15] != "-":
            return None
        suffix = session_id[16:]
        if len(suffix) != 4 or any(ch not in "0123456789abcdefABCDEF" for ch in suffix):
            return None
        return datetime.strptime(session_id[:15], "%Y%m%d-%H%M%S")
    except ValueError:
        return None
