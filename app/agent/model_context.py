"""Markers for hidden, durable model-only context messages."""

from __future__ import annotations

from typing import Any

MODEL_CONTEXT_KEY = "evoflux_model_context"
MODEL_CONTEXT_FOR_KEY = "evoflux_model_context_for"
MEMORY_RECALL_CONTEXT_KIND = "memory_recall"
PREFIX_SNAPSHOT_FROZEN_KEY = "_prefix_snapshot_frozen"
PREFIX_SNAPSHOT_DIRTY_KEY = "_prefix_snapshot_dirty"
PREFIX_SNAPSHOT_PROFILE_KEY = "_prefix_snapshot_profile_key"


def is_durable_model_context(message: Any) -> bool:
    """Return whether *message* is a hidden synthetic context row to persist."""
    extra = getattr(message, "extra", None)
    return (
        getattr(message, "role", None) == "user"
        and isinstance(extra, dict)
        and extra.get("hidden_from_user") is True
        and extra.get(MODEL_CONTEXT_KEY) == MEMORY_RECALL_CONTEXT_KIND
        and isinstance(extra.get(MODEL_CONTEXT_FOR_KEY), str)
        and bool(extra[MODEL_CONTEXT_FOR_KEY])
    )


__all__ = [
    "MEMORY_RECALL_CONTEXT_KIND",
    "MODEL_CONTEXT_FOR_KEY",
    "MODEL_CONTEXT_KEY",
    "PREFIX_SNAPSHOT_DIRTY_KEY",
    "PREFIX_SNAPSHOT_FROZEN_KEY",
    "PREFIX_SNAPSHOT_PROFILE_KEY",
    "is_durable_model_context",
]
