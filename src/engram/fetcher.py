from __future__ import annotations

import logging
import re

import httpx

from .reddit import fetch_reddit, is_reddit_url
from .youtube import extract_video_id, fetch_youtube

log = logging.getLogger(__name__)

JINA_READER = "https://r.jina.ai/"
TIMEOUT = 30.0
MAX_CHARS = 30_000  # cap per URL to keep prompts bounded

SHORTENERS = (
    "t.co/", "bit.ly/", "tinyurl.com/", "ow.ly/", "buff.ly/",
    "lnkd.in/", "goo.gl/", "is.gd/", "trib.al/", "dlvr.it/",
)
URL_IN_TEXT = re.compile(r'https?://[^\s\)\]"\'<>]+')


def _looks_like_shortener(url: str) -> bool:
    return any(s in url for s in SHORTENERS)


def _resolve_redirect(url: str) -> str:
    try:
        r = httpx.head(url, follow_redirects=True, timeout=10.0)
        return str(r.url)
    except Exception as e:
        log.warning("Could not resolve redirect for %s: %s", url, e)
        return url


def _fetch_via_jina(url: str) -> str | None:
    try:
        resp = httpx.get(
            f"{JINA_READER}{url}",
            timeout=TIMEOUT,
            headers={"Accept": "text/markdown"},
            follow_redirects=True,
        )
        resp.raise_for_status()
        text = resp.text.strip()
        if len(text) > MAX_CHARS:
            text = text[:MAX_CHARS] + "\n...[truncated]"
        log.info("Fetched %s via Jina (%d chars)", url, len(text))
        return text
    except Exception as e:
        log.warning("Jina fetch failed for %s: %s", url, e)
        return None


def fetch_url(url: str) -> str | None:
    if extract_video_id(url):
        transcript = fetch_youtube(url)
        if transcript:
            log.info("Fetched %s as YouTube transcript (%d chars)", url, len(transcript))
            return transcript
        log.info("YouTube transcript unavailable for %s; falling back to Jina", url)
    if is_reddit_url(url):
        reddit_text = fetch_reddit(url)
        if reddit_text:
            return reddit_text
        log.info("Reddit JSON unavailable for %s; falling back to Jina", url)
    return _fetch_via_jina(url)


def _discover_followups(content: str, source_url: str) -> list[str]:
    """Find shortener URLs inside fetched content and return resolved targets."""
    seen: set[str] = set()
    followups: list[str] = []
    for match in URL_IN_TEXT.findall(content):
        url = match.rstrip(".,;:!?")
        if url == source_url or url in seen:
            continue
        if not _looks_like_shortener(url):
            continue
        seen.add(url)
        resolved = _resolve_redirect(url)
        if resolved != url and resolved not in seen:
            log.info("Resolved shortener %s -> %s", url, resolved)
            followups.append(resolved)
            seen.add(resolved)
        if len(followups) >= 3:
            break
    return followups


def fetch_urls(urls: list[str]) -> dict[str, str]:
    results: dict[str, str] = {}
    for url in urls:
        content = fetch_url(url)
        if content is None:
            continue
        results[url] = content
        for followup in _discover_followups(content, url):
            if followup in results:
                continue
            sub = fetch_url(followup)
            if sub is not None:
                results[followup] = sub
    return results
