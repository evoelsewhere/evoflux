from __future__ import annotations

import asyncio
import hashlib
import json
import random
import uuid
from typing import Any, Protocol

import httpx

from app.conductor.models import (
    EffectiveResourceVersion,
    HeartbeatResponse,
    Manifest,
    RegistrationRequest,
    RegistrationResponse,
    ResourceChangePage,
    ResourceInventoryRequest,
    TelemetryBatchResponse,
    canonical_hash,
)
from app.conductor.constants.api import (
    API_BASE_RETRY_DELAY_SECONDS,
    API_DEFAULT_RETRY_ATTEMPTS,
    API_DEFAULT_TIMEOUT_SECONDS,
    API_MAX_RETRY_DELAY_SECONDS,
    API_NOT_MODIFIED_STATUS,
    API_RETRY_JITTER_DIVISOR,
    API_RETRYABLE_STATUS_CODES,
    API_TEXT_FIELD_MAX_LENGTH,
    CONDUCTOR_TOKEN_PREFIX,
    V1_HEARTBEAT_PATH,
    V1_REGISTER_PATH,
    V1_RESOURCE_USAGE_PATH,
    V1_RESOURCE_KINDS,
    V1_SUBSCRIBE_PATH,
    V1_TELEMETRY_PATH,
    V2_CHANGE_PAGE_LIMIT,
    V2_CHANGES_PATH,
    V2_INVENTORY_PATH,
)
from app.conductor.constants.telemetry import (
    TELEMETRY_EVENT_FIELD_ALLOWLIST,
    TELEMETRY_NUMERIC_TOKEN_FIELDS,
    TELEMETRY_MAX_RESOURCE_ATTRIBUTIONS,
    TELEMETRY_RESOURCE_FIELD_ALLOWLIST,
    TELEMETRY_SECRET_FIELD_MARKERS,
    TELEMETRY_SENSITIVE_MARKER_EXCEPTIONS,
    TelemetryBatchField,
    TelemetryField,
    TelemetryResourceField,
)


def redact_telemetry(value: dict[str, Any]) -> dict[str, Any]:
    """Return the small, explicit telemetry allowlist accepted by Conductor."""

    clean: dict[str, Any] = {}
    for key, item in value.items():
        lowered = key.lower()
        sensitive = (
            "token" in lowered and key not in TELEMETRY_NUMERIC_TOKEN_FIELDS
        ) or (
            key not in TELEMETRY_SENSITIVE_MARKER_EXCEPTIONS
            and any(word in lowered for word in TELEMETRY_SECRET_FIELD_MARKERS)
        )
        if key not in TELEMETRY_EVENT_FIELD_ALLOWLIST or sensitive:
            continue
        if key == TelemetryField.RESOURCES:
            clean[key] = _redact_resource_refs(item)
            continue
        if item is None or isinstance(item, (bool, int, float)):
            clean[key] = item
        elif isinstance(item, str):
            clean[key] = item[:API_TEXT_FIELD_MAX_LENGTH]
    return clean


