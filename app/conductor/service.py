from __future__ import annotations

import asyncio
import json
import platform
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import httpx
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

from app.agent.mcp.config import load_config
from app.conductor.client import (
    ConductorClient,
    ConductorRequestError,
    CredentialStore,
    CredentialStoreError,
    CredentialStoreProtocol,
)
from app.conductor.constants.telemetry import (
    TELEMETRY_BATCH_SIZE,
    TelemetryCollectionLevel,
    TelemetryField,
)
from app.conductor.models import ReconcileResult, RegistrationRequest
from app.conductor.reconciler import ResourceReconciler
from app.conductor.telemetry import TelemetryOutbox, telemetry_outbox
from app.core.config import settings
from app.core.runtime_settings import (
    ConductorSettings,
    RuntimeSettings,
    load_runtime_settings,
    save_runtime_settings,
)
from app.core.version import VERSION
from app.services import agent_fs


class ConductorStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    enrolled: bool = False
    state: str = "disabled"
    installation_id: str | None = None
    project_id: str | None = None
    project_name: str | None = None
    project_display_name: str | None = None
    project_logo_url: str | None = None
    member_display_name: str | None = None
    member_primary_role: str | None = None
    collection_level: str | None = None
    heartbeat_interval_seconds: float = 60.0
    last_heartbeat_at: datetime | None = None
    last_sync_at: datetime | None = None
    last_success_at: datetime | None = None
    manifest_revision: str | None = None
    etag: str | None = None
    offline: bool = False
    maintenance_required: bool = False
    error: str | None = None
    resources: list[dict[str, Any]] = Field(default_factory=list)


