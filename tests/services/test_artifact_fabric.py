from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest
from sqlmodel import select

from app.artifacts.domain import (
    ArtifactDriverContext,
    ArtifactDriverResult,
    ArtifactIssue,
)
from app.artifacts.drivers.base import ArtifactDriver
from app.artifacts.registry import ArtifactDriverRegistry
from app.artifacts.service import ArtifactService
from app.artifacts.storage import ArtifactStore
from app.core import db as db_module
from app.models.artifact import ArtifactReview


class FakePdfDriver(ArtifactDriver):
    format = "pdf"
    extension = ".pdf"
    media_type = "application/pdf"
    version = "fake-v1"

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.build_count = 0
        self.validate_manifest: Path | None = None

    def catalog(self) -> dict:
        return {"workflow": "fake-pdf"}

    async def inspect(self, context: ArtifactDriverContext) -> ArtifactDriverResult:
        return ArtifactDriverResult(
            metadata={"inspected": True}, manifest={"schemaVersion": 1}
        )

    async def validate(self, context: ArtifactDriverContext) -> ArtifactDriverResult:
        self.validate_manifest = context.manifest_path
        return ArtifactDriverResult(metadata={"valid": True})

    async def build(self, context: ArtifactDriverContext) -> ArtifactDriverResult:
        self.build_count += 1
        context.work_dir.mkdir(parents=True, exist_ok=True)
        candidate = context.work_dir / "candidate.pdf"
        candidate.write_bytes(b"%PDF-1.7\nimmutable-candidate\n%%EOF\n")
        preview = context.work_dir / "preview.png"
        preview.write_bytes(b"png-evidence")
        issues = (
            [
                ArtifactIssue(
                    severity="error",
                    code="qa-failed",
                    message="intentional failure",
                )
            ]
            if self.fail
            else []
        )
        return ArtifactDriverResult(
            candidate_path=candidate if not self.fail else None,
            previews=[preview],
            issues=issues,
            manifest={"page_count": 1},
            provenance={"engine": "fake"},
        )


class BlockingPdfDriver(FakePdfDriver):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def build(self, context: ArtifactDriverContext) -> ArtifactDriverResult:
        self.started.set()
        await self.release.wait()
        return await super().build(context)


def _service(tmp_path: Path, driver: FakePdfDriver) -> ArtifactService:
    registry = ArtifactDriverRegistry()
    registry.register(driver)
    return ArtifactService(
        db_factory=db_module.async_session_factory,
        store=ArtifactStore(tmp_path / "store"),
        registry=registry,
    )


@pytest.mark.asyncio
async def test_preview_creates_immutable_revision_and_publish_does_not_rebuild(
    tmp_path: Path,
) -> None:
    driver = FakePdfDriver()
    service = _service(tmp_path, driver)

    preview = await service.execute(
        action="preview",
        artifact_format="pdf",
        workspace_root=tmp_path,
        project_path=tmp_path / "project.json",
    )

    assert preview["status"] == "review_ready"
    assert driver.build_count == 1
    revision = preview["revision"]
    assert revision["qa"]["passed"] is True
    assert len(revision["previews"]) == 1

    output = tmp_path / "published.pdf"
    published = await service.publish(
        job_id=_uuid(preview["job_id"]),
        destination=output,
    )

    assert published["status"] == "published"
    assert driver.build_count == 1
    assert hashlib.sha256(output.read_bytes()).hexdigest() == revision["content_sha256"]
    async with db_module.async_session_factory() as db:
        reviews = list((await db.exec(select(ArtifactReview))).all())
    assert len(reviews) == 1
    assert reviews[0].evidence["content_sha256"] == revision["content_sha256"]


@pytest.mark.asyncio
async def test_failed_qa_never_creates_a_revision(tmp_path: Path) -> None:
    service = _service(tmp_path, FakePdfDriver(fail=True))

    value = await service.execute(
        action="preview",
        artifact_format="pdf",
        workspace_root=tmp_path,
        project_path=tmp_path / "project.json",
    )

    assert value["status"] == "failed"
    assert value["revision"] is None
    assert value["result"]["issues"][0]["code"] == "qa-failed"


@pytest.mark.asyncio
async def test_publish_fails_closed_if_cas_bytes_are_tampered(tmp_path: Path) -> None:
    service = _service(tmp_path, FakePdfDriver())
    preview = await service.execute(
        action="preview",
        artifact_format="pdf",
        workspace_root=tmp_path,
        project_path=tmp_path / "project.json",
    )
    revision = await service.get_revision(_uuid(preview["revision"]["revision_id"]))
    service.store.resolve_blob(revision.blob_key).write_bytes(b"tampered")
    output = tmp_path / "must-not-exist.pdf"

    with pytest.raises(OSError, match="integrity"):
        await service.publish(job_id=_uuid(preview["job_id"]), destination=output)

    assert not output.exists()


@pytest.mark.asyncio
async def test_cancel_stops_an_active_backend_job(tmp_path: Path) -> None:
    driver = BlockingPdfDriver()
    service = _service(tmp_path, driver)
    running = asyncio.create_task(
        service.execute(
            action="preview",
            artifact_format="pdf",
            workspace_root=tmp_path,
            project_path=tmp_path / "project.json",
        )
    )
    await driver.started.wait()
    jobs = await service.list_jobs(status="running")
    assert len(jobs) == 1

    cancelled = await service.cancel(_uuid(jobs[0]["job_id"]))

    assert cancelled["status"] == "cancelled"
    with pytest.raises(asyncio.CancelledError):
        await running


@pytest.mark.asyncio
async def test_completed_inspect_job_supplies_durable_manifest_to_next_job(
    tmp_path: Path,
) -> None:
    driver = FakePdfDriver()
    service = _service(tmp_path, driver)
    inspected = await service.execute(
        action="inspect",
        artifact_format="pdf",
        workspace_root=tmp_path,
        source_path=tmp_path / "source.pdf",
    )

    validated = await service.execute(
        action="validate",
        artifact_format="pdf",
        workspace_root=tmp_path,
        project_path=tmp_path / "project.json",
        source_path=tmp_path / "source.pdf",
        inspect_job_id=_uuid(inspected["job_id"]),
    )

    assert validated["status"] == "completed"
    assert driver.validate_manifest is not None
    assert json.loads(driver.validate_manifest.read_text(encoding="utf-8")) == {
        "schemaVersion": 1
    }


def test_content_addressed_store_deduplicates_and_materializes_exact_bytes(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path / "store")
    first = tmp_path / "first.bin"
    second = tmp_path / "second.bin"
    first.write_bytes(b"same bytes")
    second.write_bytes(b"same bytes")

    a = store.put(first)
    b = store.put(second)
    output = tmp_path / "out.bin"
    store.materialize(a.key, output, expected_sha256=a.sha256)

    assert a.key == b.key
    assert output.read_bytes() == b"same bytes"


def _uuid(value: str):
    from uuid import UUID

    return UUID(value)
