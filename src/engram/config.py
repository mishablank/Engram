from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

DEFAULT_CATEGORIES: tuple[str, ...] = (
    "AI",
    "Crypto",
    "Startups/YC",
    "Personal",
    "Health",
    "Reading",
    "Other",
)
DEFAULT_CATEGORY = "Other"

SUMMARY_MODEL = "claude-sonnet-4-6"
REDO_MODEL = "claude-opus-4-7"
VISION_MODEL = "claude-haiku-4-5"
MERGE_MODEL = "claude-sonnet-4-6"
ENTITY_MODEL = "claude-sonnet-4-6"
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIM = 1536

# Entity (wiki backbone) pages live in typed top-level folders.
ENTITY_TYPE_FOLDERS: dict[str, str] = {
    "person": "People",
    "concept": "Concepts",
    "project": "Projects",
}


@dataclass
class Config:
    telegram_token: str
    anthropic_api_key: str
    openai_api_key: str | None
    allowed_user_ids: set[int]
    base_dir: Path
    categories: tuple[str, ...] = field(default=DEFAULT_CATEGORIES)


def load_config() -> Config:
    load_dotenv(override=True)
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    api_key = os.environ["ANTHROPIC_API_KEY"]
    openai_key = os.environ.get("OPENAI_API_KEY") or None
    allowed = {
        int(x.strip())
        for x in os.environ.get("ALLOWED_USER_IDS", "").split(",")
        if x.strip()
    }
    if not allowed:
        raise RuntimeError("ALLOWED_USER_IDS must contain at least one user id")
    base_dir = Path(os.environ["BASE_DIR"]).expanduser()

    cats_env = os.environ.get("CATEGORIES", "").strip()
    if cats_env:
        categories = tuple(c.strip() for c in cats_env.split(",") if c.strip())
    else:
        categories = DEFAULT_CATEGORIES

    return Config(
        telegram_token=token,
        anthropic_api_key=api_key,
        openai_api_key=openai_key,
        allowed_user_ids=allowed,
        base_dir=base_dir,
        categories=categories,
    )
