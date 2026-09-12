"""Schema-v2 Conductor reconciliation using stable project/resource identity."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from loguru import logger

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
            item.kind in {"agent_team", "skill"}
            and (
                (
                    item.observed_state in {"applied", "in_sync"}
                    and not _local_materialization_is_current(item)
                )
                # A record that already drifted into another state still needs
                # the replay: nothing else re-evaluates an applied resource, so
                # without this it keeps whatever label it happened to land on.
                or (
                    _applied_version_id(item) == item.version_id
                    and _local_copy_diverged(item)
                )
            )
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
            # A copy that is present but different from what was applied is
            # drift, whatever the record last said. Deciding it before the
            # state branches keeps a record that already drifted into
            # ``update_pending`` from staying mislabelled — an update is not
            # what is pending, and pulling one is not what fixes it.
            if _applied_version_id(previous) == change.version_id and _local_copy_diverged(
                previous
            ):
                if enforcement_mode == "enforce":
                    # ``_apply_*`` re-checks ownership and reports the conflict
                    # itself rather than overwriting the edit.
                    return await self._apply_change(client, change, previous)
                return self._record(
                    change,
                    state="ownership_conflict",
                    message=describe_local_divergence(previous),
                    previous=previous,
                )
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
        # `error` is retryable on purpose: a pull re-fetches the version and
        # re-applies it, so a resource that failed once — a transient fetch,
        # or a release since corrected — had no way back without wiping the
        # whole enrolment. `ownership_conflict` is retryable for the same
        # reason: once the user has removed or restored the local copy, the
        # apply path re-checks ownership itself, so refusing here only left
        # the resource stuck forever.
        if previous.observed_state not in {
            "update_pending",
            "incompatible",
            "error",
            "ownership_conflict",
            "dependency_missing",
        }:
            raise ValueError(
                "Managed resource is not waiting for a version pull "
                f"(state: {previous.observed_state})."
            )
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
            if version.kind == "agent_team":
                return self._apply_team(change, version, previous)
            return self._apply_skill(change, version, previous)
        except Exception as exc:
            # The reason matters: these messages name the file or field that
            # failed, and without them an operator sees only "ValueError" for
            # any of a dozen distinct causes.
            logger.warning(
                "conductor_resource_reconcile_failed "
                f"kind={change.kind} slug={change.slug} "
                f"version={change.version} error={type(exc).__name__}: {exc}"
            )
            reason = str(exc).strip()
            return self._error(
                change,
                type(exc).__name__.lower(),
                (
                    f"Managed resource could not be reconciled: {reason}"
                    if reason
                    else f"Managed resource could not be reconciled ({type(exc).__name__})."
                ),
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
        elif previous.kind == "agent_team" and previous.local_content_sha256:
            targets = list(previous.local_agent_targets)
            actual = _team_material(targets)
            if actual is not None and actual != previous.local_content_sha256:
                return self._record(
                    change,
                    state="ownership_conflict",
                    message=(
                        "Conductor removed this Team, but its locally edited "
                        "Agent copies were kept."
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

    def _apply_team(
        self,
        change: ResourceChange,
        version: EffectiveResourceVersion,
        previous: ManagedResourceRecord | None,
    ) -> ManagedResourceRecord:
        """Materialize a lead and its members as one unit.

        A team is applied all-or-nothing: every Agent is checked for ownership
        before any is written, so a single conflicting member leaves the whole
        team untouched rather than installing a lead whose members are missing.
        """

        files = _files(version.payload)
        modes = _resource_modes(files)
        definitions = _team_definitions(files)
        lead_name = _team_lead_name(definitions)
        if lead_name != change.slug:
            raise ValueError(
                f"Managed Team lead '{lead_name}' does not match resource slug "
                f"'{change.slug}'."
            )

        targets: dict[str, str] = {}
        for name, markdown in definitions.items():
            for target in _agent_targets(name, modes):
                targets[target] = markdown

        previous_targets = list(previous.local_agent_targets) if previous else []
        existing = set(agent_fs.list_agents())
        for target in targets:
            if target in existing and target not in previous_targets:
                return self._record(
                    change,
                    state="ownership_conflict",
                    message=(
                        f"A user-owned Agent already uses '{target}'; this Team was not applied."
                    ),
                    previous=previous,
                )
        if previous is not None and previous.local_content_sha256:
            actual = _team_material(previous_targets)
            if actual is not None and actual != previous.local_content_sha256:
                return self._record(
                    change,
                    state="ownership_conflict",
                    message="The managed Team copy was edited locally.",
                    previous=previous,
                )

        for target, markdown in targets.items():
            agent_fs.write_agent(target, markdown, create=target not in existing)
        for target in set(previous_targets) - set(targets):
            try:
                agent_fs.delete_agent(target)
            except agent_fs.AgentFsNotFoundError:
                pass

        applied_targets = sorted(targets)
        skills: set[str] = set()
        servers: set[str] = set()
        for name, markdown in definitions.items():
            config = parse_agent_definition(
                markdown,
                default_name=name,
                source_label=f"Managed Team Agent '{name}'",
            )
            skills.update(config.skills)
            servers.update(config.mcp)
        return self._record(
            change,
            state="applied",
            local_content_sha256=_team_material(applied_targets),
            local_agent_targets=applied_targets,
            declared_skills=sorted(skills),
            declared_mcp=sorted(servers),
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
            self._inventory_item(item) for item in self.store.load().resources
        ]

    def _inventory_item(self, item: ManagedResourceRecord) -> dict[str, Any]:
        state = observed_state_now(item)
        return {
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
                "observed_state": state,
                # Conductor shows this under the state badge, and a bare
                # "dependency missing" or "ownership conflict" is not something
                # an operator can act on.
                "error_category": (
                    describe_unresolved(unresolved_capabilities(item))
                    if state == "dependency_missing"
                    else describe_local_divergence(item) or item.error_category
                    if state == "ownership_conflict"
                    else item.error_category
                ),
                "observed_at": item.observed_at.isoformat(),
        }

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
            elif record.kind == "agent_team" and record.local_content_sha256:
                targets = list(record.local_agent_targets)
                if _team_material(targets) == record.local_content_sha256:
                    for target in targets:
                        try:
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
        local_agent_targets: list[str] | None = None,
        declared_skills: list[str] | None = None,
        declared_mcp: list[str] | None = None,
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
            if local_agent_targets is None:
                local_agent_targets = previous.local_agent_targets
            if declared_skills is None:
                declared_skills = previous.declared_skills
            if declared_mcp is None:
                declared_mcp = previous.declared_mcp
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
            local_agent_targets=list(local_agent_targets or []),
            declared_skills=list(declared_skills or []),
            declared_mcp=list(declared_mcp or []),
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
        except (TypeError, ValueError):
            # A mode this client does not implement is skipped rather than
            # failing the resource. `aim` shipped in real releases before it
            # was retired, and rejecting the whole bundle for it left those
            # resources permanently unappliable.
            logger.info(
                "conductor_resource_mode_ignored "
                f"mode={raw_mode!r} known={[item.value for item in ResourceTargetMode]}"
            )
            continue
        if mode in selected:
            raise ValueError("Managed resource modes must not contain duplicates.")
        selected.append(mode)
    if not selected:
        raise ValueError(
            "Managed resource names no mode this EvoFlux version can serve."
        )
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


TEAM_AGENT_DIR = "agents/"
TEAM_MANIFEST_FILENAME = "team.json"


def _team_definitions(files: list[tuple[str, str]]) -> dict[str, str]:
    """Return `{agent name: markdown}` for a Team release, validating layout."""

    definitions: dict[str, str] = {}
    for path, content in files:
        if path in {TEAM_MANIFEST_FILENAME, RESOURCE_MODE_SCOPE_FILENAME}:
            continue
        if not path.startswith(TEAM_AGENT_DIR) or not path.endswith(".md"):
            raise ValueError(f"Managed Team contains an unexpected file '{path}'.")
        name = path[len(TEAM_AGENT_DIR) : -len(".md")]
        if not name or "/" in name:
            raise ValueError(f"Managed Team Agent path '{path}' is not a flat name.")
        config = parse_agent_definition(
            content,
            default_name=name,
            source_label=f"Managed Team Agent '{name}'",
        )
        if config.name != name:
            raise ValueError(
                f"Managed Team Agent frontmatter name '{config.name}' does not "
                f"match its filename '{name}'."
            )
        definitions[name] = content
    if not definitions:
        raise ValueError("Managed Team release contains no Agent definitions.")
    return definitions


def _team_lead_name(definitions: dict[str, str]) -> str:
    """Identify the single lead, and refuse a team EvoFlux would misassemble.

    A member without an explicit ``lead`` silently joins this installation's
    default lead instead of the team it shipped with, so the release is
    rejected rather than applied into the wrong roster.
    """

    leads: list[str] = []
    members: dict[str, str | None] = {}
    for name, markdown in definitions.items():
        config = parse_agent_definition(
            markdown,
            default_name=name,
            source_label=f"Managed Team Agent '{name}'",
        )
        if config.role == "lead":
            leads.append(name)
        else:
            members[name] = config.lead
    if len(leads) != 1:
        raise ValueError(
            f"Managed Team must define exactly one lead Agent; found {len(leads)}."
        )
    lead_name = leads[0]
    for name, declared in members.items():
        if not declared:
            raise ValueError(
                f"Managed Team member '{name}' does not declare its lead."
            )
        if declared != lead_name:
            raise ValueError(
                f"Managed Team member '{name}' declares lead '{declared}', "
                f"but this Team's lead is '{lead_name}'."
            )
    return lead_name


def unresolved_capabilities(record: ManagedResourceRecord) -> dict[str, list[str]]:
    """Name the Skills and MCP servers a managed release asks for but cannot get.

    EvoFlux only warns and carries on when an Agent names a Skill or MCP server
    it cannot find, so a team can look applied while running without the
    capabilities it was published with. Resolving here — at report time, against
    the catalogs as they stand now — keeps that from being reported as success,
    and lets a plugin that starts late clear itself without a re-apply.
    """

    if not record.declared_skills and not record.declared_mcp:
        return {}
    missing: dict[str, list[str]] = {}
    if record.declared_skills:
        available: set[str] = set()
        try:
            from app.agent.tools.builtin.skill import discover_skill_records_runtime

            for mode in record.modes:
                available.update(discover_skill_records_runtime(mode=mode.value))
        except Exception:  # discovery is best-effort; absence is not proof
            return {}
        absent = [name for name in record.declared_skills if name not in available]
        if absent:
            missing["skills"] = absent
    if record.declared_mcp:
        from app.plugin_platform.runtime import all_mcp_server_names

        try:
            servers = set(all_mcp_server_names())
        except Exception:
            return missing
        absent = [name for name in record.declared_mcp if name not in servers]
        if absent:
            missing["mcp"] = absent
    return missing


def describe_unresolved(missing: dict[str, list[str]]) -> str | None:
    """Name what could not be resolved, short enough for a table cell."""

    if not missing:
        return None
    labels = {"skills": "skills", "mcp": "MCP servers"}
    parts = [
        f"missing {labels.get(key, key)}: {', '.join(sorted(names))}"
        for key, names in sorted(missing.items())
        if names
    ]
    summary = "; ".join(parts)
    return summary[:197] + "..." if len(summary) > 200 else summary


def observed_state_now(record: ManagedResourceRecord) -> ObservedResourceState:
    """Report an applied release honestly rather than trusting the last apply.

    Two conditions turn a clean apply into something the operator has to know
    about, and neither of them changes the stored record:

    * the local copy no longer matches what was applied — under ``report``
      enforcement nothing re-reconciles an applied resource, so this was the
      one state that stayed silent forever;
    * a declared Skill or MCP server does not resolve on this installation.
    """

    if record.observed_state not in {"applied", "in_sync"}:
        return record.observed_state
    if _local_copy_diverged(record):
        return "ownership_conflict"
    return "dependency_missing" if unresolved_capabilities(record) else record.observed_state


def _local_copy_diverged(record: ManagedResourceRecord) -> bool:
    """Whether the local copy provably differs from what was applied.

    Deliberately narrower than :func:`_local_materialization_is_current`, which
    also answers "not current" when nothing is known. A record with no stored
    digest — written before digests were recorded — has not been shown to
    differ, and must not be accused of it.
    """

    if record.kind == "plugin" or not record.local_content_sha256:
        return False
    if record.kind == "agent_team":
        if not record.local_agent_targets:
            return False
        actual = _team_material(record.local_agent_targets)
        return actual is not None and actual != record.local_content_sha256
    try:
        material = _skill_material(record.slug)
    except (OSError, UnicodeError):
        return False
    return hashlib.sha256(material).hexdigest() != record.local_content_sha256


def describe_local_divergence(record: ManagedResourceRecord) -> str | None:
    """Explain a locally-edited managed copy, in the terms the apply path uses.

    Deliberately independent of ``observed_state``: whether the copy on disk
    matches what was applied is a fact about the files, and the callers that
    need this are the ones whose stored state has already moved on.
    """

    if not _local_copy_diverged(record):
        return None
    label = "Team" if record.kind == "agent_team" else record.kind.capitalize()
    version = record.version or "the applied release"
    # Say what to do, not just what happened. EvoFlux never overwrites a local
    # edit — the apply path refuses the write — so "pull it again" on its own
    # describes an action that cannot succeed until the file is put back.
    where = _diverged_location(record)
    return (
        f"The managed {label} copy was edited locally, so it no longer matches "
        f"{version}. EvoFlux will not overwrite your edit: revert your changes "
        f"under {where}, then retry to restore the published copy."
    )


def _diverged_location(record: ManagedResourceRecord) -> str:
    """Point at where the edited copy lives, so the fix does not need a hunt.

    Only the set digest is stored, not per-file digests, so this names the
    directory the resource owns rather than claiming which file changed.
    """

    if record.kind == "agent_team":
        return f"{agent_fs.agents_dir()} (this Team's Agent files)"
    return str(agent_fs.skills_dir() / record.slug)


def _team_material(targets: list[str]) -> str | None:
    """Digest every Agent file a Team owns, as one value.

    A team spans several files, so local edits are detected across the set
    rather than per file; a missing file yields ``None`` so the caller can tell
    "not materialized" apart from "changed".
    """

    material: list[tuple[str, str]] = []
    for target in sorted(targets):
        try:
            material.append((target, agent_fs.read_agent(target).content))
        except (agent_fs.AgentFsNotFoundError, OSError):
            return None
    encoded = json.dumps(material, ensure_ascii=False, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


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
    if record.kind == "agent_team":
        if not record.local_agent_targets:
            return False
        return _team_material(record.local_agent_targets) == record.local_content_sha256
    try:
        material = _skill_material(record.slug)
    except (OSError, UnicodeError):
        return False
    return hashlib.sha256(material).hexdigest() == record.local_content_sha256


__all__ = [
    "GovernedResourceReconciler",
    "describe_local_divergence",
    "describe_unresolved",
    "observed_state_now",
    "unresolved_capabilities",
]
