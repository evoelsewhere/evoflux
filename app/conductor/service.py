from __future__ import annotations

import asyncio
import platform
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

from app.agent.mcp.config import load_config
from app.conductor.client import ConductorClient, CredentialStore
from app.conductor.models import ReconcileResult
from app.conductor.reconciler import ResourceReconciler
from app.core.config import settings
from app.core.runtime_settings import ConductorSettings, load_runtime_settings
from app.core.version import VERSION
from app.services import agent_fs


class ConductorStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    enrolled: bool = False
    state: str = "disabled"
    last_sync_at: datetime | None = None
    last_success_at: datetime | None = None
    manifest_revision: str | None = None
    etag: str | None = None
    offline: bool = False
    maintenance_required: bool = False
    error: str | None = None
    resources: list[dict[str, Any]] = Field(default_factory=list)


class ConductorService:
    def __init__(self) -> None:
        self.status = ConductorStatus()
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._sync_lock = asyncio.Lock()
        self._client: ConductorClient | None = None
        self._reconciler = ResourceReconciler()

    def _config(self) -> ConductorSettings:
        return load_runtime_settings().conductor

    def _credential_path(self, config: ConductorSettings) -> Path:
        configured = config.machine_credential_path
        if configured:
            path = Path(configured).expanduser()
            return (
                path if path.is_absolute() else Path(settings.EVOFLUX_STATE_DIR) / path
            )
        return Path(settings.EVOFLUX_STATE_DIR) / "conductor" / "credentials.json"

    def _new_client(self, config: ConductorSettings) -> ConductorClient:
        return ConductorClient(
            config.url,
            CredentialStore(self._credential_path(config)),
            timeout=config.request_timeout_seconds,
        )

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        config = self._config()
        self.status.enabled = config.enabled
        self.status.enrolled = (
            CredentialStore(self._credential_path(config)).load() is not None
        )
        if not config.enabled:
            self.status.state = "disabled"
            return
        if not config.url:
            self.status.state = "error"
            self.status.error = "Conductor URL is not configured."
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="conductor-sync")

    async def stop(self) -> None:
        self._stop.set()
        task, self._task = self._task, None
        if task and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if self._client:
            await self._client.close()
            self._client = None

    async def restart(self) -> None:
        await self.stop()
        await self.start()

    async def enroll(self, token: str) -> ConductorStatus:
        config = self._config()
        if not config.url:
            raise ValueError("Configure the Conductor URL before enrollment.")
        client = self._new_client(config)
        try:
            await client.enroll(token, self.inventory())
        finally:
            await client.close()
        self.status.enrolled = True
        await self.restart()
        if config.enabled:
            await self.sync_now()
        return self.status

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
            self.status.enrolled = self._client.credentials.load() is not None
            if not self.status.enrolled:
                self.status.state = "unenrolled"
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
            except (httpx.HTTPError, OSError) as exc:
                self.status.offline = True
                self.status.state = "offline"
                self.status.error = f"{type(exc).__name__}: {exc}"
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
                self.status.error = f"{type(exc).__name__}: {exc}"
                logger.error(
                    "conductor_sync_failed error_type={} message={}",
                    type(exc).__name__,
                    str(exc)[:256],
                )
            return self.status

    async def _run(self) -> None:
        try:
            while not self._stop.is_set():
                await self.sync_now()
                interval = self._config().sync_interval_seconds
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=interval)
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


conductor_service = ConductorService()
