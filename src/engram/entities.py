from __future__ import annotations

import json
import logging
import re
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from anthropic import Anthropic

from .config import ENTITY_MODEL, ENTITY_TYPE_FOLDERS

log = logging.getLogger(__name__)

MAX_ENTITIES = 6
_BAD_CHARS = re.compile(r'[\\/:*?"<>|#\[\]]')
_WS = re.compile(r"\s+")

_EXTRACT_SYSTEM = (
    "You extract the salient named entities from a single note for a personal wiki. "
    "Return ONLY a JSON array. Each element is an object with:\n"
    '- "name": the canonical name (a person, a concept, or a project/company/product)\n'
    '- "type": exactly one of "person", "concept", "project"\n'
    '- "observation": ONE concrete sentence about this entity grounded in THIS note\n'
    "Rules: include at most 6 entities. Only entities that are genuinely central to "
    "the note. Skip generic words, the author's own filler, and anything you would not "
    "want a dedicated wiki page for. Use the most common canonical name (e.g. 'Andrej "
    'Karpathy\', not \'Karpathy\' or \'@karpathy\'). Return [] if nothing qualifies.'
)

_SYNTH_SYSTEM = (
    "You write the lead paragraph of a wiki page about one entity, synthesizing a list "
    "of observations gathered from many notes. Write 1-3 sentences, concrete and "
    "specific, present tense, no preamble. Do not use bullet points. Do not repeat the "
    "entity name as a heading. Output only the paragraph."
)


@dataclass
class Entity:
    name: str
    type: str
    observation: str


def _safe_name(name: str) -> str:
    name = _BAD_CHARS.sub(" ", name)
    name = _WS.sub(" ", name).strip()
    return name or "entity"


def _normalize(name: str) -> str:
    return _WS.sub(" ", _BAD_CHARS.sub(" ", name.lower())).strip()


def entity_path(base_dir: Path, entity: Entity) -> Path:
    folder = ENTITY_TYPE_FOLDERS.get(entity.type, ENTITY_TYPE_FOLDERS["concept"])
    return base_dir / folder / f"{_safe_name(entity.name)}.md"


def _parse_entities(text: str) -> list[Entity]:
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    out: list[Entity] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        etype = item.get("type")
        obs = item.get("observation", "")
        if not isinstance(name, str) or not name.strip():
            continue
        if etype not in ENTITY_TYPE_FOLDERS:
            continue
        out.append(
            Entity(
                name=name.strip(),
                type=etype,
                observation=obs.strip() if isinstance(obs, str) else "",
            )
        )
        if len(out) >= MAX_ENTITIES:
            break
    return out


def extract_entities(client: Anthropic, title: str, body: str) -> list[Entity]:
    if not body.strip():
        return []
    user_msg = f"NOTE TITLE: {title}\n\nNOTE BODY:\n{body}\n\nReturn the JSON array."
    try:
        resp = client.messages.create(
            model=ENTITY_MODEL,
            max_tokens=1000,
            system=[{"type": "text", "text": _EXTRACT_SYSTEM}],
            messages=[{"role": "user", "content": user_msg}],
        )
        text = "".join(
            b.text for b in resp.content if getattr(b, "type", None) == "text"
        )
    except Exception:
        log.exception("Entity extraction failed for %s", title)
        return []
    return _parse_entities(text)


_OBS_RE = re.compile(r"^- (?P<obs>.*?)(?: \(\[\[(?P<src>[^\]]+)\]\]\))?$")


def _build_page(
    name: str,
    etype: str,
    observations: list[tuple[str, str]],
    *,
    lead: str = "",
    created: str | None = None,
) -> str:
    now = datetime.now().isoformat(timespec="seconds")
    lines = ["---", f"entity-type: {etype}", f"created: {created or now}", f"updated: {now}", "---", ""]
    lines.append(f"# {name}")
    lines.append("")
    if lead:
        lines.append(lead.strip())
        lines.append("")
    lines.append("## Observations")
    seen_src: "OrderedDict[str, None]" = OrderedDict()
    for obs, src in observations:
        suffix = f" ([[{src}]])" if src else ""
        lines.append(f"- {obs}{suffix}")
        if src:
            seen_src.setdefault(src, None)
    lines.append("")
    lines.append("## Mentioned in")
    for src in seen_src:
        lines.append(f"- [[{src}]]")
    lines.append("")
    return "\n".join(lines)


