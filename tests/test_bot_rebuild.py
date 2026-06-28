from __future__ import annotations

from types import SimpleNamespace

from engram import bot as bot_module
from engram.vault import VaultIndex
from tests.test_bot import (
    _fake_callback_update,
    _fake_message,
    _fake_update,
    _make_state,
    _patch_enrich,
)


def _set_text(state, text: str) -> None:
    state.anthropic.messages.create.return_value = SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)]
    )


def _set_sequence(state, texts: list[str]) -> None:
    state.anthropic.messages.create.side_effect = [
        SimpleNamespace(content=[SimpleNamespace(type="text", text=t)]) for t in texts
    ]


async def test_duplicate_branch_rewrites_when_merge_safe(tmp_path, monkeypatch):
    state = _make_state(tmp_path, monkeypatch)
    _patch_enrich(monkeypatch, folder="AI", title="X", summary="body")
    ai = tmp_path / "AI"
    ai.mkdir()
    existing = ai / "Canonical.md"
    existing.write_text("---\nc: x\n---\n# Canonical\nold body\n", encoding="utf-8")
    state._vault_index = VaultIndex()
    monkeypatch.setattr(bot_module, "find_semantic_duplicate", lambda *a, **k: existing)
    # The LLM returns a valid rewrite that preserves frontmatter → safe merge.
    _set_text(state, "---\nc: x\n---\n# Canonical\nmerged new body\n")

    update = _fake_update(_fake_message(text="some related thing"))
    handlers = bot_module.make_handlers(state)
    on_message, on_folder_choice = handlers[0], handlers[4]
    await on_message(update, SimpleNamespace(application=None))
    token = next(iter(state._pending))
    ai_idx = state.config.categories.index("AI")
    await on_folder_choice(
        _fake_callback_update(f"f|{token}|{ai_idx}"), SimpleNamespace()
    )

    text = existing.read_text(encoding="utf-8")
    assert "merged new body" in text
    assert "## Update" not in text  # rewrite, not append
    assert list(ai.glob("*.md")) == [existing]  # no duplicate created


async def test_rebuild_builds_entity_pages(tmp_path, monkeypatch):
    state = _make_state(tmp_path, monkeypatch)
    state._semantic_index.embedder = None  # disable → skip merge step
    ai = tmp_path / "AI"
    ai.mkdir()
    (ai / "a.md").write_text("---\nc: x\n---\n# a\nabout karpathy\n", encoding="utf-8")
    (ai / "b.md").write_text("---\nc: y\n---\n# b\nnothing notable\n", encoding="utf-8")
    # extract(a) -> Karpathy; extract(b) -> []; then one synth lead.
    _set_sequence(
        state,
        [
            '[{"name":"Andrej Karpathy","type":"person","observation":"works on AI"}]',
            "[]",
            "Andrej Karpathy is an AI researcher.",
        ],
    )

    on_rebuild = bot_module.make_handlers(state)[13]
    update = _fake_update(_fake_message(text="/rebuild"))
    await on_rebuild(update, SimpleNamespace())

    page = tmp_path / "People" / "Andrej Karpathy.md"
    assert page.exists()
    assert "works on AI ([[a]])" in page.read_text(encoding="utf-8")
    last = update.effective_chat.send_message.call_args.args[0]
    assert "Rebuild done" in last