class ConductorService:
    def __init__(
        self,
        credential_store: CredentialStoreProtocol | None = None,
        telemetry_store: TelemetryOutbox | None = None,
    ) -> None:
        self.status = ConductorStatus()
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._sync_lock = asyncio.Lock()
        self._client: ConductorClient | None = None
        self._credential_store = credential_store
        self._reconciler = ResourceReconciler()
        self._telemetry_store = telemetry_store or telemetry_outbox

    def _config(self) -> ConductorSettings:
        return load_runtime_settings().conductor

    def _credentials(self) -> CredentialStoreProtocol:
        if self._credential_store is None:
            self._credential_store = CredentialStore()
        return self._credential_store

    def _legacy_credential_path(self, config: ConductorSettings) -> Path:
        configured = config.machine_credential_path
        if configured:
            path = Path(configured).expanduser()
            return (
                path if path.is_absolute() else Path(settings.EVOFLUX_STATE_DIR) / path
            )
        return Path(settings.EVOFLUX_STATE_DIR) / "conductor" / "credentials.json"

    def _migrate_legacy_credential(self, config: ConductorSettings) -> None:
        credentials = self._credentials()
        if credentials.load() is not None:
            return
        path = self._legacy_credential_path(config)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, ValueError, TypeError):
            logger.warning("conductor_legacy_credential_migration_failed")
            return
        credential = raw.get("credential") if isinstance(raw, dict) else None
        if not isinstance(credential, str) or not credential.startswith("evc_"):
            logger.warning("conductor_legacy_credential_invalid")
            return
        credentials.save(credential)
        path.unlink(missing_ok=True)
        logger.info("conductor_legacy_credential_migrated")

    def _new_client(self, config: ConductorSettings) -> ConductorClient:
        return ConductorClient(
            config.url,
            self._credentials(),
            timeout=config.request_timeout_seconds,
        )

    def _load_status(self, config: ConductorSettings) -> None:
        self.status.enabled = config.enabled
        self.status.installation_id = config.installation_id
        self.status.project_id = config.project_id
        self.status.project_name = config.project_name
        self.status.project_display_name = config.project_display_name
        self.status.project_logo_url = config.project_logo_url
        self.status.member_display_name = config.member_display_name
        self.status.member_primary_role = config.member_primary_role
        self.status.collection_level = config.collection_level
        self.status.heartbeat_interval_seconds = config.heartbeat_interval_seconds

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        config = self._config()
        self._load_status(config)
        try:
            self._migrate_legacy_credential(config)
            self.status.enrolled = (
                self._credentials().load() is not None
                and config.installation_id is not None
            )
        except CredentialStoreError as exc:
            self.status.state = "error"
            self.status.error = str(exc)
            logger.error("conductor_credential_store_unavailable")
            return
        if not config.enabled:
            self.status.state = "disabled"
            return
        if not config.url:
            self.status.state = "error"
            self.status.error = "Conductor URL is not configured."
            return
        if not self.status.enrolled:
            self.status.state = "disconnected"
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="conductor-connection")

    async def stop(self) -> None:
        self._stop.set()
        task, self._task = self._task, None
        if task and task is not asyncio.current_task() and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if self._client:
            await self._client.close()
            self._client = None

    async def restart(self) -> None:
        await self.stop()
        await self.start()

    async def connect(self, token: str) -> ConductorStatus:
        config = self._config()
        if not config.url:
            raise ValueError("Configure the Conductor URL before connecting.")
        installation_key = config.installation_key
        if installation_key is None:
            installation_key = str(uuid.uuid4())
            runtime = load_runtime_settings()
            runtime.conductor.installation_key = installation_key
            save_runtime_settings(runtime)
            config = runtime.conductor
        platform_name, platform_label = _platform_identity()
        client = self._new_client(config)
        try:
            registration = await client.register(
                token,
                RegistrationRequest(
                    installation_key=installation_key,
                    display_name=f"EvoFlux on {platform_label}",
                    platform=platform_name,
                    evoflux_version=VERSION,
                ),
                idempotency_key=str(uuid.uuid4()),
            )
            self._credentials().save(token.strip())
            runtime = load_runtime_settings()
            runtime.conductor.installation_key = installation_key
            runtime.conductor.installation_id = registration.installation.id
            runtime.conductor.project_id = registration.project.id
            runtime.conductor.project_name = registration.project.name
            runtime.conductor.project_display_name = registration.project.display_name
            runtime.conductor.project_logo_url = registration.project.logo_url
            runtime.conductor.member_id = registration.member.id
            runtime.conductor.member_display_name = registration.member.display_name
            runtime.conductor.member_primary_role = registration.member.primary_role
            runtime.conductor.collection_level = registration.policy.collection_level
            runtime.conductor.heartbeat_interval_seconds = float(
                registration.installation.heartbeat_interval_seconds
            )
            try:
                save_runtime_settings(runtime)
            except Exception:
                self._credentials().delete()
                raise
        finally:
            await client.close()

        config = self._config()
        self._load_status(config)
        self.status.enrolled = True
        self.status.state = "connected"
        self.status.error = None
        self.status.offline = False
        await self.restart()
        return self.status

    async def disconnect(self) -> ConductorStatus:
        await self.stop()
        self._credentials().delete()
        self._telemetry_store.clear()
        runtime = self._clear_registration_state()
        self.status = ConductorStatus(
            enabled=runtime.conductor.enabled,
            state="disconnected",
            heartbeat_interval_seconds=runtime.conductor.heartbeat_interval_seconds,
        )
        return self.status

    def _clear_registration_state(self) -> RuntimeSettings:
        runtime = load_runtime_settings()
        runtime.conductor.installation_id = None
        runtime.conductor.project_id = None
        runtime.conductor.project_name = None
        runtime.conductor.project_display_name = None
        runtime.conductor.project_logo_url = None
        runtime.conductor.member_id = None
        runtime.conductor.member_display_name = None
        runtime.conductor.member_primary_role = None
        runtime.conductor.collection_level = None
        save_runtime_settings(runtime)
        return runtime

    async def heartbeat_now(self) -> ConductorStatus:
        config = self._config()
        if not config.enabled:
            self.status.state = "disabled"
            return self.status
        if not config.installation_id or self._credentials().load() is None:
            self.status.enrolled = False
            self.status.state = "disconnected"
            return self.status
        client = self._client
        if client is None or client.base_url != config.url:
            if client:
                await client.close()
            self._client = client = self._new_client(config)
        try:
            heartbeat = await client.heartbeat(config.installation_id)
        except ConductorRequestError as exc:
            self._handle_request_error(exc, heartbeat=True)
            return self.status
        except CredentialStoreError as exc:
            self.status.state = "error"
            self.status.error = str(exc)
            return self.status
        except (httpx.HTTPError, OSError) as exc:
            self.status.offline = True
            self.status.state = "offline"
            self.status.error = f"Conductor is unreachable ({type(exc).__name__})."
            return self.status
        self.status.enrolled = True
        self.status.offline = False
        self.status.error = None
        self.status.state = "connected"
        self.status.last_heartbeat_at = datetime.now(UTC)
        next_interval = float(heartbeat.heartbeat_interval_seconds)
        self.status.heartbeat_interval_seconds = next_interval
        if next_interval != config.heartbeat_interval_seconds:
            runtime = load_runtime_settings()
            runtime.conductor.heartbeat_interval_seconds = next_interval
            save_runtime_settings(runtime)
        return self.status

    def _handle_request_error(
        self, exc: ConductorRequestError, *, heartbeat: bool = False
    ) -> None:
        self.status.offline = False
        self.status.error = str(exc)
        if exc.status_code == 401:
            self.status.state = "authorization_required"
            self._stop.set()
        elif exc.status_code == 403:
            self.status.state = "forbidden"
            self._stop.set()
        elif exc.status_code == 404 and heartbeat:
            self._clear_registration_state()
            self.status.enrolled = False
            self.status.installation_id = None
            self.status.project_id = None
            self.status.project_name = None
            self.status.project_display_name = None
            self.status.project_logo_url = None
            self.status.member_display_name = None
            self.status.member_primary_role = None
            self.status.collection_level = None
            self.status.state = "registration_required"
            self._stop.set()
        else:
            self.status.state = "error"

    async def sync_now(self) -> ConductorStatus:
        async with self._sync_lock:
            config = self._config()
            self.status.enabled = config.enabled
            self.status.last_sync_at = datetime.now(UTC)
            if not config.enabled:
                self.status.state = "disabled"
                return self.status
            if not config.url:
                raise ValueError("Conductor URL is not configured.")
            if self._client is None or self._client.base_url != config.url:
                if self._client:
                    await self._client.close()
                self._client = self._new_client(config)
            try:
                self.status.enrolled = (
                    self._client.credentials.load() is not None
                    and config.installation_id is not None
                )
            except CredentialStoreError as exc:
                self.status.state = "error"
                self.status.error = str(exc)
                return self.status
            if not self.status.enrolled:
                self.status.state = "disconnected"
                return self.status
            self.status.state = "syncing"
            try:
                manifest, etag = await self._client.fetch_manifest(self.status.etag)
                if manifest is None:
                    manifest = self._reconciler.load_last_good_manifest()
                result = (
                    await self._reconciler.reconcile(
                        manifest, enforcement_mode=config.enforcement_mode
                    )
                    if manifest is not None
                    else None
                )
                if manifest is not None:
                    self._reconciler.save_last_good_manifest(manifest)
                await self._report(result)
                self.status.etag = etag
                self.status.offline = False
                self.status.error = None
                self.status.last_success_at = datetime.now(UTC)
                self._set_result(result)
            except ConductorRequestError as exc:
                self._handle_request_error(exc)
            except (httpx.HTTPError, OSError) as exc:
                self.status.offline = True
                self.status.state = "offline"
                self.status.error = f"Conductor is unreachable ({type(exc).__name__})."
                cached = self._reconciler.load_last_good_manifest()
                if cached is not None:
                    result = await self._reconciler.reconcile(
                        cached, enforcement_mode=config.enforcement_mode
                    )
                    self._set_result(result, preserve_state=True)
                logger.warning(
                    "conductor_sync_offline error_type={} cached_manifest={}",
                    type(exc).__name__,
                    cached is not None,
                )
            except Exception as exc:
                self.status.state = "error"
                self.status.error = f"Conductor sync failed ({type(exc).__name__})."
                logger.error(
                    "conductor_sync_failed error_type={}",
                    type(exc).__name__,
                )
            return self.status

    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        next_heartbeat = 0.0
        next_sync = 0.0
        try:
            while not self._stop.is_set():
                now = loop.time()
                config = self._config()
                if now >= next_heartbeat:
                    await self.heartbeat_now()
                    next_heartbeat = now + self.status.heartbeat_interval_seconds
                if self._stop.is_set():
                    break
                if now >= next_sync:
                    await self.sync_now()
                    next_sync = now + config.sync_interval_seconds
                delay = max(0.1, min(next_heartbeat, next_sync) - loop.time())
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=delay)
                except TimeoutError:
                    pass
        except asyncio.CancelledError:
            raise

    async def _report(self, result: ReconcileResult | None) -> None:
        if self._client is None:
            return
        observed = {
            "reported_at": datetime.now(UTC).isoformat(),
            "manifest_revision": result.manifest_revision if result else None,
            "state": result.state if result else "unknown",
            "maintenance_required": result.maintenance_required if result else False,
            "resources": (
                [item.model_dump(mode="json") for item in result.resources]
                if result
                else []
            ),
        }
        await self._client.report_observed_state(observed)
        await self._client.report_inventory(self.inventory())
        await self._flush_telemetry()

    async def _flush_telemetry(self) -> None:
        if self._client is None:
            return
        config = self._config()
        if not config.installation_id or config.collection_level in {
            None,
            TelemetryCollectionLevel.OFF,
        }:
            return
        events = self._telemetry_store.peek(
            config.installation_id,
            limit=TELEMETRY_BATCH_SIZE,
        )
        if not events:
            return
        try:
            await self._client.report_telemetry(config.installation_id, events)
        except (
            ConductorRequestError,
            CredentialStoreError,
            httpx.HTTPError,
            OSError,
        ) as exc:
            logger.warning(
                "conductor_telemetry_flush_deferred error_type={} pending={}",
                type(exc).__name__,
                self._telemetry_store.count(),
            )
            return
        self._telemetry_store.acknowledge(
            {
                event_id
                for event in events
                if isinstance((event_id := event.get(TelemetryField.EVENT_ID)), str)
            }
        )

    def inventory(self) -> dict[str, Any]:
        return {
            "evoflux_version": VERSION,
            "platform": platform.system().lower(),
            "agents_count": len(agent_fs.list_agents()),
            "skills_count": len(agent_fs.list_skills()),
            "mcp_count": len(load_config().servers),
            "last_heartbeat_at": datetime.now(UTC).isoformat(),
        }

    def _set_result(
        self, result: ReconcileResult | None, *, preserve_state: bool = False
    ) -> None:
        if result is None:
            if not preserve_state:
                self.status.state = "idle"
            return
        self.status.manifest_revision = result.manifest_revision
        self.status.maintenance_required = result.maintenance_required
        self.status.resources = [
            item.model_dump(mode="json") for item in result.resources
        ]
        if not preserve_state:
            self.status.state = result.state

    def status_payload(self) -> dict[str, Any]:
        return self.status.model_dump(mode="json")


def _platform_identity() -> tuple[Literal["macos", "linux", "windows"], str]:
    current = platform.system().lower()
    if current == "darwin":
        return "macos", "macOS"
    if current == "windows":
        return "windows", "Windows"
    return "linux", "Linux"


conductor_service = ConductorService()
