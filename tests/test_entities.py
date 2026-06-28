from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from engram import entities
from engram.entities import (
    Entity,
    entity_path,
    extract_entities,
    rebuild_entity_pages,
    upsert_entity_page,
)


def _client(text: str) -> MagicMock:
    client = MagicMock()
    client.messages.create.return_value = SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)]
    )
    return client


def _client_seq(texts: list[str]) -> MagicMock:
    client = MagicMock()
    client.messages.create.side_effect = [
        SimpleNamespace(content=[SimpleNamespace(type="text", text=t)]) for t in texts
    ]
    return client


def test_extract_parses_typed_entities() -> None:
    payload = (
        '[{"name":"Andrej Karpathy","type":"person","observation":"argues for X"},'
        '{"name":"Bitter Lesson","type":"concept","observation":"scaling wins"},'
        '{"name":"junk","type":"animal","observation":"skip"}]'
    )
    ents = extract_entities(_client(payload), "Title", "body")
    assert [(e.name, e.type) for e in ents] == [
        ("Andrej Karpathy", "person"),
        ("Bitter Lesson", "concept"),
    ]


def test_extract_empty_body_skips_api() -> None:
    client = MagicMock()
    assert extract_entities(client, "t", "   ") == []
    client.messages.create.assert_not_called()


def test_entity_path_uses_typed_folder(tmp_path: Path) -> None:
    p = entity_path(tmp_path, Entity("Andrej Karpathy", "person", "x"))
    assert p == tmp_path / "People" / "Andrej Karpathy.md"
    c = entity_path(tmp_path, Entity("Bitter Lesson", "concept", "x"))
    assert c == tmp_path / "Concepts" / "Bitter Lesson.md"


def test_upsert_creates_page(tmp_path: Path) -> None:
    ent = Entity("Andrej Karpathy", "person", "coined software 2.0")
    p = upsert_entity_page(tmp_path, ent, "Source Note")
    text = p.read_text(encoding="utf-8")
    assert "entity-type: person" in text
    assert "# Andrej Karpathy" in text
    assert "- coined software 2.0 ([[Source Note]])" in text
    assert "- [[Source Note]]" in text


def test_upsert_accumulates_across_sources(tmp_path: Path) -> None:
    upsert_entity_page(tmp_path, Entity("Karpathy", "person", "obs one"), "Note A")
    p = upsert_entity_page(
        tmp_path, Entity("Karpathy", "person", "obs two"), "Note B"
    )
    text = p.read_text(encoding="utf-8")
    assert "- obs one ([[Note A]])" in text
    assert "- obs two ([[Note B]])" in text
    assert text.count("## Observations") == 1
    assert "- [[Note A]]" in text and "- [[Note B]]" in text


def test_upsert_is_idempotent_for_same_source(tmp_path: Path) -> None:
    upsert_entity_page(tmp_path, Entity("Karpathy", "person", "same obs"), "Note A")
    p = upsert_entity_page(
        tmp_path, Entity("Karpathy", "person", "same obs"), "Note A"
    )
    text = p.read_text(encoding="utf-8")
    assert text.count("- same obs ([[Note A]])") == 1


def test_rebuild_groups_entities_and_writes_pages(tmp_path: Path) -> None:
    # 2 extraction calls (one per note), then synthesis calls per unique entity.
    client = _client_seq(
        [
            '[{"name":"Karpathy","type":"person","observation":"obs from note 1"}]',
            '[{"name":"karpathy","type":"person","observation":"obs from note 2"},'
            '{"name":"RAG","type":"concept","observation":"retrieval"}]',
            "Andrej Karpathy is an AI researcher.",  # synth lead for person
            "RAG combines retrieval and generation.",  # synth lead for concept
        ]
    )
    notes = [("Note 1", "body one"), ("Note 2", "body two")]

    count = rebuild_entity_pages(tmp_path, client, notes)

    assert count == 2  # Karpathy (merged) + RAG
    person = (tmp_path / "People" / "Karpathy.md").read_text(encoding="utf-8")
    assert "obs from note 1 ([[Note 1]])" in person
    assert "obs from note 2 ([[Note 2]])" in person  # case-insensitive merge
    assert "Andrej Karpathy is an AI researcher." in person
    assert (tmp_path / "Concepts" / "RAG.md").exists()


def test_rebuild_clears_stale_pages(tmp_path: Path) -> None:
    stale = tmp_path / "People" / "Old Person.md"
    stale.parent.mkdir(parents=True)
    stale.write_text("---\nentity-type: person\n---\n# Old Person\n", encoding="utf-8")
    client = _client_seq(
        ['[{"name":"New","type":"person","observation":"o"}]', "New is a person."]
    )

    rebuild_entity_pages(tmp_path, client, [("N", "b")])

    assert not stale.exists()
    assert (tmp_path / "People" / "New.md").exists()