def _read_observations(text: str) -> list[tuple[str, str]]:
    obs: list[tuple[str, str]] = []
    in_section = False
    for line in text.splitlines():
        if line.strip() == "## Observations":
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if in_section and line.startswith("- "):
            m = _OBS_RE.match(line.rstrip())
            if m:
                obs.append((m.group("obs").strip(), (m.group("src") or "").strip()))
    return obs


def _read_field(text: str, key: str) -> str | None:
    m = re.search(rf"^{re.escape(key)}:\s*(.+)$", text, re.MULTILINE)
    return m.group(1).strip() if m else None


def upsert_entity_page(base_dir: Path, entity: Entity, source_title: str) -> Path:
    """Create or grow the wiki page for `entity`, adding this source's observation."""
    path = entity_path(base_dir, entity)
    path.parent.mkdir(parents=True, exist_ok=True)
    new_obs = (entity.observation, source_title)
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        obs = _read_observations(existing)
        if new_obs not in obs and entity.observation:
            obs.append(new_obs)
        created = _read_field(existing, "created")
        lead = _extract_lead(existing)
        path.write_text(
            _build_page(entity.name, entity.type, obs, lead=lead, created=created),
            encoding="utf-8",
        )
    else:
        obs = [new_obs] if entity.observation else []
        path.write_text(
            _build_page(entity.name, entity.type, obs), encoding="utf-8"
        )
    return path


def _extract_lead(text: str) -> str:
    """The prose between the `# Title` heading and the first `##` section."""
    lines = text.splitlines()
    out: list[str] = []
    started = False
    for line in lines:
        if line.startswith("# ") and not started:
            started = True
            continue
        if started:
            if line.startswith("## "):
                break
            out.append(line)
    return "\n".join(out).strip()


def _synthesize_lead(client: Anthropic, name: str, observations: list[str]) -> str:
    if not observations:
        return ""
    joined = "\n".join(f"- {o}" for o in observations)
    try:
        resp = client.messages.create(
            model=ENTITY_MODEL,
            max_tokens=400,
            system=[{"type": "text", "text": _SYNTH_SYSTEM}],
            messages=[{"role": "user", "content": f"ENTITY: {name}\n\nOBSERVATIONS:\n{joined}"}],
        )
        return "".join(
            b.text for b in resp.content if getattr(b, "type", None) == "text"
        ).strip()
    except Exception:
        log.exception("Lead synthesis failed for %s", name)
        return ""


def rebuild_entity_pages(
    base_dir: Path,
    client: Anthropic,
    notes: list[tuple[str, str]],
    *,
    min_mentions: int = 2,
) -> int:
    """Extract entities across all notes and rebuild typed pages from scratch.

    `notes` is a list of (title, body). Only entities mentioned in at least
    `min_mentions` distinct notes get a page — singletons are noise for a wiki
    backbone, not structure. Returns the number of entity pages written.
    """
    # group_key -> (display_name, type, [(observation, source_title)])
    groups: "OrderedDict[tuple[str, str], tuple[str, str, list[tuple[str, str]]]]" = OrderedDict()
    for title, body in notes:
        for ent in extract_entities(client, title, body):
            key = (ent.type, _normalize(ent.name))
            if key not in groups:
                groups[key] = (ent.name, ent.type, [])
            if ent.observation:
                groups[key][2].append((ent.observation, title))

    # Clear existing typed folders so the rebuild is authoritative.
    for folder in set(ENTITY_TYPE_FOLDERS.values()):
        d = base_dir / folder
        if d.is_dir():
            for f in d.glob("*.md"):
                f.unlink()

    count = 0
    for name, etype, obs in groups.values():
        distinct_sources = {src for _, src in obs if src}
        if len(distinct_sources) < min_mentions:
            continue  # singleton (or below threshold) → skip
        lead = _synthesize_lead(client, name, [o for o, _ in obs])
        path = base_dir / ENTITY_TYPE_FOLDERS[etype] / f"{_safe_name(name)}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            _build_page(name, etype, obs, lead=lead), encoding="utf-8"
        )
        count += 1
    return count
