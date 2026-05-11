from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from engram import bot as bot_module
from engram.config import DEFAULT_CATEGORIES, Config
from engram.linker import Enrichment
from engram.vault import VaultIndex


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


def _fake_message(text="", photo=None, caption=None, media_group_id=None):
    return SimpleNamespace(
        text=text,
        caption=caption,
        photo=photo or [],
        media_group_id=media_group_id,
        voice=None,
        audio=None,
        document=None,
        forward_origin=None,
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


async def test_text_capture_shows_folder_keyboard_and_writes_nothing(tmp_path, monkeypatch):
    state = _make_state(tmp_path, monkeypatch)
    _patch_enrich(monkeypatch)
    msg = _fake_message(text="https://example.com/x")
    update = _fake_update(msg)
    on_message, *_ = bot_module.make_handlers(state)

    await on_message(update, SimpleNamespace(application=None))

    assert len(state._pending) == 1
    update.effective_chat.send_message.assert_awaited_once()
    args, kwargs = update.effective_chat.send_message.call_args
    text = args[0] if args else kwargs.get("text", "")
    assert "folder" in text.lower()
    kb = kwargs["reply_markup"]
    rows = kb.inline_keyboard
    assert len(rows) == len(state.config.categories)
    labels = [btn.text for row in rows for btn in row]
    assert labels == list(state.config.categories)
    assert list(tmp_path.rglob("*.md")) == []


async def test_callback_writes_note_to_chosen_folder(tmp_path, monkeypatch):
    state = _make_state(tmp_path, monkeypatch)
    _patch_enrich(monkeypatch, folder="AI")  # auto-routed folder differs from user pick
    msg = _fake_message(text="https://example.com/x")
    update = _fake_update(msg)
    handlers = bot_module.make_handlers(state)
    on_message, on_folder_choice = handlers[0], handlers[4]
    await on_message(update, SimpleNamespace(application=None))

    token = next(iter(state._pending))
    crypto_idx = state.config.categories.index("Crypto")
    cb_update = _fake_callback_update(f"f|{token}|{crypto_idx}")

    await on_folder_choice(cb_update, SimpleNamespace())

    written = list(tmp_path.rglob("*.md"))
    assert len(written) == 1
    assert written[0].parent.name == "Crypto"
    assert token not in state._pending
    cb_update.callback_query.edit_message_text.assert_awaited_once()
    edit_args = cb_update.callback_query.edit_message_text.call_args
    edit_text = edit_args.args[0] if edit_args.args else edit_args.kwargs.get("text", "")
    assert "Crypto" in edit_text


async def test_callback_preserves_llm_enrichment(tmp_path, monkeypatch):
    state = _make_state(tmp_path, monkeypatch)
    _patch_enrich(
        monkeypatch,
        title="Real Title",
        summary="real summary body",
        tags=["a", "b"],
        folder="AI",
    )
    captured: dict = {}
    real_write = bot_module.write_note

    def spy(msg, vault_dir, *, related, tags):
        captured["msg"] = msg
        captured["tags"] = tags
        captured["related"] = related
        captured["vault_dir"] = vault_dir
        return real_write(msg, vault_dir, related=related, tags=tags)

    monkeypatch.setattr(bot_module, "write_note", spy)

    msg = _fake_message(text="https://example.com/x")
    update = _fake_update(msg)
    handlers = bot_module.make_handlers(state)
    on_message, on_folder_choice = handlers[0], handlers[4]
    await on_message(update, SimpleNamespace(application=None))

    token = next(iter(state._pending))
    idx = state.config.categories.index("Personal")
    cb_update = _fake_callback_update(f"f|{token}|{idx}")
    await on_folder_choice(cb_update, SimpleNamespace())

    assert captured["tags"] == ["a", "b"]
    assert captured["msg"].title == "Real Title"
    assert "real summary body" in captured["msg"].text
    assert captured["vault_dir"].name == "Personal"


async def test_album_shows_single_keyboard(tmp_path, monkeypatch):
    state = _make_state(tmp_path, monkeypatch)
    monkeypatch.setattr(bot_module, "MEDIA_GROUP_DEBOUNCE", 0.0)
    _patch_enrich(monkeypatch)

    bot_send = AsyncMock()
    app = SimpleNamespace(bot=SimpleNamespace(send_message=bot_send))
    state._media_groups["g1"] = bot_module._GroupBuffer(
        messages=[_fake_message(text="a"), _fake_message(text="b")]
    )

    await bot_module._flush_group(state, "g1", chat_id=999, app=app)

    assert len(state._pending) == 1
    pending = next(iter(state._pending.values()))
    assert len(pending.messages) == 2
    bot_send.assert_awaited_once()
    _, kwargs = bot_send.call_args
    assert "reply_markup" in kwargs


async def test_voice_shows_keyboard_after_transcription(tmp_path, monkeypatch):
    state = _make_state(tmp_path, monkeypatch)
    _patch_enrich(monkeypatch)
    fake_audio = tmp_path / "x.ogg"
    fake_audio.write_bytes(b"")
    monkeypatch.setattr(bot_module, "_download_voice", AsyncMock(return_value=fake_audio))
    monkeypatch.setattr(bot_module, "transcribe", lambda p, k: "hello world")

    msg = _fake_message()
    msg.voice = SimpleNamespace()
    update = _fake_update(msg)

    await bot_module._handle_voice(state, update, msg)

    assert len(state._pending) == 1
    pending = next(iter(state._pending.values()))
    assert pending.extra_text == "hello world"
    # send_message called twice: "Transcribing voice…" then "Choose a folder:"
    assert update.effective_chat.send_message.await_count == 2
    last_kwargs = update.effective_chat.send_message.call_args.kwargs
    assert "reply_markup" in last_kwargs


async def test_expired_token_returns_friendly_error(tmp_path, monkeypatch):
    state = _make_state(tmp_path, monkeypatch)
    _patch_enrich(monkeypatch)
    write_spy = MagicMock()
    monkeypatch.setattr(bot_module, "write_note", write_spy)

    cb_update = _fake_callback_update("f|nonexistent|0")
    on_folder_choice = bot_module.make_handlers(state)[4]

    await on_folder_choice(cb_update, SimpleNamespace())

    cb_update.callback_query.answer.assert_awaited_once()
    call = cb_update.callback_query.answer.call_args
    msg = call.args[0] if call.args else call.kwargs.get("text", "")
    assert "expired" in msg.lower()
    write_spy.assert_not_called()


async def test_low_confidence_stamps_review_pending(tmp_path, monkeypatch):
    state = _make_state(tmp_path, monkeypatch)
    _patch_enrich(monkeypatch, folder="AI", title="X", summary="thin", )
    # Override confidence on the enrichment patcher
    from engram.linker import Enrichment
    monkeypatch.setattr(
        bot_module,
        "enrich_note",
        lambda *a, **k: Enrichment(
            title="X", summary="thin", related=[], tags=[],
            folder="AI", source_type="other", confidence="low",
        ),
    )

    msg = _fake_message(text="interesting")
    update = _fake_update(msg)
    handlers = bot_module.make_handlers(state)
    on_message, on_folder_choice = handlers[0], handlers[4]
    await on_message(update, SimpleNamespace(application=None))

    token = next(iter(state._pending))
    ai_idx = state.config.categories.index("AI")
    cb_update = _fake_callback_update(f"f|{token}|{ai_idx}")
    await on_folder_choice(cb_update, SimpleNamespace())

    written = list(tmp_path.rglob("*.md"))
    assert len(written) == 1
    body = written[0].read_text(encoding="utf-8")
    assert "review: pending" in body


async def test_inbox_command_lists_pending(tmp_path, monkeypatch):
    state = _make_state(tmp_path, monkeypatch)
    (tmp_path / "AI").mkdir()
    (tmp_path / "AI" / "alpha.md").write_text(
        "---\nreview: pending\n---\n\nA\n", encoding="utf-8"
    )
    update = _fake_update(_fake_message(text="/inbox"))

    on_inbox = bot_module.make_handlers(state)[9]
    await on_inbox(update, SimpleNamespace(args=[]))

    update.effective_chat.send_message.assert_awaited_once()
    text = update.effective_chat.send_message.call_args.args[0]
    assert "pending review" in text
    assert "alpha" in text


async def test_inbox_command_empty(tmp_path, monkeypatch):
    state = _make_state(tmp_path, monkeypatch)
    update = _fake_update(_fake_message(text="/inbox"))
    on_inbox = bot_module.make_handlers(state)[9]
    await on_inbox(update, SimpleNamespace(args=[]))
    text = update.effective_chat.send_message.call_args.args[0]
    assert "empty" in text.lower()


async def test_review_shows_card_with_keyboard(tmp_path, monkeypatch):
    state = _make_state(tmp_path, monkeypatch)
    (tmp_path / "AI").mkdir()
    note = tmp_path / "AI" / "alpha.md"
    note.write_text("---\nreview: pending\n---\n\nbody line\n", encoding="utf-8")

    update = _fake_update(_fake_message(text="/review"))
    on_review = bot_module.make_handlers(state)[10]
    await on_review(update, SimpleNamespace(args=[]))

    update.effective_chat.send_message.assert_awaited_once()
    kwargs = update.effective_chat.send_message.call_args.kwargs
    assert "reply_markup" in kwargs
    kb = kwargs["reply_markup"].inline_keyboard
    # One token should be stored.
    assert len(state._review_items) == 1
    token = next(iter(state._review_items))
    flat = [btn.callback_data for row in kb for btn in row]
    assert any(f"r|{token}|mv|" in cd for cd in flat)
    assert any(cd == f"r|{token}|mark" for cd in flat)
    assert any(cd == f"r|{token}|del" for cd in flat)


async def test_review_mark_clears_pending_and_advances(tmp_path, monkeypatch):
    state = _make_state(tmp_path, monkeypatch)
    (tmp_path / "AI").mkdir()
    a = tmp_path / "AI" / "a.md"
    b = tmp_path / "AI" / "b.md"
    a.write_text("---\nreview: pending\n---\n\nA\n", encoding="utf-8")
    b.write_text("---\nreview: pending\n---\n\nB\n", encoding="utf-8")

    on_review = bot_module.make_handlers(state)[10]
    on_review_choice = bot_module.make_handlers(state)[11]

    update = _fake_update(_fake_message(text="/review"))
    await on_review(update, SimpleNamespace(args=[]))
    token = next(iter(state._review_items))

    cb_update = _fake_callback_update(f"r|{token}|mark")
    cb_update = SimpleNamespace(
        effective_user=cb_update.effective_user,
        effective_chat=SimpleNamespace(id=999, send_message=AsyncMock()),
        effective_message=None,
        callback_query=cb_update.callback_query,
    )
    await on_review_choice(cb_update, SimpleNamespace())

    # 'review: pending' was cleared from a.md
    assert "review: pending" not in a.read_text(encoding="utf-8")
    # And a new review card was shown for the next item (b).
    cb_update.effective_chat.send_message.assert_awaited()
    # New token should exist for b.
    assert any(it.path == b for it in state._review_items.values())


async def test_review_move_relocates_note(tmp_path, monkeypatch):
    state = _make_state(tmp_path, monkeypatch)
    (tmp_path / "Other").mkdir()
    note = tmp_path / "Other" / "n.md"
    note.write_text("---\nreview: pending\n---\n\nbody\n", encoding="utf-8")

    on_review = bot_module.make_handlers(state)[10]
    on_review_choice = bot_module.make_handlers(state)[11]

    update = _fake_update(_fake_message(text="/review"))
    await on_review(update, SimpleNamespace(args=[]))
    token = next(iter(state._review_items))

    ai_idx = state.config.categories.index("AI")
    cb_update = _fake_callback_update(f"r|{token}|mv|{ai_idx}")
    cb_update = SimpleNamespace(
        effective_user=cb_update.effective_user,
        effective_chat=SimpleNamespace(id=999, send_message=AsyncMock()),
        effective_message=None,
        callback_query=cb_update.callback_query,
    )
    await on_review_choice(cb_update, SimpleNamespace())

    moved = tmp_path / "AI" / "n.md"
    assert moved.exists()
    assert not note.exists()
    assert "review: pending" not in moved.read_text(encoding="utf-8")


async def test_relink_command_disabled_when_no_semantic_index(tmp_path, monkeypatch):
    state = _make_state(tmp_path, monkeypatch)
    state._semantic_index.embedder = None  # force disabled
    update = _fake_update(_fake_message(text="/relink"))
    on_relink = bot_module.make_handlers(state)[12]
    await on_relink(update, SimpleNamespace(args=[]))
    text = update.effective_chat.send_message.call_args.args[0]
    assert "disabled" in text.lower()


async def test_relink_command_with_folder_runs_over_each_note(tmp_path, monkeypatch):
    state = _make_state(tmp_path, monkeypatch)
    ai = tmp_path / "AI"
    ai.mkdir()
    a = ai / "a.md"
    b = ai / "b.md"
    a.write_text("a body\n", encoding="utf-8")
    b.write_text("b body\n", encoding="utf-8")

    seen: list[Path] = []

    def fake_relink(path, idx, **kw):
        seen.append(path)
        return True, []

    monkeypatch.setattr(bot_module, "relink_note", fake_relink)
    monkeypatch.setattr(state._semantic_index, "refresh", lambda: None)
    # Force enabled regardless of embedder None.
    state._semantic_index.embedder = SimpleNamespace(dim=4, embed=lambda x: [[0]*4 for _ in x])

    update = _fake_update(_fake_message(text="/relink AI"))
    on_relink = bot_module.make_handlers(state)[12]
    await on_relink(update, SimpleNamespace(args=["AI"]))

    assert set(seen) == {a, b}
    # Final message reports counts.
    last_text = update.effective_chat.send_message.call_args.args[0]
    assert "2/2" in last_text or "2/2 note" in last_text


async def test_semantic_duplicate_appends_even_without_url_match(tmp_path, monkeypatch):
    state = _make_state(tmp_path, monkeypatch)
    _patch_enrich(monkeypatch, folder="AI", title="Different Headline", summary="body")

    ai_dir = tmp_path / "AI"
    ai_dir.mkdir()
    existing = ai_dir / "Sora 2 launch recap.md"
    existing.write_text(
        "---\nurls: []\n---\n\nbody about sora 2 launch\n",
        encoding="utf-8",
    )

    # No URL or title match in the vault index; only semantic dedupe should fire.
    state._vault_index = VaultIndex()

    monkeypatch.setattr(
        bot_module,
        "find_semantic_duplicate",
        lambda idx, client, title, summary, **k: existing,
    )

    msg = _fake_message(text="OpenAI just shipped Sora 2 — looks insane")
    update = _fake_update(msg)
    handlers = bot_module.make_handlers(state)
    on_message, on_folder_choice = handlers[0], handlers[4]
    await on_message(update, SimpleNamespace(application=None))

    token = next(iter(state._pending))
    ai_idx = state.config.categories.index("AI")
    cb_update = _fake_callback_update(f"f|{token}|{ai_idx}")
    await on_folder_choice(cb_update, SimpleNamespace())

    text = existing.read_text(encoding="utf-8")
    assert "## Update" in text
    # No second note was created.
    assert list(ai_dir.glob("*.md")) == [existing]


async def test_ask_stores_thread_keyed_by_bot_message_id(tmp_path, monkeypatch):
    state = _make_state(tmp_path, monkeypatch)
    sent = SimpleNamespace(message_id=777)
    update = _fake_update(_fake_message(text="/ask whatever"))
    update.effective_chat.send_message = AsyncMock(return_value=sent)

    from engram.linker import AskResult
    monkeypatch.setattr(
        bot_module,
        "answer_from_vault",
        lambda *a, **k: AskResult(answer="apples are red", sources=[]),
    )

    on_ask = bot_module.make_handlers(state)[6]
    context = SimpleNamespace(args=["why", "apples"])
    await on_ask(update, context)

    assert (999, 777) in state._ask_threads
    thread = state._ask_threads[(999, 777)]
    assert thread.turns == [("why apples", "apples are red")]


async def test_reply_to_ask_answer_continues_thread(tmp_path, monkeypatch):
    state = _make_state(tmp_path, monkeypatch)
    # Pre-seed an existing thread keyed by the bot's prior answer message id.
    state._ask_threads[(999, 555)] = bot_module._AskThread(
        turns=[("when did sora 2 launch", "October 2025 [[Sora 2 Launch]]")],
        created_at=time.time(),
    )

    captured: dict = {}

    def fake_answer(question, base_dir, client, *, top_k=8, prior_turns=None, semantic_index=None):
        from engram.linker import AskResult
        captured["question"] = question
        captured["prior_turns"] = prior_turns
        return AskResult(answer="October 8 specifically", sources=[])

    monkeypatch.setattr(bot_module, "answer_from_vault", fake_answer)

    sent = SimpleNamespace(message_id=556)
    msg = _fake_message(text="what day in october")
    msg.reply_to_message = SimpleNamespace(message_id=555)
    update = _fake_update(msg)
    update.effective_chat.send_message = AsyncMock(return_value=sent)

    on_message = bot_module.make_handlers(state)[0]
    await on_message(update, SimpleNamespace(application=None))

    assert captured["question"] == "what day in october"
    assert captured["prior_turns"] == [
        ("when did sora 2 launch", "October 2025 [[Sora 2 Launch]]"),
    ]
    # New bot message stored with chained history.
    assert (999, 556) in state._ask_threads
    new_turns = state._ask_threads[(999, 556)].turns
    assert new_turns[-1] == ("what day in october", "October 8 specifically")
    assert len(new_turns) == 2
    # No pending capture should have been created.
    assert state._pending == {}


async def test_reply_to_unrelated_message_is_normal_capture(tmp_path, monkeypatch):
    state = _make_state(tmp_path, monkeypatch)
    _patch_enrich(monkeypatch)
    # Reply target is NOT in _ask_threads → treat as a regular text capture.
    msg = _fake_message(text="some thought")
    msg.reply_to_message = SimpleNamespace(message_id=12345)
    update = _fake_update(msg)

    on_message = bot_module.make_handlers(state)[0]
    await on_message(update, SimpleNamespace(application=None))

    assert len(state._pending) == 1


async def test_ask_thread_caps_at_max_turns(tmp_path, monkeypatch):
    state = _make_state(tmp_path, monkeypatch)
    monkeypatch.setattr(bot_module, "ASK_THREAD_MAX_TURNS", 3)

    # Pre-seed a thread already at the cap.
    state._ask_threads[(999, 100)] = bot_module._AskThread(
        turns=[("q1", "a1"), ("q2", "a2"), ("q3", "a3")],
        created_at=time.time(),
    )

    from engram.linker import AskResult
    monkeypatch.setattr(
        bot_module,
        "answer_from_vault",
        lambda *a, **k: AskResult(answer="a4", sources=[]),
    )

    sent = SimpleNamespace(message_id=101)
    msg = _fake_message(text="q4")
    msg.reply_to_message = SimpleNamespace(message_id=100)
    update = _fake_update(msg)
    update.effective_chat.send_message = AsyncMock(return_value=sent)

    on_message = bot_module.make_handlers(state)[0]
    await on_message(update, SimpleNamespace(application=None))

    new_turns = state._ask_threads[(999, 101)].turns
    assert len(new_turns) == 3
    assert new_turns == [("q2", "a2"), ("q3", "a3"), ("q4", "a4")]


async def test_duplicate_url_appends_regardless_of_choice(tmp_path, monkeypatch):
    state = _make_state(tmp_path, monkeypatch)
    _patch_enrich(monkeypatch, folder="AI")

    ai_dir = tmp_path / "AI"
    ai_dir.mkdir()
    existing = ai_dir / "old.md"
    existing.write_text(
        "---\nurls:\n  - https://example.com/x\n---\n\nold body\n",
        encoding="utf-8",
    )
    state._vault_index = VaultIndex(
        titles=["old"],
        tags=[],
        url_to_path={"https://example.com/x": existing},
        norm_title_to_path={"old": existing},
    )
    state._vault_loaded_at = time.time()

    msg = _fake_message(text="https://example.com/x extra info")
    update = _fake_update(msg)
    handlers = bot_module.make_handlers(state)
    on_message, on_folder_choice = handlers[0], handlers[4]
    await on_message(update, SimpleNamespace(application=None))

    token = next(iter(state._pending))
    crypto_idx = state.config.categories.index("Crypto")
    cb_update = _fake_callback_update(f"f|{token}|{crypto_idx}")
    await on_folder_choice(cb_update, SimpleNamespace())

    assert not (tmp_path / "Crypto").exists()
    text = existing.read_text(encoding="utf-8")
    assert "## Update" in text
