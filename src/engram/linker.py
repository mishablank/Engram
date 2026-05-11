from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path

from anthropic import Anthropic

from .config import DEFAULT_CATEGORIES, DEFAULT_CATEGORY, REDO_MODEL, SUMMARY_MODEL
from .embeddings import SemanticIndex, hybrid_search
from .vault import SearchHit, VaultIndex, load_note_body, search_vault

log = logging.getLogger(__name__)

MAX_RELATED = 5
MAX_TAGS = 5
RETRY_DELAY_SECONDS = 1.0
SOURCE_TYPES: tuple[str, ...] = (
    "tweet", "article", "youtube", "paper", "image", "video", "podcast", "other"
)
DEFAULT_SOURCE_TYPE = "other"
CONFIDENCE_LEVELS: tuple[str, ...] = ("high", "medium", "low")
DEFAULT_CONFIDENCE = "high"

CATEGORY_GUIDANCE = {
    "AI": "LLMs, agents, prompting, ML/AI tooling, AI products, AI safety, AI startups",
    "Crypto": "blockchain, DeFi, tokens, on-chain protocols, crypto market analysis, web3, exchanges",
    "Startups/YC": "Y Combinator content, founder posts, fundraising, startup advice, company building",
    "Personal": "relationships, journaling, life events, hobbies, friends, family",
    "Health": "fitness, nutrition, mental health, sleep, longevity, biohacking",
    "Reading": "book notes, longform essays/articles when not domain-specific",
    "Other": "anything not matching the above",
}


def _category_rules_block(categories: tuple[str, ...]) -> str:
    lines: list[str] = []
    for c in categories:
        guidance = CATEGORY_GUIDANCE.get(c, "use your judgment based on the dominant theme")
        lines.append(f'- "{c}" — {guidance}')
    return "\n".join(lines)


def _system_prompt(categories: tuple[str, ...], redo: bool = False) -> str:
    cat_list = ", ".join(f'"{c}"' for c in categories)
    type_list = ", ".join(f'"{t}"' for t in SOURCE_TYPES)
    quality_clause = ""
    if redo:
        quality_clause = (
            "\n\nThis is a REDO request — the previous summary was unsatisfactory. "
            "Be sharper and more concrete: lead with the strongest insight or claim, "
            "preserve specific names/numbers/quotes, and avoid generic phrasing."
        )
    return f"""You are an Obsidian note curator. The user sends raw input (free text and/or URLs) captured from a chat. The actual fetched content of any URL is provided to you in the FETCHED CONTENT block — use it as the ground truth and do NOT rely on prior knowledge about the URL.{quality_clause}

Return ONLY a JSON object with these fields:
- "folder": exactly one of {cat_list} — pick the best fit by content. Routing rules:
{_category_rules_block(categories)}
- "source_type": exactly one of {type_list}. Use "tweet" for X/Twitter posts, "youtube" for YouTube videos, "paper" for academic/arxiv papers, "podcast" for podcast episodes, "article" for any other web article/blog post, "image" if input is just an OCR'd image, "video" for non-YouTube video content, "other" otherwise.
- "title": a short, human-readable headline (5-12 words) derived from the fetched content. NEVER use URLs, slugs, or random IDs. For an X/Twitter post, distill the post's main thesis as the title.
- "summary": EXACTLY 10 sentences summarizing the actual content. Each sentence on its own line, prefixed with "- ". Be concrete and specific — quote names, numbers, claims, and key terminology from the source. Do NOT include the URL in the summary itself. Do NOT say "the post says" or "the author writes" — just state the content directly. If the fetched content is too short or empty, summarize what is actually there in fewer sentences and clearly state the source was inaccessible.
- "related": up to 5 EXACT vault note titles from the provided list, semantically relevant. Empty list if none fit.
- "tags": up to 5 lowercase tags (no #, hyphens for spaces). Reuse existing tags when possible; invent new ones only when none fit.
- "confidence": one of "high", "medium", "low" — your confidence that "folder" is correct. Use "low" when the input is ambiguous, terse ("interesting"), domain-straddling, or content was unfetchable; "medium" when plausible but multiple folders fit; "high" when the routing is clear.

Critical: never invent or guess facts about the source. If the fetched content is missing, say so."""


@dataclass
class Enrichment:
    title: str
    summary: str
    related: list[str]
    tags: list[str]
    folder: str = DEFAULT_CATEGORY
    source_type: str = DEFAULT_SOURCE_TYPE
    confidence: str = DEFAULT_CONFIDENCE


def _build_index_block(index: VaultIndex) -> str:
    titles = "\n".join(f"- {t}" for t in index.titles)
    tags = ", ".join(index.tags) if index.tags else "(none)"
    return f"VAULT NOTE TITLES:\n{titles}\n\nEXISTING TAGS:\n{tags}"


def _parse_response(
    text: str,
    valid_titles: set[str],
    categories: tuple[str, ...],
) -> Enrichment | None:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    title = data.get("title", "").strip() if isinstance(data.get("title"), str) else ""
    summary = data.get("summary", "").strip() if isinstance(data.get("summary"), str) else ""
    related = [
        r for r in data.get("related", []) if isinstance(r, str) and r in valid_titles
    ][:MAX_RELATED]
    tags: list[str] = []
    for t in data.get("tags", []):
        if not isinstance(t, str):
            continue
        t = t.lstrip("#").strip().lower().replace(" ", "-")
        if t and t not in tags:
            tags.append(t)
    folder_raw = data.get("folder", "")
    folder = folder_raw if isinstance(folder_raw, str) and folder_raw in categories else DEFAULT_CATEGORY
    src_raw = data.get("source_type", "")
    src = src_raw if isinstance(src_raw, str) and src_raw in SOURCE_TYPES else DEFAULT_SOURCE_TYPE
    conf_raw = data.get("confidence", "")
    conf = (
        conf_raw.strip().lower()
        if isinstance(conf_raw, str) and conf_raw.strip().lower() in CONFIDENCE_LEVELS
        else DEFAULT_CONFIDENCE
    )
    if not title and not summary:
        return None
    return Enrichment(
        title=title,
        summary=summary,
        related=related,
        tags=tags[:MAX_TAGS],
        folder=folder,
        source_type=src,
        confidence=conf,
    )


