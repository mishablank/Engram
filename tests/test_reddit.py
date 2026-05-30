from unittest.mock import MagicMock, patch

import pytest

from engram import reddit as reddit_mod
from engram.reddit import is_reddit_url, fetch_reddit, _canonicalize


@pytest.fixture(autouse=True)
def reddit_env(monkeypatch):
    monkeypatch.setenv("REDDIT_CLIENT_ID", "test-id")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "test-secret")
    reddit_mod._token_cache["token"] = "cached-token"
    reddit_mod._token_cache["expires_at"] = 9_999_999_999.0
    yield
    reddit_mod._token_cache["token"] = ""
    reddit_mod._token_cache["expires_at"] = 0.0


def test_is_reddit_url():
    assert is_reddit_url("https://www.reddit.com/r/NavalRavikant/s/Pv14v1RZ5d")
    assert is_reddit_url("https://old.reddit.com/r/python/comments/abc/foo/")
    assert is_reddit_url("https://reddit.com/r/python")
    assert is_reddit_url("https://redd.it/abc123")
    assert not is_reddit_url("https://www.youtube.com/watch?v=x")
    assert not is_reddit_url("https://example.com/r/python")


def test_canonicalize_strips_trailing_slash_and_query():
    assert _canonicalize("https://www.reddit.com/r/x/comments/1/y/?foo=1") == \
        "https://www.reddit.com/r/x/comments/1/y"
    assert _canonicalize("https://www.reddit.com/r/x/comments/1/y") == \
        "https://www.reddit.com/r/x/comments/1/y"


def _post_payload(title="Hello", selftext="Body text", author="someone", subreddit="NavalRavikant",
                  url=None, comments=None):
    post = {
        "data": {
            "children": [
                {
                    "data": {
                        "title": title,
                        "selftext": selftext,
                        "author": author,
                        "subreddit": subreddit,
                        "url": url or "https://example.com",
                        "score": 42,
                        "num_comments": len(comments or []),
                    }
                }
            ]
        }
    }
    comment_children = [
        {"kind": "t1", "data": {"author": c[0], "body": c[1], "score": c[2]}}
        for c in (comments or [])
    ]
    comments_payload = {"data": {"children": comment_children}}
    return [post, comments_payload]


def test_fetch_reddit_returns_none_for_non_reddit():
    assert fetch_reddit("https://example.com/foo") is None


def test_fetch_reddit_returns_none_without_credentials(monkeypatch):
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
    reddit_mod._token_cache["token"] = ""
    reddit_mod._token_cache["expires_at"] = 0.0
    assert fetch_reddit("https://www.reddit.com/r/x/comments/1/y/") is None


def test_fetch_reddit_parses_post_and_comments():
    payload = _post_payload(
        title="On wealth",
        selftext="Seek wealth, not money.",
        author="naval_fan",
        comments=[
            ("alice", "Great quote", 10),
            ("bob", "Agreed", 5),
        ],
    )
    fake_resp = MagicMock(status_code=200)
    fake_resp.json.return_value = payload
    fake_resp.raise_for_status = MagicMock()

    with patch("engram.reddit.httpx.get", return_value=fake_resp) as get:
        result = fetch_reddit("https://www.reddit.com/r/NavalRavikant/comments/abc/on_wealth/")

    assert result is not None
    assert "On wealth" in result
    assert "Seek wealth" in result
    assert "naval_fan" in result
    assert "alice" in result
    assert "Great quote" in result

    url_called = get.call_args.args[0]
    headers = get.call_args.kwargs["headers"]
    assert url_called.startswith("https://oauth.reddit.com/")
    assert url_called.endswith(".json")
    assert headers["Authorization"] == "Bearer cached-token"
    assert "User-Agent" in headers


def test_fetch_reddit_resolves_share_link_then_fetches_json():
    resolved = "https://www.reddit.com/r/NavalRavikant/comments/abc/on_wealth/"

    head_resp = MagicMock()
    head_resp.url = resolved

    json_resp = MagicMock(status_code=200)
    json_resp.json.return_value = _post_payload(title="On wealth", selftext="Body")
    json_resp.raise_for_status = MagicMock()

    with patch("engram.reddit.httpx.head", return_value=head_resp) as head, \
         patch("engram.reddit.httpx.get", return_value=json_resp) as get:
        result = fetch_reddit("https://www.reddit.com/r/NavalRavikant/s/Pv14v1RZ5d")

    assert result is not None
    assert "On wealth" in result
    head.assert_called_once()
    get_url = get.call_args.args[0]
    assert get_url == "https://oauth.reddit.com/r/NavalRavikant/comments/abc/on_wealth.json"


def test_fetch_reddit_returns_none_on_http_error():
    fake_resp = MagicMock(status_code=403)
    fake_resp.raise_for_status.side_effect = RuntimeError("403 Forbidden")

    with patch("engram.reddit.httpx.get", return_value=fake_resp):
        result = fetch_reddit("https://www.reddit.com/r/NavalRavikant/comments/abc/on_wealth/")

    assert result is None


def test_fetch_reddit_handles_empty_selftext_link_post():
    payload = _post_payload(
        title="Cool link",
        selftext="",
        url="https://nav.al/wealth",
        comments=[("alice", "thx", 3)],
    )
    fake_resp = MagicMock(status_code=200)
    fake_resp.json.return_value = payload
    fake_resp.raise_for_status = MagicMock()

    with patch("engram.reddit.httpx.get", return_value=fake_resp):
        result = fetch_reddit("https://www.reddit.com/r/NavalRavikant/comments/abc/cool_link/")

    assert result is not None
    assert "Cool link" in result
    assert "https://nav.al/wealth" in result
    assert "alice" in result


def test_fetch_reddit_obtains_token_when_cache_empty(monkeypatch):
    reddit_mod._token_cache["token"] = ""
    reddit_mod._token_cache["expires_at"] = 0.0

    token_resp = MagicMock(status_code=200)
    token_resp.json.return_value = {"access_token": "fresh-token", "expires_in": 3600}
    token_resp.raise_for_status = MagicMock()

    json_resp = MagicMock(status_code=200)
    json_resp.json.return_value = _post_payload(title="T", selftext="S")
    json_resp.raise_for_status = MagicMock()

    with patch("engram.reddit.httpx.post", return_value=token_resp) as post, \
         patch("engram.reddit.httpx.get", return_value=json_resp) as get:
        result = fetch_reddit("https://www.reddit.com/r/x/comments/1/y/")

    assert result is not None
    post.assert_called_once()
    auth_header = get.call_args.kwargs["headers"]["Authorization"]
    assert auth_header == "Bearer fresh-token"
