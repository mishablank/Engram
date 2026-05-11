from unittest.mock import MagicMock, patch

from engram.youtube import extract_video_id, fetch_transcript, fetch_youtube


def test_extract_video_id_watch_url():
    assert extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_video_id("https://youtube.com/watch?v=abc123&t=42s") == "abc123"


def test_extract_video_id_short_url():
    assert extract_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_video_id("https://youtu.be/dQw4w9WgXcQ?si=foo") == "dQw4w9WgXcQ"


def test_extract_video_id_shorts_and_embed():
    assert extract_video_id("https://www.youtube.com/shorts/abc123") == "abc123"
    assert extract_video_id("https://www.youtube.com/embed/abc123") == "abc123"
    assert extract_video_id("https://m.youtube.com/watch?v=abc123") == "abc123"


def test_extract_video_id_non_youtube():
    assert extract_video_id("https://x.com/foo/123") is None
    assert extract_video_id("https://example.com/watch?v=abc") is None


def _fake_fetched(snippets):
    fetched = MagicMock()
    fetched.snippets = [MagicMock(text=t) for t in snippets]
    return fetched


def test_fetch_transcript_joins_snippets():
    with patch("engram.youtube.YouTubeTranscriptApi") as Api:
        Api.return_value.fetch.return_value = _fake_fetched(["hello", "world", "  "])
        result = fetch_transcript("vid")
    assert result == "hello world"


def test_fetch_youtube_returns_none_for_non_youtube_url():
    assert fetch_youtube("https://example.com/foo") is None


def test_fetch_youtube_returns_labelled_transcript():
    with patch("engram.youtube.YouTubeTranscriptApi") as Api:
        Api.return_value.fetch.return_value = _fake_fetched(["hi", "there"])
        result = fetch_youtube("https://www.youtube.com/watch?v=abc123")
    assert result is not None
    assert "YOUTUBE TRANSCRIPT" in result
    assert "abc123" in result
    assert "hi there" in result


def test_fetch_youtube_returns_none_when_no_transcript():
    with patch("engram.youtube.YouTubeTranscriptApi") as Api:
        Api.return_value.fetch.side_effect = RuntimeError("no captions")
        Api.return_value.list.side_effect = RuntimeError("no transcripts")
        result = fetch_youtube("https://www.youtube.com/watch?v=abc123")
    assert result is None
