from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.conductor.models import Manifest
from app.conductor.reconciler import ResourceReconciler
from app.core.config import settings


@pytest.fixture
def conductor_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    config = tmp_path / "config"
    state = tmp_path / "state"
    monkeypatch.setattr(settings, "EVOFLUX_CONFIG_DIR", str(config))
    monkeypatch.setattr(settings, "EVOFLUX_STATE_DIR", str(state))
    monkeypatch.setattr(settings, "AGENTS_DIR", str(config / "agents"))
    monkeypatch.setattr(settings, "SKILLS_DIR", str(config / "skills"))
    (config / "agents").mkdir(parents=True)
    (config / "skills").mkdir(parents=True)
    return tmp_path


def agent_manifest(*, revision: str = "m1") -> Manifest:
    return Manifest.model_validate(
        {
            "schema_version": 1,
            "revision": revision,
            "resources": [
                {
                    "kind": "agent",
                    "slug": "worker",
                    "revision": "r1",
                    "payload": {
                        "frontmatter": {"name": "worker", "role": "member"},
                        "system_prompt": "Managed prompt.",
                    },
                }
            ],
        }
    )


def test_drift_classifies_missing_modified_and_wrong_revision(
    conductor_dirs: Path,
) -> None:
    reconciler = ResourceReconciler(conductor_dirs / "state" / "conductor")
    manifest = agent_manifest()
    assert {item.category for item in reconciler.classify_drift(manifest)} == {
        "missing"
    }

    staged = reconciler.stage(manifest)[0]
    agent = conductor_dirs / "config" / "agents" / "worker.md"
    agent.write_text("locally modified", encoding="utf-8")
    reconciler.metadata_path.parent.mkdir(parents=True)
    reconciler.metadata_path.write_text(
        json.dumps(
            {
                "resources": {
                    "agent/worker": {
                        "revision": "old",
                        "artifact_hash": staged.artifact_hash,
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    categories = {item.category for item in reconciler.classify_drift(manifest)}
    assert categories == {"modified", "wrong_revision"}


def test_policy_classifies_unexpected_local_resource(conductor_dirs: Path) -> None:
    (conductor_dirs / "config" / "agents" / "local.md").write_text(
        "---\nname: local\nrole: member\n---\nLocal\n", encoding="utf-8"
    )
    manifest = Manifest.model_validate(
        {
            "schema_version": 1,
            "revision": "m1",
            "resources": [],
            "policy": {"allow_local_resources": False},
        }
    )

    drift = ResourceReconciler(conductor_dirs / "state" / "conductor").classify_drift(
        manifest
    )

    assert [(item.slug, item.category) for item in drift] == [("local", "policy")]


def test_drift_classifies_dependency_state(conductor_dirs: Path) -> None:
    manifest = Manifest.model_validate(
        {
            "schema_version": 1,
            "revision": "m1",
            "resources": [
                {
                    "kind": "skill",
                    "slug": "research",
                    "revision": "s1",
                    "payload": {"skill_md": "# Research"},
                },
                {
                    "kind": "agent",
                    "slug": "worker",
                    "payload": {
                        "frontmatter": {"name": "worker", "role": "member"},
                        "system_prompt": "Use research.",
                    },
                    "dependencies": [
                        {"kind": "skill", "slug": "research", "revision": "s1"}
                    ],
                },
            ],
        }
    )

    drift = ResourceReconciler(conductor_dirs / "state" / "conductor").classify_drift(
        manifest
    )

    worker_categories = {
        item.category
        for item in drift
        if item.kind == "agent" and item.slug == "worker"
    }
    assert worker_categories == {"missing", "dependency"}


@pytest.mark.asyncio
async def test_apply_failure_restores_atomic_snapshot(
    conductor_dirs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent = conductor_dirs / "config" / "agents" / "worker.md"
    original = "---\nname: worker\nrole: member\n---\nOriginal\n"
    agent.write_text(original, encoding="utf-8")
    reconciler = ResourceReconciler(conductor_dirs / "state" / "conductor")

    async def fail_after_write(*_args, **_kwargs) -> None:
        agent.write_text("partially applied", encoding="utf-8")
        raise RuntimeError("apply failed")

    monkeypatch.setattr(reconciler, "_apply", fail_after_write)

    with pytest.raises(RuntimeError, match="apply failed"):
        await reconciler.reconcile(agent_manifest(), enforcement_mode="enforce")

    assert agent.read_text(encoding="utf-8") == original
