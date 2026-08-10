from __future__ import annotations

import asyncio
import random
import uuid
from typing import Any, Protocol

import httpx

from app.conductor.models import (
    HeartbeatResponse,
    Manifest,
    RegistrationRequest,
    RegistrationResponse,
    canonical_hash,
)

_V1_RESOURCE_KINDS = frozenset({"agent", "skill", "mcp"})
_V1_SUBSCRIBE_PATH = "/api/v1/subscribe/resources"
_V1_REGISTER_PATH = "/api/v1/client/register"
_V1_HEARTBEAT_PATH = "/api/v1/client/heartbeat"

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


class CredentialStoreProtocol(Protocol):
    def load(self) -> str | None: ...

    def save(self, credential: str) -> None: ...

    def delete(self) -> None: ...


class CredentialStoreError(RuntimeError):
    """The operating system credential vault could not complete an operation."""


class CredentialStore:
    """Store the Conductor token in the operating system credential vault."""

    _SERVICE = "EvoFlux Conductor"
    _ACCOUNT = "connection-token"

    def load(self) -> str | None:
        try:
            import keyring

            return keyring.get_password(self._SERVICE, self._ACCOUNT)
        except Exception as exc:
            raise CredentialStoreError(
                "The operating system credential vault is unavailable."
            ) from exc

    def save(self, credential: str) -> None:
        try:
            import keyring

            keyring.set_password(self._SERVICE, self._ACCOUNT, credential)
        except Exception as exc:
            raise CredentialStoreError(
                "The Conductor token could not be saved to the operating system credential vault."
            ) from exc

    def delete(self) -> None:
        try:
            import keyring
            from keyring.errors import PasswordDeleteError
        except Exception as exc:
            raise CredentialStoreError(
                "The operating system credential vault is unavailable."
            ) from exc

        try:
            keyring.delete_password(self._SERVICE, self._ACCOUNT)
        except PasswordDeleteError:
            return
        except Exception as exc:
            raise CredentialStoreError(
                "The Conductor token could not be deleted from the operating system credential vault."
            ) from exc


class ConductorRequestError(RuntimeError):
    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        super().__init__(message[:256])


class ConductorClient:
    def __init__(
        self,
        base_url: str,
        credential_store: CredentialStoreProtocol,
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

    async def register(
        self,
        enrollment_token: str,
        request: RegistrationRequest,
        *,
        idempotency_key: str,
    ) -> RegistrationResponse:
        token = enrollment_token.strip()
        if not token.startswith("evc_"):
            raise ValueError("Conductor V1 connection tokens must start with evc_.")
        response = await self._request(
            "POST",
            _V1_REGISTER_PATH,
            headers={
                "Authorization": f"Bearer {token}",
                "Idempotency-Key": idempotency_key,
            },
            json=request.model_dump(mode="json"),
        )
        return RegistrationResponse.model_validate(response.json())

    async def heartbeat(self, installation_id: str) -> HeartbeatResponse:
        response = await self._request(
            "POST",
            _V1_HEARTBEAT_PATH,
            headers=self._auth_headers(),
            json={"installation_id": installation_id},
        )
        return HeartbeatResponse.model_validate(response.json())

    async def fetch_manifest(
        self, etag: str | None = None
    ) -> tuple[Manifest | None, str | None]:
        response = await self._request(
            "GET",
            _V1_SUBSCRIBE_PATH,
            headers=self._auth_headers(),
        )
        manifest = _manifest_from_v1_snapshot(response.json())
        next_etag = f'"v1-{manifest.revision}"'
        if etag == next_etag:
            return None, next_etag
        return manifest, next_etag

    async def report_observed_state(self, payload: dict[str, Any]) -> None:
        # Temporary V1 local compatibility: Conductor has no observed-state API.
        del payload

    async def report_inventory(self, payload: dict[str, Any]) -> None:
        # Temporary V1 local compatibility: inventory sync is not implemented.
        del payload

    async def report_telemetry(self, events: list[dict[str, Any]]) -> None:
        # V1 accepts resource outcome events, not the generic V2 event shape.
        del events

    def _auth_headers(self) -> dict[str, str]:
        loaded = self.credentials.load()
        if loaded is None:
            raise RuntimeError("EvoFlux is not connected to Conductor.")
        return {"Authorization": f"Bearer {loaded}"}

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
                    if response.is_error:
                        raise ConductorRequestError(
                            response.status_code, _safe_error_message(response)
                        )
                    return response
                if attempt == self.retries:
                    raise ConductorRequestError(
                        response.status_code, _safe_error_message(response)
                    )
            except (httpx.TimeoutException, httpx.NetworkError):
                if attempt == self.retries:
                    raise
            delay = min(8.0, 0.25 * (2**attempt))
            await asyncio.sleep(delay + random.uniform(0, delay / 4))
        raise RuntimeError("Conductor request exhausted retries.")


def _safe_error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        message = payload.get("error") or payload.get("detail")
        if isinstance(message, str) and message:
            return message
    return f"Conductor returned HTTP {response.status_code}."


def _manifest_from_v1_snapshot(payload: Any) -> Manifest:
    """Translate Conductor's V1 ManagedResource list into an EvoFlux manifest."""

    if not isinstance(payload, list):
        raise ValueError("Conductor V1 resource snapshot must be a JSON array.")

    resources: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("Conductor V1 resource entries must be JSON objects.")
        kind = item.get("kind")
        if kind not in _V1_RESOURCE_KINDS:
            continue
        resource_payload = item.get("payload")
        if not isinstance(resource_payload, dict):
            raise ValueError(
                f"Conductor V1 {kind} resource payload must be a JSON object."
            )
        dependencies = resource_payload.get("dependencies", [])
        resources.append(
            {
                "kind": kind,
                "slug": item.get("slug"),
                "revision": item.get("version", "1"),
                "payload": resource_payload,
                "dependencies": dependencies,
            }
        )

    resources.sort(key=lambda item: (str(item["kind"]), str(item["slug"])))
    return Manifest.model_validate(
        {
            "schema_version": 1,
            "revision": canonical_hash(resources),
            "resources": resources,
        }
    )
