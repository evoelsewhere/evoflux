"""Shared in-process metadata for the repository-backed EASD projection."""

from __future__ import annotations

from typing import Any
from uuid import UUID

RUN_HASHES: dict[UUID, str] = {}
RUN_GENERATIONS: dict[UUID, int] = {}
RUN_MISSIONS: dict[UUID, list[dict[str, Any]]] = {}


def update_run_state(run_id: str | UUID, payload: dict[str, Any]) -> None:
    normalized = UUID(str(run_id))
    RUN_HASHES[normalized] = str(payload.get("document_hash") or "")
    RUN_GENERATIONS[normalized] = int(payload.get("store_generation") or 0)


__all__ = ["RUN_GENERATIONS", "RUN_HASHES", "RUN_MISSIONS", "update_run_state"]
