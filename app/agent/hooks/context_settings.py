"""Read the operator's context-window overrides without letting them break a run.

Every hook that has a tunable constant resolves it through here rather than
loading ``settings.yaml`` itself. Two reasons: a malformed file must degrade
to built-in defaults instead of disabling compaction or offloading, and the
resolution rule ("``None`` means use the default") then lives in one place.
"""

from __future__ import annotations

from app.core.runtime_settings import ContextSettings

_FALLBACK = ContextSettings()


def context_settings() -> ContextSettings:
    """Current overrides, or built-in defaults if the file cannot be read."""
    from app.core.runtime_settings import load_runtime_settings

    try:
        return load_runtime_settings().context
    except (ValueError, OSError):
        return _FALLBACK


def resolve(field: str, default: int) -> int:
    """Return the override for *field*, or *default* when it is unset.

    ``0`` is a meaningful value for some fields (``keep_recent_turns``), so
    this tests for ``None`` rather than falsiness.
    """
    value = getattr(context_settings(), field, None)
    return default if value is None else int(value)


__all__ = ["context_settings", "resolve"]
