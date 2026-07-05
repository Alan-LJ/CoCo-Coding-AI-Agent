from __future__ import annotations

import pytest

from coco_code.permission.blacklist import hits_blacklist


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf /",
        "rm -fr ~",
        ":(){ :|:& };:",
        "dd if=/dev/zero of=/dev/sda",
        "mkfs.ext4 /dev/sda1",
        "chmod -R 777 /",
    ],
)
def test_blacklist_blocks_high_risk_commands(command: str) -> None:
    assert hits_blacklist(command) is True


@pytest.mark.parametrize("command", ["git status", "ls -la", "rm -rf ./build"])
def test_blacklist_allows_non_high_risk_commands(command: str) -> None:
    assert hits_blacklist(command) is False
