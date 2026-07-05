from __future__ import annotations

import re

# Heuristic, intentionally non-configurable command denylist. This is not complete; it only
# catches high-signal destructive commands before any user/project rules can allow them.
_BLACKLIST: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\brm\s+-[A-Za-z]*[rf][A-Za-z]*[rf][A-Za-z]*\s+(?:/|/\*|~|\$HOME\b|%USERPROFILE%\b|[A-Za-z]:\\)(?:\s|$)",
        re.IGNORECASE,
    ),
    re.compile(r"\bdd\b.*\bof\s*=\s*/dev/(?:sd|hd|vd|nvme|disk|rdisk)", re.IGNORECASE),
    re.compile(r":\s*\(\s*\)\s*\{\s*:\s*\|\s*:\s*&\s*}\s*;?\s*:"),
    re.compile(r"\bmkfs(?:\.[A-Za-z0-9_-]+)?\b", re.IGNORECASE),
    re.compile(r">\s*/dev/(?:sd|hd|vd|nvme|disk|rdisk)", re.IGNORECASE),
    re.compile(r"\bchmod\s+-R\s+0?777\s+/(?:\s|$)", re.IGNORECASE),
    re.compile(
        r"\bRemove-Item\b.*\b-Recurse\b.*\b-Force\b.*(?:[A-Za-z]:\\|~|\$HOME)", re.IGNORECASE
    ),
)


def hits_blacklist(command: str) -> bool:
    return any(pattern.search(command) for pattern in _BLACKLIST)
