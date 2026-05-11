from pathlib import Path

from engram.vault import scan_vault


def test_scan_extracts_titles_and_tags(tmp_path: Path) -> None:
    (tmp_path / "Note A.md").write_text("body #crypto #defi\n")
    (tmp_path / "Note B.md").write_text(
        "---\ntags: [research, ai]\n---\n\n# B\nstuff #crypto\n"
    )
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "Note C.md").write_text("# C\n")
    (tmp_path / "attachments").mkdir()
    (tmp_path / "attachments" / "img.md").write_text("# ignored #skip\n")

    idx = scan_vault(tmp_path)

    assert "Note A" in idx.titles
    assert "Note B" in idx.titles
    assert "Note C" in idx.titles
    assert "img" not in idx.titles
    assert "crypto" in idx.tags
    assert "research" in idx.tags
    assert "ai" in idx.tags
    assert "defi" in idx.tags
    assert "skip" not in idx.tags


def test_scan_handles_yaml_list_tags(tmp_path: Path) -> None:
    (tmp_path / "X.md").write_text("---\ntags:\n  - alpha\n  - beta\n---\nbody\n")
    idx = scan_vault(tmp_path)
    assert "alpha" in idx.tags
    assert "beta" in idx.tags


def test_scan_indexes_urls_from_frontmatter_and_body(tmp_path: Path) -> None:
    (tmp_path / "Note 1.md").write_text(
        "---\nurls:\n  - https://x.com/a/1\n---\nbody\n"
    )
    (tmp_path / "Note 2.md").write_text(
        "# heading\n\n> Source: https://example.com/article\n\nbody\n"
    )
    idx = scan_vault(tmp_path)
    assert idx.find_by_url("https://x.com/a/1").name == "Note 1.md"
    assert idx.find_by_url("https://example.com/article").name == "Note 2.md"
    assert idx.find_by_url("https://nope.com") is None


def test_find_by_title_normalized(tmp_path: Path) -> None:
    (tmp_path / "Meta-Meta-Prompting Secret to AI Agents.md").write_text("body\n")
    idx = scan_vault(tmp_path)
    assert idx.find_by_title("meta meta prompting secret to AI agents") is not None
    assert idx.find_by_title("Meta-Meta-Prompting: Secret to AI Agents!") is not None
    assert idx.find_by_title("totally different") is None
