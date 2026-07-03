"""Filesystem-tool post-mutation hook for config caches.

Filesystem tools (``write``, ``edit``, ``rm``) call :func:`notify_fs_change`
after a successful mutation.  The hook decides whether the path falls
under one of the config trees that have process-level caches, and
invalidates the right cache.

Today this only matters for ``{SKILLS_DIR}/*/SKILL.md`` — the
``discover_skills`` cache in ``app.agent.tools.builtin.skill`` is
mtime-keyed, so it self-heals on the next call, but eagerly clearing
the LRU avoids relying on filesystem mtime granularity (1s on most
platforms) when the agent writes a skill and immediately validates it
in the same turn.

Kept in this module (not in the skill module itself) to avoid pulling
``functools.lru_cache`` internals across module boundaries from fs-tool
imports, and to keep the dependency direction one-way:
filesystem tools → builtin.skill, never the reverse.
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger


def notify_fs_change(resolved_path: Path) -> None:
    """Inform config-aware caches that *resolved_path* was created/edited/deleted.

    Safe to call unconditionally after every successful ``write`` / ``edit``
    / ``rm`` — the helper only does work when the path is inside a known
    config tree.  Exceptions are swallowed and logged because cache
    invalidation must never fail the tool call.
    """
    try:
        from app.core.config import settings

        skills_root = Path(settings.SKILLS_DIR).resolve()
    except Exception:  # noqa: BLE001 — settings missing in some test contexts
        return

    try:
        # ``relative_to`` raises ``ValueError`` when *path* is not under
        # *skills_root*; that's the common case (every workspace write).
        resolved_path.relative_to(skills_root)
    except ValueError:
        return
    except Exception as exc:  # noqa: BLE001 — defensive: never fail the caller
        logger.warning(
            "fs_config_watch_check_failed path={} error={}", resolved_path, exc
        )
        return

    try:
        from app.agent.tools.builtin.skill import _discover_skills_cached

        _discover_skills_cached.cache_clear()
        logger.debug("fs_config_watch_skill_cache_cleared path={}", resolved_path)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "fs_config_watch_skill_cache_clear_failed path={} error={}",
            resolved_path,
            exc,
        )
