"""First-boot seeder for the wiki directory.

Creates ``{EVOFLUX_WIKI_DIR}/topics/``, ``{EVOFLUX_WIKI_DIR}/notes/``, and
``{EVOFLUX_WIKI_DIR}/USER.md`` with a default template if missing.

Idempotent — existing files are never overwritten.
Called from the FastAPI lifespan handler at startup.
"""

from __future__ import annotations

from loguru import logger

from app.services.memory import IMPORTS_DIR, WIKI_DIR, seed_memory
from app.services.wiki import (
    DEFAULT_USER_FILE,
    NOTES_DIR,
    TOPICS_DIR,
    USER_FILE,
    wiki_root,
)


def seed_wiki() -> None:
    """Create the wiki directory structure and default files if missing."""
    wiki = wiki_root()
    for sub in (TOPICS_DIR, NOTES_DIR, IMPORTS_DIR, WIKI_DIR):
        (wiki / sub).mkdir(parents=True, exist_ok=True)
    seed_memory()

    user_file = wiki / USER_FILE
    if not user_file.exists():
        user_file.write_text(DEFAULT_USER_FILE, encoding="utf-8")
        logger.info("wiki_seeded root={} created={}", wiki, USER_FILE)

    if user_file.exists():
        logger.debug("wiki_seed_skipped root={} (already initialised)", wiki)
