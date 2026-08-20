from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.conductor.governed_reconciler import GovernedResourceReconciler
from app.conductor.managed_state import ManagedResourceStore
from app.conductor.models import (
    EffectiveResourceVersion,
    ManagedResourceRecord,
    ResourceChange,
    ResourceChangePage,
    ResourceVersionNotice,
)
from app.conductor.provenance import (
    managed_resource_provider,
    managed_resource_provider_from_record,
)
from app.core.config import settings
from app.core.runtime_settings import load_runtime_settings, save_runtime_settings
from app.plugin_platform.models import PLUGIN_SCHEMA_ID
from app.plugin_platform.registry import get_installation


@pytest.fixture
def governed_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    config = tmp_path / "config"
    monkeypatch.setattr(settings, "EVOFLUX_CONFIG_DIR", str(config))
    monkeypatch.setattr(settings, "EVOFLUX_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(settings, "EVOFLUX_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(settings, "EVOFLUX_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(settings, "AGENTS_DIR", str(config / "agents"))
    monkeypatch.setattr(settings, "SKILLS_DIR", str(config / "skills"))
    (config / "agents").mkdir(parents=True)
    (config / "skills").mkdir(parents=True)
    return tmp_path


class FakeClient:
    def __init__(
        self, version: EffectiveResourceVersion, artifact: bytes = b""
    ) -> None:
        self.version = version
        self.artifact = artifact
        self.version_requests = 0

    async def fetch_resource_version(
        self, resource_id: str, version_id: str
    ) -> EffectiveResourceVersion:
        self.version_requests += 1
        assert resource_id == self.version.resource_id
        assert version_id == self.version.version_id
        return self.version

    async def download_resource_artifact(
        self,
        resource_id: str,
        version_id: str,
        *,
        expected_sha256: str,
        expected_size: int,
    ) -> bytes:
        assert resource_id == self.version.resource_id
        assert version_id == self.version.version_id
        assert hashlib.sha256(self.artifact).hexdigest() == expected_sha256
        assert len(self.artifact) == expected_size
        return self.artifact


def test_inventory_pairs_digest_with_the_applied_version_only(
    governed_dirs: Path,
) -> None:
    store = ManagedResourceStore(governed_dirs / "state" / "conductor")
    reconciler = GovernedResourceReconciler(store)
    record = ManagedResourceRecord(
        project_id="project-1",
        resource_id="agent-1",
        version_id="desired-version-2",
        version="2.0.0",
        applied_version_id="applied-version-1",
        applied_version="1.0.0",
        kind="agent",
        slug="managed-agent",
        content_sha256="d" * 64,
        applied_content_sha256="a" * 64,
        observed_state="update_pending",
        observed_at=datetime.now(UTC),
    )
    store.upsert(record)

    [item] = reconciler.inventory()

    assert item["desired_version_id"] == "desired-version-2"
    assert item["applied_version_id"] == "applied-version-1"
    assert item["content_sha256"] == "a" * 64


def test_legacy_inventory_omits_an_unverified_applied_digest(
    governed_dirs: Path,
) -> None:
    store = ManagedResourceStore(governed_dirs / "state" / "conductor")
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "project_id": "project-1",
                "committed_cursor": "cursor-1",
                "resources": [
                    {
                        "project_id": "project-1",
                        "resource_id": "agent-1",
                        "version_id": "desired-version-2",
                        "version": "2.0.0",
                        "applied_version_id": "applied-version-1",
                        "applied_version": "1.0.0",
                        "kind": "agent",
                        "slug": "managed-agent",
                        "content_sha256": "d" * 64,
                        "observed_state": "update_pending",
                        "observed_at": datetime.now(UTC).isoformat(),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    [item] = GovernedResourceReconciler(store).inventory()

    assert item["applied_version_id"] == "applied-version-1"
    assert item["content_sha256"] is None


def _change(kind: str, sha256: str, size: int) -> ResourceChange:
    return ResourceChange.model_validate(
        {
            "project_id": "project-1",
            "resource_id": f"{kind}-1",
            "version_id": f"{kind}-version-1",
            "kind": kind,
            "slug": f"managed-{kind}",
            "version": "0.1.0",
            "release_channel": "published",
            "sha256": sha256,
            "size": size,
            "trust_required": kind == "plugin",
        }
    )


def _page(change: ResourceChange) -> ResourceChangePage:
    return ResourceChangePage(
        schema_version=2,
        project_id="project-1",
        next_cursor="cursor-1",
        has_more=False,
        changes=[change],
    )


@pytest.mark.asyncio
async def test_report_mode_records_update_without_touching_local_files(
    governed_dirs: Path,
) -> None:
    payload = {
        "files": [
            {
                "path": "managed-agent.md",
                "content": "---\nname: managed-agent\ndescription: Test\n---\nPrompt\n",
            }
        ]
    }
    digest = hashlib.sha256(json.dumps(payload).encode()).hexdigest()
    change = _change("agent", digest, len(json.dumps(payload)))
    version = EffectiveResourceVersion.model_validate(
        {
            **change.model_dump(exclude={"tombstone", "trust_required"}),
            "version_id": change.version_id,
            "release_channel": "published",
            "payload": payload,
            "artifact_key": None,
        }
    )
    client = FakeClient(version)
    store = ManagedResourceStore(governed_dirs / "state" / "conductor")
    results = await GovernedResourceReconciler(store).reconcile_page(
        client,
        _page(change),
        expected_project_id="project-1",
        enforcement_mode="report",
    )
    assert results[0].observed_state == "update_pending"
    assert client.version_requests == 0
    assert not (governed_dirs / "config" / "agents" / "managed-agent.md").exists()
    assert store.load().committed_cursor == "cursor-1"


@pytest.mark.asyncio
async def test_enforce_applies_agent_by_project_resource_identity(
    governed_dirs: Path,
) -> None:
    content = "---\nname: managed-agent\ndescription: Test\n---\nPrompt\n"
    payload = {"files": [{"path": "managed-agent.md", "content": content}]}
    raw = json.dumps(payload, separators=(",", ":")).encode()
    change = _change("agent", hashlib.sha256(raw).hexdigest(), len(raw))
    version = EffectiveResourceVersion.model_validate(
        {
            **change.model_dump(exclude={"tombstone", "trust_required"}),
            "release_channel": "published",
            "payload": payload,
            "artifact_key": None,
        }
    )
    store = ManagedResourceStore(governed_dirs / "state" / "conductor")
    results = await GovernedResourceReconciler(store).reconcile_page(
        FakeClient(version),
        _page(change),
        expected_project_id="project-1",
        enforcement_mode="enforce",
    )
    assert results[0].observed_state == "applied"
    assert results[0].resource_id == "agent-1"
    assert (
        governed_dirs / "config" / "agents" / "managed-agent.md"
    ).read_text() == content
    runtime = load_runtime_settings()
    runtime.conductor.project_id = "project-1"
    runtime.conductor.project_name = "platform-core"
    runtime.conductor.project_display_name = "Platform Core"
    save_runtime_settings(runtime)
    provider = managed_resource_provider("agent", "managed-agent")
    assert provider is not None
    assert provider.project_name == "Platform Core"
    assert provider.resource_id == "agent-1"
    assert provider.version == "0.1.0"


@pytest.mark.asyncio
async def test_enforce_mounts_agent_only_in_selected_evoflux_mode(
    governed_dirs: Path,
) -> None:
    content = "---\nname: managed-agent\ndescription: Test\n---\nPrompt\n"
    payload = {
        "files": [
            {"path": "managed-agent.md", "content": content},
            {
                "path": ".evoflux.json",
                "content": json.dumps({"modes": ["coding"]}),
            },
        ]
    }
    raw = json.dumps(payload, separators=(",", ":")).encode()
    change = _change("agent", hashlib.sha256(raw).hexdigest(), len(raw))
    version = EffectiveResourceVersion.model_validate(
        {
            **change.model_dump(exclude={"tombstone", "trust_required"}),
            "release_channel": "published",
            "payload": payload,
            "artifact_key": None,
        }
    )

    result = await GovernedResourceReconciler(
        ManagedResourceStore(governed_dirs / "state" / "conductor")
    ).reconcile_page(
        FakeClient(version),
        _page(change),
        expected_project_id="project-1",
        enforcement_mode="enforce",
    )

    assert result[0].modes == ["coding"]
    assert not (governed_dirs / "config" / "agents" / "managed-agent.md").exists()
    assert (
        governed_dirs / "config" / "agents" / "coding" / "managed-agent.md"
    ).read_text() == content


@pytest.mark.asyncio
async def test_same_version_backfills_a_missing_agent_mode_copy(
    governed_dirs: Path,
) -> None:
    content = "---\nname: managed-agent\ndescription: Test\n---\nPrompt\n"
    payload = {"files": [{"path": "managed-agent.md", "content": content}]}
    raw = json.dumps(payload, separators=(",", ":")).encode()
    change = _change("agent", hashlib.sha256(raw).hexdigest(), len(raw))
    version = EffectiveResourceVersion.model_validate(
        {
            **change.model_dump(exclude={"tombstone", "trust_required"}),
            "release_channel": "published",
            "payload": payload,
            "artifact_key": None,
        }
    )
    store = ManagedResourceStore(governed_dirs / "state" / "conductor")
    reconciler = GovernedResourceReconciler(store)

    await reconciler.reconcile_page(
        FakeClient(version),
        _page(change),
        expected_project_id="project-1",
        enforcement_mode="enforce",
    )
    coding_copy = governed_dirs / "config" / "agents" / "coding" / "managed-agent.md"
    coding_copy.unlink()

    replay_client = FakeClient(version)
    replayed = await reconciler.reconcile_page(
        replay_client,
        _page(change),
        expected_project_id="project-1",
        enforcement_mode="enforce",
    )

    assert replayed[0].observed_state == "applied"
    assert replay_client.version_requests == 1
    assert coding_copy.read_text() == content


@pytest.mark.asyncio
async def test_new_agent_version_waits_for_explicit_pull_before_replacing_source(
    governed_dirs: Path,
) -> None:
    first_content = "---\nname: managed-agent\ndescription: First\n---\nFirst prompt\n"
    first_payload = {"files": [{"path": "managed-agent.md", "content": first_content}]}
    first_raw = json.dumps(first_payload, separators=(",", ":")).encode()
    first_change = _change(
        "agent", hashlib.sha256(first_raw).hexdigest(), len(first_raw)
    )
    first_version = EffectiveResourceVersion.model_validate(
        {
            **first_change.model_dump(exclude={"tombstone", "trust_required"}),
            "release_channel": "published",
            "payload": first_payload,
            "artifact_key": None,
        }
    )
    store = ManagedResourceStore(governed_dirs / "state" / "conductor")
    reconciler = GovernedResourceReconciler(store)
    await reconciler.reconcile_page(
        FakeClient(first_version),
        _page(first_change),
        expected_project_id="project-1",
        enforcement_mode="enforce",
    )

    second_content = (
        "---\nname: managed-agent\ndescription: Second\n---\nSecond prompt\n"
    )
    second_payload = {
        "files": [{"path": "managed-agent.md", "content": second_content}]
    }
    second_raw = json.dumps(second_payload, separators=(",", ":")).encode()
    second_change = first_change.model_copy(
        update={
            "version_id": "agent-version-2",
            "version": "1.0.0",
            "description": "Managed release analyst",
            "changelog": "Adds breaking release policy checks.",
            "version_history": [
                ResourceVersionNotice(
                    version_id="agent-version-1",
                    version="0.1.0",
                    status="deprecated",
                    release_channel="published",
                    changelog="Initial release.",
                    deprecation_reason="Known policy bypass.",
                ),
                ResourceVersionNotice(
                    version_id="agent-version-2",
                    version="1.0.0",
                    status="published",
                    release_channel="published",
                    changelog="Adds breaking release policy checks.",
                ),
            ],
            "sha256": hashlib.sha256(second_raw).hexdigest(),
            "size": len(second_raw),
        }
    )
    second_version = EffectiveResourceVersion.model_validate(
        {
            **second_change.model_dump(exclude={"tombstone", "trust_required"}),
            "release_channel": "published",
            "payload": second_payload,
            "artifact_key": None,
        }
    )

    pending = await reconciler.reconcile_page(
        FakeClient(second_version),
        ResourceChangePage(
            schema_version=2,
            project_id="project-1",
            next_cursor="cursor-2",
            has_more=False,
            changes=[second_change],
        ),
        expected_project_id="project-1",
        enforcement_mode="report",
    )
    assert pending[0].observed_state == "update_pending"
    assert pending[0].local_content_sha256 is not None
    assert pending[0].applied_version == "0.1.0"
    assert pending[0].version == "1.0.0"
    provider = managed_resource_provider_from_record(pending[0], "Platform Core")
    assert provider.update_available is True
    assert provider.update_required is True
    assert provider.version_gap == "major"
    assert provider.current_version_deprecation_reason == "Known policy bypass."
    target = governed_dirs / "config" / "agents" / "managed-agent.md"
    assert target.read_text() == first_content

    enforce_replay = await reconciler.reconcile_page(
        FakeClient(second_version),
        ResourceChangePage(
            schema_version=2,
            project_id="project-1",
            next_cursor="cursor-3",
            has_more=False,
            changes=[second_change],
        ),
        expected_project_id="project-1",
        enforcement_mode="enforce",
    )
    assert enforce_replay[0].observed_state == "update_pending"
    assert target.read_text() == first_content

    applied = await reconciler.pull(FakeClient(second_version), "project-1", "agent-1")
    assert applied.observed_state == "applied"
    assert applied.version == "1.0.0"
    assert applied.applied_version == "1.0.0"
    assert target.read_text() == second_content


@pytest.mark.asyncio
async def test_enforce_rejects_agent_payload_that_is_not_evoflux_native(
    governed_dirs: Path,
) -> None:
    content = "---\nname: another-agent\ndescription: Wrong identity\n---\nPrompt\n"
    payload = {"files": [{"path": "managed-agent.md", "content": content}]}
    raw = json.dumps(payload, separators=(",", ":")).encode()
    change = _change("agent", hashlib.sha256(raw).hexdigest(), len(raw))
    version = EffectiveResourceVersion.model_validate(
        {
            **change.model_dump(exclude={"tombstone", "trust_required"}),
            "release_channel": "published",
            "payload": payload,
            "artifact_key": None,
        }
    )

    store = ManagedResourceStore(governed_dirs / "state" / "conductor")
    result = await GovernedResourceReconciler(store).reconcile_page(
        FakeClient(version),
        _page(change),
        expected_project_id="project-1",
        enforcement_mode="enforce",
    )

    assert result[0].observed_state == "error"
    assert store.load().committed_cursor is None
    assert not (governed_dirs / "config" / "agents" / "managed-agent.md").exists()


@pytest.mark.asyncio
async def test_enforce_applies_evoflux_native_skill_bundle(
    governed_dirs: Path,
) -> None:
    content = (
        "---\nname: managed-skill\ndescription: Managed workflow\n---\n"
        "Use the managed workflow.\n"
    )
    payload = {
        "files": [
            {"path": "SKILL.md", "content": content},
            {"path": "references/guide.md", "content": "# Guide\n"},
        ]
    }
    raw = json.dumps(payload, separators=(",", ":")).encode()
    change = _change("skill", hashlib.sha256(raw).hexdigest(), len(raw))
    version = EffectiveResourceVersion.model_validate(
        {
            **change.model_dump(exclude={"tombstone", "trust_required"}),
            "release_channel": "published",
            "payload": payload,
            "artifact_key": None,
        }
    )

    result = await GovernedResourceReconciler(
        ManagedResourceStore(governed_dirs / "state" / "conductor")
    ).reconcile_page(
        FakeClient(version),
        _page(change),
        expected_project_id="project-1",
        enforcement_mode="enforce",
    )

    assert result[0].observed_state == "applied"
    skill_root = governed_dirs / "config" / "skills" / "managed-skill"
    assert (skill_root / "SKILL.md").read_text() == content
    assert (skill_root / "references" / "guide.md").read_text() == "# Guide\n"
    assert json.loads((skill_root / ".evoflux.json").read_text()) == {
        "modes": ["work", "coding"]
    }


@pytest.mark.asyncio
async def test_plugin_is_installed_disabled_until_explicit_local_approval(
    governed_dirs: Path,
) -> None:
    plugin_json = json.dumps(
        {
            "$schema": PLUGIN_SCHEMA_ID,
            "name": "managed-plugin",
            "version": "0.1.0",
            "extensions": {},
        }
    )
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("plugin.json", plugin_json)
        bundle.writestr(
            "skills/managed-plugin/SKILL.md",
            "---\nname: managed-plugin\ndescription: Managed\n---\nInstructions\n",
        )
    artifact = archive.getvalue()
    digest = hashlib.sha256(artifact).hexdigest()
    change = _change("plugin", digest, len(artifact))
    version = EffectiveResourceVersion.model_validate(
        {
            **change.model_dump(exclude={"tombstone", "trust_required"}),
            "release_channel": "published",
            "payload": {"files": [{"path": "plugin.json", "content": plugin_json}]},
            "artifact_key": f"sha256/{digest[:2]}/{digest}",
        }
    )
    store = ManagedResourceStore(governed_dirs / "state" / "conductor")
    reconciler = GovernedResourceReconciler(store)
    results = await reconciler.reconcile_page(
        FakeClient(version, artifact),
        _page(change),
        expected_project_id="project-1",
        enforcement_mode="enforce",
    )
    staged = results[0]
    assert staged.observed_state == "trust_pending"
    assert staged.trust_review is not None
    installation = get_installation(staged.plugin_installation_id or "")
    assert installation is not None
    assert installation.enabled is False
    assert installation.managed_project_id == "project-1"
    replay = _page(change).model_copy(update={"next_cursor": "cursor-2"})
    replayed = await reconciler.reconcile_page(
        FakeClient(version, artifact),
        replay,
        expected_project_id="project-1",
        enforcement_mode="enforce",
    )
    assert replayed[0].observed_state == "trust_pending"
    assert replayed[0].plugin_installation_id == installation.id
    approved = reconciler.approve_plugin("project-1", "plugin-1")
    assert approved.observed_state == "applied"
    assert get_installation(installation.id).enabled is True  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_failed_resource_does_not_advance_cursor_and_retries(
    governed_dirs: Path,
) -> None:
    content = "---\nname: managed-agent\ndescription: Test\n---\nPrompt\n"
    payload = {"files": [{"path": "managed-agent.md", "content": content}]}
    raw = json.dumps(payload, separators=(",", ":")).encode()
    change = _change("agent", hashlib.sha256(raw).hexdigest(), len(raw))
    version = EffectiveResourceVersion.model_validate(
        {
            **change.model_dump(exclude={"tombstone", "trust_required"}),
            "release_channel": "published",
            "payload": payload,
            "artifact_key": None,
        }
    )
    store = ManagedResourceStore(governed_dirs / "state" / "conductor")
    reconciler = GovernedResourceReconciler(store)

    failed = await reconciler.reconcile_page(
        FakeClient(version.model_copy(update={"project_id": "wrong-project"})),
        _page(change),
        expected_project_id="project-1",
        enforcement_mode="enforce",
    )
    assert failed[0].observed_state == "error"
    assert store.load().committed_cursor is None

    retried = await reconciler.reconcile_page(
        FakeClient(version),
        _page(change),
        expected_project_id="project-1",
        enforcement_mode="enforce",
    )
    assert retried[0].observed_state == "applied"
    assert store.load().committed_cursor == "cursor-1"


@pytest.mark.asyncio
async def test_minimum_client_version_blocks_incompatible_release(
    governed_dirs: Path,
) -> None:
    content = "---\nname: managed-agent\ndescription: Test\n---\nPrompt\n"
    payload = {"files": [{"path": "managed-agent.md", "content": content}]}
    raw = json.dumps(payload, separators=(",", ":")).encode()
    change = _change("agent", hashlib.sha256(raw).hexdigest(), len(raw)).model_copy(
        update={"minimum_evoflux_version": "999.0.0"}
    )
    version = EffectiveResourceVersion.model_validate(
        {
            **change.model_dump(exclude={"tombstone", "trust_required"}),
            "release_channel": "published",
            "payload": payload,
            "artifact_key": None,
        }
    )
    store = ManagedResourceStore(governed_dirs / "state" / "conductor")
    results = await GovernedResourceReconciler(store).reconcile_page(
        FakeClient(version),
        _page(change),
        expected_project_id="project-1",
        enforcement_mode="enforce",
    )
    assert results[0].observed_state == "incompatible"
    assert not (governed_dirs / "config" / "agents" / "managed-agent.md").exists()
    assert store.load().committed_cursor == "cursor-1"


@pytest.mark.asyncio
async def test_tombstone_removes_unmodified_managed_agent(
    governed_dirs: Path,
) -> None:
    content = "---\nname: managed-agent\ndescription: Test\n---\nPrompt\n"
    payload = {"files": [{"path": "managed-agent.md", "content": content}]}
    raw = json.dumps(payload, separators=(",", ":")).encode()
    change = _change("agent", hashlib.sha256(raw).hexdigest(), len(raw))
    version = EffectiveResourceVersion.model_validate(
        {
            **change.model_dump(exclude={"tombstone", "trust_required"}),
            "release_channel": "published",
            "payload": payload,
            "artifact_key": None,
        }
    )
    store = ManagedResourceStore(governed_dirs / "state" / "conductor")
    reconciler = GovernedResourceReconciler(store)
    await reconciler.reconcile_page(
        FakeClient(version),
        _page(change),
        expected_project_id="project-1",
        enforcement_mode="enforce",
    )
    target = governed_dirs / "config" / "agents" / "managed-agent.md"
    assert target.exists()

    tombstone = change.model_copy(
        update={
            "version_id": None,
            "version": None,
            "release_channel": None,
            "sha256": None,
            "size": 0,
            "tombstone": True,
        }
    )
    removed = await reconciler.reconcile_page(
        FakeClient(version),
        ResourceChangePage(
            schema_version=2,
            project_id="project-1",
            next_cursor="cursor-2",
            has_more=False,
            changes=[tombstone],
        ),
        expected_project_id="project-1",
        enforcement_mode="enforce",
    )
    assert removed[0].observed_state == "removed"
    assert not target.exists()


@pytest.mark.asyncio
async def test_tombstone_keeps_locally_modified_managed_agent(
    governed_dirs: Path,
) -> None:
    content = "---\nname: managed-agent\ndescription: Test\n---\nPrompt\n"
    payload = {"files": [{"path": "managed-agent.md", "content": content}]}
    raw = json.dumps(payload, separators=(",", ":")).encode()
    change = _change("agent", hashlib.sha256(raw).hexdigest(), len(raw))
    version = EffectiveResourceVersion.model_validate(
        {
            **change.model_dump(exclude={"tombstone", "trust_required"}),
            "release_channel": "published",
            "payload": payload,
            "artifact_key": None,
        }
    )
    store = ManagedResourceStore(governed_dirs / "state" / "conductor")
    reconciler = GovernedResourceReconciler(store)
    await reconciler.reconcile_page(
        FakeClient(version),
        _page(change),
        expected_project_id="project-1",
        enforcement_mode="enforce",
    )
    target = governed_dirs / "config" / "agents" / "managed-agent.md"
    target.write_text(content + "Local change\n")

    tombstone = change.model_copy(
        update={
            "version_id": None,
            "version": None,
            "release_channel": None,
            "sha256": None,
            "size": 0,
            "tombstone": True,
        }
    )
    kept = await reconciler.reconcile_page(
        FakeClient(version),
        ResourceChangePage(
            schema_version=2,
            project_id="project-1",
            next_cursor="cursor-2",
            has_more=False,
            changes=[tombstone],
        ),
        expected_project_id="project-1",
        enforcement_mode="enforce",
    )
    assert kept[0].observed_state == "ownership_conflict"
    assert target.exists()
