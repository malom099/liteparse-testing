#!/usr/bin/env python3
"""Non-blocking reminder to update CHANGELOG.md when source code changes."""

import subprocess  # nosec B404
import sys

result = subprocess.run(  # nosec B603 B607
    ["git", "diff", "--cached", "--name-only"],
    capture_output=True,
    text=True,
)
staged = [f.strip() for f in result.stdout.strip().splitlines() if f.strip()]


def _is_source_file(path: str) -> bool:
    p = path.lower().replace("\\", "/")
    if not path.endswith(".py"):
        return False
    # Exclude tests and this script itself
    return not any(seg in p for seg in ("test", "check_changelog_reminder"))


source_changed = any(_is_source_file(f) for f in staged)
changelog_staged = any("changelog" in f.lower() for f in staged)

if source_changed and not changelog_staged:
    print("Reminder: .py source files changed but CHANGELOG.md was not updated.")
    print(
        "  -> If this is a notable change, add an entry under [Unreleased] before merging."
    )

sys.exit(0)
