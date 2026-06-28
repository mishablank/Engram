from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from engram.note_writer import CapturedMessage, merge_into_note


def _client(text: str) -> MagicMock:
    client = MagicMock()
    client.messages.create.return_value = SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)]
    )
    return client


def _msg(**kw) -> CapturedMessage:
    base = dict(text="new info", created=datetime(2026, 6, 3, 9, 0))
    base.update(kw)
    return CapturedMessage(**base)


def test_merge_rewrites_note_in_place(tmp_path: Path) -> None:
    note = tmp_path / "n.md"
    note.write_text("---\ncreated: x\n---\n# T\nold body\n", encoding="utf-8")
    merged_doc = "---\ncreated: x\n---\n# T\nintegrated body with new info\n"
    client = _client(merged_doc)

    path, merged = merge_into_note(note, _msg(), client)

    assert merged is True
    assert "integrated body with new info" in note.read_text(encoding="utf-8")
    assert "## Update" not in note.read_text(encoding="utf-8")


def test_falls_back_to_append_when_frontmatter_dropped(tmp_path: Path) -> None:
    note = tmp_path / "n.md"
    note.write_text("---\ncreated: x\n---\n# T\nold body\n", encoding="utf-8")
    # LLM returned a doc that lost the frontmatter → unsafe.
    client = _client("# T\nintegrated but no frontmatter\n")

    path, merged = merge_into_note(note, _msg(), client)

    assert merged is False
    body = note.read_text(encoding="utf-8")
    assert body.startswith("---\ncreated: x\n---")  # original preserved
    assert "## Update" in body  # append fallback fired


def test_falls_back_when_attachment_embed_dropped(tmp_path: Path) -> None:
    note = tmp_path / "n.md"
    note.write_text(
        "---\nc: x\n---\n# T\nbody\n![[attachments/pic.jpg]]\n", encoding="utf-8"
    )
    client = _client("---\nc: x\n---\n# T\nrewrote and dropped the image\n")

    _, merged = merge_into_note(note, _msg(), client)

    assert merged is False
    assert "![[attachments/pic.jpg]]" in note.read_text(encoding="utf-8")


def test_new_media_and_url_appended_after_merge(tmp_path: Path) -> None:
    note = tmp_path / "n.md"
    note.write_text("---\nc: x\n---\n# T\nold\n", encoding="utf-8")
    client = _client("---\nc: x\n---\n# T\nmerged prose\n")

    _, merged = merge_into_note(
        note,
        _msg(source_urls=["https://new.example/post"], images=["attachments/new.jpg"]),
        client,
    )

    body = note.read_text(encoding="utf-8")
    assert merged is True
    assert "https://new.example/post" in body
    assert "![[attachments/new.jpg]]" in body


def test_new_media_inserted_before_related_block(tmp_path: Path) -> None:
    note = tmp_path / "n.md"
    note.write_text("---\nc: x\n---\n# T\nold\n", encoding="utf-8")
    merged_doc = (
        "---\nc: x\n---\n# T\nmerged prose\n\n---\n*Related: [[Other]]*\n\n#ai\n"
    )
    client = _client(merged_doc)

    _, merged = merge_into_note(
        note, _msg(images=["attachments/new.jpg"]), client
    )

    body = note.read_text(encoding="utf-8")
    assert body.index("![[attachments/new.jpg]]") < body.index("*Related:")
