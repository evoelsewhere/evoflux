from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import yaml
from fastapi.testclient import TestClient

from app.agent.schemas.chat import AssistantMessage
from app.services.easd_repository_store import EasdRepositoryStore, document_hash

pytestmark = pytest.mark.usefixtures("setup_db")


@pytest.fixture
def client():
    from app.api.app import create_app

    yield TestClient(create_app())


def _payload(workspace: str, *, risk_tier: str = "standard") -> dict:
    return {
        "workspace": workspace,
        "specification": {
            "title": "EASD API",
            "problem": "Completion is not traceable.",
            "outcome": "AC-1 has machine evidence.",
            "impact_targets": [
                {
                    "repository": Path(workspace).name,
                    "path": "app/service.py",
                    "reason": "Owns the API behavior",
                }
            ],
            "risk_tier": risk_tier,
            "criteria": [
                {
                    "id": "AC-1",
                    "statement": "The EASD API roundtrip succeeds.",
                    "evidence_policy": {
                        "allowed_kinds": ["machine", "review"],
                        "machine_required": True,
                        "minimum_passes": 1,
                    },
                }
            ],
        },
    }


def _approve_plan(client, detail: dict) -> dict:
    run = detail["run"]
    spec = detail["active_spec"] or next(
        item for item in detail["revisions"] if item["status"] == "accepted"
    )
    missions = [
        {
            "id": "M1",
            "kind": "implementation",
            "title": "Implement accepted behavior",
            "goal": "Implement AC-1.",
            "acceptance_criteria": ["AC-1"],
            "target_repositories": [Path(run["workspace"]).name],
            "target_paths": ["app/service.py"],
            "expected_output": "Implementation and evidence.",
        }
    ]
    review_required = run["risk_tier"] in {"cross_layer", "critical"}
    missions.append(
        {
            "id": "M2",
            "kind": "review",
            "title": "Review accepted behavior",
            "goal": (
                "Independently review AC-1."
                if review_required
                else "Review AC-1 against the integrated result."
            ),
            "acceptance_criteria": ["AC-1"],
            "target_repositories": [Path(run["workspace"]).name],
            "target_paths": ["app/service.py"],
            "depends_on": ["M1"],
            "expected_output": "Cited review evidence.",
            "isolation": "shared",
        }
    )
    created = client.post(
        f"/api/easd/runs/{run['id']}/plans",
        json={
            "plan": {
                "spec_hash": spec["content_hash"],
                "review_required": review_required,
                "missions": missions,
            }
        },
    )
    assert created.status_code == 201, created.text
    plan = created.json()
    accepted = client.post(
        f"/api/easd/runs/{run['id']}/plans/{plan['id']}/accept",
        json={"expected_hash": plan["content_hash"]},
    )
    assert accepted.status_code == 200, accepted.text
    return accepted.json()


def _initialize(client, workspace: str, *, project_id: str | None = None) -> dict:
    response = client.post(
        "/api/easd/setup",
        json={"workspace": workspace, "project_id": project_id},
    )
    assert response.status_code == 200
    assert response.json()["ready"] is True
    repository = response.json()["repositories"][0]
    assert "schema_version" not in repository
    assert "skill_bundle_version" not in repository
    assert repository["data_directory"] == "documents/easd"
    assert repository["rules_path"] == ".evoflux/easd/RULES.md"
    assert repository["skills_path"] == ".evoflux/skills"
    assert repository["skill_names"] == [
        "easd-specify",
        "easd-plan",
        "easd-implement",
        "easd-review",
        "easd-verify",
    ]
    return response.json()


def _start_run(client, workspace: str, run_id: str, session_id: str | None = None):
    if session_id is None:
        session_id = client.post(
            "/api/team/sessions/resolve",
            json={"mode": "coding", "workspace": workspace, "create": True},
        ).json()["id"]
    return client.post(
        f"/api/easd/runs/{run_id}/start",
        json={"session_id": session_id},
    )


