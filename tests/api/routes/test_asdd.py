from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.usefixtures("setup_db")

DELTA = """## ADDED Requirements

### Requirement: Slug identity

A change SHALL be identified by its directory name.

#### Scenario: Two chats open the same change

- **WHEN** two Coding chats point at the same change
- **THEN** both read and write the same change folder
"""


@pytest.fixture
def client():
    from app.api.app import create_app

    yield TestClient(create_app())


@pytest.fixture
def workspace(tmp_path: Path) -> str:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "README.md").write_text("# repo\n", encoding="utf-8")
    return str(root)


def install(client: TestClient, workspace: str) -> dict:
    response = client.post("/api/asdd/setup", json={"workspace": workspace})
    assert response.status_code == 200, response.text
    return response.json()


def new_change(client: TestClient, workspace: str, **overrides: object) -> dict:
    body = {
        "workspace": workspace,
        "title": "Add user authentication",
        # The propose phase normally sets these; a fixture that skipped them
        # would be testing the create form rather than the lifecycle.
        "risk": "standard",
        "capabilities": ["user-auth"],
    }
    body.update(overrides)
    response = client.post("/api/asdd/changes", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def write_delta(workspace: str, change_id: str, capability: str = "user-auth") -> None:
    path = (
        Path(workspace)
        / "documents"
        / "asdd"
        / "changes"
        / change_id
        / "specs"
        / capability
        / "spec.md"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(DELTA, encoding="utf-8")


def test_setup_separates_this_workspace_from_the_whole_scope(
    client: TestClient, workspace: str
) -> None:
    """A catalogue belongs to one repository, so readiness is per-repository."""

    install(client, workspace)

    payload = client.get("/api/asdd/setup", params={"workspace": workspace}).json()

    assert payload["workspace_ready"] is True
    assert payload["ready"] is True
    assert payload["workspace"] == payload["repositories"][0]["path"]


def test_setup_reports_not_initialized_then_ready(
    client: TestClient, workspace: str
) -> None:
    before = client.get("/api/asdd/setup", params={"workspace": workspace})
    assert before.status_code == 200
    assert before.json()["repositories"][0]["status"] == "not_initialized"

    after = install(client, workspace)

    assert after["ready"] is True
    assert after["repositories"][0]["status"] == "ready"


def test_a_new_change_is_created_at_drafting(
    client: TestClient, workspace: str
) -> None:
    install(client, workspace)

    detail = new_change(client, workspace)

    assert detail["change"]["change_id"] == "add-user-authentication"
    assert detail["change"]["status"] == "drafting"
    assert detail["rail"]["primary_action"] == "draft_proposal"


def test_a_change_id_may_be_chosen_explicitly(
    client: TestClient, workspace: str
) -> None:
    install(client, workspace)

    detail = new_change(client, workspace, change_id="add-user-auth")

    assert detail["change"]["change_id"] == "add-user-auth"


def test_creating_the_same_change_twice_conflicts(
    client: TestClient, workspace: str
) -> None:
    install(client, workspace)
    new_change(client, workspace, change_id="add-user-auth")

    response = client.post(
        "/api/asdd/changes",
        json={
            "workspace": workspace,
            "title": "Again",
            "change_id": "add-user-auth",
        },
    )

    assert response.status_code == 409


def test_no_endpoint_asks_for_a_hash_or_a_session(
    client: TestClient, workspace: str
) -> None:
    """The two identifiers that used to gate every call are gone from the API."""

    schema = client.get("/openapi.json").json()
    asdd_paths = {
        path: item for path, item in schema["paths"].items() if "/api/asdd" in path
    }
    assert asdd_paths
    serialized = str(asdd_paths) + str(
        {
            name: component
            for name, component in schema["components"]["schemas"].items()
            if name.startswith("Asdd")
        }
    )

    for absent in ("expected_hash", "content_hash", "spec_hash", "session_id"):
        assert absent not in serialized


def test_the_full_lifecycle_runs_without_a_single_identifier_being_restated(
    client: TestClient, workspace: str
) -> None:
    install(client, workspace)
    change_id = new_change(client, workspace, change_id="add-user-auth")["change"][
        "change_id"
    ]
    body = {"workspace": workspace}

    # The agent normally declares this when it finishes writing; the test does
    # what it would do. Until then the change is at `drafting` and the gate is
    # shut, which is what keeps an untouched proposal template out.
    _set_status(workspace, change_id, "proposed")
    approved = client.post(f"/api/asdd/changes/{change_id}/approve/proposal", json=body)
    assert approved.status_code == 200, approved.text
    assert approved.json()["change"]["status"] == "specifying"

    write_delta(workspace, change_id)
    client.post(f"/api/asdd/changes/{change_id}/actions/draft_specs", json=body)
    detail = client.get(
        f"/api/asdd/changes/{change_id}", params={"workspace": workspace}
    ).json()
    assert detail["deltas"][0]["added"] == ["Slug identity"]

    # The agent normally sets this; the test does what it would do.
    _set_status(workspace, change_id, "specified")
    assert (
        client.post(f"/api/asdd/changes/{change_id}/approve/specs", json=body).json()[
            "change"
        ]["status"]
        == "tasking"
    )

    _write_tasks(workspace, change_id)
    _set_status(workspace, change_id, "tasked")
    assert (
        client.post(f"/api/asdd/changes/{change_id}/approve/tasks", json=body).json()[
            "change"
        ]["status"]
        == "implementing"
    )

    _write_tasks(workspace, change_id, done=True)
    evidence = client.post(
        f"/api/asdd/changes/{change_id}/evidence",
        json={
            "workspace": workspace,
            "evidence_id": "pytest",
            "kind": "machine",
            "result": "passed",
            # Citing the requirement is what makes this cover anything: the
            # archive gate asks whether each approved requirement was exercised.
            "requirement": "Slug identity",
            "summary": "pytest tests/services — 214 passed",
        },
    )
    assert evidence.status_code == 201, evidence.text

    ready = client.post(f"/api/asdd/changes/{change_id}/ready", json=body)
    assert ready.status_code == 200, ready.text
    assert ready.json()["change"]["status"] == "ready"

    archived = client.post(f"/api/asdd/changes/{change_id}/archive", json=body)
    assert archived.status_code == 200, archived.text
    assert archived.json() == {
        "change_id": change_id,
        "archived_as": archived.json()["archived_as"],
        "capabilities_updated": ["user-auth"],
    }

    spec = client.get(
        "/api/asdd/specs/user-auth", params={"workspace": workspace}
    ).json()
    assert [item["name"] for item in spec["requirements"]] == ["Slug identity"]
    assert (
        client.get("/api/asdd/changes", params={"workspace": workspace}).json()[
            "changes"
        ]
        == []
    )


def test_approving_specs_is_refused_while_a_capability_has_no_delta(
    client: TestClient, workspace: str
) -> None:
    install(client, workspace)
    change_id = new_change(client, workspace, change_id="add-user-auth")["change"][
        "change_id"
    ]
    _set_status(workspace, change_id, "proposed")
    client.post(
        f"/api/asdd/changes/{change_id}/approve/proposal", json={"workspace": workspace}
    )
    _set_status(workspace, change_id, "specified")

    response = client.post(
        f"/api/asdd/changes/{change_id}/approve/specs", json={"workspace": workspace}
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "asdd_action_blocked"
    assert detail["blockers"][0]["code"] == "missing_artifact"


def test_approving_a_proposal_nobody_has_written_is_refused(
    client: TestClient, workspace: str
) -> None:
    # `POST /approve/{artifact}` takes the artifact from the URL, so it can be
    # asked for an approval the rail never offered. A new change carries a
    # proposal template, and an existence check alone waved it through.
    install(client, workspace)
    change_id = new_change(client, workspace, change_id="add-user-auth")["change"][
        "change_id"
    ]

    response = client.post(
        f"/api/asdd/changes/{change_id}/approve/proposal", json={"workspace": workspace}
    )

    assert response.status_code == 409
    assert response.json()["detail"]["blockers"][0]["code"] == "gate_not_reached"
    detail = client.get(
        f"/api/asdd/changes/{change_id}", params={"workspace": workspace}
    ).json()
    assert detail["change"]["status"] == "drafting"
    assert detail["change"]["approvals"]["proposal"] is None


def test_an_action_the_phase_does_not_offer_is_refused(
    client: TestClient, workspace: str
) -> None:
    install(client, workspace)
    change_id = new_change(client, workspace, change_id="add-user-auth")["change"][
        "change_id"
    ]

    response = client.post(
        f"/api/asdd/changes/{change_id}/actions/start_implementation",
        json={"workspace": workspace},
    )

    assert response.status_code == 409


def test_an_action_returns_a_prompt_that_names_the_folder_and_the_skill(
    client: TestClient, workspace: str
) -> None:
    install(client, workspace)
    change_id = new_change(client, workspace, change_id="add-user-auth")["change"][
        "change_id"
    ]

    response = client.post(
        f"/api/asdd/changes/{change_id}/actions/draft_proposal",
        json={"workspace": workspace},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["skill"] == "asdd-propose"
    assert "add-user-auth" in payload["prompt"]
    assert "documents/asdd/changes/add-user-auth" in payload["prompt"]


def test_an_unknown_change_is_a_404(client: TestClient, workspace: str) -> None:
    install(client, workspace)

    response = client.get(
        "/api/asdd/changes/never-existed", params={"workspace": workspace}
    )

    assert response.status_code == 404


def test_a_change_can_be_deleted_before_it_is_archived(
    client: TestClient, workspace: str
) -> None:
    install(client, workspace)
    change_id = new_change(client, workspace, change_id="add-user-auth")["change"][
        "change_id"
    ]

    response = client.request(
        "DELETE",
        f"/api/asdd/changes/{change_id}",
        params={"workspace": workspace},
    )

    assert response.status_code == 204
    assert (
        client.get("/api/asdd/changes", params={"workspace": workspace}).json()[
            "changes"
        ]
        == []
    )


def _change_path(workspace: str, change_id: str) -> Path:
    return Path(workspace) / "documents" / "asdd" / "changes" / change_id


def _set_status(workspace: str, change_id: str, status: str) -> None:
    path = _change_path(workspace, change_id) / "proposal.md"
    text = path.read_text(encoding="utf-8")
    current = next(line for line in text.split("\n") if line.startswith("status: "))
    path.write_text(text.replace(current, f"status: {status}", 1), encoding="utf-8")


def _write_tasks(workspace: str, change_id: str, *, done: bool = False) -> None:
    mark = "x" if done else " "
    (_change_path(workspace, change_id) / "tasks.md").write_text(
        f"## 1. Implementation\n\n- [{mark}] Add the store → Slug identity\n",
        encoding="utf-8",
    )


def test_a_title_in_the_users_own_language_opens_a_change(
    client: TestClient, workspace: str
) -> None:
    # The form says the title becomes the change's slug, and the title field
    # was validated as though it already were one — so an ordinary title was
    # refused for its punctuation, and a Vietnamese title could not open a
    # change at all.
    install(client, workspace)

    response = client.post(
        "/api/asdd/changes",
        json={"workspace": workspace, "title": "Thêm tìm kiếm ghi chú!"},
    )

    assert response.status_code == 201, response.text
    assert response.json()["change"]["change_id"] == "them-tim-kiem-ghi-chu"
    assert response.json()["change"]["title"] == "Thêm tìm kiếm ghi chú!"


def test_a_title_with_no_latin_form_asks_for_an_explicit_id(
    client: TestClient, workspace: str
) -> None:
    install(client, workspace)

    refused = client.post(
        "/api/asdd/changes", json={"workspace": workspace, "title": "日本語のタイトル"}
    )
    assert refused.status_code == 422
    assert "id of its own" in refused.json()["detail"]

    accepted = client.post(
        "/api/asdd/changes",
        json={
            "workspace": workspace,
            "title": "日本語のタイトル",
            "change_id": "japanese-title",
        },
    )
    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["change"]["change_id"] == "japanese-title"


def test_autopilot_is_a_property_of_the_change_not_the_session(
    client: TestClient, workspace: str
) -> None:
    install(client, workspace)
    change_id = new_change(client, workspace, change_id="add-user-auth")["change"][
        "change_id"
    ]

    on = client.post(
        f"/api/asdd/changes/{change_id}/autopilot",
        json={"workspace": workspace, "enabled": True},
    )
    assert on.status_code == 200, on.text
    assert on.json()["change"]["autopilot"] is True

    proposal = (
        Path(workspace) / "documents" / "asdd" / "changes" / change_id / "proposal.md"
    ).read_text(encoding="utf-8")
    assert "autopilot: true" in proposal

    off = client.post(
        f"/api/asdd/changes/{change_id}/autopilot",
        json={"workspace": workspace, "enabled": False},
    )
    assert off.json()["change"]["autopilot"] is False


def test_autopilot_leads_the_rail_with_continue(
    client: TestClient, workspace: str
) -> None:
    install(client, workspace)
    change_id = new_change(client, workspace, change_id="add-user-auth")["change"][
        "change_id"
    ]
    client.post(
        f"/api/asdd/changes/{change_id}/autopilot",
        json={"workspace": workspace, "enabled": True},
    )
    _set_status(workspace, change_id, "proposed")

    rail = client.get(
        f"/api/asdd/changes/{change_id}", params={"workspace": workspace}
    ).json()["rail"]
    assert rail["primary_action"] == "autopilot_continue"

    started = client.post(
        f"/api/asdd/changes/{change_id}/actions/autopilot_continue",
        json={"workspace": workspace},
    )
    assert started.status_code == 200, started.text
    assert started.json()["skill"] == "asdd-specify"
    assert "AUTOPILOT IS ON" in started.json()["prompt"]
    assert "auto_approvals" in started.json()["prompt"]


def test_the_autopilot_prompt_names_the_gates_a_tier_reserves(
    client: TestClient, workspace: str
) -> None:
    install(client, workspace)
    change_id = new_change(client, workspace, change_id="ship-auth", risk="critical")[
        "change"
    ]["change_id"]
    client.post(
        f"/api/asdd/changes/{change_id}/autopilot",
        json={"workspace": workspace, "enabled": True},
    )
    _set_status(workspace, change_id, "proposed")

    prompt = client.post(
        f"/api/asdd/changes/{change_id}/actions/autopilot_continue",
        json={"workspace": workspace},
    ).json()["prompt"]

    assert "`critical` reserves these for the user" in prompt
    assert "`design`" in prompt and "`archive`" in prompt


def test_approving_clears_a_hold_the_agent_raised(
    client: TestClient, workspace: str
) -> None:
    install(client, workspace)
    change_id = new_change(client, workspace, change_id="add-user-auth")["change"][
        "change_id"
    ]
    path = (
        Path(workspace) / "documents" / "asdd" / "changes" / change_id / "proposal.md"
    )
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "status: drafting",
            "status: proposed\nautopilot: true\nhold:\n"
            "  gate: proposal\n  reason: Scope is wider than the title",
        ),
        encoding="utf-8",
    )
    held = client.get(
        f"/api/asdd/changes/{change_id}", params={"workspace": workspace}
    ).json()
    assert held["rail"]["hold"]["reason"] == "Scope is wider than the title"
    assert held["rail"]["primary_action"] == "approve_proposal"

    approved = client.post(
        f"/api/asdd/changes/{change_id}/approve/proposal", json={"workspace": workspace}
    )

    assert approved.status_code == 200, approved.text
    assert approved.json()["change"]["hold"] is None


def test_autopilot_continue_runs_the_implementation_phase(
    client: TestClient, workspace: str
) -> None:
    install(client, workspace)
    change_id = new_change(client, workspace, change_id="add-user-auth")["change"][
        "change_id"
    ]
    client.post(
        f"/api/asdd/changes/{change_id}/autopilot",
        json={"workspace": workspace, "enabled": True},
    )
    write_delta(workspace, change_id)
    _write_tasks(workspace, change_id)
    _set_status(workspace, change_id, "implementing")

    started = client.post(
        f"/api/asdd/changes/{change_id}/actions/autopilot_continue",
        json={"workspace": workspace},
    )

    assert started.status_code == 200, started.text
    assert started.json()["skill"] == "asdd-implement"
    assert "set `status` to the next one" in started.json()["prompt"]


def test_autopilot_continue_moves_to_verification_once_tasks_are_done(
    client: TestClient, workspace: str
) -> None:
    install(client, workspace)
    change_id = new_change(client, workspace, change_id="add-user-auth")["change"][
        "change_id"
    ]
    client.post(
        f"/api/asdd/changes/{change_id}/autopilot",
        json={"workspace": workspace, "enabled": True},
    )
    write_delta(workspace, change_id)
    _write_tasks(workspace, change_id, done=True)
    _set_status(workspace, change_id, "implementing")

    started = client.post(
        f"/api/asdd/changes/{change_id}/actions/autopilot_continue",
        json={"workspace": workspace},
    )

    assert started.json()["skill"] == "asdd-verify"


def test_autopilot_does_not_offer_to_archive(
    client: TestClient, workspace: str
) -> None:
    install(client, workspace)
    change_id = new_change(client, workspace, change_id="add-user-auth")["change"][
        "change_id"
    ]
    client.post(
        f"/api/asdd/changes/{change_id}/autopilot",
        json={"workspace": workspace, "enabled": True},
    )
    write_delta(workspace, change_id)
    _write_tasks(workspace, change_id, done=True)
    _set_status(workspace, change_id, "ready")

    rail = client.get(
        f"/api/asdd/changes/{change_id}", params={"workspace": workspace}
    ).json()["rail"]

    assert rail["primary_action"] == "archive"
    refused = client.post(
        f"/api/asdd/changes/{change_id}/actions/autopilot_continue",
        json={"workspace": workspace},
    )
    assert refused.status_code == 409


def test_a_change_needs_only_a_title_a_problem_and_an_outcome(
    client: TestClient, workspace: str
) -> None:
    # The form used to ask for a risk tier and capabilities before anything had
    # been read. Nobody can tier a change they have not analysed, and the
    # propose phase is what the analysis is.
    install(client, workspace)

    created = client.post(
        "/api/asdd/changes",
        json={
            "workspace": workspace,
            "title": "Export notes to PDF",
            "problem": "Readers can only share notes by copying text by hand.",
            "outcome": "One command writes every note into a PDF they can send.",
        },
    )

    assert created.status_code == 201, created.text
    change = created.json()["change"]
    assert change["change_id"] == "export-notes-to-pdf"
    assert change["capabilities"] == []

    # The requester's words are in the file the propose phase reads, not in a
    # request field stored beside it.
    proposal = created.json()["proposal"]
    assert "copying text by hand" in proposal
    assert "writes every note into a PDF" in proposal
    assert "_State the problem in the user's terms" not in proposal


def test_an_untiered_proposal_cannot_be_approved(
    client: TestClient, workspace: str
) -> None:
    # `risk` is omitted rather than defaulted, so the tier is a decision the
    # propose phase makes rather than one the create form makes silently.
    install(client, workspace)
    created = client.post(
        "/api/asdd/changes",
        json={"workspace": workspace, "title": "Rotate keys", "problem": "Keys age."},
    ).json()
    change_id = created["change"]["change_id"]
    assert created["change"]["risk"] == "standard"

    path = Path(workspace) / "documents" / "asdd" / "changes" / change_id
    assert "risk:" not in (path / "proposal.md").read_text(encoding="utf-8")

    _set_status(workspace, change_id, "proposed")
    refused = client.post(
        f"/api/asdd/changes/{change_id}/approve/proposal", json={"workspace": workspace}
    )

    assert refused.status_code == 409
    assert refused.json()["detail"]["blockers"][0]["code"] == "risk_not_set"
