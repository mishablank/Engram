from datetime import datetime
from pathlib import Path

from tg_obsidian_bot.note_writer import (
    CapturedMessage,
    append_to_note,
    build_content,
    build_filename,
    slugify,
    write_note,
)


def test_slugify_strips_bad_chars():
    assert slugify("Hello/World: a [test]") == "Hello World a test"
    assert slugify("") == "note"
    assert slugify("one two three four five six seven", max_words=4) == "one two three four"


def test_filename_collision(tmp_path: Path):
    msg = CapturedMessage(text="topic note", created=datetime(2026, 5, 10, 14, 32))
    p1 = build_filename(msg, tmp_path)
    p1.write_text("x")
    p2 = build_filename(msg, tmp_path)
    p2.write_text("x")
    p3 = build_filename(msg, tmp_path)
    assert p1.name == "2026-05-10 14-32 topic note.md"
    assert p2.name == "2026-05-10 14-32 topic note (2).md"
    assert p3.name == "2026-05-10 14-32 topic note (3).md"


def test_build_content_has_frontmatter_related_tags():
    msg = CapturedMessage(
        text="some thought about defi",
        created=datetime(2026, 5, 10, 14, 32),
    )
    content = build_content(msg, related=["Note A", "Note B"], tags=["crypto", "defi"])
    assert content.startswith(
        "---\ncreated: 2026-05-10T14:32:00\nsource: telegram\nsource-type: other\n---"
    )
    assert "# some thought about defi" in content
    assert "*Related: [[Note A]] · [[Note B]]*" in content
    assert "#crypto #defi" in content


def test_build_content_embeds_images():
    msg = CapturedMessage(
        text="caption",
        images=["attachments/2026-05-10-1.jpg"],
        created=datetime(2026, 5, 10, 14, 32),
    )
    content = build_content(msg, related=[], tags=[])
    assert "![[attachments/2026-05-10-1.jpg]]" in content
    assert "caption" in content


def test_explicit_title_used_over_text_first_line():
    msg = CapturedMessage(
        text="raw body",
        title="Meta-Meta-Prompting: The Secret to Making AI Agents Work",
        source_urls=["https://x.com/garrytan/status/123"],
        created=datetime(2026, 5, 10, 14, 32),
    )
    content = build_content(msg, related=[], tags=["ai"])
    assert "# Meta-Meta-Prompting" in content
    assert "> Source: https://x.com/garrytan/status/123" in content
    assert "raw body" in content


def test_url_only_text_does_not_become_title():
    msg = CapturedMessage(
        text="https://x.com/garrytan/status/123",
        created=datetime(2026, 5, 10, 14, 32),
    )
    content = build_content(msg, related=[], tags=[])
    assert "# https" not in content
    assert "# Note 2026-05-10 14-32" in content


def test_write_note_creates_file(tmp_path: Path):
    msg = CapturedMessage(text="hello world", created=datetime(2026, 5, 10, 14, 32))
    path = write_note(msg, tmp_path, related=["X"], tags=["t"])
    assert path.exists()
    assert "[[X]]" in path.read_text()


def test_frontmatter_includes_urls():
    msg = CapturedMessage(
        text="body",
        title="t",
        source_urls=["https://x.com/foo/1"],
        created=datetime(2026, 5, 10, 14, 32),
    )
    content = build_content(msg, related=[], tags=[])
    assert "urls:" in content
    assert "  - https://x.com/foo/1" in content


def test_frontmatter_includes_source_type():
    msg = CapturedMessage(
        text="body",
        title="t",
        source_type="tweet",
        created=datetime(2026, 5, 10, 14, 32),
    )
    content = build_content(msg, related=[], tags=[])
    assert "source-type: tweet" in content


def test_append_to_note_adds_update_section(tmp_path: Path):
    msg1 = CapturedMessage(
        text="original", title="Topic",
        source_urls=["https://example.com/a"],
        created=datetime(2026, 5, 10, 14, 32),
    )
    path = write_note(msg1, tmp_path, related=[], tags=["t"])
    original_text = path.read_text()

    msg2 = CapturedMessage(
        text="more thoughts",
        source_urls=["https://example.com/b"],
        created=datetime(2026, 5, 11, 9, 0),
    )
    append_to_note(path, msg2)
    new_text = path.read_text()

    assert new_text.startswith(original_text.rstrip())
    assert "## Update 2026-05-11 09:00" in new_text
    assert "more thoughts" in new_text
    assert "> Source: https://example.com/b" in new_text