def test_easd_api_create_accept_start_evidence_and_converge(client, tmp_path):
    _initialize(client, str(tmp_path))
    session = client.post(
        "/api/team/sessions/resolve",
        json={"mode": "coding", "workspace": str(tmp_path), "create": True},
    ).json()
    payload = _payload(str(tmp_path))
    payload["session_id"] = session["id"]
    payload["specification"]["criteria"][0]["evidence_policy"] = {
        "allowed_kinds": ["review"],
        "machine_required": False,
        "minimum_passes": 1,
    }
    created = client.post("/api/easd/runs", json=payload)
    assert created.status_code == 201
    detail = created.json()
    run_id = detail["run"]["id"]
    draft = detail["revisions"][0]
    assert detail["criteria"] == []
    assert detail["action_rail"] == {
        "phase": "draft",
        "primary_action": "approve_specification",
        "actions": [
            {
                "id": "approve_specification",
                "label": "Approve specification",
                "state": "available",
                "blockers": [],
            },
            {
                "id": "retry_specification",
                "label": "Redraft in chat",
                "state": "available",
                "blockers": [],
            },
        ],
    }
    trace = client.get(f"/api/easd/runs/{run_id}/trace")
    assert trace.status_code == 200
    trace_body = trace.json()
    assert trace_body["version"] == 1
    assert trace_body["run_id"] == run_id
    assert [event["event"] for event in trace_body["events"]] == ["intent_created"]
    assert any(node["kind"] == "specification" for node in trace_body["nodes"])
    assert any(node["kind"] == "criterion" for node in trace_body["nodes"])
    assert any(edge["kind"] == "defines" for edge in trace_body["edges"])

    accepted = client.post(
        f"/api/easd/runs/{run_id}/revisions/{draft['id']}/accept",
        json={"expected_hash": draft["content_hash"]},
    )
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "accepted"
    catalog_directory = next(
        (tmp_path / "documents" / "easd" / "specs").glob(f"*--{run_id}")
    )
    catalog_index = yaml.safe_load((catalog_directory / "index.yaml").read_text())
    published_revision = yaml.safe_load(
        (catalog_directory / catalog_index["current_path"]).read_text()
    )
    assert catalog_index["current_hash"] == draft["content_hash"]
    assert published_revision["content_hash"] == draft["content_hash"]

    (catalog_directory / catalog_index["current_path"]).unlink()
    (catalog_directory / "revisions").rmdir()
    (catalog_directory / "index.yaml").unlink()
    catalog_directory.rmdir()
    repaired = client.post(
        f"/api/easd/runs/{run_id}/revisions/{draft['id']}/accept",
        json={"expected_hash": draft["content_hash"]},
    )
    assert repaired.status_code == 200
    assert (
        next((tmp_path / "documents" / "easd" / "specs").glob(f"*--{run_id}"))
        .joinpath("index.yaml")
        .is_file()
    )

    _approve_plan(client, client.get(f"/api/easd/runs/{run_id}").json())
    planned_trace = client.get(f"/api/easd/runs/{run_id}/trace").json()
    assert any(node["kind"] == "plan" for node in planned_trace["nodes"])
    assert (
        sum(node["kind"] == "mission_contract" for node in planned_trace["nodes"]) == 2
    )
    assert any(edge["kind"] == "compiled_to" for edge in planned_trace["edges"])
    active = _start_run(client, str(tmp_path), run_id, session["id"])
    assert active.status_code == 200
    assert active.json()["status"] == "active"

    evidence = client.post(
        f"/api/easd/runs/{run_id}/evidence",
        json={
            "spec_hash": draft["content_hash"],
            "criterion_ids": ["AC-1"],
            "producer": "independent-reviewer",
            "kind": "review",
            "result": "passed",
            "summary": "focused tests pass",
            "revision": "deadbeef",
            "artifact_hash": "f" * 64,
            "source_key": "api-test-evidence",
        },
    )
    assert evidence.status_code == 201

    fetched = client.get(f"/api/easd/runs/{run_id}")
    assert fetched.status_code == 200
    assert fetched.json()["criteria"][0]["status"] == "passed"

    legacy_fetched = client.get(f"/api/trace/runs/{run_id}")
    assert legacy_fetched.status_code == 200
    assert legacy_fetched.json() == fetched.json()

    review = client.post(
        f"/api/easd/runs/{run_id}/review/start",
        json={"session_id": session["id"]},
    )
    assert review.status_code == 200
    assert review.json()["status"] == "reviewing"
    verifying = client.post(
        f"/api/easd/runs/{run_id}/verification/start",
        json={"session_id": session["id"]},
    )
    assert verifying.status_code == 200
    assert verifying.json()["status"] == "verifying"

    converged = client.post(f"/api/easd/runs/{run_id}/converge")
    assert converged.status_code == 200
    assert converged.json()["report"]["criteria"]["passed"] == 1
    run_directory = next(
        (tmp_path / "documents" / "easd" / "runs").glob(f"*--{run_id}")
    )
    stored_run = yaml.safe_load((run_directory / "run.yaml").read_text())
    assert stored_run["status"] == "converged"
    assert stored_run["delivery_flow"]["mode"] == "planned"
    assert stored_run["spec_catalog_index"].endswith(f"--{run_id}/index.yaml")
    assert len(list((run_directory / "specifications").glob("*.yaml"))) == 1
    assert len(list((run_directory / "plans").glob("*.yaml"))) == 1
    assert len(list((run_directory / "evidence").glob("*.yaml"))) == 1
    assert (run_directory / "convergence.yaml").is_file()
    assert len(list((run_directory / "events").glob("*.yaml"))) >= 6


