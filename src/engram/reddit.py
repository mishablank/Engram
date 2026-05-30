from __future__ import annotations

import logging
import os
import threading
import time
from urllib.parse import urlparse, urlunparse

import httpx

log = logging.getLogger(__name__)

REDDIT_HOSTS = {"reddit.com", "www.reddit.com", "old.reddit.com", "new.reddit.com", "np.reddit.com", "redd.it"}
USER_AGENT = "engram-bot/0.1 (Obsidian capture)"
OAUTH_BASE = "https://oauth.reddit.com"
TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
TIMEOUT = 20.0
MAX_COMMENTS = 10
MAX_COMMENT_CHARS = 600
MAX_TOTAL_CHARS = 30_000

_token_lock = threading.Lock()
_token_cache: dict[str, float | str] = {"token": "", "expires_at": 0.0}


def is_reddit_url(url: str) -> bool:
    try:
        host = urlparse(url).netloc.lower()
    except ValueError:
        return False
    return host in REDDIT_HOSTS


def _canonicalize(url: str) -> str:
    p = urlparse(url)
    path = p.path.rstrip("/")
    return urlunparse((p.scheme, p.netloc, path, "", "", ""))


def _credentials() -> tuple[str, str] | None:
    client_id = os.environ.get("REDDIT_CLIENT_ID", "").strip()
    client_secret = os.environ.get("REDDIT_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        return None
    return client_id, client_secret


def _get_token() -> str | None:
    creds = _credentials()
    if not creds:
        return None
    client_id, client_secret = creds

    with _token_lock:
        now = time.time()
        token = _token_cache.get("token") or ""
        expires_at = float(_token_cache.get("expires_at") or 0.0)
        if token and now < expires_at - 30:
            return str(token)

        try:
            resp = httpx.post(
                TOKEN_URL,
                auth=(client_id, client_secret),
                data={"grant_type": "client_credentials"},
                headers={"User-Agent": USER_AGENT},
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            payload = resp.json()
        except Exception as e:
            log.warning("Reddit OAuth token request failed: %s", e)
            return None

        token = payload.get("access_token")
        if not token:
            log.warning("Reddit OAuth response missing access_token")
            return None
        _token_cache["token"] = token
        _token_cache["expires_at"] = now + float(payload.get("expires_in", 3600))
        return token


def _resolve_share_link(url: str) -> str:
    """Reddit /s/<id> share links redirect to the canonical post URL."""
    try:
        r = httpx.head(
            url,
            follow_redirects=True,
            timeout=10.0,
            headers={"User-Agent": USER_AGENT},
        )
        return str(r.url)
    except Exception as e:
        log.warning("Could not resolve Reddit share link %s: %s", url, e)
        return url


def _format_post(payload: list) -> str | None:
    try:
        post = payload[0]["data"]["children"][0]["data"]
    except (IndexError, KeyError, TypeError):
        return None

    title = post.get("title", "").strip()
    selftext = post.get("selftext", "").strip()
    author = post.get("author", "").strip()
    subreddit = post.get("subreddit", "").strip()
    link_url = post.get("url", "").strip()
    score = post.get("score", 0)
    num_comments = post.get("num_comments", 0)

    lines: list[str] = []
    lines.append(f"REDDIT POST (r/{subreddit}):")
    if title:
        lines.append(f"Title: {title}")
    if author:
        lines.append(f"Author: u/{author}")
    lines.append(f"Score: {score} | Comments: {num_comments}")
    if selftext:
        lines.append("")
        lines.append(selftext)
    elif link_url:
        lines.append("")
        lines.append(f"Linked URL: {link_url}")

    comments = []
    try:
        children = payload[1]["data"]["children"]
    except (IndexError, KeyError, TypeError):
        children = []
    for child in children:
        if child.get("kind") != "t1":
            continue
        d = child.get("data", {})
        body = (d.get("body") or "").strip()
        if not body:
            continue
        if len(body) > MAX_COMMENT_CHARS:
            body = body[:MAX_COMMENT_CHARS] + "...[truncated]"
        comments.append((d.get("author", "?"), d.get("score", 0), body))
        if len(comments) >= MAX_COMMENTS:
            break

    if comments:
        lines.append("")
        lines.append("TOP COMMENTS:")
        for author, score, body in comments:
            lines.append(f"- u/{author} ({score}): {body}")

    text = "\n".join(lines)
    if len(text) > MAX_TOTAL_CHARS:
        text = text[:MAX_TOTAL_CHARS] + "\n...[truncated]"
    return text


def _path_for_oauth(url: str) -> str:
    p = urlparse(url)
    return p.path.rstrip("/")


def fetch_reddit(url: str) -> str | None:
    if not is_reddit_url(url):
        return None

    token = _get_token()
    if not token:
        log.info(
            "Reddit credentials not configured (REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET); "
            "skipping Reddit handler for %s",
            url,
        )
        return None

    target = url
    if "/s/" in urlparse(url).path:
        resolved = _resolve_share_link(url)
        if is_reddit_url(resolved):
            target = resolved

    json_url = OAUTH_BASE + _path_for_oauth(target) + ".json"
    try:
        resp = httpx.get(
            json_url,
            timeout=TIMEOUT,
            headers={
                "Authorization": f"Bearer {token}",
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
            },
            follow_redirects=True,
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception as e:
        log.warning("Reddit JSON fetch failed for %s: %s", json_url, e)
        return None

    if not isinstance(payload, list) or len(payload) < 1:
        log.warning("Unexpected Reddit JSON shape for %s", json_url)
        return None

    formatted = _format_post(payload)
    if formatted:
        log.info("Fetched %s via Reddit OAuth (%d chars)", url, len(formatted))
    return formatted