def _redact_resource_refs(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    clean: list[dict[str, str]] = []
    for item in value[:TELEMETRY_MAX_RESOURCE_ATTRIBUTIONS]:
        if not isinstance(item, dict):
            continue
        reference = {
            str(key): raw[:API_TEXT_FIELD_MAX_LENGTH]
            for key, raw in item.items()
            if str(key) in TELEMETRY_RESOURCE_FIELD_ALLOWLIST
            and isinstance(raw, str)
            and raw
        }
        required = {
            TelemetryResourceField.RESOURCE_ID,
            TelemetryResourceField.VERSION_ID,
            TelemetryResourceField.RELATION,
        }
        if all(field in reference for field in required):
            clean.append(reference)
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
        super().__init__(message[:API_TEXT_FIELD_MAX_LENGTH])


class ConductorClient:
    def __init__(
        self,
        base_url: str,
        credential_store: CredentialStoreProtocol,
        *,
        timeout: float = API_DEFAULT_TIMEOUT_SECONDS,
        retries: int = API_DEFAULT_RETRY_ATTEMPTS,
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
        if not token.startswith(CONDUCTOR_TOKEN_PREFIX):
            raise ValueError("Conductor V1 connection tokens must start with evc_.")
        response = await self._request(
            "POST",
            V1_REGISTER_PATH,
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
            V1_HEARTBEAT_PATH,
            headers=self._auth_headers(),
            json={"installation_id": installation_id},
        )
        return HeartbeatResponse.model_validate(response.json())

    async def fetch_manifest(
        self, etag: str | None = None
    ) -> tuple[Manifest | None, str | None]:
        response = await self._request(
            "GET",
            V1_SUBSCRIBE_PATH,
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
        request = ResourceInventoryRequest.model_validate(payload)
        try:
            await self._request(
                "PUT",
                V2_INVENTORY_PATH,
                headers=self._auth_headers(),
                json=request.model_dump(mode="json"),
                idempotent=True,
            )
        except ConductorRequestError as exc:
            if exc.status_code != 404:
                raise

    async def fetch_changes(self, cursor: str | None) -> ResourceChangePage:
        query: dict[str, str | int] = {"limit": V2_CHANGE_PAGE_LIMIT}
        if cursor:
            query["cursor"] = cursor
        params = str(httpx.QueryParams(query))
        response = await self._request(
            "GET",
            f"{V2_CHANGES_PATH}?{params}",
            headers=self._auth_headers(),
        )
        return ResourceChangePage.model_validate(response.json())

    async def fetch_resource_version(
        self, resource_id: str, version_id: str
    ) -> EffectiveResourceVersion:
        response = await self._request(
            "GET",
            f"/api/v1/resources/{resource_id}/versions/{version_id}",
            headers=self._auth_headers(),
        )
        version = EffectiveResourceVersion.model_validate(response.json())
        if version.kind != "plugin":
            payload = json.dumps(
                version.payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
            if len(payload) != version.size:
                raise ValueError("Conductor managed-resource payload size mismatch.")
            if hashlib.sha256(payload).hexdigest() != version.sha256:
                raise ValueError("Conductor managed-resource payload digest mismatch.")
        return version

    async def download_resource_artifact(
        self,
        resource_id: str,
        version_id: str,
        *,
        expected_sha256: str,
        expected_size: int,
    ) -> bytes:
        response = await self._request(
            "GET",
            f"/api/v1/resources/{resource_id}/versions/{version_id}/artifact",
            headers=self._auth_headers(),
        )
        payload = response.content
        if len(payload) != expected_size:
            raise ValueError("Conductor Plugin artifact size mismatch.")
        actual = hashlib.sha256(payload).hexdigest()
        if actual != expected_sha256:
            raise ValueError("Conductor Plugin artifact digest mismatch.")
        return payload

    async def report_telemetry(
        self, installation_id: str, events: list[dict[str, Any]]
    ) -> TelemetryBatchResponse:
        clean_events: list[dict[str, Any]] = []
        for event in events:
            clean = redact_telemetry(event)
            clean.pop(TelemetryField.INSTALLATION_ID, None)
            clean_events.append(clean)
        response = await self._request(
            "POST",
            V1_TELEMETRY_PATH,
            headers=self._auth_headers(),
            json={
                TelemetryBatchField.INSTALLATION_ID: installation_id,
                TelemetryBatchField.EVENTS: clean_events,
            },
        )
        return TelemetryBatchResponse.model_validate(response.json())

    async def report_resource_usage(self, events: list[dict[str, object]]) -> None:
        """Report content-free managed-resource usage events."""

        if not events:
            return
        await self._request(
            "POST",
            V1_RESOURCE_USAGE_PATH,
            headers=self._auth_headers(),
            json={"events": events},
            idempotent=True,
        )

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
                if (
                    allow_not_modified
                    and response.status_code == API_NOT_MODIFIED_STATUS
                ):
                    return response
                if response.status_code not in API_RETRYABLE_STATUS_CODES:
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
            delay = min(
                API_MAX_RETRY_DELAY_SECONDS,
                API_BASE_RETRY_DELAY_SECONDS * (2**attempt),
            )
            await asyncio.sleep(
                delay + random.uniform(0, delay / API_RETRY_JITTER_DIVISOR)
            )
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
        if kind not in V1_RESOURCE_KINDS:
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
