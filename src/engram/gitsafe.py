from __future__ import annotations

import logging
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

_IDENTITY = ("-c", "user.name=Engram", "-c", "user.email=engram@local")


def _git(base_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(base_dir), *args],
        capture_output=True,
        text=True,
    )


def is_repo(base_dir: Path) -> bool:
    try:
        r = _git(base_dir, "rev-parse", "--is-inside-work-tree")
    except FileNotFoundError:
        return False
    return r.returncode == 0 and r.stdout.strip() == "true"


def ensure_repo(base_dir: Path) -> bool:
    """Make `base_dir` a git repo if it isn't already. Returns True if git is usable."""
    if not base_dir.is_dir():
        return False
    try:
        if is_repo(base_dir):
            return True
        r = _git(base_dir, "init")
    except FileNotFoundError:
        log.warning("git not available; vault snapshots disabled")
        return False
    if r.returncode != 0:
        log.warning("git init failed in %s: %s", base_dir, r.stderr.strip())
        return False
    return True


def snapshot(base_dir: Path, message: str) -> bool:
    """Commit the current vault state. Returns True only when a commit was created.

    Safe no-op (returns False) when git is unavailable or there is nothing to commit.
    Never raises — a failed snapshot must not block a capture.
    """
    if not ensure_repo(base_dir):
        return False
    try:
        add = _git(base_dir, "add", "-A")
        if add.returncode != 0:
            log.warning("git add failed in %s: %s", base_dir, add.stderr.strip())
            return False
        # Nothing staged → nothing to commit.
        if _git(base_dir, "diff", "--cached", "--quiet").returncode == 0:
            return False
        commit = _git(base_dir, *_IDENTITY, "commit", "-m", message)
    except FileNotFoundError:
        return False
    if commit.returncode != 0:
        log.warning("git commit failed in %s: %s", base_dir, commit.stderr.strip())
        return False
    return True