def test_easd_api_rejects_caller_supplied_machine_evidence(client, tmp_path):
    _initialize(client, str(tmp_path))
    created = client.post("/api/easd/runs", json=_payload(str(tmp_path))).json()
    run_id = created["run"]["id"]
    draft = created["revisions"][0]
    client.post(
        f"/api/easd/runs/{run_id}/revisions/{draft['id']}/accept",
        json={"expected_hash": draft["content_hash"]},
    )
    _start_run(client, str(tmp_path), run_id)

    response = client.post(
        f"/api/easd/runs/{run_id}/evidence",
        json={
            "spec_hash": draft["content_hash"],
            "criterion_ids": ["AC-1"],
            "producer": "untrusted-caller",
            "kind": "machine",
            "result": "passed",
            "summary": "caller claims a machine result",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]


def test_easd_run_persists_reviewed_authoring_provenance(client, tmp_path):
    _initialize(client, str(tmp_path))
    payload = _payload(str(tmp_path))
    payload["authoring"] = {
        "generations": [
            {
                "generation_id": "00000000-0000-0000-0000-000000000123",
                "generated_at": "2026-08-24T00:00:00Z",
                "provider": "test",
                "model": "test:model",
                "confidence": 0.91,
                "rationale": "Grounded in the API and tests.",
                "context_fingerprint": "a" * 64,
                "base_fingerprint": "b" * 64,
                "applied_sections": ["scope", "proof"],
                "edited_sections": ["proof"],
                "sources": [
                    {
                        "repository": "repo",
                        "path": "tests/test_api.py",
                        "kind": "test",
                        "sha256": "c" * 64,
                        "truncated": False,
                        "used_for": ["proof"],
                    }
                ],
                "usage": {"input": 100, "output": 40},
            }
        ]
    }

    response = client.post("/api/easd/runs", json=payload)

    assert response.status_code == 201
    authoring = response.json()["revisions"][0]["authoring"]
    assert authoring["generations"][0]["model"] == "test:model"
    assert authoring["generations"][0]["edited_sections"] == ["proof"]


def test_easd_api_rejects_stale_spec_and_lists_by_workspace(client, tmp_path):
    _initialize(client, str(tmp_path))
    created = client.post("/api/easd/runs", json=_payload(str(tmp_path))).json()
    run_id = created["run"]["id"]
    draft = created["revisions"][0]

    stale = client.post(
        f"/api/easd/runs/{run_id}/revisions/{draft['id']}/accept",
        json={"expected_hash": "0" * 64},
    )
    assert stale.status_code == 409

    listed = client.get("/api/easd/runs", params={"workspace": str(tmp_path)})
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["runs"]] == [run_id]


def test_repository_status_wins_over_local_runtime_projection(client, tmp_path):
    _initialize(client, str(tmp_path))
    created = client.post("/api/easd/runs", json=_payload(str(tmp_path))).json()
    run_id = created["run"]["id"]
    store = EasdRepositoryStore(tmp_path)
    current = store.load_run(run_id).run
    store.update_run(
        run_id,
        {**current, "status": "cancelled"},
        expected_hash=document_hash(current),
        event={
            "event": "collaborator_cancelled",
            "from_status": current["status"],
            "to_status": "cancelled",
            "actor": "collaborator",
        },
    )

    listed = client.get("/api/easd/runs", params={"workspace": str(tmp_path)})

    assert listed.status_code == 200
    assert listed.json()["runs"][0]["status"] == "cancelled"


