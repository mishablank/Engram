from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from tg_obsidian_bot import bot as bot_module
from tg_obsidian_bot.config import DEFAULT_CATEGORIES, Config
from tg_obsidian_bot.linker import Enrichment
from tg_obsidian_bot.vault import VaultIndex


def _make_state(tmp_path: Path, monkeypatch) -> bot_module.BotState:
    monkeypatch.setattr(bot_module, "Anthropic", lambda api_key=None: MagicMock())
    cfg = Config(
        telegram_token="t",
        anthropic_api_key="k",
        openai_api_key="o",
        allowed_user_ids={42},
        base_dir=tmp_path,
        categories=DEFAULT_CATEGORIES,
    )
    state = bot_module.BotState(cfg)
    state._vault_index = VaultIndex()
    state._vault_loaded_at = time.time()
    return state


def _fake_message(
    text="",
    photo=None,
    caption=None,
    media_group_id=None,
    document=None,
    forward_origin=None,
):
    return SimpleNamespace(
        text=text,
        caption=caption,
        photo=photo or [],
        media_group_id=media_group_id,
        voice=None,
        audio=None,
        document=document,
        forward_origin=forward_origin,
        forward_from_chat=None,
        forward_from=None,
        forward_date=None,
        forward_from_message_id=None,
        reply_to_message=None,
    )


def _fake_update(message, user_id=42, chat_id=999):
    chat = SimpleNamespace(id=chat_id, send_message=AsyncMock())
    user = SimpleNamespace(id=user_id)
    return SimpleNamespace(
        effective_user=user,
        effective_chat=chat,
        effective_message=message,
        callback_query=None,
    )


def _fake_callback_update(data: str, user_id=42, chat_id=999):
    query = SimpleNamespace(
        data=data,
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
    )
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=user_id),
        effective_chat=SimpleNamespace(id=chat_id),
        effective_message=None,
        callback_query=query,
    )


def _patch_enrich(monkeypatch, **kw):
    enr = Enrichment(
        title=kw.get("title", "Auto Title"),
        summary=kw.get("summary", "auto summary"),
        related=kw.get("related", []),
        tags=kw.get("tags", []),
        folder=kw.get("folder", "AI"),
        source_type=kw.get("source_type", "article"),
    )
    monkeypatch.setattr(bot_module, "enrich_note", lambda *a, **k: enr)
    monkeypatch.setattr(bot_module, "fetch_urls", lambda urls: {})
    return enr


# ---------- forward provenance ----------


def test_extract_forward_info_from_channel():
    chat = SimpleNamespace(username="acmechan", title="Acme Channel")
    origin = SimpleNamespace(
        chat=chat, message_id=42, date=datetime(2026, 5, 1, 12, 0, 0)
    )
    msg = _fake_message(text="forwarded text", forward_origin=origin)
    info = bot_module._extract_forward_info([msg])
    assert info["from"] == "@acmechan"
    assert info["message_id"] == 42
    assert info["date"] == datetime(2026, 5, 1, 12, 0, 0)


def test_extract_forward_info_from_user_no_username():
    user = SimpleNamespace(username=None, full_name="Alice")
    origin = SimpleNamespace(sender_user=user, date=datetime(2026, 5, 1))
    msg = _fake_message(text="x", forward_origin=origin)
    info = bot_module._extract_forward_info([msg])
    assert info["from"] == "Alice"


def test_extract_forward_info_returns_none_when_not_forwarded():
    msg = _fake_message(text="ordinary")
    assert bot_module._extract_forward_info([msg]) is None


