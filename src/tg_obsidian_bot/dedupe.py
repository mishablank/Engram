from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from anthropic import Anthropic

from .config import VISION_MODEL
from .embeddings import SemanticIndex
from .vault import load_note_body

log = logging.getLogger(__name__)

AUTO_THRESHOLD = 0.88
JUDGE_THRESHOLD = 0.75
JUDGE_MODEL = VISION_MODEL  # cheap, fast

_JUDGE_SYSTEM = (
    "You decide whether two notes are about the SAME specific topic and should be "
    "merged into one Obsidian note. Same topic means same event, same subject, same "
    "person — not just related themes. Answer with a JSON object: "
    '{"match": "yes" | "no", "reason": "one short clause"}. '
    'Use "no" when in doubt.'
)


def _build_query_text(title: str | None, summary: str) -> str:
    parts: list[str] = []
    if title:
        parts.append(title)
    if summary:
        parts.append(summary[:600])
    return "\n".join(parts).strip()


def _judge_match(
    client: Anthropic, new_title: str, new_summary: str, candidate_body: str
) -> bool:
    user_msg = (
        f"NEW NOTE:\nTitle: {new_title}\nSummary: {new_summary[:1200]}\n\n"
        f"EXISTING NOTE:\n{candidate_body[:1500]}\n\n"
        "Same topic — should the new note be merged into the existing one? "
        "Respond JSON only."
    )
    try:
        resp = client.messages.create(
            model=JUDGE_MODEL,
            max_tokens=200,
            system=[{"type": "text", "text": _JUDGE_SYSTEM}],
            messages=[{"role": "user", "content": user_msg}],
        )
        text = "".join(
            b.text for b in resp.content if getattr(b, "type", None) == "text"
        )
    except Exception:
        log.exception("Dedupe judge failed")
        return False
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return False
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return False
    return isinstance(data.get("match"), str) and data["match"].strip().lower() == "yes"


def find_semantic_duplicate(
    semantic_index: SemanticIndex | None,
    client: Anthropic,
    title: str | None,
    summary: str,
    *,
    skip_paths: set[Path] | None = None,
) -> Path | None:
    """Return an existing note's path if it's clearly the same topic, else None.

    Two-stage: cosine pre-filter, then LLM judge for the medium-confidence band.
    Anything below JUDGE_THRESHOLD is ignored.
    """
    if semantic_index is None or not semantic_index.enabled:
        return None
    query = _build_query_text(title, summary)
    if not query:
        return None
    skip = skip_paths or set()
    hits = semantic_index.nearest(query, k=3)
    for hit in hits:
        if hit.path in skip:
            continue
        if hit.score >= AUTO_THRESHOLD:
            log.info("Semantic dedupe AUTO match (%.3f): %s", hit.score, hit.path.name)
            return hit.path
        if hit.score >= JUDGE_THRESHOLD:
            body = load_note_body(hit.path)
            if not body:
                continue
            if _judge_match(client, title or "", summary, body):
                log.info("Semantic dedupe JUDGE match (%.3f): %s", hit.score, hit.path.name)
                return hit.path
            log.info("Semantic dedupe JUDGE rejected (%.3f): %s", hit.score, hit.path.name)
            # Don't keep walking down — the next candidate is even less similar.
            return None
        # Top hit below judge threshold — nothing else will be closer.
        return None
    return None
