"""Schema-v2 Conductor reconciliation using stable project/resource identity."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from app.agent.config import parse_agent_definition
from app.agent.skills.validation import (
    parse_skill_definition,
    portable_skill_name_error,
)
from app.conductor.client import ConductorClient
from app.conductor.constants.resource import (
    DEFAULT_RESOURCE_TARGET_MODES,
    RESOURCE_MODE_SCOPE_FILENAME,
    ResourceTargetMode,
)
from app.conductor.managed_state import ManagedResourceStore
from app.conductor.models import (
    EffectiveResourceVersion,
    ManagedResourceRecord,
    ObservedResourceState,
    ResourceChange,
    ResourceChangePage,
)
from app.conductor.semver import SemanticVersion
from app.core.skill_scope import serialize_skill_modes
from app.core.skill_settings import (
    delete_skill_runtime_settings,
    skill_settings_id,
)
from app.core.version import VERSION
from app.plugin_platform.installer import install_plugin
from app.plugin_platform.registry import (
    get_installation,
    replace_installation,
    set_enabled,
)
from app.plugin_platform.registry import plugin_data_root
from app.plugin_platform.validator import inspect_plugin
from app.services import agent_fs, team_manager


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

    def needs_change_replay(self, project_id: str) -> bool:
        """Return whether applied local state needs an authoritative feed replay."""

        document = self.store.load()
        if document.project_id != project_id:
            return False
        return any(
            item.observed_state in {"applied", "in_sync"}
            and item.kind in {"agent", "skill"}
            and not _local_materialization_is_current(item)
            for item in document.resources
        )

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
                change,
                "invalid_change",
                "Change omitted immutable identity.",
                previous=previous,
            )
        if previous and previous.version_id == change.version_id:
            if previous.observed_state in {
                "applied",
                "in_sync",
            } and _local_materialization_is_current(previous):
                return _refresh_record_metadata(
                    previous,
                    change,
                    state="in_sync",
                    observed_at=now,
                )
            if previous.observed_state in {
                "trust_pending",
                "update_pending",
                "incompatible",
            }:
                return _refresh_record_metadata(
                    previous,
                    change,
                    state=previous.observed_state,
                    observed_at=now,
                )
            if (
                previous.observed_state in {"applied", "in_sync"}
                and enforcement_mode == "enforce"
            ):
                return await self._apply_change(client, change, previous)
        if previous is not None and _applied_version_id(previous) is not None:
            return self._record(
                change,
                state="update_pending",
                message=(
                    "A managed update is available. Review the version changes "
                    "and pull it when you are ready."
                ),
                previous=previous,
            )
        if enforcement_mode != "enforce":
            return self._record(
                change,
                state="update_pending",
                message="A managed resource is available to pull from Conductor.",
                previous=previous,
            )
        return await self._apply_change(client, change, previous)

    async def pull(
        self,
        client: ConductorClient,
        project_id: str,
        resource_id: str,
    ) -> ManagedResourceRecord:
        """Apply one explicitly selected desired version without advancing sync state."""

        previous = self.store.find(project_id, resource_id)
        if (
            previous is None
            or previous.version_id is None
            or previous.content_sha256 is None
        ):
            raise KeyError(resource_id)
        if previous.observed_state not in {"update_pending", "incompatible"}:
            raise ValueError("Managed resource is not waiting for a version pull.")
        change = ResourceChange(
            project_id=previous.project_id,
            resource_id=previous.resource_id,
            version_id=previous.version_id,
            kind=previous.kind,
            slug=previous.slug,
            version=previous.version,
            description=previous.description,
            changelog=previous.changelog,
            version_history=previous.version_history,
            release_channel=previous.release_channel,
            sha256=previous.content_sha256,
            size=previous.content_size,
            minimum_evoflux_version=previous.minimum_evoflux_version,
            trust_required=previous.trust_required,
        )
        result = await self._apply_change(client, change, previous)
        self.store.upsert(result)
        return result

    async def _apply_change(
        self,
        client: ConductorClient,
        change: ResourceChange,
        previous: ManagedResourceRecord | None,
    ) -> ManagedResourceRecord:
        try:
            assert change.version_id is not None
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
                        previous=previous,
                    )
                if current < minimum:
                    return self._record(
                        change,
                        state="incompatible",
                        message=(
                            f"Managed update requires EvoFlux {minimum.major}."
                            f"{minimum.minor}.{minimum.patch} or newer."
                        ),
                        previous=previous,
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
                previous=previous,
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
            targets = _agent_targets(previous.slug, previous.modes)
            for target in targets:
                try:
                    current = agent_fs.read_agent(target).content
                except agent_fs.AgentFsNotFoundError:
                    continue
                if (
                    hashlib.sha256(current.encode("utf-8")).hexdigest()
                    != previous.local_content_sha256
                ):
                    return self._record(
                        change,
                        state="ownership_conflict",
                        message=(
                            "Conductor removed this Agent, but a locally edited "
                            "mode copy was kept."
                        ),
                        previous=previous,
                    )
            for target in targets:
                try:
                    agent_fs.delete_agent(target)
                except agent_fs.AgentFsNotFoundError:
                    pass
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
                    previous=previous,
                )
            if material is not None:
                root = (agent_fs.skills_dir() / previous.slug).resolve()
                skills_root = agent_fs.skills_dir().resolve()
                if root.is_relative_to(skills_root):
                    import shutil

                    shutil.rmtree(root, ignore_errors=True)
                    team_manager.invalidate_skill_cache()
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
            previous=previous,
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
        modes = _resource_modes(files)
        definition_files = [
            item for item in files if item[0] != RESOURCE_MODE_SCOPE_FILENAME
        ]
        expected_path = f"{change.slug}.md"
        if len(definition_files) != 1 or definition_files[0][0] != expected_path:
            raise ValueError(
                f"Agent release must contain one root '{expected_path}' definition."
            )
        markdown = definition_files[0][1]
        config = parse_agent_definition(
            markdown,
            default_name=change.slug,
            source_label=f"Managed Agent '{change.slug}'",
        )
        if config.name != change.slug:
            raise ValueError(
                f"Managed Agent frontmatter name '{config.name}' does not match "
                f"resource slug '{change.slug}'."
            )
        local_hash = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
        targets = _agent_targets(change.slug, modes)
        previous_targets = (
            set(_agent_targets(change.slug, previous.modes)) if previous else set()
        )
        existing = set(agent_fs.list_agents())
        for target in targets:
            if target in existing and target not in previous_targets:
                return self._record(
                    change,
                    state="ownership_conflict",
                    message=(
                        f"A user-owned Agent already uses '{target}'; it was not overwritten."
                    ),
                    previous=previous,
                )
            if (
                target in existing
                and target in previous_targets
                and previous is not None
                and previous.local_content_sha256
            ):
                actual = hashlib.sha256(
                    agent_fs.read_agent(target).content.encode("utf-8")
                ).hexdigest()
                if actual != previous.local_content_sha256:
                    return self._record(
                        change,
                        state="ownership_conflict",
                        message=f"The managed Agent copy '{target}' was edited locally.",
                        previous=previous,
                    )
        for target in targets:
            agent_fs.write_agent(target, markdown, create=target not in existing)
        for target in previous_targets - set(targets):
            try:
                current = agent_fs.read_agent(target).content
            except agent_fs.AgentFsNotFoundError:
                continue
            if (
                previous
                and hashlib.sha256(current.encode("utf-8")).hexdigest()
                == previous.local_content_sha256
            ):
                agent_fs.delete_agent(target)
        return self._record(
            change,
            state="applied",
            local_content_sha256=local_hash,
            modes=modes,
        )

    def _apply_skill(
        self,
        change: ResourceChange,
        version: EffectiveResourceVersion,
        previous: ManagedResourceRecord | None,
    ) -> ManagedResourceRecord:
        files = _files(version.payload)
        modes = _resource_modes(files)
        skill_md = next(
            (content for path, content in files if path == "SKILL.md"), None
        )
        if skill_md is None:
            raise ValueError("Skill release has no root SKILL.md.")
        name_error = portable_skill_name_error(change.slug)
        if name_error is not None:
            raise ValueError(name_error)
        _description, definition_error = parse_skill_definition(change.slug, skill_md)
        if definition_error is not None:
            raise ValueError(definition_error)
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
                previous=previous,
            )
        agent_fs.write_skill(change.slug, skill_md, create=not exists)
        resources = [
            (path, content, "utf-8")
            for path, content in files
            if path not in {"SKILL.md", RESOURCE_MODE_SCOPE_FILENAME}
        ]
        root = agent_fs.skills_dir() / change.slug
        existing_paths = {item.path for item in agent_fs.list_skill_bundle_files(root)}
        desired_paths = {path for path, _, _ in resources}
        agent_fs.apply_skill_bundle_files(
            root,
            resources,
            sorted(existing_paths - desired_paths),
        )
        (root / RESOURCE_MODE_SCOPE_FILENAME).write_text(
            serialize_skill_modes(modes),
            encoding="utf-8",
        )
        settings_id = skill_settings_id(
            source="global-EvoFlux",
            root=agent_fs.skills_dir(),
            stem=change.slug,
        )
        delete_skill_runtime_settings(settings_id)
        material = _skill_material(change.slug)
        team_manager.invalidate_skill_cache()
        return self._record(
            change,
            state="applied",
            local_content_sha256=hashlib.sha256(material).hexdigest(),
            modes=modes,
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
                "applied_version_id": record.version_id,
                "applied_version": record.version,
                "applied_content_sha256": record.content_sha256,
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
                    item.applied_version_id
                    or (
                        item.version_id
                        if item.observed_state in {"applied", "in_sync"}
                        else None
                    )
                ),
                "release_channel": item.release_channel,
                "content_sha256": item.applied_content_sha256,
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
        removed_skill = False
        for record in document.resources:
            if record.kind == "plugin" and record.plugin_installation_id:
                installation = get_installation(record.plugin_installation_id)
                if installation is not None and installation.enabled:
                    set_enabled(installation.id, False)
            elif record.kind == "agent" and record.local_content_sha256:
                for target in _agent_targets(record.slug, record.modes):
                    try:
                        current = agent_fs.read_agent(target).content
                        if (
                            hashlib.sha256(current.encode()).hexdigest()
                            == record.local_content_sha256
                        ):
                            agent_fs.delete_agent(target)
                    except agent_fs.AgentFsNotFoundError:
                        pass
            elif record.kind == "skill" and record.local_content_sha256:
                material = _skill_material(record.slug)
                if hashlib.sha256(material).hexdigest() == record.local_content_sha256:
                    target = (agent_fs.skills_dir() / record.slug).resolve()
                    if target.is_relative_to(agent_fs.skills_dir()):
                        import shutil

                        shutil.rmtree(target, ignore_errors=True)
                        removed_skill = True
        if removed_skill:
            team_manager.invalidate_skill_cache()

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
        modes: list[ResourceTargetMode] | None = None,
        previous: ManagedResourceRecord | None = None,
    ) -> ManagedResourceRecord:
        if previous is not None:
            if plugin_installation_id is None:
                plugin_installation_id = previous.plugin_installation_id
            if previous_plugin_installation_id is None:
                previous_plugin_installation_id = (
                    previous.previous_plugin_installation_id
                )
            if local_content_sha256 is None:
                local_content_sha256 = previous.local_content_sha256
            if modes is None:
                modes = previous.modes
        applied_version_id = None
        applied_version = None
        if state == "applied":
            applied_version_id = change.version_id
            applied_version = change.version
        elif previous is not None:
            applied_version_id = previous.applied_version_id or (
                previous.version_id
                if previous.observed_state in {"applied", "in_sync"}
                else None
            )
            applied_version = previous.applied_version or (
                previous.version
                if previous.observed_state in {"applied", "in_sync"}
                else None
            )
        return ManagedResourceRecord(
            project_id=change.project_id,
            resource_id=change.resource_id,
            version_id=change.version_id,
            version=change.version,
            applied_version_id=applied_version_id,
            applied_version=applied_version,
            release_channel=change.release_channel,
            kind=change.kind,
            slug=change.slug,
            modes=modes or list(DEFAULT_RESOURCE_TARGET_MODES),
            content_sha256=change.sha256,
            applied_content_sha256=(
                change.sha256
                if state == "applied"
                else previous.applied_content_sha256
                if previous is not None
                else None
            ),
            content_size=change.size,
            minimum_evoflux_version=change.minimum_evoflux_version,
            local_content_sha256=local_content_sha256,
            plugin_installation_id=plugin_installation_id,
            previous_plugin_installation_id=previous_plugin_installation_id,
            observed_state=state,
            trust_required=change.trust_required,
            trust_review=trust_review,
            message=message,
            description=change.description,
            changelog=change.changelog,
            version_history=change.version_history,
            observed_at=datetime.now(UTC),
        )

    def _error(
        self,
        change: ResourceChange,
        category: str,
        message: str,
        *,
        previous: ManagedResourceRecord | None = None,
    ) -> ManagedResourceRecord:
        return self._record(
            change, state="error", message=message, previous=previous
        ).model_copy(update={"error_category": category[:80]})

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
            or version.description != change.description
            or version.changelog != change.changelog
            or version.version_history != change.version_history
            or version.release_channel != change.release_channel
            or version.sha256 != change.sha256
            or version.size != change.size
            or version.minimum_evoflux_version != change.minimum_evoflux_version
        ):
            raise ValueError("Version metadata does not match the authorized change.")


def _applied_version_id(record: ManagedResourceRecord) -> str | None:
    return record.applied_version_id or (
        record.version_id if record.observed_state in {"applied", "in_sync"} else None
    )


def _refresh_record_metadata(
    record: ManagedResourceRecord,
    change: ResourceChange,
    *,
    state: ObservedResourceState,
    observed_at: datetime,
) -> ManagedResourceRecord:
    return record.model_copy(
        update={
            "description": change.description,
            "changelog": change.changelog,
            "version_history": change.version_history,
            "release_channel": change.release_channel,
            "content_sha256": change.sha256,
            "applied_content_sha256": (
                change.sha256
                if _applied_version_id(record) == change.version_id
                else record.applied_content_sha256
            ),
            "content_size": change.size,
            "minimum_evoflux_version": change.minimum_evoflux_version,
            "trust_required": change.trust_required,
            "observed_state": state,
            "observed_at": observed_at,
        }
    )


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


def _resource_modes(
    files: list[tuple[str, str]],
) -> list[ResourceTargetMode]:
    scope = next(
        (content for path, content in files if path == RESOURCE_MODE_SCOPE_FILENAME),
        None,
    )
    if scope is None:
        return list(DEFAULT_RESOURCE_TARGET_MODES)
    value = json.loads(scope)
    raw_modes = value.get("modes") if isinstance(value, dict) else None
    if not isinstance(raw_modes, list) or not raw_modes:
        raise ValueError("Managed resource modes must be a non-empty array.")
    selected: list[ResourceTargetMode] = []
    for raw_mode in raw_modes:
        try:
            mode = ResourceTargetMode(raw_mode)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "Managed resource modes may contain only work and coding."
            ) from exc
        if mode in selected:
            raise ValueError("Managed resource modes must not contain duplicates.")
        selected.append(mode)
    return [mode for mode in DEFAULT_RESOURCE_TARGET_MODES if mode in selected]


def _agent_targets(
    slug: str,
    modes: list[ResourceTargetMode],
) -> list[str]:
    targets: list[str] = []
    if ResourceTargetMode.WORK in modes:
        targets.append(slug)
    if ResourceTargetMode.CODING in modes:
        targets.append(f"coding/{slug}")
    return targets


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


def _local_materialization_is_current(record: ManagedResourceRecord) -> bool:
    """Verify same-version resources before declaring them in sync.

    This deliberately rechecks local materialization so clients installed before
    mode-aware delivery can backfill a missing Work or Coding copy without a new
    Conductor release. A changed copy also falls through to normal reconciliation,
    where ownership protection reports the conflict instead of overwriting it.
    """

    if record.kind == "plugin":
        return True
    if not record.local_content_sha256:
        return False
    if record.kind == "agent":
        for target in _agent_targets(record.slug, record.modes):
            try:
                content = agent_fs.read_agent(target).content
            except (agent_fs.AgentFsNotFoundError, OSError):
                return False
            if (
                hashlib.sha256(content.encode("utf-8")).hexdigest()
                != record.local_content_sha256
            ):
                return False
        return True
    try:
        material = _skill_material(record.slug)
    except (OSError, UnicodeError):
        return False
    return hashlib.sha256(material).hexdigest() == record.local_content_sha256


__all__ = ["GovernedResourceReconciler"]
