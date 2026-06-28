from __future__ import annotations

import logging

from anthropic import Anthropic

from .config import MERGE_MODEL

log = logging.getLogger(__name__)

_MERGE_SYSTEM = (
    "You maintain a personal Obsidian wiki. You are given an EXISTING note and a NEW "
    "source that is about the same topic. Rewrite the note so it integrates the new "
    "source into a single coherent page. Output the complete updated note in Markdown "
    "and NOTHING else.\n\n"
    "Rules:\n"
    "- Keep the YAML frontmatter block (the part between the opening and closing --- "
    "lines) at the very top. You may add new entries but never delete existing keys.\n"
    "- Integrate the new information into the existing prose. Remove redundancy so the "
    "note becomes sharper, not just longer. Do NOT keep dated '## Update' sections.\n"
    "- When the new source contradicts the existing note, keep the newer claim and add "
    "a short inline note of the change with its date, e.g. '(was X as of May 11; "
    "updated June 3)'.\n"
    "- Preserve every wikilink [[...]] and every embed ![[...]] exactly as written.\n"
    "- Keep the trailing '*Related: ...*' line and the '#tags' line if present.\n"
    "- Do not wrap the output in code fences."
)


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        lines = t.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        t = "\n".join(lines)
    return t.strip()


def merge_note(
    client: Anthropic,
    existing_text: str,
    new_text: str,
    *,
    new_source_date: str | None = None,
) -> str:
    """Return the full rewritten note that integrates `new_text` into `existing_text`.

    Returns "" on any failure so the caller can fall back to a safe append.
    """
    if not existing_text.strip():
        return ""
    date_clause = f" (captured {new_source_date})" if new_source_date else ""
    user_msg = (
        f"EXISTING NOTE:\n{existing_text}\n\n"
        f"NEW SOURCE{date_clause}:\n{new_text}\n\n"
        "Return the complete merged note in Markdown."
    )
    try:
        resp = client.messages.create(
            model=MERGE_MODEL,
            max_tokens=4000,
            system=[{"type": "text", "text": _MERGE_SYSTEM}],
            messages=[{"role": "user", "content": user_msg}],
        )
        text = "".join(
            b.text for b in resp.content if getattr(b, "type", None) == "text"
        )
    except Exception:
        log.exception("Merge rewrite failed")
        return ""
    return _strip_fences(text)
