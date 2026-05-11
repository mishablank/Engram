from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from engram import dedupe
from engram.dedupe import find_semantic_duplicate
from engram.embeddings import NearestHit


class FakeSemanticIndex:
    def __init__(self, ranked: list[tuple[Path, float]]):
        self._ranked = [NearestHit(path=p, score=s) for p, s in ranked]
        self.enabled = True

    def nearest(self, query: str, k: int = 5) -> list[NearestHit]:
        return self._ranked[:k]


def _fake_anthropic_with_json(payload: str) -> MagicMock:
    client = MagicMock()
    client.messages.create.return_value = SimpleNamespace(
        content=[SimpleNamespace(type="text", text=payload)]
    )
    return client


def test_returns_none_when_index_disabled(tmp_path: Path) -> None:
    class Disabled:
        enabled = False

        def nearest(self, *a, **k):
            return []

    result = find_semantic_duplicate(
        Disabled(), MagicMock(), title="t", summary="s"
    )
    assert result is None


def test_auto_appends_above_high_threshold(tmp_path: Path) -> None:
    existing = tmp_path / "AI" / "existing.md"
    existing.parent.mkdir(parents=True)
    existing.write_text("body\n", encoding="utf-8")

    idx = FakeSemanticIndex([(existing, 0.95)])
    client = MagicMock()  # should not be called

    result = find_semantic_duplicate(
        idx, client, title="new title", summary="new summary"
    )
    assert result == existing
    client.messages.create.assert_not_called()


def test_judge_band_yes_returns_match(tmp_path: Path) -> None:
    existing = tmp_path / "AI" / "existing.md"
    existing.parent.mkdir(parents=True)
    existing.write_text("existing body about Sora 2\n", encoding="utf-8")

    idx = FakeSemanticIndex([(existing, 0.80)])
    client = _fake_anthropic_with_json('{"match": "yes", "reason": "same launch"}')

    result = find_semantic_duplicate(
        idx, client, title="Sora 2 launch recap", summary="OpenAI launched Sora 2"
    )
    assert result == existing
    client.messages.create.assert_called_once()


def test_judge_band_no_returns_none(tmp_path: Path) -> None:
    existing = tmp_path / "AI" / "existing.md"
    existing.parent.mkdir(parents=True)
    existing.write_text("different topic\n", encoding="utf-8")

    idx = FakeSemanticIndex([(existing, 0.80)])
    client = _fake_anthropic_with_json('{"match": "no", "reason": "different"}')

    result = find_semantic_duplicate(
        idx, client, title="x", summary="y"
    )
    assert result is None


def test_below_judge_threshold_returns_none_without_calling_judge(tmp_path: Path) -> None:
    existing = tmp_path / "AI" / "existing.md"
    existing.parent.mkdir(parents=True)
    existing.write_text("body\n", encoding="utf-8")

    idx = FakeSemanticIndex([(existing, 0.50)])
    client = MagicMock()

    result = find_semantic_duplicate(idx, client, title="x", summary="y")
    assert result is None
    client.messages.create.assert_not_called()


def test_skips_explicitly_excluded_paths(tmp_path: Path) -> None:
    a = tmp_path / "AI" / "a.md"
    b = tmp_path / "AI" / "b.md"
    a.parent.mkdir(parents=True)
    a.write_text("body a\n", encoding="utf-8")
    b.write_text("body b\n", encoding="utf-8")

    idx = FakeSemanticIndex([(a, 0.95), (b, 0.90)])
    client = MagicMock()

    result = find_semantic_duplicate(
        idx, client, title="x", summary="y", skip_paths={a}
    )
    assert result == b


def test_recovers_from_judge_api_error(tmp_path: Path) -> None:
    existing = tmp_path / "AI" / "existing.md"
    existing.parent.mkdir(parents=True)
    existing.write_text("body\n", encoding="utf-8")

    idx = FakeSemanticIndex([(existing, 0.80)])
    client = MagicMock()
    client.messages.create.side_effect = RuntimeError("boom")

    result = find_semantic_duplicate(idx, client, title="x", summary="y")
    assert result is None
