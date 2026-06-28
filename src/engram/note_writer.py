from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from anthropic import Anthropic

from .merger import merge_note
from .vault import FRONTMATTER_RE

log = logging.getLogger(__name__)

URL_RE = re.compile(r"https?://\S+")
SLUG_BAD_CHARS = re.compile(r'[\\/:*?"<>|#\[\]]')
WHITESPACE = re.compile(r"\s+")
EMBED_RE = re.compile(r"!\[\[[^\]]+\]\]")
RELATED_BLOCK_RE = re.compile(r"\n---\n\*Related: .*?\*[ \t]*\n", re.DOTALL)


@dataclass
class CapturedMessage:
    text: str = ""
    url_title: str | None = None
    title: str | None = None  # explicit title (e.g., from LLM enrichment)
    source_urls: list[str] = field(default_factory=list)
    images: list[str] = field(default_factory=list)  # vault-relative paths
    attachments: list[str] = field(default_factory=list)  # non-image embeds, e.g. PDFs
    source_type: str = "other"
    created: datetime = field(default_factory=datetime.now)
    forwarded_from: str | None = None
    forwarded_at: datetime | None = None
    original_message_id: int | None = None
    review_pending: bool = False


def extract_urls(text: str) -> list[str]:
    return URL_RE.findall(text or "")


def slugify(text: str, max_words: int = 6) -> str:
    text = SLUG_BAD_CHARS.sub(" ", text)
    text = WHITESPACE.sub(" ", text).strip()
    if not text:
        return "note"
    words = text.split()[:max_words]
    return " ".join(words)


def derive_title(msg: CapturedMessage) -> str:
    if msg.title:
        return slugify(msg.title, max_words=12)
    if msg.url_title:
        return slugify(msg.url_title, max_words=12)
    if msg.text.strip():
        first_line = msg.text.strip().splitlines()[0]
        # Avoid using a bare URL as title
        if URL_RE.match(first_line.strip()):
            return f"Note {msg.created.strftime('%Y-%m-%d %H-%M')}"
        return slugify(first_line)
    if msg.images:
        return f"Image {msg.created.strftime('%H-%M-%S')}"
    return "note"


def build_filename(msg: CapturedMessage, vault_dir: Path) -> Path:
    title = derive_title(msg)
    base = f"{msg.created.strftime('%Y-%m-%d %H-%M')} {title}"
    candidate = vault_dir / f"{base}.md"
    n = 2
    while candidate.exists():
        candidate = vault_dir / f"{base} ({n}).md"
        n += 1
    return candidate


def build_content(
    msg: CapturedMessage,
    related: list[str],
    tags: list[str],
) -> str:
    lines: list[str] = []
    lines.append("---")
    lines.append(f"created: {msg.created.isoformat(timespec='seconds')}")
    lines.append("source: telegram")
    lines.append(f"source-type: {msg.source_type}")
    if msg.source_urls:
        lines.append("urls:")
        for url in msg.source_urls:
            lines.append(f"  - {url}")
    if msg.forwarded_from:
        lines.append(f"forwarded-from: {msg.forwarded_from}")
    if msg.forwarded_at is not None:
        lines.append(f"forwarded-at: {msg.forwarded_at.isoformat(timespec='seconds')}")
    if msg.original_message_id is not None:
        lines.append(f"original-message-id: {msg.original_message_id}")
    if msg.review_pending:
        lines.append("review: pending")
    lines.append("---")
    lines.append("")
    lines.append(f"# {derive_title(msg)}")
    lines.append("")

    for url in msg.source_urls:
        lines.append(f"> Source: {url}")
    if msg.source_urls:
        lines.append("")

    for img in msg.images:
        lines.append(f"![[{img}]]")
    if msg.images:
        lines.append("")

    for att in msg.attachments:
        lines.append(f"![[{att}]]")
    if msg.attachments:
        lines.append("")

    if msg.text.strip():
        lines.append(msg.text.strip())
        lines.append("")

    if related:
        related_str = " · ".join(f"[[{r}]]" for r in related)
        lines.append("---")
        lines.append(f"*Related: {related_str}*")
        lines.append("")

    if tags:
        lines.append(" ".join(f"#{t}" for t in tags))
        lines.append("")

    return "\n".join(lines)