async def test_forwarded_text_writes_provenance_to_frontmatter(tmp_path: Path, monkeypatch):
    state = _make_state(tmp_path, monkeypatch)
    _patch_enrich(monkeypatch, folder="AI")

    chat = SimpleNamespace(username="acmechan", title="Acme Channel")
    origin = SimpleNamespace(
        chat=chat, message_id=42, date=datetime(2026, 5, 1, 12, 0, 0)
    )
    msg = _fake_message(text="forwarded body", forward_origin=origin)
    update = _fake_update(msg)
    handlers = bot_module.make_handlers(state)
    on_message, on_folder_choice = handlers[0], handlers[4]

    await on_message(update, SimpleNamespace(application=None))
    token = next(iter(state._pending))
    ai_idx = state.config.categories.index("AI")
    cb = _fake_callback_update(f"f|{token}|{ai_idx}")
    await on_folder_choice(cb, SimpleNamespace())

    written = list(tmp_path.rglob("*.md"))
    assert len(written) == 1
    content = written[0].read_text(encoding="utf-8")
    assert "forwarded-from: @acmechan" in content
    assert "forwarded-at: 2026-05-01T12:00:00" in content
    assert "original-message-id: 42" in content


# ---------- /undo and /edit ----------


async def test_undo_deletes_last_capture(tmp_path: Path, monkeypatch):
    state = _make_state(tmp_path, monkeypatch)
    _patch_enrich(monkeypatch, folder="AI")
    msg = _fake_message(text="https://example.com/x")
    update = _fake_update(msg)
    handlers = bot_module.make_handlers(state)
    on_message, on_folder_choice, on_undo = handlers[0], handlers[4], handlers[7]

    await on_message(update, SimpleNamespace(application=None))
    token = next(iter(state._pending))
    ai_idx = state.config.categories.index("AI")
    cb = _fake_callback_update(f"f|{token}|{ai_idx}")
    await on_folder_choice(cb, SimpleNamespace())
    written = list(tmp_path.rglob("*.md"))
    assert len(written) == 1
    last = state._last_capture[999]
    assert last == written[0]

    undo_update = _fake_update(_fake_message(text="/undo"))
    ctx = SimpleNamespace(args=[])
    await on_undo(undo_update, ctx)
    assert not last.exists()
    assert 999 not in state._last_capture


async def test_undo_with_no_history_replies_friendly(tmp_path: Path, monkeypatch):
    state = _make_state(tmp_path, monkeypatch)
    on_undo = bot_module.make_handlers(state)[7]
    update = _fake_update(_fake_message(text="/undo"))
    await on_undo(update, SimpleNamespace(args=[]))
    text = update.effective_chat.send_message.call_args.args[0]
    assert "nothing" in text.lower()


async def test_edit_replaces_last_capture_in_same_folder(tmp_path: Path, monkeypatch):
    state = _make_state(tmp_path, monkeypatch)
    _patch_enrich(monkeypatch, folder="AI", title="First")
    msg = _fake_message(text="original text")
    update = _fake_update(msg)
    handlers = bot_module.make_handlers(state)
    on_message, on_folder_choice, on_edit = handlers[0], handlers[4], handlers[8]

    await on_message(update, SimpleNamespace(application=None))
    token = next(iter(state._pending))
    crypto_idx = state.config.categories.index("Crypto")
    cb = _fake_callback_update(f"f|{token}|{crypto_idx}")
    await on_folder_choice(cb, SimpleNamespace())
    first_path = state._last_capture[999]
    assert first_path.parent.name == "Crypto"
    assert first_path.exists()

    _patch_enrich(monkeypatch, folder="AI", title="Second", summary="rewritten")
    edit_update = _fake_update(_fake_message(text="/edit"))
    await on_edit(edit_update, SimpleNamespace(args=["new", "corrected", "text"]))

    new_path = state._last_capture[999]
    assert new_path != first_path
    assert not first_path.exists()
    # Same folder as the original capture
    assert new_path.parent.name == "Crypto"
    assert "rewritten" in new_path.read_text(encoding="utf-8")


# ---------- PDF capture ----------


