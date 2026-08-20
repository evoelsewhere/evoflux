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
from pydantic import BaseModel, ConfigDict, Field, ValidationError

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
    TELEMETRY_DRAIN_MAX_BATCHES,
    TELEMETRY_FLUSH_INTERVAL_SECONDS,
    TelemetryCollectionLevel,
    TelemetryField,
)
from app.conductor.models import (
    ManagedResourceRecord,
    ReconcileResult,
    RegistrationRequest,
    TelemetryDeliverySummary,
)
from app.conductor.provenance import managed_resource_provider_from_record
from app.conductor.governed_reconciler import GovernedResourceReconciler
from app.conductor.reconciler import ResourceReconciler
from app.conductor.telemetry import (
    TelemetryOutbox,
    clear_usage,
    flush_usage,
    telemetry_outbox,
)
from app.core.config import settings
from app.core.runtime_settings import (
    ConductorSettings,
    RuntimeSettings,
    load_runtime_settings,
    save_runtime_settings,
)
from app.core.version import VERSION
from app.services import agent_fs


class ConductorSyncLaneStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: Literal["idle", "syncing", "healthy", "offline", "paused", "error"] = "idle"
    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    error: str | None = None


class ConductorSyncReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    heartbeat: ConductorSyncLaneStatus = Field(default_factory=ConductorSyncLaneStatus)
    resources: ConductorSyncLaneStatus = Field(default_factory=ConductorSyncLaneStatus)
    inventory: ConductorSyncLaneStatus = Field(default_factory=ConductorSyncLaneStatus)
    telemetry: ConductorSyncLaneStatus = Field(default_factory=ConductorSyncLaneStatus)


class ConductorTelemetryReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pending_events: int = 0
    capacity: int = 0
    utilization_percent: float = 0.0
    oldest_event_at: str | None = None
    pending_requests: int = 0
    pending_model_calls: int = 0
    pending_tool_calls: int = 0
    attributed_events: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cache_read_tokens: int = 0
    estimated_cost_usd_micros: int = 0
    last_flush_accepted: int = 0
    last_flush_duplicates: int = 0
    delivery: TelemetryDeliverySummary | None = None


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
    sync: ConductorSyncReport = Field(default_factory=ConductorSyncReport)
    telemetry: ConductorTelemetryReport = Field(
        default_factory=ConductorTelemetryReport
    )


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
        self._usage_flush_lock = asyncio.Lock()
        self._client: ConductorClient | None = None
        self._credential_store = credential_store
        self._reconciler = ResourceReconciler()
        self._governed_reconciler = GovernedResourceReconciler()
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
            previous_project_id = load_runtime_settings().conductor.project_id
            if previous_project_id and previous_project_id != registration.project.id:
                self._governed_reconciler.deactivate_project(previous_project_id)
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
        current_project_id = self._config().project_id
        if current_project_id:
            self._governed_reconciler.deactivate_project(current_project_id)
        self._credentials().delete()
        self._telemetry_store.clear()
        clear_usage()
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
        lane = self.status.sync.heartbeat
        lane.last_attempt_at = datetime.now(UTC)
        lane.state = "syncing"
        if not config.enabled:
            self.status.state = "disabled"
            lane.state = "paused"
            return self.status
        if not config.installation_id or self._credentials().load() is None:
            self.status.enrolled = False
            self.status.state = "disconnected"
            lane.state = "paused"
            return self.status
        client = self._client
        if client is None or client.base_url != config.url:
            if client:
                await client.close()
            self._client = client = self._new_client(config)
        try:
            heartbeat = await client.heartbeat(config.installation_id)
        except ConductorRequestError as exc:
            lane.state = "error"
            lane.error = str(exc)
            self._handle_request_error(exc, heartbeat=True)
            return self.status
        except CredentialStoreError as exc:
            self.status.state = "error"
            self.status.error = str(exc)
            lane.state = "error"
            lane.error = str(exc)
            return self.status
        except (httpx.HTTPError, OSError) as exc:
            self.status.offline = True
            self.status.state = "offline"
            self.status.error = f"Conductor is unreachable ({type(exc).__name__})."
            lane.state = "offline"
            lane.error = self.status.error
            return self.status
        self.status.enrolled = True
        self.status.offline = False
        self.status.error = None
        self.status.state = "connected"
        self.status.last_heartbeat_at = datetime.now(UTC)
        lane.state = "healthy"
        lane.error = None
        lane.last_success_at = self.status.last_heartbeat_at
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
            resource_lane = self.status.sync.resources
            resource_lane.state = "syncing"
            resource_lane.last_attempt_at = self.status.last_sync_at
            resource_lane.error = None
            await self._flush_usage_queues()
            try:
                if await self._sync_governed(config):
                    self.status.etag = None
                    self.status.offline = False
                    self.status.error = None
                    self.status.last_success_at = datetime.now(UTC)
                    resource_lane.state = "healthy"
                    resource_lane.last_success_at = self.status.last_success_at
                    return self.status
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
                resource_lane.state = "healthy"
                resource_lane.last_success_at = self.status.last_success_at
                self._set_result(result)
            except ConductorRequestError as exc:
                resource_lane.state = "error"
                resource_lane.error = str(exc)
                self._handle_request_error(exc)
            except (httpx.HTTPError, OSError) as exc:
                self.status.offline = True
                self.status.state = "offline"
                self.status.error = f"Conductor is unreachable ({type(exc).__name__})."
                resource_lane.state = "offline"
                resource_lane.error = self.status.error
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
                resource_lane.state = "error"
                resource_lane.error = self.status.error
                logger.error(
                    "conductor_sync_failed error_type={}",
                    type(exc).__name__,
                )
            return self.status

    async def _sync_governed(self, config: ConductorSettings) -> bool:
        """Prefer schema-v2 changes; return False only for a V1-only server/client."""

        if self._client is None or not hasattr(self._client, "fetch_changes"):
            return False
        project_id = config.project_id
        installation_id = config.installation_id
        if not project_id or not installation_id:
            return False
        document = self._governed_reconciler.store.replace_project(project_id)
        cursor = document.committed_cursor
        if cursor is not None and self._governed_reconciler.needs_change_replay(
            project_id
        ):
            logger.info("conductor_change_replay_required project_id={}", project_id)
            self._governed_reconciler.store.clear_cursor(project_id)
            cursor = None
        recovered_rejected_cursor = False
        results = []
        for _ in range(100):
            try:
                page = await self._client.fetch_changes(cursor)
            except ConductorRequestError as exc:
                if exc.status_code == 404:
                    return False
                if (
                    cursor is not None
                    and exc.status_code == httpx.codes.BAD_REQUEST
                    and not recovered_rejected_cursor
                ):
                    logger.warning(
                        "conductor_change_cursor_rejected project_id={}", project_id
                    )
                    self._governed_reconciler.store.clear_cursor(project_id)
                    cursor = None
                    recovered_rejected_cursor = True
                    continue
                raise
            page_results = await self._governed_reconciler.reconcile_page(
                self._client,
                page,
                expected_project_id=project_id,
                enforcement_mode=config.enforcement_mode,
            )
            results.extend(page_results)
            if any(item.observed_state == "error" for item in page_results):
                cursor = self._governed_reconciler.store.load().committed_cursor
                break
            cursor = page.next_cursor
            if not page.has_more:
                break
        else:
            raise RuntimeError("Conductor change feed exceeded 100 pages in one sync.")

        inventory_lane = self.status.sync.inventory
        inventory_lane.state = "syncing"
        inventory_lane.last_attempt_at = datetime.now(UTC)
        try:
            await self._client.report_inventory(
                {
                    "installation_id": installation_id,
                    "items": self._governed_reconciler.inventory(),
                }
            )
        except Exception as exc:
            inventory_lane.state = "error"
            inventory_lane.error = _safe_sync_error(exc)
            raise
        inventory_lane.state = "healthy"
        inventory_lane.error = None
        inventory_lane.last_success_at = datetime.now(UTC)
        current = self._governed_reconciler.store.load().resources
        self.status.manifest_revision = cursor
        self._refresh_governed_status(current)
        self.status.maintenance_required = False
        states = {item.observed_state for item in current}
        if "error" in states:
            self.status.state = "error"
        elif states & {"trust_pending", "update_pending", "ownership_conflict"}:
            self.status.state = "update_pending"
        elif results:
            self.status.state = "applied"
        else:
            self.status.state = "in_sync"
        return True

    def approve_governed_plugin(self, resource_id: str) -> dict[str, Any]:
        config = self._config()
        if not config.project_id:
            raise ValueError("EvoFlux is not connected to a Conductor project.")
        record = self._governed_reconciler.approve_plugin(
            config.project_id, resource_id
        )
        self._refresh_governed_status()
        return self._governed_resource_payload(record)

    async def pull_governed_resource(self, resource_id: str) -> dict[str, Any]:
        async with self._sync_lock:
            config = self._config()
            if (
                not config.enabled
                or not config.project_id
                or not config.installation_id
            ):
                raise ValueError("EvoFlux is not connected to a Conductor project.")
            if self._client is None or self._client.base_url != config.url:
                if self._client:
                    await self._client.close()
                self._client = self._new_client(config)
            record = await self._governed_reconciler.pull(
                self._client,
                config.project_id,
                resource_id,
            )
            await self._client.report_inventory(
                {
                    "installation_id": config.installation_id,
                    "items": self._governed_reconciler.inventory(),
                }
            )
            self._refresh_governed_status()
            self.status.last_sync_at = datetime.now(UTC)
            self.status.last_success_at = self.status.last_sync_at
            self.status.state = (
                "update_pending"
                if record.observed_state in {"trust_pending", "update_pending"}
                else record.observed_state
            )
            return self._governed_resource_payload(record)

    def _governed_resource_payload(
        self, record: ManagedResourceRecord
    ) -> dict[str, Any]:
        project_name = (
            self.status.project_display_name
            or self.status.project_name
            or record.project_id
        )
        provider = managed_resource_provider_from_record(record, project_name)
        return {
            **record.model_dump(mode="json"),
            **provider.model_dump(mode="json"),
        }

    def _refresh_governed_status(
        self, resources: list[ManagedResourceRecord] | None = None
    ) -> None:
        current = resources
        if current is None:
            current = self._governed_reconciler.store.load().resources
        self.status.resources = [
            self._governed_resource_payload(item) for item in current
        ]

    async def _run(self) -> None:
        try:
            async with asyncio.TaskGroup() as group:
                group.create_task(
                    self._connection_loop(), name="conductor-control-plane"
                )
                group.create_task(
                    self._telemetry_loop(), name="conductor-telemetry-drain"
                )
        except asyncio.CancelledError:
            raise

    async def _connection_loop(self) -> None:
        loop = asyncio.get_running_loop()
        next_heartbeat = 0.0
        next_sync = 0.0
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

    async def _telemetry_loop(self) -> None:
        while not self._stop.is_set():
            config = self._config()
            if (
                config.enabled
                and config.installation_id
                and self._client is not None
                and self.status.enrolled
            ):
                await self._flush_usage_queues()
            try:
                await asyncio.wait_for(
                    self._stop.wait(), timeout=TELEMETRY_FLUSH_INTERVAL_SECONDS
                )
            except TimeoutError:
                pass

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
        config = self._config()
        if config.installation_id:
            inventory_lane = self.status.sync.inventory
            inventory_lane.state = "syncing"
            inventory_lane.last_attempt_at = datetime.now(UTC)
            try:
                await self._client.report_inventory(
                    {"installation_id": config.installation_id, "items": []}
                )
            except Exception as exc:
                inventory_lane.state = "error"
                inventory_lane.error = _safe_sync_error(exc)
                raise
            inventory_lane.state = "healthy"
            inventory_lane.error = None
            inventory_lane.last_success_at = datetime.now(UTC)
        await self._flush_usage_queues()

    async def _flush_usage_queues(self) -> None:
        async with self._usage_flush_lock:
            await self._flush_telemetry_unlocked()
            await self._flush_skill_usage()

    async def _flush_skill_usage(self) -> None:
        if self._client is None:
            return
        try:
            await flush_usage(self._client)
        except (
            ConductorRequestError,
            CredentialStoreError,
            httpx.HTTPError,
            OSError,
        ) as exc:
            logger.warning(
                "conductor_skill_usage_flush_deferred error_type={}",
                type(exc).__name__,
            )

    async def _flush_telemetry(self) -> None:
        async with self._usage_flush_lock:
            await self._flush_telemetry_unlocked()

    async def _flush_telemetry_unlocked(self) -> None:
        if self._client is None:
            return
        config = self._config()
        if not config.installation_id or config.collection_level in {
            None,
            TelemetryCollectionLevel.OFF,
        }:
            self.status.sync.telemetry.state = "paused"
            return
        lane = self.status.sync.telemetry
        accepted_total = 0
        duplicates_total = 0
        for batch_index in range(TELEMETRY_DRAIN_MAX_BATCHES + 1):
            events = self._telemetry_store.peek(
                config.installation_id,
                limit=TELEMETRY_BATCH_SIZE,
            )
            if events and batch_index == TELEMETRY_DRAIN_MAX_BATCHES:
                break
            lane.state = "syncing"
            lane.last_attempt_at = datetime.now(UTC)
            try:
                response = await self._client.report_telemetry(
                    config.installation_id, events
                )
            except ConductorRequestError as exc:
                if not events and exc.status_code == 400:
                    # Older Conductor releases rejected empty batches. Keep the
                    # delivery lane healthy during a rolling upgrade; the
                    # authoritative summary appears after the server upgrades.
                    lane.state = "healthy"
                    lane.error = None
                    lane.last_success_at = datetime.now(UTC)
                    break
                lane.state = "error"
                lane.error = _safe_sync_error(exc)
                logger.warning(
                    "conductor_telemetry_flush_deferred error_type={} pending={}",
                    type(exc).__name__,
                    self._telemetry_store.count(),
                )
                break
            except (
                CredentialStoreError,
                httpx.HTTPError,
                json.JSONDecodeError,
                OSError,
                ValidationError,
            ) as exc:
                lane.state = (
                    "offline"
                    if isinstance(exc, (httpx.HTTPError, OSError))
                    else "error"
                )
                lane.error = _safe_sync_error(exc)
                logger.warning(
                    "conductor_telemetry_flush_deferred error_type={} pending={}",
                    type(exc).__name__,
                    self._telemetry_store.count(),
                )
                break
            if response.accepted + response.duplicates != len(events):
                lane.state = "error"
                lane.error = "Conductor acknowledged an incomplete telemetry batch."
                logger.warning(
                    "conductor_telemetry_partial_ack submitted={} accepted={} duplicates={}",
                    len(events),
                    response.accepted,
                    response.duplicates,
                )
                break
            if response.summary is not None:
                self.status.telemetry.delivery = response.summary
            self._telemetry_store.acknowledge(
                {
                    event_id
                    for event in events
                    if isinstance((event_id := event.get(TelemetryField.EVENT_ID)), str)
                }
            )
            accepted_total += response.accepted
            duplicates_total += response.duplicates
            lane.state = "healthy"
            lane.error = None
            lane.last_success_at = datetime.now(UTC)
            if not events:
                break
        if accepted_total or duplicates_total:
            self.status.telemetry.last_flush_accepted = accepted_total
            self.status.telemetry.last_flush_duplicates = duplicates_total

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
        config = self._config()
        stats = self._telemetry_store.stats(config.installation_id)
        self.status.telemetry = self.status.telemetry.model_copy(update=stats)
        return self.status.model_dump(mode="json")


def _platform_identity() -> tuple[Literal["macos", "linux", "windows"], str]:
    current = platform.system().lower()
    if current == "darwin":
        return "macos", "macOS"
    if current == "windows":
        return "windows", "Windows"
    return "linux", "Linux"


def _safe_sync_error(exc: Exception) -> str:
    if isinstance(exc, ConductorRequestError):
        return str(exc)
    return f"Sync failed ({type(exc).__name__})."


conductor_service = ConductorService()
