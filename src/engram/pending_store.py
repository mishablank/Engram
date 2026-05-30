"""On-disk persistence for in-flight folder-picker captures.

The bot keeps each capture awaiting a folder choice in ``BotState._pending``.
That dict lives in memory only, so any process restart (or crash) leaves every
outstanding inline-keyboard button pointing at a missing token — the user taps
it and sees "Expired — please resend." This module mirrors the dict to a
JSON file so restarts don't kill in-flight captures.

The schema is intentionally tiny: a version int and a token->entry map. Telegram
``Message`` objects round-trip via ``Message.to_dict()`` / ``Message.de_json()``;
``forward_info.date`` (a ``datetime``) is ISO-stringified. Temp files referenced
in ``pending_files`` are caller-managed — this module only records paths.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from telegram import Message

if TYPE_CHECKING:
    from telegram import Bot

log = logging.getLogger("engram.pending_store")

SCHEMA_VERSION = 1


def _serialize_forward_info(info: dict | None) -> dict | None:
    if info is None:
        return None
    out: dict[str, Any] = dict(info)
    date = out.get("date")
    if isinstance(date, datetime):
        out["date"] = date.isoformat()
    return out


def _deserialize_forward_info(info: dict | None) -> dict | None:
    if info is None:
        return None
    out: dict[str, Any] = dict(info)
    date = out.get("date")
    if isinstance(date, str):
        try:
            out["date"] = datetime.fromisoformat(date)
        except ValueError:
            out["date"] = None
    return out


def serialize(pending: dict[str, Any]) -> dict[str, Any]:
    items: dict[str, Any] = {}
    for token, entry in pending.items():
        items[token] = {
            "messages": [m.to_dict() for m in entry.messages],
            "extra_text": entry.extra_text,
            "created_at": entry.created_at,
            "pending_files": [str(p) for p in entry.pending_files],
            "forward_info": _serialize_forward_info(entry.forward_info),
        }
    return {"version": SCHEMA_VERSION, "items": items}


def write(path: Path, pending: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(serialize(pending), ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    tmp.replace(path)


def load(
    path: Path,
    bot: "Bot",
    pending_cls: Callable[..., Any],
) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        log.exception("Failed to read pending store at %s; ignoring", path)
        return {}
    if raw.get("version") != SCHEMA_VERSION:
        log.warning(
            "Pending store at %s has version %r (expected %d); ignoring",
            path, raw.get("version"), SCHEMA_VERSION,
        )
        return {}
    items = raw.get("items") or {}
    out: dict[str, Any] = {}
    for token, data in items.items():
        try:
            messages = [Message.de_json(m, bot) for m in data.get("messages", [])]
        except Exception:
            log.exception("Could not rehydrate messages for token %s; dropping", token)
            continue
        pending_files = [Path(p) for p in data.get("pending_files", [])]
        missing = [p for p in pending_files if not p.exists()]
        if missing:
            log.warning(
                "Dropping pending capture %s: missing files %s",
                token, [str(p) for p in missing],
            )
            continue
        out[token] = pending_cls(
            messages=messages,
            extra_text=data.get("extra_text", ""),
            created_at=float(data.get("created_at") or 0.0),
            pending_files=pending_files,
            forward_info=_deserialize_forward_info(data.get("forward_info")),
        )
    return out
