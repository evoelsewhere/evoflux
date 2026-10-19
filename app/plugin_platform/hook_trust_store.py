"""Atomic, digest-bound approvals for executable lifecycle hooks."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from threading import RLock
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.config import settings


class HookTrustGrant(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    owner_type: Literal["plugin", "settings"]
    owner_id: str = Field(min_length=1, max_length=128)
    hook_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    digest: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    isolation_profile: str = Field(min_length=1, max_length=128)


class _HookTrustDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    grants: list[HookTrustGrant] = Field(default_factory=list)


class HookTrustStore:
    """Persists reviewed hook digests outside plugin installs and Settings."""

    _lock = RLock()

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = (
            Path(path)
            if path is not None
            else Path(settings.EVOFLUX_DATA_DIR) / "plugin_platform" / "hook-trust.json"
        )

    def grants(self) -> tuple[HookTrustGrant, ...]:
        with self._lock:
            if not self.path.exists():
                return ()
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                document = _HookTrustDocument.model_validate(raw)
            except (OSError, UnicodeError, json.JSONDecodeError, ValidationError):
                # Corrupt approvals never authorize execution.
                return ()
            return tuple(document.grants)

    def is_trusted(
        self,
        *,
        owner_type: Literal["plugin", "settings"],
        owner_id: str,
        hook_id: str,
        digest: str,
        isolation_profile: str,
    ) -> bool:
        candidate = HookTrustGrant(
            owner_type=owner_type,
            owner_id=owner_id,
            hook_id=hook_id,
            digest=digest,
            isolation_profile=isolation_profile,
        )
        return candidate in self.grants()

    def approve(self, grant: HookTrustGrant) -> None:
        with self._lock:
            existing = set(self.grants())
            existing.add(grant)
            self._write(tuple(sorted(existing, key=self._sort_key)))

    def revoke(
        self,
        *,
        owner_type: Literal["plugin", "settings"],
        owner_id: str,
        hook_id: str,
    ) -> None:
        with self._lock:
            remaining = tuple(
                item
                for item in self.grants()
                if (item.owner_type, item.owner_id, item.hook_id)
                != (owner_type, owner_id, hook_id)
            )
            self._write(remaining)

    @staticmethod
    def _sort_key(grant: HookTrustGrant) -> tuple[str, str, str, str, str]:
        return (
            grant.owner_type,
            grant.owner_id,
            grant.hook_id,
            grant.digest,
            grant.isolation_profile,
        )

    def _write(self, grants: tuple[HookTrustGrant, ...]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = _HookTrustDocument(grants=list(grants)).model_dump_json(indent=2)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temp_path = Path(handle.name)
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self.path)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)


__all__ = ["HookTrustGrant", "HookTrustStore"]