async def test_pdf_capture_extracts_text_and_embeds_attachment(tmp_path: Path, monkeypatch):
    state = _make_state(tmp_path, monkeypatch)
    _patch_enrich(monkeypatch, folder="Reading", title="Paper Notes")

    fake_pdf = tmp_path / "_incoming.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr(
        bot_module,
        "_download_document",
        AsyncMock(return_value=(fake_pdf, "paper.pdf")),
    )
    monkeypatch.setattr(bot_module, "extract_pdf_text", lambda p: "Extracted body content")

    doc = SimpleNamespace(file_name="paper.pdf", mime_type="application/pdf")
    msg = _fake_message(text="", caption="my notes", document=doc)
    update = _fake_update(msg)
    handlers = bot_module.make_handlers(state)
    on_message, on_folder_choice = handlers[0], handlers[4]

    await on_message(update, SimpleNamespace(application=None))
    assert len(state._pending) == 1
    pending = next(iter(state._pending.values()))
    assert pending.pending_files and pending.pending_files[0].name == "_incoming.pdf"
    assert "Extracted body content" in pending.extra_text
    assert "my notes" in pending.extra_text

    token = next(iter(state._pending))
    reading_idx = state.config.categories.index("Reading")
    cb = _fake_callback_update(f"f|{token}|{reading_idx}")
    await on_folder_choice(cb, SimpleNamespace())

    written = list((tmp_path / "Reading").glob("*.md"))
    assert len(written) == 1
    content = written[0].read_text(encoding="utf-8")
    # PDF moved into attachments and embedded.
    assert (tmp_path / "Reading" / "attachments" / "_incoming.pdf").exists()
    assert "![[attachments/_incoming.pdf]]" in content
    assert not fake_pdf.exists()  # was moved


async def test_non_pdf_document_replies_unsupported(tmp_path: Path, monkeypatch):
    state = _make_state(tmp_path, monkeypatch)
    doc = SimpleNamespace(file_name="thing.zip", mime_type="application/zip")
    msg = _fake_message(text="", document=doc)
    update = _fake_update(msg)
    on_message = bot_module.make_handlers(state)[0]
    await on_message(update, SimpleNamespace(application=None))
    sent_calls = [c.args[0] for c in update.effective_chat.send_message.call_args_list]
    assert any("Unsupported" in s for s in sent_calls)
    assert state._pending == {}


async def test_markdown_capture_uses_file_text_as_source(tmp_path: Path, monkeypatch):
    state = _make_state(tmp_path, monkeypatch)
    _patch_enrich(monkeypatch, folder="Reading", title="MD Notes")

    fake_md = tmp_path / "_incoming.md"
    fake_md.write_text("# Heading\n\nbody from markdown file\n", encoding="utf-8")
    monkeypatch.setattr(
        bot_module,
        "_download_document",
        AsyncMock(return_value=(fake_md, "notes.md")),
    )

    doc = SimpleNamespace(file_name="notes.md", mime_type="text/markdown")
    msg = _fake_message(text="", caption="caption text", document=doc)
    update = _fake_update(msg)
    handlers = bot_module.make_handlers(state)
    on_message, on_folder_choice = handlers[0], handlers[4]

    await on_message(update, SimpleNamespace(application=None))
    assert len(state._pending) == 1
    pending = next(iter(state._pending.values()))
    # File contents flow into extra_text alongside any caption.
    assert "body from markdown file" in pending.extra_text
    assert "caption text" in pending.extra_text
    # The .md file itself is not kept as an attachment — body is already inline.
    assert pending.pending_files == []

    token = next(iter(state._pending))
    reading_idx = state.config.categories.index("Reading")
    cb = _fake_callback_update(f"f|{token}|{reading_idx}")
    await on_folder_choice(cb, SimpleNamespace())

    written = list((tmp_path / "Reading").glob("*.md"))
    assert len(written) == 1
    # Original temp file cleaned up; nothing dropped into attachments/.
    assert not fake_md.exists()
    assert not (tmp_path / "Reading" / "attachments").exists()


