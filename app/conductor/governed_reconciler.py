"""Schema-v2 Conductor reconciliation using stable project/resource identity."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from app.conductor.client import ConductorClient
from app.conductor.managed_state import ManagedResourceStore
from app.conductor.models import (
    EffectiveResourceVersion,
    ManagedResourceRecord,
    ObservedResourceState,
    ResourceChange,
    ResourceChangePage,
)
from app.conductor.semver import SemanticVersion
from app.core.version import VERSION
from app.plugin_platform.installer import install_plugin
from app.plugin_platform.registry import (
    get_installation,
    replace_installation,
    set_enabled,
)
from app.plugin_platform.registry import plugin_data_root
from app.plugin_platform.validator import inspect_plugin
from app.services import agent_fs


class GovernedResourceReconciler:
    def __init__(self, store: ManagedResourceStore | None = None) -> None:
        self.store = store or ManagedResourceStore()

    async def reconcile_page(
        self,
        client: ConductorClient,
        page: ResourceChangePage,
        *,
        expected_project_id: str,
        enforcement_mode: str,
    ) -> list[ManagedResourceRecord]:
        if page.project_id != expected_project_id:
            raise ValueError("Conductor change page belongs to another project.")
        self.store.replace_project(expected_project_id)
        results: list[ManagedResourceRecord] = []
        for change in page.changes:
            if change.project_id != expected_project_id:
                raise ValueError("Conductor resource change crosses project scope.")
            result = await self._reconcile_change(
                client,
                change,
                enforcement_mode=enforcement_mode,
            )
            self.store.upsert(result)
            results.append(result)
        # A failed resource must remain on the current page so the next sync can
        # retry it. Successfully applied siblings are idempotent on replay.
        if not any(item.observed_state == "error" for item in results):
            self.store.commit_cursor(expected_project_id, page.next_cursor)
        return results

    async def _reconcile_change(
        self,
        client: ConductorClient,
        change: ResourceChange,
        *,
        enforcement_mode: str,
    ) -> ManagedResourceRecord:
        now = datetime.now(UTC)
        previous = self.store.find(change.project_id, change.resource_id)
        if change.tombstone:
            return self._remove(change, previous)
        if change.version_id is None or change.sha256 is None:
            return self._error(
                change, "invalid_change", "Change omitted immutable identity."
            )
        if previous and previous.version_id == change.version_id:
            if previous.observed_state in {"applied", "in_sync"}:
                return previous.model_copy(
                    update={"observed_state": "in_sync", "observed_at": now}
                )
            if previous.observed_state in {"trust_pending", "update_pending"}:
                return previous.model_copy(update={"observed_at": now})
        if enforcement_mode != "enforce":
            return self._record(
                change,
                state="update_pending",
                message="A managed update is available. Enforcement is report-only.",
            )
        try:
            version = await client.fetch_resource_version(
                change.resource_id, change.version_id
            )
            self._validate_version(change, version)
            if version.minimum_evoflux_version is not None:
                minimum = SemanticVersion.parse(version.minimum_evoflux_version)
                try:
                    current = SemanticVersion.parse(VERSION)
                except ValueError:
                    return self._record(
                        change,
                        state="incompatible",
                        message="EvoFlux client version is unknown; managed update was not applied.",
                    )
                if current < minimum:
                    return self._record(
                        change,
                        state="incompatible",
                        message=(
                            f"Managed update requires EvoFlux {minimum.major}."
                            f"{minimum.minor}.{minimum.patch} or newer."
                        ),
                    )
            if version.kind == "plugin":
                return await self._stage_plugin(client, change, version, previous)
            if version.kind == "agent":
                return self._apply_agent(change, version, previous)
            return self._apply_skill(change, version, previous)
        except Exception as exc:
            return self._error(
                change,
                type(exc).__name__.lower(),
                f"Managed resource could not be reconciled ({type(exc).__name__}).",
            )

    def _remove(
        self,
        change: ResourceChange,
        previous: ManagedResourceRecord | None,
    ) -> ManagedResourceRecord:
        if previous is None:
            return self._record(
                change,
                state="removed",
                message="Conductor removed this resource from the effective audience.",
            )
        if previous.kind == "plugin":
            installation_ids = {
                previous.plugin_installation_id,
                previous.previous_plugin_installation_id,
            }
            for installation_id in installation_ids:
                if installation_id is None:
                    continue
                installation = get_installation(installation_id)
                if installation is not None and installation.enabled:
                    set_enabled(installation.id, False)
        elif previous.kind == "agent" and previous.local_content_sha256:
            try:
                current = agent_fs.read_agent(previous.slug).content
            except agent_fs.AgentFsNotFoundError:
                current = None
            if (
                current is not None
                and hashlib.sha256(current.encode("utf-8")).hexdigest()
                != previous.local_content_sha256
            ):
                return self._record(
                    change,
                    state="ownership_conflict",
                    message="Conductor removed this Agent, but its locally edited file was kept.",
                )
            if current is not None:
                agent_fs.delete_agent(previous.slug)
        elif previous.kind == "skill" and previous.local_content_sha256:
            try:
                material = _skill_material(previous.slug)
            except (OSError, UnicodeError):
                material = None
            if (
                material is not None
                and hashlib.sha256(material).hexdigest()
                != previous.local_content_sha256
            ):
                return self._record(
                    change,
                    state="ownership_conflict",
                    message="Conductor removed this Skill, but its locally edited files were kept.",
                )
            if material is not None:
                root = (agent_fs.skills_dir() / previous.slug).resolve()
                skills_root = agent_fs.skills_dir().resolve()
                if root.is_relative_to(skills_root):
                    import shutil

                    shutil.rmtree(root, ignore_errors=True)
        return self._record(
            change,
            state="removed",
            message="Conductor removed this resource from the effective audience.",
        )

    async def _stage_plugin(
        self,
        client: ConductorClient,
        change: ResourceChange,
        version: EffectiveResourceVersion,
        previous: ManagedResourceRecord | None,
    ) -> ManagedResourceRecord:
        artifact = await client.download_resource_artifact(
            change.resource_id,
            change.version_id or "",
            expected_sha256=version.sha256,
            expected_size=version.size,
        )
        staging = self.store.root / "plugin-staging"
        staging.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{change.resource_id}.", suffix=".evoplugin", dir=staging
        )
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(artifact)
                handle.flush()
                os.fsync(handle.fileno())
            installation = install_plugin(
                temporary,
                enabled=False,
                source_ref=(
                    f"conductor://{change.project_id}/{change.resource_id}/"
                    f"{change.version_id}"
                ),
            )
            installation = installation.model_copy(
                update={
                    "managed_by": "conductor",
                    "managed_project_id": change.project_id,
                    "managed_resource_id": change.resource_id,
                    "managed_version_id": change.version_id,
                }
            )
            replace_installation(installation)
            trust_review = inspect_plugin(
                Path(installation.root),
                data_root=plugin_data_root(installation.id),
            ).trust.model_dump(mode="json")
        finally:
            Path(temporary).unlink(missing_ok=True)
        return self._record(
            change,
            state="trust_pending",
            plugin_installation_id=installation.id,
            previous_plugin_installation_id=(
                previous.plugin_installation_id if previous else None
            ),
            trust_review=trust_review,
            message=(
                "Plugin was verified and installed disabled. Review its commands, hosts, "
                "environment fields and capabilities before enabling it."
            ),
        )

    def _apply_agent(
        self,
        change: ResourceChange,
        version: EffectiveResourceVersion,
        previous: ManagedResourceRecord | None,
    ) -> ManagedResourceRecord:
        files = _files(version.payload)
        markdown = next(
            (content for path, content in files if path.endswith(".md")), None
        )
        if markdown is None:
            raise ValueError("Agent release has no Markdown definition.")
        local_hash = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
        exists = change.slug in agent_fs.list_agents()
        if exists and previous is None:
            return self._record(
                change,
                state="ownership_conflict",
                message="A user-owned Agent already uses this slug; it was not overwritten.",
            )
        if exists and previous and previous.local_content_sha256:
            actual = hashlib.sha256(
                agent_fs.read_agent(change.slug).content.encode("utf-8")
            ).hexdigest()
            if actual != previous.local_content_sha256:
                return self._record(
                    change,
                    state="ownership_conflict",
                    message="The previously managed Agent was edited locally.",
                )
        agent_fs.write_agent(change.slug, markdown, create=not exists)
        return self._record(
            change,
            state="applied",
            local_content_sha256=local_hash,
        )

    def _apply_skill(
        self,
        change: ResourceChange,
        version: EffectiveResourceVersion,
        previous: ManagedResourceRecord | None,
    ) -> ManagedResourceRecord:
        files = _files(version.payload)
        skill_md = next(
            (content for path, content in files if path == "SKILL.md"), None
        )
        if skill_md is None:
            raise ValueError("Skill release has no root SKILL.md.")
        exists = change.slug in agent_fs.list_skills()
        if exists and previous is None:
            return self._record(
                change,
                state="ownership_conflict",
                message="A user-owned Skill already uses this slug; it was not overwritten.",
            )
        actual_material = _skill_material(change.slug) if exists else None
        if (
            previous
            and previous.local_content_sha256
            and actual_material is not None
            and hashlib.sha256(actual_material).hexdigest()
            != previous.local_content_sha256
        ):
            return self._record(
                change,
                state="ownership_conflict",
                message="The previously managed Skill was edited locally.",
            )
        agent_fs.write_skill(change.slug, skill_md, create=not exists)
        resources = [
            (path, content, "utf-8") for path, content in files if path != "SKILL.md"
        ]
        root = agent_fs.skills_dir() / change.slug
        existing_paths = {item.path for item in agent_fs.list_skill_bundle_files(root)}
        desired_paths = {path for path, _, _ in resources}
        agent_fs.apply_skill_bundle_files(
            root,
            resources,
            sorted(existing_paths - desired_paths),
        )
        material = _skill_material(change.slug)
        return self._record(
            change,
            state="applied",
            local_content_sha256=hashlib.sha256(material).hexdigest(),
        )

    def approve_plugin(
        self, project_id: str, resource_id: str
    ) -> ManagedResourceRecord:
        record = self.store.find(project_id, resource_id)
        if (
            record is None
            or record.kind != "plugin"
            or not record.plugin_installation_id
        ):
            raise KeyError(resource_id)
        installation = get_installation(record.plugin_installation_id)
        if installation is None:
            raise KeyError(record.plugin_installation_id)
        if installation.managed_project_id != project_id:
            raise ValueError(
                "Plugin installation belongs to another Conductor project."
            )
        set_enabled(installation.id, True)
        if record.previous_plugin_installation_id:
            previous = get_installation(record.previous_plugin_installation_id)
            if previous is not None and previous.enabled:
                set_enabled(previous.id, False)
        updated = record.model_copy(
            update={
                "observed_state": "applied",
                "trust_required": False,
                "observed_at": datetime.now(UTC),
                "message": "Local Plugin trust was approved.",
            }
        )
        self.store.upsert(updated)
        return updated

    def inventory(self) -> list[dict[str, Any]]:
        return [
            {
                "resource_id": item.resource_id,
                "desired_version_id": item.version_id,
                "applied_version_id": (
                    item.version_id
                    if item.observed_state in {"applied", "in_sync", "trust_pending"}
                    else None
                ),
                "release_channel": item.release_channel,
                "content_sha256": item.content_sha256,
                "plugin_installation_id": item.plugin_installation_id,
                "observed_state": item.observed_state,
                "error_category": item.error_category,
                "observed_at": item.observed_at.isoformat(),
            }
            for item in self.store.load().resources
        ]

    def deactivate_project(self, project_id: str) -> None:
        """Unmount one managed namespace without deleting cached packages or data."""

        document = self.store.load()
        if document.project_id != project_id:
            return
        for record in document.resources:
            if record.kind == "plugin" and record.plugin_installation_id:
                installation = get_installation(record.plugin_installation_id)
                if installation is not None and installation.enabled:
                    set_enabled(installation.id, False)
            elif record.kind == "agent" and record.local_content_sha256:
                try:
                    current = agent_fs.read_agent(record.slug).content
                    if (
                        hashlib.sha256(current.encode()).hexdigest()
                        == record.local_content_sha256
                    ):
                        agent_fs.delete_agent(record.slug)
                except agent_fs.AgentFsNotFoundError:
                    pass
            elif record.kind == "skill" and record.local_content_sha256:
                material = _skill_material(record.slug)
                if hashlib.sha256(material).hexdigest() == record.local_content_sha256:
                    target = (agent_fs.skills_dir() / record.slug).resolve()
                    if target.is_relative_to(agent_fs.skills_dir()):
                        import shutil

                        shutil.rmtree(target, ignore_errors=True)

    def _record(
        self,
        change: ResourceChange,
        *,
        state: ObservedResourceState,
        message: str | None = None,
        plugin_installation_id: str | None = None,
        previous_plugin_installation_id: str | None = None,
        local_content_sha256: str | None = None,
        trust_review: dict[str, Any] | None = None,
    ) -> ManagedResourceRecord:
        return ManagedResourceRecord(
            project_id=change.project_id,
            resource_id=change.resource_id,
            version_id=change.version_id,
            version=change.version,
            release_channel=change.release_channel,
            kind=change.kind,
            slug=change.slug,
            content_sha256=change.sha256,
            local_content_sha256=local_content_sha256,
            plugin_installation_id=plugin_installation_id,
            previous_plugin_installation_id=previous_plugin_installation_id,
            observed_state=state,
            trust_required=change.trust_required,
            trust_review=trust_review,
            message=message,
            observed_at=datetime.now(UTC),
        )

    def _error(
        self, change: ResourceChange, category: str, message: str
    ) -> ManagedResourceRecord:
        return self._record(change, state="error", message=message).model_copy(
            update={"error_category": category[:80]}
        )

    @staticmethod
    def _validate_version(
        change: ResourceChange, version: EffectiveResourceVersion
    ) -> None:
        if (
            version.project_id != change.project_id
            or version.resource_id != change.resource_id
            or version.version_id != change.version_id
            or version.kind != change.kind
            or version.slug != change.slug
            or version.version != change.version
            or version.release_channel != change.release_channel
            or version.sha256 != change.sha256
            or version.size != change.size
            or version.minimum_evoflux_version != change.minimum_evoflux_version
        ):
            raise ValueError("Version metadata does not match the authorized change.")


def _files(payload: dict[str, Any]) -> list[tuple[str, str]]:
    raw = payload.get("files")
    if not isinstance(raw, list):
        raise ValueError("Managed payload has no file list.")
    files: list[tuple[str, str]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("Managed file entry is invalid.")
        path = item.get("path")
        content = item.get("content")
        if not isinstance(path, str) or not isinstance(content, str):
            raise ValueError("Managed file entry must contain text path/content.")
        pure = PurePosixPath(path)
        if (
            not path
            or "\\" in path
            or pure.is_absolute()
            or any(part in {"", ".", ".."} for part in pure.parts)
            or path in seen
        ):
            raise ValueError("Managed file path is unsafe or duplicated.")
        seen.add(path)
        files.append((path, content))
    return files


def _skill_material(slug: str) -> bytes:
    root = (agent_fs.skills_dir() / slug).resolve()
    if not root.is_relative_to(agent_fs.skills_dir()) or not root.is_dir():
        return b""
    material: list[tuple[str, str]] = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            material.append(
                (path.relative_to(root).as_posix(), path.read_text(encoding="utf-8"))
            )
    return json.dumps(material, ensure_ascii=False, separators=(",", ":")).encode()


__all__ = ["GovernedResourceReconciler"]
