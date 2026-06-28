from __future__ import annotations

import subprocess
from pathlib import Path

from engram import gitsafe


def _log(base: Path) -> list[str]:
    r = subprocess.run(
        ["git", "-C", str(base), "log", "--pretty=%s"],
        capture_output=True, text=True,
    )
    return [line for line in r.stdout.splitlines() if line]


def test_snapshot_inits_repo_and_commits(tmp_path: Path) -> None:
    (tmp_path / "note.md").write_text("hello\n", encoding="utf-8")
    assert not gitsafe.is_repo(tmp_path)

    created = gitsafe.snapshot(tmp_path, "engram: first")

    assert created is True
    assert gitsafe.is_repo(tmp_path)
    assert _log(tmp_path) == ["engram: first"]


def test_snapshot_noop_when_nothing_changed(tmp_path: Path) -> None:
    (tmp_path / "note.md").write_text("hello\n", encoding="utf-8")
    assert gitsafe.snapshot(tmp_path, "engram: first") is True

    # No file changes since the last commit.
    assert gitsafe.snapshot(tmp_path, "engram: second") is False
    assert _log(tmp_path) == ["engram: first"]


def test_snapshot_commits_subsequent_change(tmp_path: Path) -> None:
    note = tmp_path / "note.md"
    note.write_text("hello\n", encoding="utf-8")
    gitsafe.snapshot(tmp_path, "engram: first")

    note.write_text("hello world\n", encoding="utf-8")
    created = gitsafe.snapshot(tmp_path, "engram: edit")

    assert created is True
    assert _log(tmp_path) == ["engram: edit", "engram: first"]


def test_snapshot_returns_false_for_missing_dir(tmp_path: Path) -> None:
    assert gitsafe.snapshot(tmp_path / "nope", "x") is False
