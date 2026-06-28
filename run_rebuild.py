"""One-off runner: executes the exact /rebuild logic against the configured vault."""
from __future__ import annotations

from engram import gitsafe
from engram.bot import BotState, _vault_note_paths
from engram.config import load_config
from engram.entities import rebuild_entity_pages
from engram.retro import merge_duplicate_notes
from engram.vault import load_note_body

cfg = load_config()
state = BotState(cfg)
base = cfg.base_dir
print(f"Vault: {base}")
print(f"Notes before: {len(_vault_note_paths(base))}")

committed = gitsafe.snapshot(base, "engram: pre-rebuild snapshot")
print(f"Pre-rebuild git snapshot: {'created' if committed else 'none (clean/unavailable)'}")

merges = 0
if state._semantic_index.enabled:
    print("Refreshing semantic index (embedding all notes)…")
    state._semantic_index.refresh()
    paths = _vault_note_paths(base)
    print(f"Merging duplicates across {len(paths)} notes…")
    merges = merge_duplicate_notes(base, state._semantic_index, state.anthropic, paths)
else:
    print("Semantic index disabled (no OPENAI_API_KEY) — skipping duplicate merge.")

notes = [(p.stem, load_note_body(p)) for p in _vault_note_paths(base)]
print(f"Extracting entities + building wiki pages from {len(notes)} notes…")
pages = rebuild_entity_pages(base, state.anthropic, notes)

gitsafe.snapshot(base, "engram: post-rebuild")
print(f"\nDONE. Merged {merges} duplicate(s); wrote {pages} entity page(s).")
print(f"Notes after: {len(_vault_note_paths(base))}")
print("Revert with: git -C \"$BASE_DIR\" reset --hard HEAD~")
