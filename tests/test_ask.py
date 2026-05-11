from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from tg_obsidian_bot.linker import answer_from_vault


def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _fake_anthropic_with_text(reply: str) -> MagicMock:
    client = MagicMock()
    client.messages.create.return_value = SimpleNamespace(
        content=[SimpleNamespace(type="text", text=reply)]
    )
    return client


def test_answer_from_vault_passes_top_hits_and_returns_sources(tmp_path: Path) -> None:
    _write(tmp_path / "AI" / "Sora 2 Launch.md", "Sora 2 launched in October 2025 with new capabilities.\n")
    _write(tmp_path / "Other" / "Unrelated.md", "totally unrelated content\n")

    client = _fake_anthropic_with_text("Sora 2 launched in October 2025 [[Sora 2 Launch]]")
    result = answer_from_vault("when did sora 2 launch", tmp_path, client, top_k=4)

    client.messages.create.assert_called_once()
    call = client.messages.create.call_args
    user_msg = call.kwargs["messages"][0]["content"]
    assert "when did sora 2 launch" in user_msg.lower()
    assert "Sora 2 Launch" in user_msg
    assert "Sora 2 launched in October 2025" in user_msg

    assert "[[Sora 2 Launch]]" in result.answer
    assert any(h.title == "Sora 2 Launch" for h in result.sources)


def test_answer_from_vault_handles_no_matches(tmp_path: Path) -> None:
    _write(tmp_path / "Other" / "Note.md", "irrelevant\n")
    client = MagicMock()
    result = answer_from_vault("solana outage", tmp_path, client)
    client.messages.create.assert_not_called()
    assert "no vault notes" in result.answer.lower()
    assert result.sources == []


def test_answer_from_vault_recovers_from_api_error(tmp_path: Path) -> None:
    _write(tmp_path / "AI" / "n.md", "alpha gamma\n")
    client = MagicMock()
    client.messages.create.side_effect = RuntimeError("boom")
    result = answer_from_vault("alpha", tmp_path, client)
    assert "boom" in result.answer or "Error" in result.answer
    assert result.sources  # we still return what we found


def test_answer_from_vault_passes_prior_turns_as_history(tmp_path: Path) -> None:
    _write(tmp_path / "AI" / "Sora 2 Launch.md", "Sora 2 launched in October 2025.\n")
    client = _fake_anthropic_with_text("Yes, October 8 specifically. [[Sora 2 Launch]]")

    prior = [
        ("when did sora 2 launch", "Sora 2 launched in October 2025 [[Sora 2 Launch]]"),
    ]
    result = answer_from_vault(
        "what day in october",
        tmp_path,
        client,
        prior_turns=prior,
    )

    call = client.messages.create.call_args
    messages = call.kwargs["messages"]
    # Expect prior turn pair (user + assistant) preceding the new user message.
    assert len(messages) == 3
    assert messages[0]["role"] == "user"
    assert "when did sora 2 launch" in messages[0]["content"]
    assert messages[1]["role"] == "assistant"
    assert "October 2025" in messages[1]["content"]
    assert messages[2]["role"] == "user"
    assert "what day in october" in messages[2]["content"]

    assert "October 8" in result.answer
    assert result.sources  # fresh retrieval still happened


def test_answer_from_vault_ignores_empty_prior_turns(tmp_path: Path) -> None:
    _write(tmp_path / "AI" / "n.md", "alpha gamma\n")
    client = _fake_anthropic_with_text("answer")
    answer_from_vault("alpha", tmp_path, client, prior_turns=[])
    call = client.messages.create.call_args
    assert len(call.kwargs["messages"]) == 1  # no history prepended