def test_easd_api_blocking_deviation_returns_structured_convergence_reasons(
    client, tmp_path
):
    _initialize(client, str(tmp_path))
    session = client.post(
        "/api/team/sessions/resolve",
        json={"mode": "coding", "workspace": str(tmp_path), "create": True},
    ).json()
    payload = _payload(str(tmp_path))
    payload["session_id"] = session["id"]
    payload["specification"]["criteria"][0]["evidence_policy"]["machine_required"] = (
        False
    )
    created = client.post("/api/easd/runs", json=payload).json()
    run_id = created["run"]["id"]
    draft = created["revisions"][0]
    client.post(
        f"/api/easd/runs/{run_id}/revisions/{draft['id']}/accept",
        json={"expected_hash": draft["content_hash"]},
    )
    _approve_plan(client, client.get(f"/api/easd/runs/{run_id}").json())
    _start_run(client, str(tmp_path), run_id, session["id"])
    client.post(
        f"/api/easd/runs/{run_id}/evidence",
        json={
            "spec_hash": draft["content_hash"],
            "criterion_ids": ["AC-1"],
            "producer": "reviewer",
            "kind": "review",
            "result": "passed",
            "summary": "review passed",
        },
    )
    deviation = client.post(
        f"/api/easd/runs/{run_id}/deviations",
        json={
            "description": "Public behavior must change.",
            "criterion_id": "AC-1",
        },
    )
    assert deviation.status_code == 201
    assert (
        client.post(
            f"/api/easd/runs/{run_id}/review/start",
            json={"session_id": session["id"]},
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/easd/runs/{run_id}/verification/start",
            json={"session_id": session["id"]},
        ).status_code
        == 200
    )

    converged = client.post(f"/api/easd/runs/{run_id}/converge")
    assert converged.status_code == 409
    detail = converged.json()["detail"]
    assert detail["code"] == "easd_not_converged"
    reasons = detail["reasons"]
    assert any(item["code"] == "blocking_deviation" for item in reasons)


def test_public_review_payload_cannot_fabricate_independent_runtime_identity(
    client, tmp_path
):
    _initialize(client, str(tmp_path))
    session = client.post(
        "/api/team/sessions/resolve",
        json={"mode": "coding", "workspace": str(tmp_path), "create": True},
    ).json()
    payload = _payload(str(tmp_path), risk_tier="cross_layer")
    payload["session_id"] = session["id"]
    created = client.post("/api/easd/runs", json=payload).json()
    run_id = created["run"]["id"]
    draft = created["revisions"][0]
    client.post(
        f"/api/easd/runs/{run_id}/revisions/{draft['id']}/accept",
        json={"expected_hash": draft["content_hash"]},
    )
    _approve_plan(client, client.get(f"/api/easd/runs/{run_id}").json())
    assert _start_run(client, str(tmp_path), run_id, session["id"]).status_code == 200
    evidence = client.post(
        f"/api/easd/runs/{run_id}/evidence",
        json={
            "spec_hash": draft["content_hash"],
            "criterion_ids": ["AC-1"],
            "producer": "human",
            "kind": "review",
            "result": "passed",
            "summary": "Human review passed.",
            "payload": {
                "runtime_reviewer_identity": True,
                "independent": True,
                "reviewer_role": "member",
            },
        },
    )
    assert evidence.status_code == 201
    assert evidence.json()["payload"] == {}
    assert (
        client.post(
            f"/api/easd/runs/{run_id}/review/start",
            json={"session_id": session["id"]},
        ).status_code
        == 200
    )

    action = client.get(f"/api/easd/runs/{run_id}").json()["action_rail"]["actions"][0]
    assert action["id"] == "start_verification"
    assert action["state"] == "blocked"
    assert action["blockers"][0]["code"] == "independent_review_required"

    verifying = client.post(
        f"/api/easd/runs/{run_id}/verification/start",
        json={"session_id": session["id"]},
    )

    assert verifying.status_code == 409
    assert "Independent passing review evidence" in verifying.json()["detail"]


