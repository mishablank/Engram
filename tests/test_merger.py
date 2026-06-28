from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from engram.merger import merge_note


def _client(text: str) -> MagicMock:
    client = MagicMock()
    client.messages.create.return_value = SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)]
    )
    return client


def test_returns_merged_text() -> None:
    merged = "---\ncreated: x\n---\n# T\nintegrated body\n"
    client = _client(merged)
    out = merge_note(client, "---\ncreated: x\n---\n# T\nold body\n", "new info")
    assert out == merged.strip()
    client.messages.create.assert_called_once()


def test_strips_code_fences() -> None:
    client = _client("```markdown\n---\na: b\n---\n# T\nbody\n```")
    out = merge_note(client, "---\na: b\n---\n# T\nold\n", "new")
    assert out.startswith("---")
    assert "```" not in out


def test_empty_existing_returns_empty_without_calling_api() -> None:
    client = MagicMock()
    assert merge_note(client, "   ", "new") == ""
    client.messages.create.assert_not_called()


def test_api_error_returns_empty() -> None:
    client = MagicMock()
    client.messages.create.side_effect = RuntimeError("boom")
    assert merge_note(client, "existing body", "new") == ""
