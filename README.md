# Engram

> **Forward anything to Telegram. Get a tagged, linked, deduplicated Obsidian note back.**

[![CI](https://github.com/mishablank/Engram/actions/workflows/ci.yml/badge.svg)](https://github.com/mishablank/Engram/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/engram-bot.svg)](https://pypi.org/project/engram-bot/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

An *engram* is the physical trace a memory leaves in the brain — the durable scar left behind after an experience. **Engram** is a single-tenant Telegram bot that does the same thing for your chat stream: drop in a tweet, voice memo, PDF, YouTube link, or photo of a whiteboard, and Claude classifies it, summarises it, tags it, finds related notes already in your [Obsidian](https://obsidian.md/) vault, and writes a Markdown file with proper frontmatter and `[[backlinks]]`. The forgettable river of messages becomes durable, indexed memory.

Built as a personal second-brain pipeline; published in case it's useful to anyone else.

[![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/new/template?template=https://github.com/mishablank/Engram)

---

## What it does

- **Capture anything** — text, URLs, photos, voice notes, PDFs, Word docs (`.docx`/`.doc`), plain-text/code files, forwarded posts, YouTube links. Media groups (multi-photo posts) are debounced and stitched into a single note.
- **Read the contents, not just the message** — Claude vision OCR for photos, OpenAI Whisper for voice, PyPDF/python-docx for documents, YouTube Transcript API for videos, plain HTTP fetcher for web pages.
- **AI routing** — Claude (Sonnet) picks a folder, writes a title, summarises the body, generates tags, and proposes up to 5 related notes from your existing vault. Falls back to an "Other" bucket and an inbox queue when confidence is low.
- **Merge-and-rewrite dedupe** — incoming notes that match by URL, title, or semantic similarity (cosine on OpenAI embeddings) are **merged into the canonical note**: Claude rewrites the page to integrate the new source, collapse redundancy, and reconcile contradictions inline (instead of stacking dated append blocks). The vault is git-snapshotted before every rewrite; if a rewrite would drop the frontmatter or an attachment it safely falls back to a plain append, so a capture is never lost.
- **Entity (wiki) pages** — every capture also grows typed backbone pages under `People/`, `Concepts/`, and `Projects/`. Each entity page accumulates one grounded observation per source note plus `[[backlinks]]`, turning the chronological capture stream into a navigable wiki.
- **Vault-grounded Q&A** — `/ask` runs a hybrid keyword + embedding retrieval over your notes and answers with Claude, with multi-turn follow-ups via Telegram reply threads.
- **Retroactive rebuild** — `/rebuild` git-snapshots the vault, merges existing duplicate notes, and rebuilds all entity pages from scratch. One command turns an existing note pile into the wiki.
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
Dedupe check (URL → title → semantic)
     ├─ match    → git snapshot → Claude merge-rewrites the canonical note
     └─ no match → create new note
     ↓
Entity pass: extract people/concepts/projects → grow typed wiki pages
     ↓
<vault>/<Category>/<Title>.md   with YAML frontmatter + [[backlinks]] + attachments/
<vault>/{People,Concepts,Projects}/<Entity>.md   accumulating observations + backlinks
```

## Requirements

- Python **3.11+**
- [`uv`](https://docs.astral.sh/uv/) (or plain `pip` if you prefer)
- A Telegram bot token from [@BotFather](https://t.me/BotFather)
- An [Anthropic API key](https://console.anthropic.com/)
- *(optional)* An [OpenAI API key](https://platform.openai.com/) for voice transcription, semantic dedupe, semantic `/search`, and `/relink`
- An existing Obsidian vault (or any folder you want filled with `.md` files)

## Setup

### Install from PyPI

```bash
pip install engram-bot   # or: uv pip install engram-bot
# create .env in your working dir (see Configuration below), then:
engram
```

The PyPI distribution name is `engram-bot` (because `engram` is squatted on PyPI); the Python import name and the console script are both `engram`.

### From source

```bash
git clone https://github.com/mishablank/Engram.git
cd Engram
uv sync
cp .env.example .env
# edit .env — see Configuration below
uv run python -m engram.bot
```

### One-click deploy (Railway)

Click the **Deploy on Railway** button above. Railway will build the project, prompt you for the env vars below, and run `uv run python -m engram.bot` as a long-lived process.

The catch: your Obsidian vault is *local*, but Railway runs in the cloud. Two ways to make this work:

1. **Recommended** — attach a Railway volume mounted at e.g. `/data`, set `BASE_DIR=/data`, and use [Obsidian Sync](https://obsidian.md/sync), Syncthing, or rclone to mirror that volume into your local Obsidian vault. The bot writes to the cloud copy; your desktop reads it via sync.
2. **Quick test** — point `BASE_DIR` at the container filesystem and treat it as ephemeral. Notes survive restarts but vanish if Railway redeploys without a volume. Fine for kicking the tyres, not for real use.

If you don't want any of that, just run it on your laptop or a home server. See "Running it as a daemon" below.

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
| `LOG_FILE` | no | Defaults to `~/.engram.log` (rotated, 5 MB × 3 backups) |

## Commands

| Command | Effect |
|---|---|
| `/start` | Show usage hint with the current category list |
| `/search <query>` | Hybrid (keyword + embedding) search across titles, tags, and bodies |
| `/ask <question>` | RAG over your vault. Reply to my answer to continue the thread (up to 6 turns) |
| `/inbox` | List notes flagged for review (low-confidence routing) |
| `/review` | Walk pending notes one at a time with move / mark-reviewed / delete buttons |
| `/relink [folder]` | Refresh related-note backlinks. No arg = last capture; with arg = entire folder |
| `/rebuild` | Git-snapshot the vault, merge existing duplicate notes, and rebuild all `People`/`Concepts`/`Projects` entity pages from scratch. Destructive but reversible (see below) |
| `/redo` | Reply with `/redo` to regenerate a capture using the higher-quality Opus model |
| `/edit <text>` | Replace the source of the last capture and re-enrich |
| `/undo` | Delete the last capture in this chat |
| `/refresh` | Rescan the vault index (also runs automatically every 10 minutes) |

### Rolling back a merge or rebuild

Every merge and every `/rebuild` commits the vault to a git repo (auto-initialised at `BASE_DIR` on first use) **before** writing. To undo the most recent rewrite:

```bash
git -C "$BASE_DIR" log --oneline      # find the engram: pre-* commit
git -C "$BASE_DIR" reset --hard HEAD~ # discard the last rewrite
```

> **iCloud note:** if your vault lives in an iCloud-synced folder, the `.git` directory is synced too. This works fine but can cause occasional sync churn; that is the documented trade-off for in-vault rollback.

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

- **macOS (launchd):** drop a `~/Library/LaunchAgents/com.you.engram.plist` that runs `uv run python -m engram.bot` with `KeepAlive=true`.
- **Linux (systemd user unit):** a one-screen `~/.config/systemd/user/engram.service` with `ExecStart=…` and `Restart=on-failure`, then `systemctl --user enable --now engram`.
- **Quick and dirty:** `tmux new -d -s engram "uv run python -m engram.bot"`.

Logs go to `LOG_FILE` (default `~/.engram.log`).

## Development

```bash
uv sync
uv run pytest -v
```

The test suite covers the bot handlers, vault indexing, embeddings, dedupe, link enrichment, the merge-and-rewrite path, entity extraction/pages, the retroactive `/rebuild` flow, git snapshotting, vision/whisper/youtube/pdf adapters, and the inbox/review flow. `pytest-asyncio` is in `auto` mode. CI runs on push and PR against Python 3.11 / 3.12 / 3.13.

## Roadmap

- **Local-model support** — swap Claude / OpenAI for Ollama or llama.cpp so the bot can run end-to-end without paid API keys. Embeddings first (cheapest win), then enrichment. Tracked in [#1](https://github.com/mishablank/Engram/issues/1) — help welcome.
- **Scheduled maintenance** — a nightly pass that re-synthesises entity leads, reconciles contradictions across notes, and DMs a digest of what changed in the vault overnight.

## Security model

This bot is **single-tenant on purpose**. It does exactly one thing to keep you safe:

- Every handler checks `update.effective_user.id` against `ALLOWED_USER_IDS` before doing anything. Unauthorised users get a flat `"Unauthorized."` reply.

That's it. There is no per-user vault, no row-level auth, no rate limiting. Don't share your bot token. Don't add other users to `ALLOWED_USER_IDS` unless you want them writing into the same vault you do.

`.env` is gitignored. Treat your `TELEGRAM_BOT_TOKEN` and `ANTHROPIC_API_KEY` like passwords — if either leaks, rotate immediately (BotFather → `/revoke`, Anthropic console → revoke key).

## License

[MIT](LICENSE) © 2026 Mikhail Blank