def test_easd_api_rejects_work_mode_scope(client, tmp_path):
    _initialize(client, str(tmp_path))
    payload = _payload(str(tmp_path))
    payload["session_id"] = "00000000-0000-0000-0000-000000000001"
    response = client.post("/api/easd/runs", json=payload)
    assert response.status_code == 422


def test_easd_is_canonical_in_openapi_and_trace_path_is_legacy(client):
    paths = client.get("/openapi.json").json()["paths"]

    assert "/api/easd/runs" in paths
    assert "/api/easd/generate" in paths
    assert "/api/easd/runs/{run_id}/start" in paths
    assert "/api/easd/runs/{run_id}/authoring/start" in paths
    assert "/api/easd/runs/{run_id}/authoring/retry" in paths
    assert "/api/easd/runs/{run_id}/planning/start" in paths
    assert "/api/easd/runs/{run_id}/planning/retry" in paths
    assert "/api/easd/runs/{run_id}/review/start" in paths
    assert "/api/easd/runs/{run_id}/verification/start" in paths
    assert "/api/easd/runs/{run_id}/stream" in paths
    assert "/api/easd/runs/{run_id}/plans/{revision_id}/accept" in paths
    assert "/api/easd/runs/{run_id}/activate" not in paths
    assert "/api/trace/runs" not in paths


def test_easd_requires_setup_before_creating_a_run(client, tmp_path):
    setup = client.get("/api/easd/setup", params={"workspace": str(tmp_path)})
    assert setup.status_code == 200
    assert setup.json()["ready"] is False

    response = client.post("/api/easd/runs", json=_payload(str(tmp_path)))

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "easd_setup_required"


def test_easd_setup_api_exposes_and_completes_legacy_skill_upgrade(client, tmp_path):
    easd = tmp_path / ".evoflux" / "easd"
    (easd / "specs").mkdir(parents=True)
    (easd / "config.json").write_text(
        json.dumps(
            {
                "methodology": "EASD",
                "product": "Evo Agent Specs",
                "schema_version": 1,
                "specs_directory": ".evoflux/easd/specs",
            }
        ),
        encoding="utf-8",
    )

    before = client.get("/api/easd/setup", params={"workspace": str(tmp_path)})

    assert before.status_code == 200
    repository = before.json()["repositories"][0]
    assert repository["status"] == "upgrade_required"
    assert repository["skill_names"] == [
        "easd-specify",
        "easd-plan",
        "easd-implement",
        "easd-review",
        "easd-verify",
    ]

    upgraded = client.post("/api/easd/setup", json={"workspace": str(tmp_path)})

    assert upgraded.status_code == 200
    repository = upgraded.json()["repositories"][0]
    assert repository["status"] == "ready"
    assert "schema_version" not in repository
    assert "skill_bundle_version" not in repository
    assert repository["data_directory"] == "documents/easd"
    assert (tmp_path / ".evoflux" / "skills" / "easd-specify" / "SKILL.md").is_file()


def test_easd_setup_api_accepts_custom_repository_data_directory(client, tmp_path):
    response = client.post(
        "/api/easd/setup",
        json={
            "workspace": str(tmp_path),
            "data_directory": "documents/easd",
        },
    )

    assert response.status_code == 200
    repository = response.json()["repositories"][0]
    assert repository["data_directory"] == "documents/easd"
    assert (tmp_path / "documents" / "easd" / "templates" / "run.yaml").is_file()


def test_easd_run_create_requires_exactly_one_intent_or_specification(client, tmp_path):
    _initialize(client, str(tmp_path))
    missing = client.post("/api/easd/runs", json={"workspace": str(tmp_path)})
    both = client.post(
        "/api/easd/runs",
        json={
            **_payload(str(tmp_path)),
            "intent": {
                "title": "Ambiguous create",
                "problem": "Two authoring sources were supplied.",
            },
        },
    )

    assert missing.status_code == 422
    assert both.status_code == 422