def write_note(
    msg: CapturedMessage,
    vault_dir: Path,
    related: list[str],
    tags: list[str],
) -> Path:
    vault_dir.mkdir(parents=True, exist_ok=True)
    path = build_filename(msg, vault_dir)
    path.write_text(build_content(msg, related, tags), encoding="utf-8")
    return path


def build_update_section(msg: CapturedMessage) -> str:
    lines: list[str] = []
    lines.append("")
    lines.append("---")
    lines.append(f"## Update {msg.created.strftime('%Y-%m-%d %H:%M')}")
    lines.append("")
    new_urls = [u for u in msg.source_urls]
    for url in new_urls:
        lines.append(f"> Source: {url}")
    if new_urls:
        lines.append("")
    for img in msg.images:
        lines.append(f"![[{img}]]")
    if msg.images:
        lines.append("")
    for att in msg.attachments:
        lines.append(f"![[{att}]]")
    if msg.attachments:
        lines.append("")
    if msg.text.strip():
        lines.append(msg.text.strip())
        lines.append("")
    return "\n".join(lines)


def append_to_note(path: Path, msg: CapturedMessage) -> Path:
    existing = path.read_text(encoding="utf-8").rstrip()
    new_text = existing + "\n" + build_update_section(msg)
    path.write_text(new_text, encoding="utf-8")
    return path


def _embeds(text: str) -> set[str]:
    return set(EMBED_RE.findall(text))


def is_safe_merge(existing: str, merged: str) -> bool:
    """The LLM rewrite must not drop frontmatter or any attachment embed."""
    if not merged.strip():
        return False
    if FRONTMATTER_RE.match(existing) and not FRONTMATTER_RE.match(merged):
        return False
    if not _embeds(existing).issubset(_embeds(merged)):
        return False
    return True


def _insert_before_related(text: str, block: str) -> str:
    """Insert `block` ahead of a trailing `*Related: ...*` section, else at the end."""
    m = RELATED_BLOCK_RE.search(text)
    if m is not None:
        return text[: m.start()] + "\n" + block.rstrip() + "\n" + text[m.start():]
    return text.rstrip() + "\n" + block.rstrip() + "\n"


def _new_media_block(merged: str, msg: CapturedMessage) -> str:
    lines: list[str] = []
    for url in msg.source_urls:
        if url and url not in merged:
            lines.append(f"> Source: {url}")
    for embed in [*msg.images, *msg.attachments]:
        token = f"![[{embed}]]"
        if token not in merged:
            lines.append(token)
    return "\n".join(lines)


def merge_into_note(
    path: Path, msg: CapturedMessage, client: Anthropic
) -> tuple[Path, bool]:
    """Rewrite an existing note to integrate `msg`, the Karpathy-wiki way.

    Returns (path, merged). When the LLM rewrite is unsafe (dropped frontmatter or
    an attachment), falls back to the mechanical append so a capture is never lost,
    and returns merged=False.
    """
    existing = path.read_text(encoding="utf-8")
    merged = merge_note(
        client,
        existing,
        msg.text or "",
        new_source_date=msg.created.strftime("%Y-%m-%d"),
    )
    if not is_safe_merge(existing, merged):
        log.info("Merge unsafe for %s; falling back to append", path.name)
        append_to_note(path, msg)
        return path, False
    block = _new_media_block(merged, msg)
    if block:
        merged = _insert_before_related(merged, block)
    path.write_text(merged.rstrip() + "\n", encoding="utf-8")
    return path, True