async def test_markdown_capture_by_extension_when_mime_missing(tmp_path: Path, monkeypatch):
    state = _make_state(tmp_path, monkeypatch)
    _patch_enrich(monkeypatch, folder="AI")

    fake_md = tmp_path / "_incoming2.md"
    fake_md.write_text("plain markdown without mime\n", encoding="utf-8")
    monkeypatch.setattr(
        bot_module,
        "_download_document",
        AsyncMock(return_value=(fake_md, "thing.md")),
    )

    # Telegram sometimes sends application/octet-stream for .md uploads.
    doc = SimpleNamespace(file_name="thing.md", mime_type="application/octet-stream")
    msg = _fake_message(text="", document=doc)
    update = _fake_update(msg)
    on_message = bot_module.make_handlers(state)[0]

    await on_message(update, SimpleNamespace(application=None))
    assert len(state._pending) == 1
    pending = next(iter(state._pending.values()))
    assert "plain markdown without mime" in pending.extra_text


async def test_plaintext_txt_uses_file_text_as_source(tmp_path: Path, monkeypatch):
    state = _make_state(tmp_path, monkeypatch)
    _patch_enrich(monkeypatch, folder="AI")

    fake_txt = tmp_path / "_incoming.txt"
    fake_txt.write_text("hello from a plain text file\n", encoding="utf-8")
    monkeypatch.setattr(
        bot_module,
        "_download_document",
        AsyncMock(return_value=(fake_txt, "note.txt")),
    )

    doc = SimpleNamespace(file_name="note.txt", mime_type="text/plain")
    msg = _fake_message(text="", document=doc)
    update = _fake_update(msg)
    on_message = bot_module.make_handlers(state)[0]

    await on_message(update, SimpleNamespace(application=None))
    pending = next(iter(state._pending.values()))
    assert "hello from a plain text file" in pending.extra_text
    assert pending.pending_files == []


async def test_text_star_mime_is_treated_as_text(tmp_path: Path, monkeypatch):
    """Any text/* MIME (e.g. text/csv, text/html) should be treated as readable text."""
    state = _make_state(tmp_path, monkeypatch)
    _patch_enrich(monkeypatch, folder="AI")

    fake_csv = tmp_path / "_incoming.csv"
    fake_csv.write_text("col1,col2\nfoo,bar\n", encoding="utf-8")
    monkeypatch.setattr(
        bot_module,
        "_download_document",
        AsyncMock(return_value=(fake_csv, "data.csv")),
    )

    doc = SimpleNamespace(file_name="data.csv", mime_type="text/csv")
    msg = _fake_message(text="", document=doc)
    update = _fake_update(msg)
    on_message = bot_module.make_handlers(state)[0]

    await on_message(update, SimpleNamespace(application=None))
    pending = next(iter(state._pending.values()))
    assert "foo,bar" in pending.extra_text


