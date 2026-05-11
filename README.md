# tg-obsidian-bot

> **Forward anything to Telegram. Get a tagged, linked, deduplicated Obsidian note back.**

A single-tenant Telegram bot that turns your chat into a frictionless capture layer for an [Obsidian](https://obsidian.md/) vault. Drop in a tweet, voice memo, PDF, YouTube link, or a photo of a whiteboard — Claude classifies it, summarises it, tags it, finds related notes already in your vault, and writes a Markdown file with proper frontmatter and `[[backlinks]]`. Built as a personal second-brain pipeline; published in case it's useful to anyone else.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

---

## What it does

- **Capture anything** — text, URLs, photos, voice notes, PDFs, Word docs (`.docx`/`.doc`), plain-text/code files, forwarded posts, YouTube links. Media groups (multi-photo posts) are debounced and stitched into a single note.
- **Read the contents, not just the message** — Claude vision OCR for photos, OpenAI Whisper for voice, PyPDF/python-docx for documents, YouTube Transcript API for videos, plain HTTP fetcher for web pages.
- **AI routing** — Claude (Sonnet) picks a folder, writes a title, summarises the body, generates tags, and proposes up to 5 related notes from your existing vault. Falls back to an "Other" bucket and an inbox queue when confidence is low.
- **Smart dedupe** — incoming notes that match by URL, title, or semantic similarity (cosine on OpenAI embeddings) get *appended* to the existing note instead of creating a duplicate.
- **Vault-grounded Q&A** — `/ask` runs a hybrid keyword + embedding retrieval over your notes and answers with Claude, with multi-turn follow-ups via Telegram reply threads.
- **Manual override** — every capture shows an inline-keyboard folder picker; misroutes are one tap away. `/redo`, `/edit`, `/undo`, and `/relink` cover the rest.
- **Single-tenant by design** — an `ALLOWED_USER_IDS` allowlist gates every handler. Nobody else who finds your bot can use it.

## How it works

```
Telegram message
     │
     ├─ photo?       → Claude vision OCR
     ├─ voice/audio? → OpenAI Whisper
     ├─ PDF / DOCX / DOC / text? → text extraction
     └─ URLs?        → page fetch · YouTube transcript
     ↓
Claude enrichment: title · summary · tags · folder · related notes · confidence
     ↓
Dedupe check (URL → title → semantic) → append to existing OR create new
     ↓
<vault>/<Category>/<Title>.md   with YAML frontmatter + [[backlinks]] + attachments/
```

## Requirements

- Python **3.11+**
- [`uv`](https://docs.astral.sh/uv/) (or plain `pip` if you prefer)
- A Telegram bot token from [@BotFather](https://t.me/BotFather)
- An [Anthropic API key](https://console.anthropic.com/)
- *(optional)* An [OpenAI API key](https://platform.openai.com/) for voice transcription, semantic dedupe, semantic `/search`, and `/relink`
- An existing Obsidian vault (or any folder you want filled with `.md` files)

## Setup

```bash
git clone https://github.com/mishablank/tg-2-obsidian.git
cd tg-2-obsidian
uv sync
cp .env.example .env
# edit .env — see Configuration below
uv run python -m tg_obsidian_bot.bot
```

If you `uv pip install -e .` you'll also get a `tg-obsidian-bot` console entry point.

## Configuration

All config is via environment variables (loaded from `.env` if present). See [.env.example](.env.example).

| Variable | Required | Purpose |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | yes | Bot token from @BotFather |
| `ANTHROPIC_API_KEY` | yes | Used for enrichment, vision OCR, `/ask` |
| `ALLOWED_USER_IDS` | yes | Comma-separated Telegram numeric IDs. Only these users can talk to the bot. Find yours via [@userinfobot](https://t.me/userinfobot). |
| `BASE_DIR` | yes | Absolute path to your Obsidian vault root |
| `OPENAI_API_KEY` | no | Enables Whisper voice transcription, semantic dedupe, `/relink`, and semantic ranking inside `/search` and `/ask` |
| `CATEGORIES` | no | Comma-separated folder names. Default: `AI,Crypto,Startups/YC,Personal,Health,Reading,Other` |
| `LOG_FILE` | no | Defaults to `~/.tg-obsidian-bot.log` (rotated, 5 MB × 3 backups) |

## Commands

| Command | Effect |
|---|---|
| `/start` | Show usage hint with the current category list |
| `/search <query>` | Hybrid (keyword + embedding) search across titles, tags, and bodies |
| `/ask <question>` | RAG over your vault. Reply to my answer to continue the thread (up to 6 turns) |
| `/inbox` | List notes flagged for review (low-confidence routing) |
| `/review` | Walk pending notes one at a time with move / mark-reviewed / delete buttons |
| `/relink [folder]` | Refresh related-note backlinks. No arg = last capture; with arg = entire folder |
| `/redo` | Reply with `/redo` to regenerate a capture using the higher-quality Opus model |
| `/edit <text>` | Replace the source of the last capture and re-enrich |
| `/undo` | Delete the last capture in this chat |
| `/refresh` | Rescan the vault index (also runs automatically every 10 minutes) |

The plain message path: send a message → tap a folder button → done. Send a photo without a caption and the bot OCRs it first so it can route by content.

## What a note looks like

```markdown
---
title: "Notes on bitter-lesson scaling laws"
created: 2026-05-11T18:32:04
source: https://example.com/post
source_type: article
tags: [scaling-laws, rich-sutton, ai]
forwarded_from: "@somechannel"
forwarded_at: 2026-05-11T18:30:00
---

Sutton argues that the only methods that consistently win across decades
are those that scale with compute and data — search and learning — and that
hand-tuned domain knowledge tends to be a local optimum at best.

## Related
- [[The bitter lesson, revisited]]
- [[Compute overhang and capability surprises]]

![[attachments/2026-05-11_18-32-04-1.jpg]]
```

## Running it as a daemon

The bot is a long-lived process. Some lightweight options:

- **macOS (launchd):** drop a `~/Library/LaunchAgents/com.you.tg-obsidian-bot.plist` that runs `uv run python -m tg_obsidian_bot.bot` with `KeepAlive=true`.
- **Linux (systemd user unit):** a one-screen `~/.config/systemd/user/tg-obsidian-bot.service` with `ExecStart=…` and `Restart=on-failure`, then `systemctl --user enable --now tg-obsidian-bot`.
- **Quick and dirty:** `tmux new -d -s tg "uv run python -m tg_obsidian_bot.bot"`.

Logs go to `LOG_FILE` (default `~/.tg-obsidian-bot.log`).

## Development

```bash
uv sync
uv run pytest -v
```

15 test modules cover the bot handlers, vault indexing, embeddings, dedupe, link enrichment, vision/whisper/youtube/pdf adapters, and the inbox/review flow. `pytest-asyncio` is in `auto` mode.

## Security model

This bot is **single-tenant on purpose**. It does exactly one thing to keep you safe:

- Every handler checks `update.effective_user.id` against `ALLOWED_USER_IDS` before doing anything. Unauthorised users get a flat `"Unauthorized."` reply.

That's it. There is no per-user vault, no row-level auth, no rate limiting. Don't share your bot token. Don't add other users to `ALLOWED_USER_IDS` unless you want them writing into the same vault you do.

`.env` is gitignored. Treat your `TELEGRAM_BOT_TOKEN` and `ANTHROPIC_API_KEY` like passwords — if either leaks, rotate immediately (BotFather → `/revoke`, Anthropic console → revoke key).

## License

[MIT](LICENSE) © 2026 Mikhail Blank
