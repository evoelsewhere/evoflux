from __future__ import annotations

import asyncio
import json
import os
import random
import tempfile
import uuid
from pathlib import Path
from typing import Any

import httpx

from app.conductor.models import EnrollmentResponse, Manifest

_SAFE_EVENT_FIELDS = frozenset(
    {
        "event",
        "kind",
        "resource_kind",
        "resource_slug",
        "revision",
        "state",
        "category",
        "duration_ms",
        "tokens_in",
        "tokens_out",
        "tool_calls",
        "active_agents",
        "machine_id",
        "evoflux_version",
        "platform",
        "agents_count",
        "skills_count",
        "mcp_count",
        "last_heartbeat_at",
        "reported_at",
    }
)
_SECRET_WORDS = (
    "secret",
    "password",
    "authorization",
    "cookie",
    "credential",
    "prompt",
    "response",
    "code",
    "argument",
    "result",
)


def redact_telemetry(value: dict[str, Any]) -> dict[str, Any]:
    """Return the small, explicit telemetry allowlist accepted by Conductor."""

    clean: dict[str, Any] = {}
    for key, item in value.items():
        lowered = key.lower()
        sensitive = (
            "token" in lowered and key not in {"tokens_in", "tokens_out"}
        ) or any(word in lowered for word in _SECRET_WORDS)
        if key not in _SAFE_EVENT_FIELDS or sensitive:
            continue
        if item is None or isinstance(item, (bool, int, float)):
            clean[key] = item
        elif isinstance(item, str):
            clean[key] = item[:256]
    return clean


class CredentialStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> tuple[str, str] | None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        if not isinstance(raw, dict):
            raise ValueError("Machine credential file must contain a JSON object.")
        machine_id = raw.get("machine_id")
        credential = raw.get("credential")
        if not isinstance(machine_id, str) or not isinstance(credential, str):
            raise ValueError("Machine credential file is incomplete.")
        return machine_id, credential

    def save(self, machine_id: str, credential: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent
        )
        temporary = Path(name)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(
                    {"version": 1, "machine_id": machine_id, "credential": credential},
                    handle,
                )
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            self.path.chmod(0o600)
        finally:
            temporary.unlink(missing_ok=True)


class ConductorClient:
    def __init__(
        self,
        base_url: str,
        credential_store: CredentialStore,
        *,
        timeout: float = 15.0,
        retries: int = 3,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.credentials = credential_store
        self.retries = retries
        self._http = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(timeout),
            follow_redirects=False,
            transport=transport,
        )

    async def close(self) -> None:
        await self._http.aclose()

    async def enroll(
        self, enrollment_token: str, inventory: dict[str, Any]
    ) -> EnrollmentResponse:
        response = await self._request(
            "POST",
            "/api/v2/enroll",
            headers={"Authorization": f"Bearer {enrollment_token}"},
            json={"inventory": inventory},
            idempotent=True,
        )
        enrolled = EnrollmentResponse.model_validate(response.json())
        self.credentials.save(enrolled.machine_id, enrolled.credential())
        return enrolled

    async def fetch_manifest(
        self, etag: str | None = None
    ) -> tuple[Manifest | None, str | None]:
        headers = self._auth_headers()
        if etag:
            headers["If-None-Match"] = etag
        response = await self._request(
            "GET", "/api/v2/manifest", headers=headers, allow_not_modified=True
        )
        if response.status_code == 304:
            return None, etag
        return Manifest.model_validate(response.json()), response.headers.get("etag")

    async def report_observed_state(self, payload: dict[str, Any]) -> None:
        await self._request(
            "POST",
            "/api/v2/observed-state",
            headers=self._auth_headers(),
            json=payload,
            idempotent=True,
        )

    async def report_inventory(self, payload: dict[str, Any]) -> None:
        await self._request(
            "PUT",
            "/api/v2/inventory",
            headers=self._auth_headers(),
            json=redact_telemetry(payload),
            idempotent=True,
        )

    async def report_telemetry(self, events: list[dict[str, Any]]) -> None:
        safe = [redact_telemetry(event) for event in events]
        safe = [event for event in safe if event]
        if not safe:
            return
        await self._request(
            "POST",
            "/api/v2/telemetry",
            headers=self._auth_headers(),
            json={"events": safe},
            idempotent=True,
        )

    def _auth_headers(self) -> dict[str, str]:
        loaded = self.credentials.load()
        if loaded is None:
            raise RuntimeError("EvoFlux is not enrolled with Conductor.")
        machine_id, credential = loaded
        return {
            "Authorization": f"Bearer {credential}",
            "X-EvoFlux-Machine-ID": machine_id,
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        json: Any = None,
        idempotent: bool = False,
        allow_not_modified: bool = False,
    ) -> httpx.Response:
        request_headers = dict(headers or {})
        if idempotent:
            request_headers["Idempotency-Key"] = str(uuid.uuid4())
        for attempt in range(self.retries + 1):
            try:
                response = await self._http.request(
                    method, path, headers=request_headers, json=json
                )
                if allow_not_modified and response.status_code == 304:
                    return response
                if response.status_code not in {408, 425, 429, 500, 502, 503, 504}:
                    response.raise_for_status()
                    return response
                if attempt == self.retries:
                    response.raise_for_status()
            except (httpx.TimeoutException, httpx.NetworkError):
                if attempt == self.retries:
                    raise
            delay = min(8.0, 0.25 * (2**attempt))
            await asyncio.sleep(delay + random.uniform(0, delay / 4))
        raise RuntimeError("Conductor request exhausted retries.")