async def test_docx_capture_extracts_text_and_embeds_attachment(
    tmp_path: Path, monkeypatch
):
    state = _make_state(tmp_path, monkeypatch)
    _patch_enrich(monkeypatch, folder="Reading", title="Doc Notes")

    fake_docx = tmp_path / "_incoming.docx"
    fake_docx.write_bytes(b"PK\x03\x04 fake docx")
    monkeypatch.setattr(
        bot_module,
        "_download_document",
        AsyncMock(return_value=(fake_docx, "essay.docx")),
    )
    monkeypatch.setattr(
        bot_module, "extract_docx_text", lambda p: "extracted docx body"
    )

    doc = SimpleNamespace(
        file_name="essay.docx",
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    msg = _fake_message(text="", caption="my caption", document=doc)
    update = _fake_update(msg)
    handlers = bot_module.make_handlers(state)
    on_message, on_folder_choice = handlers[0], handlers[4]

    await on_message(update, SimpleNamespace(application=None))
    pending = next(iter(state._pending.values()))
    assert "extracted docx body" in pending.extra_text
    assert "my caption" in pending.extra_text
    assert pending.pending_files and pending.pending_files[0].name == "_incoming.docx"

    token = next(iter(state._pending))
    reading_idx = state.config.categories.index("Reading")
    cb = _fake_callback_update(f"f|{token}|{reading_idx}")
    await on_folder_choice(cb, SimpleNamespace())

    content = next((tmp_path / "Reading").glob("*.md")).read_text(encoding="utf-8")
    assert (tmp_path / "Reading" / "attachments" / "_incoming.docx").exists()
    assert "![[attachments/_incoming.docx]]" in content
    assert not fake_docx.exists()  # was moved


async def test_doc_capture_uses_textutil_and_embeds_attachment(
    tmp_path: Path, monkeypatch
):
    state = _make_state(tmp_path, monkeypatch)
    _patch_enrich(monkeypatch, folder="Reading", title="Legacy Doc")

    fake_doc = tmp_path / "_incoming.doc"
    fake_doc.write_bytes(b"\xd0\xcf\x11\xe0 fake legacy doc")
    monkeypatch.setattr(
        bot_module,
        "_download_document",
        AsyncMock(return_value=(fake_doc, "legacy.doc")),
    )
    monkeypatch.setattr(
        bot_module, "extract_doc_text", lambda p: "legacy doc body via textutil"
    )

    doc = SimpleNamespace(file_name="legacy.doc", mime_type="application/msword")
    msg = _fake_message(text="", document=doc)
    update = _fake_update(msg)
    handlers = bot_module.make_handlers(state)
    on_message, on_folder_choice = handlers[0], handlers[4]

    await on_message(update, SimpleNamespace(application=None))
    pending = next(iter(state._pending.values()))
    assert "legacy doc body via textutil" in pending.extra_text
    assert pending.pending_files and pending.pending_files[0].name == "_incoming.doc"

    token = next(iter(state._pending))
    reading_idx = state.config.categories.index("Reading")
    cb = _fake_callback_update(f"f|{token}|{reading_idx}")
    await on_folder_choice(cb, SimpleNamespace())

    assert (tmp_path / "Reading" / "attachments" / "_incoming.doc").exists()
    assert not fake_doc.exists()


# ---------- /search and /ask ----------


async def test_search_returns_hits(tmp_path: Path, monkeypatch):
    state = _make_state(tmp_path, monkeypatch)
    (tmp_path / "AI").mkdir()
    (tmp_path / "AI" / "Transformers Paper.md").write_text(
        "attention is all you need\n", encoding="utf-8"
    )
    on_search = bot_module.make_handlers(state)[5]
    update = _fake_update(_fake_message(text="/search transformers"))
    await on_search(update, SimpleNamespace(args=["transformers"]))
    text = update.effective_chat.send_message.call_args.args[0]
    assert "Transformers Paper" in text
    assert "obsidian://" in text


async def test_search_empty_query_shows_usage(tmp_path: Path, monkeypatch):
    state = _make_state(tmp_path, monkeypatch)
    on_search = bot_module.make_handlers(state)[5]
    update = _fake_update(_fake_message(text="/search"))
    await on_search(update, SimpleNamespace(args=[]))
    text = update.effective_chat.send_message.call_args.args[0]
    assert "usage" in text.lower()


async def test_ask_routes_to_answer_from_vault(tmp_path: Path, monkeypatch):
    state = _make_state(tmp_path, monkeypatch)

    from tg_obsidian_bot.linker import AskResult
    from tg_obsidian_bot.vault import SearchHit

    captured = {}

    def fake_answer(question, base_dir, client, **kw):
        captured["question"] = question
        captured["base_dir"] = base_dir
        return AskResult(
            answer="42 is the answer.",
            sources=[
                SearchHit(
                    path=tmp_path / "Other" / "Note.md",
                    title="Note",
                    snippet="...",
                    score=1,
                    category="Other",
                )
            ],
        )

    monkeypatch.setattr(bot_module, "answer_from_vault", fake_answer)
    on_ask = bot_module.make_handlers(state)[6]
    update = _fake_update(_fake_message(text="/ask life"))
    await on_ask(update, SimpleNamespace(args=["life", "the", "universe"]))

    assert captured["question"] == "life the universe"
    last = update.effective_chat.send_message.call_args.args[0]
    assert "42 is the answer." in last
    assert "[[Note]]" in last
