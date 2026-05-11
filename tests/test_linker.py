from types import SimpleNamespace
from unittest.mock import MagicMock

from tg_obsidian_bot.linker import enrich_note
from tg_obsidian_bot.vault import VaultIndex


def _fake_response(text: str):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])


def test_enrich_parses_title_summary_related_tags():
    client = MagicMock()
    client.messages.create.return_value = _fake_response(
        '{"folder": "AI", "source_type": "tweet", "title": "Meta-Meta-Prompting", '
        '"summary": "- point one\\n- point two", '
        '"related": ["Note A", "Unknown"], "tags": ["#AI", "Agents"]}'
    )
    idx = VaultIndex(titles=["Note A", "Note B"], tags=["ai"])
    out = enrich_note("https://x.com/garrytan/status/123", idx, client)
    assert out.title == "Meta-Meta-Prompting"
    assert "point one" in out.summary
    assert out.related == ["Note A"]
    assert out.tags == ["ai", "agents"]
    assert out.folder == "AI"
    assert out.source_type == "tweet"


def test_enrich_redo_uses_opus_model():
    client = MagicMock()
    client.messages.create.return_value = _fake_response(
        '{"folder": "AI", "source_type": "article", "title": "t", "summary": "s", "related": [], "tags": []}'
    )
    enrich_note("hi", VaultIndex(titles=[]), client, redo=True)
    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["model"] == "claude-opus-4-7"
    system_text = kwargs["system"][0]["text"]
    assert "REDO request" in system_text


def test_enrich_invalid_source_type_defaults_to_other():
    client = MagicMock()
    client.messages.create.return_value = _fake_response(
        '{"folder": "AI", "source_type": "weird", "title": "t", "summary": "s", "related": [], "tags": []}'
    )
    out = enrich_note("hi", VaultIndex(titles=[]), client)
    assert out.source_type == "other"


def test_enrich_invalid_folder_defaults_to_other():
    client = MagicMock()
    client.messages.create.return_value = _fake_response(
        '{"folder": "Bogus", "source_type": "article", "title": "t", "summary": "s", "related": [], "tags": []}'
    )
    out = enrich_note("hi", VaultIndex(titles=[]), client, categories=("AI", "Crypto", "Other"))
    assert out.folder == "Other"


def test_enrich_missing_folder_defaults_to_other():
    client = MagicMock()
    client.messages.create.return_value = _fake_response(
        '{"title": "t", "summary": "s", "related": [], "tags": []}'
    )
    out = enrich_note("hi", VaultIndex(titles=[]), client)
    assert out.folder == "Other"


def test_enrich_system_prompt_lists_categories():
    client = MagicMock()
    client.messages.create.return_value = _fake_response(
        '{"folder": "AI", "source_type": "article", "title": "t", "summary": "s", "related": [], "tags": []}'
    )
    enrich_note(
        "hi",
        VaultIndex(titles=[]),
        client,
        categories=("AI", "Crypto", "Startups/YC", "Other"),
    )
    system = client.messages.create.call_args.kwargs["system"]
    system_text = system[0]["text"]
    assert '"AI"' in system_text
    assert '"Crypto"' in system_text
    assert '"Startups/YC"' in system_text
    assert '"Other"' in system_text


def test_enrich_includes_fetched_content_in_prompt():
    client = MagicMock()
    client.messages.create.return_value = _fake_response(
        '{"title": "x", "summary": "y", "related": [], "tags": []}'
    )
    enrich_note(
        "https://x.com/foo/123",
        VaultIndex(titles=[], tags=[]),
        client,
        fetched={"https://x.com/foo/123": "Real tweet content here about AI agents"},
    )
    kwargs = client.messages.create.call_args.kwargs
    user_msg = kwargs["messages"][0]["content"]
    assert "Real tweet content here about AI agents" in user_msg
    assert "FETCHED CONTENT for https://x.com/foo/123" in user_msg


def test_enrich_warns_when_url_present_but_unfetched():
    client = MagicMock()
    client.messages.create.return_value = _fake_response(
        '{"title": "x", "summary": "y", "related": [], "tags": []}'
    )
    enrich_note(
        "https://x.com/foo/123",
        VaultIndex(titles=[], tags=[]),
        client,
        fetched={},
    )
    kwargs = client.messages.create.call_args.kwargs
    user_msg = kwargs["messages"][0]["content"]
    assert "could not be fetched" in user_msg


def test_enrich_uses_prompt_cache_on_index():
    client = MagicMock()
    client.messages.create.return_value = _fake_response(
        '{"title": "t", "summary": "s", "related": [], "tags": []}'
    )
    enrich_note("hi", VaultIndex(titles=["X"], tags=["t"]), client)
    system = client.messages.create.call_args.kwargs["system"]
    assert any(b.get("cache_control", {}).get("type") == "ephemeral" for b in system)


def test_enrich_falls_back_on_api_error(monkeypatch):
    monkeypatch.setattr("tg_obsidian_bot.linker.RETRY_DELAY_SECONDS", 0)
    client = MagicMock()
    client.messages.create.side_effect = RuntimeError("boom")
    out = enrich_note("hello world", VaultIndex(titles=["A"]), client)
    assert out.title == "hello world"
    assert out.summary == "hello world"
    assert out.related == []
    assert out.tags == []
    assert client.messages.create.call_count == 2


def test_enrich_fallback_for_url_only_input(monkeypatch):
    monkeypatch.setattr("tg_obsidian_bot.linker.RETRY_DELAY_SECONDS", 0)
    client = MagicMock()
    client.messages.create.side_effect = RuntimeError("boom")
    out = enrich_note("https://x.com/garrytan/status/123", VaultIndex(titles=[]), client)
    assert out.title == "Captured link"
    assert "https://" in out.summary


def test_enrich_retries_once_on_transient_error(monkeypatch):
    monkeypatch.setattr("tg_obsidian_bot.linker.RETRY_DELAY_SECONDS", 0)
    client = MagicMock()
    client.messages.create.side_effect = [
        RuntimeError("transient"),
        _fake_response(
            '{"folder": "AI", "source_type": "article", "title": "Real Title", '
            '"summary": "real summary", "related": [], "tags": []}'
        ),
    ]
    out = enrich_note("https://example.com/ai-thing", VaultIndex(titles=[]), client)
    assert out.folder == "AI"
    assert out.title == "Real Title"
    assert client.messages.create.call_count == 2


def test_enrich_empty_input():
    client = MagicMock()
    out = enrich_note("   ", VaultIndex(titles=["A"]), client)
    assert out.summary == ""
    client.messages.create.assert_not_called()