def _fallback(raw: str) -> Enrichment:
    stripped = raw.strip()
    if not stripped:
        return Enrichment(
            title="Untitled note", summary="", related=[], tags=[],
            folder=DEFAULT_CATEGORY, source_type=DEFAULT_SOURCE_TYPE,
        )
    first = stripped.splitlines()[0]
    if re.match(r"^https?://\S+$", first.strip()):
        title = "Captured link"
    else:
        title = first[:80]
    return Enrichment(
        title=title, summary=stripped, related=[], tags=[],
        folder=DEFAULT_CATEGORY, source_type=DEFAULT_SOURCE_TYPE,
    )


def _build_user_message(raw_body: str, fetched: dict[str, str]) -> str:
    parts = [f"USER INPUT:\n{raw_body}"]
    for url, content in fetched.items():
        parts.append(f"\n\nFETCHED CONTENT for {url}:\n{content}")
    if not fetched and re.search(r"https?://", raw_body):
        parts.append("\n\n[Note: URL(s) in the input could not be fetched.]")
    parts.append("\n\nReturn JSON only.")
    return "".join(parts)


def enrich_note(
    raw_body: str,
    index: VaultIndex,
    client: Anthropic,
    fetched: dict[str, str] | None = None,
    categories: tuple[str, ...] = DEFAULT_CATEGORIES,
    *,
    redo: bool = False,
) -> Enrichment:
    if not raw_body.strip():
        return Enrichment(
            title="Untitled note", summary="", related=[], tags=[],
            folder=DEFAULT_CATEGORY, source_type=DEFAULT_SOURCE_TYPE,
        )
    fetched = fetched or {}
    model = REDO_MODEL if redo else SUMMARY_MODEL
    for attempt in range(2):
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=4000,
                system=[
                    {"type": "text", "text": _system_prompt(categories, redo=redo)},
                    {
                        "type": "text",
                        "text": _build_index_block(index),
                        "cache_control": {"type": "ephemeral"},
                    },
                ],
                messages=[
                    {
                        "role": "user",
                        "content": _build_user_message(raw_body, fetched),
                    }
                ],
            )
            text = "".join(
                block.text for block in resp.content if getattr(block, "type", None) == "text"
            )
            log.info("Claude (%s) raw response (%d chars): %s", model, len(text), text[:500])
            parsed = _parse_response(text, set(index.titles), categories)
            if parsed is None:
                log.warning("Could not parse Claude response, using fallback. Full text: %s", text)
                return _fallback(raw_body)
            return parsed
        except Exception as e:
            if attempt == 0:
                log.warning("Claude enrichment failed (attempt 1/2): %s; retrying", e)
                time.sleep(RETRY_DELAY_SECONDS)
                continue
            log.exception("Claude enrichment failed after retry: %s", e)
            return _fallback(raw_body)
    return _fallback(raw_body)


ASK_TOP_K = 8

_ASK_SYSTEM_PROMPT = (
    "You answer questions strictly from the user's Obsidian vault notes provided below. "
    "Be concrete and direct: quote specific names, numbers, and claims from the notes. "
    "Cite sources by note title in double brackets, e.g. [[Note Title]], at the end of "
    "the relevant claim. If the notes do not contain enough to answer, say so plainly "
    "and name the closest related notes. Do not invent facts not present in the notes."
)


@dataclass
class AskResult:
    answer: str
    sources: list[SearchHit]


def _build_notes_block(hits: list[SearchHit]) -> str:
    parts: list[str] = []
    for h in hits:
        body = load_note_body(h.path)
        parts.append(f"### [[{h.title}]] (folder: {h.category})\n{body}")
    return "\n\n---\n\n".join(parts)


def answer_from_vault(
    question: str,
    base_dir: Path,
    client: Anthropic,
    *,
    top_k: int = ASK_TOP_K,
    prior_turns: list[tuple[str, str]] | None = None,
    semantic_index: SemanticIndex | None = None,
) -> AskResult:
    hits = hybrid_search(base_dir, question, k=top_k, semantic_index=semantic_index)
    if not hits:
        return AskResult(
            answer="No vault notes matched that question.",
            sources=[],
        )
    notes_block = _build_notes_block(hits)
    user_msg = (
        f"QUESTION: {question}\n\n"
        f"VAULT NOTES (top {len(hits)} by lexical match):\n\n{notes_block}\n\n"
        "Answer the question using only the notes above. Cite sources as [[Title]]."
    )
    messages: list[dict] = []
    for q, a in prior_turns or []:
        messages.append({"role": "user", "content": q})
        messages.append({"role": "assistant", "content": a})
    messages.append({"role": "user", "content": user_msg})
    try:
        resp = client.messages.create(
            model=SUMMARY_MODEL,
            max_tokens=1500,
            system=[{"type": "text", "text": _ASK_SYSTEM_PROMPT}],
            messages=messages,
        )
        text = "".join(
            block.text for block in resp.content if getattr(block, "type", None) == "text"
        ).strip()
    except Exception as e:
        log.exception("Claude /ask failed")
        text = f"Error querying Claude: {e}"
    return AskResult(answer=text, sources=hits)
