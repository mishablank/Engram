from __future__ import annotations

import logging
from urllib.parse import parse_qs, urlparse

from youtube_transcript_api import YouTubeTranscriptApi

log = logging.getLogger(__name__)

YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "music.youtube.com"}
PREFERRED_LANGUAGES = ("en", "en-US", "en-GB")
MAX_TRANSCRIPT_CHARS = 60_000


def extract_video_id(url: str) -> str | None:
    try:
        p = urlparse(url)
    except ValueError:
        return None
    host = p.netloc.lower()
    if host not in YOUTUBE_HOSTS and not host.endswith(".youtube.com"):
        return None
    if host == "youtu.be":
        vid = p.path.lstrip("/").split("/")[0]
        return vid or None
    if p.path == "/watch":
        vid = parse_qs(p.query).get("v", [None])[0]
        return vid
    parts = p.path.strip("/").split("/")
    if len(parts) >= 2 and parts[0] in ("shorts", "embed", "live", "v"):
        return parts[1] or None
    return None


def fetch_transcript(video_id: str) -> str | None:
    try:
        api = YouTubeTranscriptApi()
        fetched = api.fetch(video_id, languages=list(PREFERRED_LANGUAGES))
    except Exception as e:
        log.warning("Preferred-language transcript failed for %s (%s); trying any language", video_id, e)
        try:
            api = YouTubeTranscriptApi()
            transcript_list = api.list(video_id)
            transcript = next(iter(transcript_list))
            fetched = transcript.fetch()
        except Exception as e2:
            log.warning("No transcript available for %s: %s", video_id, e2)
            return None

    text = " ".join(snippet.text.strip() for snippet in fetched.snippets if snippet.text.strip())
    text = text.replace("\n", " ")
    if len(text) > MAX_TRANSCRIPT_CHARS:
        text = text[:MAX_TRANSCRIPT_CHARS] + " ...[truncated]"
    return text


def fetch_youtube(url: str) -> str | None:
    video_id = extract_video_id(url)
    if not video_id:
        return None
    transcript = fetch_transcript(video_id)
    if transcript is None:
        return None
    return f"YOUTUBE TRANSCRIPT (video id {video_id}):\n{transcript}"