def test_easd_accepted_spec_plans_then_starts_atomically_in_a_coding_chat(
    client, tmp_path, monkeypatch
):
    _initialize(client, str(tmp_path))
    session = client.post(
        "/api/team/sessions/resolve",
        json={"mode": "coding", "workspace": str(tmp_path), "create": True},
    ).json()
    created = client.post("/api/easd/runs", json=_payload(str(tmp_path))).json()
    run_id = created["run"]["id"]
    draft = created["revisions"][0]
    client.post(
        f"/api/easd/runs/{run_id}/revisions/{draft['id']}/accept",
        json={"expected_hash": draft["content_hash"]},
    )

    premature = client.post(
        f"/api/easd/runs/{run_id}/start",
        json={"session_id": session["id"]},
    )
    assert premature.status_code == 409
    assert "accepted implementation plan" in premature.json()["detail"]
    planning = client.post(
        f"/api/easd/runs/{run_id}/planning/start",
        json={"session_id": session["id"]},
    )
    assert planning.status_code == 200
    assert planning.json()["status"] == "planning"
    _approve_plan(client, client.get(f"/api/easd/runs/{run_id}").json())

    monkeypatch.setattr(
        "app.api.routes.easd.stream_store.running_session_ids",
        lambda: {session["id"]},
    )
    busy = client.post(
        f"/api/easd/runs/{run_id}/start",
        json={"session_id": session["id"]},
    )
    assert busy.status_code == 409
    assert busy.json()["detail"]["code"] == "easd_chat_busy"
    unchanged = client.get(f"/api/easd/runs/{run_id}").json()["run"]
    assert unchanged["session_id"] == session["id"]
    assert unchanged["status"] == "planned"

    monkeypatch.setattr(
        "app.api.routes.easd.stream_store.running_session_ids", lambda: set()
    )
    started = client.post(
        f"/api/easd/runs/{run_id}/start",
        json={"session_id": session["id"]},
    )

    assert started.status_code == 200
    assert started.json()["session_id"] == session["id"]
    assert started.json()["status"] == "active"


def test_easd_minimal_intent_starts_spec_authoring_without_a_draft(
    client, tmp_path, monkeypatch
):
    _initialize(client, str(tmp_path))
    session = client.post(
        "/api/team/sessions/resolve",
        json={"mode": "coding", "workspace": str(tmp_path), "create": True},
    ).json()
    created = client.post(
        "/api/easd/runs",
        json={
            "workspace": str(tmp_path),
            "session_id": session["id"],
            "intent": {
                "title": "Draft from Intent",
                "problem": "The specification does not exist yet.",
            },
        },
    )

    assert created.status_code == 201, created.text
    detail = created.json()
    run_id = detail["run"]["id"]
    assert detail["run"]["status"] == "intent"
    assert detail["run"]["intent"]["outcome"] == ""
    assert detail["revisions"] == []

    monkeypatch.setattr(
        "app.api.routes.easd.stream_store.running_session_ids",
        lambda: {session["id"]},
    )
    busy = client.post(
        f"/api/easd/runs/{run_id}/authoring/start",
        json={"session_id": session["id"]},
    )
    assert busy.status_code == 409
    assert client.get(f"/api/easd/runs/{run_id}").json()["run"]["status"] == "intent"

    monkeypatch.setattr(
        "app.api.routes.easd.stream_store.running_session_ids", lambda: set()
    )
    started = client.post(
        f"/api/easd/runs/{run_id}/authoring/start",
        json={"session_id": session["id"]},
    )
    assert started.status_code == 200
    assert started.json()["status"] == "authoring"

    draft = client.post(
        f"/api/easd/runs/{run_id}/revisions",
        json={"specification": _payload(str(tmp_path))["specification"]},
    )
    assert draft.status_code == 201, draft.text
    assert client.get(f"/api/easd/runs/{run_id}").json()["run"]["status"] == "draft"

    retried = client.post(
        f"/api/easd/runs/{run_id}/authoring/retry",
        json={"session_id": session["id"]},
    )
    assert retried.status_code == 200, retried.text
    assert retried.json()["status"] == "authoring"


