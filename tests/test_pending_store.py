from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

from telegram import Chat, Message

from engram import bot as bot_module
from engram import pending_store
from engram.bot import _PendingCapture
from engram.config import DEFAULT_CATEGORIES, Config
from engram.vault import VaultIndex


def _stub_bot() -> MagicMock:
    """A bot stub whose ``defaults`` is None — required for Message.de_json."""
    bot = MagicMock()
    bot.defaults = None
    return bot


def _real_message(text: str, message_id: int = 1, chat_id: int = 999) -> Message:
    chat = Chat(id=chat_id, type=Chat.PRIVATE)
    return Message(
        message_id=message_id,
        date=datetime(2026, 5, 30, 18, 0, tzinfo=timezone.utc),
        chat=chat,
        text=text,
    )


def _make_state(tmp_path: Path, monkeypatch, *, state_dir: Path | None = None) -> bot_module.BotState:
    monkeypatch.setattr(bot_module, "Anthropic", lambda api_key=None: MagicMock())
    cfg = Config(
        telegram_token="t",
        anthropic_api_key="k",
        openai_api_key=None,
        allowed_user_ids={42},
        base_dir=tmp_path,
        categories=DEFAULT_CATEGORIES,
    )
    state = bot_module.BotState(cfg, state_dir=state_dir)
    state._vault_index = VaultIndex()
    state._vault_loaded_at = time.time()
    return state


def test_round_trip_preserves_capture(tmp_path):
    msg = _real_message("hello world")
    pending = {
        "abc123": _PendingCapture(
            messages=[msg],
            extra_text="caption",
            created_at=1700000000.0,
            pending_files=[],
            forward_info={
                "from": "@somebody",
                "date": datetime(2026, 5, 30, 12, 0, tzinfo=timezone.utc),
                "message_id": 7,
            },
        )
    }

    path = tmp_path / "pending.json"
    pending_store.write(path, pending)

    restored = pending_store.load(path, _stub_bot(), _PendingCapture)

    assert set(restored) == {"abc123"}
    entry = restored["abc123"]
    assert entry.extra_text == "caption"
    assert entry.created_at == 1700000000.0
    assert entry.forward_info["from"] == "@somebody"
    assert entry.forward_info["message_id"] == 7
    assert isinstance(entry.forward_info["date"], datetime)
    assert len(entry.messages) == 1
    assert entry.messages[0].text == "hello world"
    assert entry.messages[0].message_id == 1


def test_load_skips_entries_with_missing_files(tmp_path):
    msg = _real_message("doc capture")
    missing = tmp_path / "gone.pdf"
    pending = {
        "tok": _PendingCapture(
            messages=[msg],
            extra_text="",
            created_at=time.time(),
            pending_files=[missing],
            forward_info=None,
        )
    }
    path = tmp_path / "pending.json"
    pending_store.write(path, pending)

    restored = pending_store.load(path, _stub_bot(), _PendingCapture)
    assert restored == {}


def test_load_missing_file_returns_empty(tmp_path):
    assert pending_store.load(tmp_path / "nope.json", MagicMock(), _PendingCapture) == {}


def test_load_wrong_version_returns_empty(tmp_path):
    path = tmp_path / "pending.json"
    path.write_text('{"version": 999, "items": {}}', encoding="utf-8")
    assert pending_store.load(path, _stub_bot(), _PendingCapture) == {}


def test_load_malformed_json_returns_empty(tmp_path):
    path = tmp_path / "pending.json"
    path.write_text("not json {", encoding="utf-8")
    assert pending_store.load(path, _stub_bot(), _PendingCapture) == {}


def test_state_persist_writes_file(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    state = _make_state(tmp_path / "vault", monkeypatch, state_dir=state_dir)
    state._pending["t1"] = _PendingCapture(
        messages=[_real_message("hi", message_id=2)],
        extra_text="",
        created_at=time.time(),
        pending_files=[],
        forward_info=None,
    )
    state.persist_pending()

    assert (state_dir / "pending.json").exists()
    restored = pending_store.load(state_dir / "pending.json", _stub_bot(), _PendingCapture)
    assert set(restored) == {"t1"}


def test_state_persist_noop_without_state_dir(tmp_path, monkeypatch):
    state = _make_state(tmp_path, monkeypatch, state_dir=None)
    state._pending["t1"] = _PendingCapture(
        messages=[_real_message("hi", message_id=3)],
        extra_text="",
        created_at=time.time(),
        pending_files=[],
        forward_info=None,
    )
    state.persist_pending()  # must not raise
    assert state._pending_path is None


def test_stash_pending_files_moves_into_state_dir(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    state = _make_state(tmp_path / "vault", monkeypatch, state_dir=state_dir)
    src = tmp_path / "scratch.pdf"
    src.write_bytes(b"hello pdf")

    stashed = state.stash_pending_files("tokX", [src])

    assert len(stashed) == 1
    assert stashed[0].exists()
    assert stashed[0].parent == state_dir / "pending_files" / "tokX"
    assert not src.exists()
    state._drop_pending_files("tokX")
    assert not (state_dir / "pending_files" / "tokX").exists()


def test_cleanup_pending_persists_and_clears_files(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    state = _make_state(tmp_path / "vault", monkeypatch, state_dir=state_dir)
    # Stash a file under a stale token, then mark it ancient.
    src = tmp_path / "stale.pdf"
    src.write_bytes(b"x")
    stashed = state.stash_pending_files("oldtok", [src])
    state._pending["oldtok"] = _PendingCapture(
        messages=[_real_message("old", message_id=4)],
        extra_text="",
        created_at=time.time() - bot_module.PENDING_TTL_SECONDS - 10,
        pending_files=stashed,
        forward_info=None,
    )
    state.persist_pending()
    assert (state_dir / "pending.json").exists()

    state._cleanup_pending()

    assert "oldtok" not in state._pending
    assert not (state_dir / "pending_files" / "oldtok").exists()
    restored = pending_store.load(state_dir / "pending.json", _stub_bot(), _PendingCapture)
    assert restored == {}
