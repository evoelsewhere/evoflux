"""Durable lifecycle orchestration for Artifact Fabric."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Literal, cast
from uuid import UUID

from loguru import logger
from sqlmodel import col, select

from app.artifacts.domain import ArtifactDriverContext, ArtifactFormat
from app.artifacts.registry import ArtifactDriverRegistry, build_default_registry
from app.artifacts.storage import ArtifactStore
from app.core.db import DbFactory, resolve_db_factory, sqlite_write_guard
from app.models.artifact import ArtifactJob, ArtifactReview, ArtifactRevision

RunAction = Literal["inspect", "validate", "preview"]
_TERMINAL = {"completed", "review_ready", "published", "failed", "cancelled"}


class ArtifactService:
    """Own jobs, immutable revisions, QA evidence, and exact-byte publish."""

    def __init__(
        self,
        *,
        db_factory: DbFactory | None = None,
        store: ArtifactStore | None = None,
        registry: ArtifactDriverRegistry | None = None,
    ) -> None:
        self.db_factory = resolve_db_factory(db_factory)
        self.store = store or ArtifactStore()
        self.registry = registry or build_default_registry()
        self._active_tasks: dict[UUID, asyncio.Task[Any]] = {}

    def catalog(self, artifact_format: ArtifactFormat | None = None) -> dict[str, Any]:
        catalog = self.registry.catalog()
        if artifact_format is None:
            return catalog
        driver = self.registry.get(artifact_format)
        return {
            "schema_version": catalog["schema_version"],
            "workflow": catalog["workflow"],
            "actions": catalog["actions"],
            "invariants": catalog["invariants"],
            "format": artifact_format,
            "driver": {
                **driver.catalog(),
                "extension": driver.extension,
                "media_type": driver.media_type,
                "driver_version": driver.version,
                "protocol_version": driver.protocol_version,
            },
        }

    async def execute(
        self,
        *,
        action: RunAction,
        artifact_format: ArtifactFormat,
        workspace_root: Path,
        project_path: Path | None = None,
        source_path: Path | None = None,
        manifest_path: Path | None = None,
        inspect_job_id: UUID | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        driver = self.registry.get(artifact_format)
        lane = _lane(artifact_format, source_path)
        job = ArtifactJob(
            session_id=_session_uuid(session_id),
            artifact_format=artifact_format,
            lane=lane,
            action=action,
            status="running",
            workspace_root=str(workspace_root.resolve()),
            request_data={
                "project_path": str(project_path) if project_path else None,
                "source_path": str(source_path) if source_path else None,
                "manifest_path": str(manifest_path) if manifest_path else None,
                "inspect_job_id": str(inspect_job_id) if inspect_job_id else None,
            },
        )
        await self._insert_job(job)
        current_task = asyncio.current_task()
        if current_task is not None:
            self._active_tasks[job.id] = current_task
        work_dir = self.store.root / "work" / str(job.id)
        try:
            effective_manifest = manifest_path
            if effective_manifest is None and inspect_job_id is not None:
                inspected = await self.status(inspect_job_id)
                if (
                    inspected["action"] != "inspect"
                    or inspected["status"] != "completed"
                    or inspected["format"] != artifact_format
                ):
                    raise ValueError(
                        "inspect_job_id must reference a completed inspect job for "
                        f"format {artifact_format}"
                    )
                result_data = inspected.get("result")
                manifest_data = (
                    result_data.get("manifest")
                    if isinstance(result_data, dict)
                    else None
                )
                if not isinstance(manifest_data, dict) or not manifest_data:
                    raise ValueError("inspect job did not produce a reusable manifest")
                effective_manifest = work_dir / "inspect-manifest.json"
                await asyncio.to_thread(_write_json, effective_manifest, manifest_data)
            context = ArtifactDriverContext(
                workspace_root=workspace_root,
                work_dir=work_dir,
                project_path=project_path,
                source_path=source_path,
                manifest_path=effective_manifest,
                session_id=session_id,
            )
            if action == "inspect":
                result = await driver.inspect(context)
            elif action == "validate":
                result = await driver.validate(context)
            else:
                result = await driver.build(context)
            if action == "preview" and result.passed and result.candidate_path:
                revision = await self._create_revision(job, driver, result)
                job.latest_revision_id = revision.id
                job.status = "review_ready"
                job.result_data = {
                    **result.to_dict(),
                    "candidate_path": None,
                    "revision_id": str(revision.id),
                    "content_sha256": revision.content_sha256,
                    "byte_size": revision.byte_size,
                }
            else:
                job.status = "completed" if result.passed else "failed"
                job.result_data = result.to_dict()
                if action == "preview" and result.passed and not result.candidate_path:
                    job.status = "failed"
                    job.error_data = {
                        "type": "DriverContractError",
                        "message": "driver passed QA without producing candidate bytes",
                    }
            job.completed_at = _utcnow()
            await self._update_job(job)
        except asyncio.CancelledError:
            job.status = "cancelled"
            job.completed_at = _utcnow()
            await self._update_job(job)
            raise
        except Exception as exc:  # noqa: BLE001 - failure must become durable
            logger.exception(
                "artifact_job_failed job_id={} format={} action={} error={}",
                job.id,
                artifact_format,
                action,
                exc,
            )
            job.status = "failed"
            job.error_data = {"type": type(exc).__name__, "message": str(exc)}
            job.completed_at = _utcnow()
            await self._update_job(job)
        finally:
            self._active_tasks.pop(job.id, None)
        return await self.status(job.id)

    async def publish(
        self,
        *,
        job_id: UUID,
        destination: Path,
        revision_id: UUID | None = None,
        actor: str = "agent",
        comment: str | None = None,
    ) -> dict[str, Any]:
        job, revision = await self._job_and_revision(job_id, revision_id)
        driver = self.registry.get(cast(ArtifactFormat, job.artifact_format))
        if destination.suffix.lower() != driver.extension:
            raise ValueError(
                f"published {job.artifact_format} destination must end in {driver.extension}"
            )
        if job.status not in {"review_ready", "published"}:
            raise ValueError(
                f"artifact job {job.id} is {job.status}; only review_ready revisions publish"
            )
        await asyncio.to_thread(
            self.store.materialize,
            revision.blob_key,
            destination,
            expected_sha256=revision.content_sha256,
        )
        digest, size = await asyncio.to_thread(self.store.hash_file, destination)
        if digest != revision.content_sha256 or size != revision.byte_size:
            destination.unlink(missing_ok=True)
            raise OSError("published bytes differ from the verified artifact revision")
        review = ArtifactReview(
            revision_id=revision.id,
            decision="approved",
            actor=actor,
            comment=comment,
            evidence={
                "destination": str(destination),
                "content_sha256": digest,
                "byte_size": size,
            },
        )
        job.status = "published"
        job.published_at = _utcnow()
        job.completed_at = job.completed_at or job.published_at
        job.result_data = {
            **job.result_data,
            "published_output": str(destination),
            "published_sha256": digest,
        }
        async with sqlite_write_guard():
            async with self.db_factory() as db:
                db.add(review)
                db.add(job)
                await db.commit()
        return await self.status(job.id)

    async def cancel(self, job_id: UUID) -> dict[str, Any]:
        already_terminal = False
        async with sqlite_write_guard():
            async with self.db_factory() as db:
                job = await db.get(ArtifactJob, job_id)
                if job is None:
                    raise KeyError(f"artifact job not found: {job_id}")
                if job.status in _TERMINAL:
                    already_terminal = True
                else:
                    job.status = "cancelled"
                    job.completed_at = _utcnow()
                    job.version += 1
                    job.updated_at = _utcnow()
                    db.add(job)
                    await db.commit()
        if not already_terminal:
            task = self._active_tasks.get(job_id)
            if task is not None and task is not asyncio.current_task():
                task.cancel()
        return await self.status(job_id)

    async def list_jobs(
        self,
        *,
        session_id: UUID | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        statement = select(ArtifactJob)
        if session_id is not None:
            statement = statement.where(ArtifactJob.session_id == session_id)
        if status is not None:
            statement = statement.where(ArtifactJob.status == status)
        statement = statement.order_by(col(ArtifactJob.created_at).desc()).limit(limit)
        async with self.db_factory() as db:
            rows = list((await db.exec(statement)).all())
            values: list[dict[str, Any]] = []
            for job in rows:
                revision = None
                if job.latest_revision_id:
                    revision = await db.get(ArtifactRevision, job.latest_revision_id)
                values.append(_job_dict(job, revision))
            return values

    async def status(self, job_id: UUID) -> dict[str, Any]:
        async with self.db_factory() as db:
            job = await db.get(ArtifactJob, job_id)
            if job is None:
                raise KeyError(f"artifact job not found: {job_id}")
            revision = None
            if job.latest_revision_id:
                revision = await db.get(ArtifactRevision, job.latest_revision_id)
            return _job_dict(job, revision)

    async def get_revision(self, revision_id: UUID) -> ArtifactRevision:
        async with self.db_factory() as db:
            revision = await db.get(ArtifactRevision, revision_id)
            if revision is None:
                raise KeyError(f"artifact revision not found: {revision_id}")
            return revision

    async def _insert_job(self, job: ArtifactJob) -> None:
        async with sqlite_write_guard():
            async with self.db_factory() as db:
                db.add(job)
                await db.commit()

    async def _update_job(self, job: ArtifactJob) -> None:
        job.version += 1
        job.updated_at = _utcnow()
        async with sqlite_write_guard():
            async with self.db_factory() as db:
                current = await db.get(ArtifactJob, job.id)
                if (
                    current is not None
                    and current.status == "cancelled"
                    and job.status != "cancelled"
                ):
                    return
                await db.merge(job)
                await db.commit()

    async def _create_revision(
        self, job: ArtifactJob, driver: Any, result: Any
    ) -> ArtifactRevision:
        blob = await asyncio.to_thread(self.store.put, result.candidate_path)
        revision = ArtifactRevision(
            job_id=job.id,
            revision_number=1,
            artifact_format=job.artifact_format,
            media_type=driver.media_type,
            candidate_name=f"{job.id}{driver.extension}",
            content_sha256=blob.sha256,
            byte_size=blob.byte_size,
            blob_key=blob.key,
            qa={
                "passed": result.passed,
                "issues": [
                    issue.model_dump(exclude_none=True) for issue in result.issues
                ],
            },
            manifest_data=result.manifest,
            provenance={
                **result.provenance,
                "job_id": str(job.id),
                "lane": job.lane,
            },
            driver_version=driver.version,
            protocol_version=driver.protocol_version,
        )
        revision.previews = await asyncio.to_thread(
            self.store.preserve_previews, revision.id, result.previews
        )
        async with sqlite_write_guard():
            async with self.db_factory() as db:
                db.add(revision)
                await db.commit()
        return revision

    async def _job_and_revision(
        self, job_id: UUID, revision_id: UUID | None
    ) -> tuple[ArtifactJob, ArtifactRevision]:
        async with self.db_factory() as db:
            job = await db.get(ArtifactJob, job_id)
            if job is None:
                raise KeyError(f"artifact job not found: {job_id}")
            selected = revision_id or job.latest_revision_id
            if selected is None:
                raise ValueError(f"artifact job {job_id} has no candidate revision")
            revision = await db.get(ArtifactRevision, selected)
            if revision is None or revision.job_id != job.id:
                raise KeyError(
                    f"artifact revision not found for job {job_id}: {selected}"
                )
            return job, revision


def _job_dict(job: ArtifactJob, revision: ArtifactRevision | None) -> dict[str, Any]:
    value: dict[str, Any] = {
        "job_id": str(job.id),
        "session_id": str(job.session_id) if job.session_id else None,
        "format": job.artifact_format,
        "lane": job.lane,
        "action": job.action,
        "status": job.status,
        "request": job.request_data,
        "result": job.result_data,
        "error": job.error_data,
        "version": job.version,
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "published_at": job.published_at.isoformat() if job.published_at else None,
    }
    if revision:
        value["revision"] = {
            "revision_id": str(revision.id),
            "revision_number": revision.revision_number,
            "format": revision.artifact_format,
            "media_type": revision.media_type,
            "candidate_name": revision.candidate_name,
            "content_sha256": revision.content_sha256,
            "byte_size": revision.byte_size,
            "previews": revision.previews,
            "qa": revision.qa,
            "manifest": revision.manifest_data,
            "provenance": revision.provenance,
            "driver_version": revision.driver_version,
            "protocol_version": revision.protocol_version,
            "created_at": revision.created_at.isoformat(),
        }
    else:
        value["revision"] = None
    return value


def _lane(artifact_format: ArtifactFormat, source_path: Path | None) -> str:
    if artifact_format == "pdf":
        return "form" if source_path else "new"
    return "template" if source_path else "new"


def _session_uuid(value: str | None) -> UUID | None:
    if not value:
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


_default_service: ArtifactService | None = None


def get_artifact_service() -> ArtifactService:
    global _default_service
    if _default_service is None:
        _default_service = ArtifactService()
    return _default_service


__all__ = ["ArtifactService", "RunAction", "get_artifact_service"]