def test_easd_recovery_redrafts_idempotently_and_rejects_stale_generation(
    client, tmp_path
):
    _initialize(client, str(tmp_path))
    session = client.post(
        "/api/team/sessions/resolve",
        json={"mode": "coding", "workspace": str(tmp_path), "create": True},
    ).json()
    payload = _payload(str(tmp_path))
    payload["session_id"] = session["id"]
    created = client.post("/api/easd/runs", json=payload).json()
    run_id = created["run"]["id"]

    preview = client.get(f"/api/easd/runs/{run_id}/recovery")
    assert preview.status_code == 200
    body = preview.json()
    assert body["store_generation"] == 1
    assert body["actions"][0]["id"] == "redraft_specification"
    assert body["actions"][0]["reuses"][0] == "Specification revision v1"
    draft_hash = created["revisions"][0]["content_hash"]
    assert draft_hash not in " ".join(body["actions"][0]["reuses"])
    assert "Prior revisions and attempts" in body["actions"][0]["preserves"]
    request = {
        "action_id": "redraft_specification",
        "session_id": session["id"],
        "expected_generation": body["store_generation"],
        "idempotency_key": "00000000-0000-0000-0000-000000000101",
    }

    recovered = client.post(f"/api/easd/runs/{run_id}/recovery", json=request)
    repeated = client.post(f"/api/easd/runs/{run_id}/recovery", json=request)

    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["run"]["status"] == "authoring"
    assert repeated.status_code == 200
    assert repeated.json() == recovered.json()
    stale = client.post(
        f"/api/easd/runs/{run_id}/recovery",
        json={
            **request,
            "action_id": "retry_specification",
            "idempotency_key": "00000000-0000-0000-0000-000000000102",
        },
    )
    assert stale.status_code == 409
    assert "generation changed" in stale.json()["detail"]

    fresh = client.get(f"/api/easd/runs/{run_id}/recovery").json()
    wrong_session = client.post(
        f"/api/easd/runs/{run_id}/recovery",
        json={
            "action_id": "retry_specification",
            "session_id": "00000000-0000-0000-0000-000000000999",
            "expected_generation": fresh["store_generation"],
            "idempotency_key": "00000000-0000-0000-0000-000000000104",
        },
    )
    assert wrong_session.status_code == 422
    assert "requires a Coding session" in wrong_session.json()["detail"]

    trace = client.get(f"/api/easd/runs/{run_id}/trace").json()
    assert [
        event["event"]
        for event in trace["events"]
        if event["event"] == "specification_authoring_retried"
    ] == ["specification_authoring_retried"]


def test_easd_recovery_retries_active_phase_without_deleting_history(client, tmp_path):
    _initialize(client, str(tmp_path))
    session = client.post(
        "/api/team/sessions/resolve",
        json={"mode": "coding", "workspace": str(tmp_path), "create": True},
    ).json()
    payload = _payload(str(tmp_path))
    payload["session_id"] = session["id"]
    created = client.post("/api/easd/runs", json=payload).json()
    run_id = created["run"]["id"]
    draft = created["revisions"][0]
    client.post(
        f"/api/easd/runs/{run_id}/revisions/{draft['id']}/accept",
        json={"expected_hash": draft["content_hash"]},
    )
    _approve_plan(client, client.get(f"/api/easd/runs/{run_id}").json())
    assert _start_run(client, str(tmp_path), run_id, session["id"]).status_code == 200
    preview = client.get(f"/api/easd/runs/{run_id}/recovery").json()
    assert preview["actions"][0]["id"] == "retry_implementation"

    recovered = client.post(
        f"/api/easd/runs/{run_id}/recovery",
        json={
            "action_id": "retry_implementation",
            "session_id": session["id"],
            "expected_generation": preview["store_generation"],
            "idempotency_key": "00000000-0000-0000-0000-000000000103",
        },
    )

    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["run"]["status"] == "active"
    assert recovered.json()["recovery"]["from_status"] == "active"
    trace = client.get(f"/api/easd/runs/{run_id}/trace").json()
    assert trace["events"][-1]["event"] == "implementation_retried"


def test_easd_project_setup_initializes_each_repository(client, tmp_path):
    api_repo = tmp_path / "api"
    web_repo = tmp_path / "web"
    api_repo.mkdir()
    web_repo.mkdir()
    project = client.post(
        "/api/team/projects",
        json={
            "name": "Multi-repo EASD",
            "workspace_paths": [str(api_repo), str(web_repo)],
        },
    ).json()
    project_id = project["id"]

    partial = client.post(
        "/api/easd/setup",
        json={
            "workspace": str(api_repo),
            "project_id": project_id,
            "repository_paths": [str(api_repo)],
        },
    )
    assert partial.status_code == 200
    assert partial.json()["installed_count"] == 1
    assert partial.json()["ready"] is False

    payload = _payload(str(api_repo))
    payload["project_id"] = project_id
    blocked = client.post("/api/easd/runs", json=payload)
    assert blocked.status_code == 409

    ready = _initialize(client, str(api_repo), project_id=project_id)
    assert ready["repository_count"] == 2
    assert [item["status"] for item in ready["repositories"]] == ["ready", "ready"]

    created = client.post("/api/easd/runs", json=payload)
    assert created.status_code == 201
    project_session = client.post(
        "/api/team/sessions/resolve",
        json={"mode": "coding", "project_id": project_id, "create": True},
    ).json()
    sibling_owned = client.post(
        "/api/easd/runs",
        json={
            "workspace": str(web_repo),
            "project_id": project_id,
            "session_id": project_session["id"],
            "intent": {
                "title": "Web-owned Intent",
                "problem": "The owning repository differs from the session primary.",
            },
        },
    )
    assert sibling_owned.status_code == 201, sibling_owned.text
    assert sibling_owned.json()["run"]["workspace"] == str(web_repo.resolve())


def test_easd_generation_uses_authorized_project_context_without_creating_run(
    client, tmp_path, monkeypatch
):
    api_repo = tmp_path / "api"
    web_repo = tmp_path / "web"
    api_repo.mkdir()
    web_repo.mkdir()
    (api_repo / "AGENTS.md").write_text(
        "Keep API responses stable.\n", encoding="utf-8"
    )
    (api_repo / "routes.py").write_text(
        "def get_items(): return []\n", encoding="utf-8"
    )
    (web_repo / "AGENTS.md").write_text(
        "Use client queries for server state.\n", encoding="utf-8"
    )
    (web_repo / "view.tsx").write_text(
        "export const View = () => null\n", encoding="utf-8"
    )
    project = client.post(
        "/api/team/projects",
        json={
            "name": "Generated EASD",
            "workspace_paths": [str(api_repo), str(web_repo)],
        },
    ).json()
    project_id = project["id"]
    _initialize(client, str(api_repo), project_id=project_id)
    session = client.post(
        "/api/team/sessions/resolve",
        json={"mode": "coding", "project_id": project_id, "create": True},
    ).json()
    payload = {
        "status": "ready",
        "confidence": 0.9,
        "rationale": "Grounded in both repositories.",
        "questions": [],
        "outcome": "The API and UI expose one observable project feature.",
        "scope": {
            "goals": ["Add the feature"],
            "non_goals": [],
            "source_refs": [],
            "impact_targets": [
                {
                    "repository": "api",
                    "path": "routes.py",
                    "module": "API",
                    "reason": "Owns behavior",
                }
            ],
            "constraints": [],
            "used_sources": [],
        },
        "proof": {
            "risk_tier": "cross_layer",
            "criteria": [
                {
                    "id": "AC-1",
                    "statement": "The API and UI expose the feature.",
                    "required": True,
                    "evidence_policy": {
                        "allowed_kinds": ["machine", "review"],
                        "machine_required": True,
                        "minimum_passes": 1,
                    },
                }
            ],
            "verification_commands": ["pytest -q"],
            "independent_review_required": True,
            "used_sources": [],
        },
    }
    provider = SimpleNamespace(
        provider_name="test",
        chat=AsyncMock(return_value=AssistantMessage(content=json.dumps(payload))),
    )
    team = SimpleNamespace(
        lead=SimpleNamespace(agent=SimpleNamespace(llm_provider=provider)),
        _provider_factory=None,
    )
    monkeypatch.setattr(
        "app.api.routes.easd.team_manager.find_team_for_session",
        lambda _session_id: team,
    )

    response = client.post(
        "/api/easd/generate",
        json={
            "workspace": str(api_repo),
            "project_id": project_id,
            "session_id": session["id"],
            "target": "both",
            "intent": {
                "title": "Add project feature",
                "problem": "The feature is missing.",
            },
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ready"
    assert body["outcome"] == "The API and UI expose one observable project feature."
    assert body["proof"]["independent_review_required"] is True
    assert {item["repository"] for item in body["provenance"]} == {"api", "web"}
    assert (
        client.get("/api/easd/runs", params={"project_id": project_id}).json()["runs"]
        == []
    )
    sent = provider.chat.await_args.args[0][1].content
    assert "api:routes.py" in sent
    assert "web:view.tsx" in sent
