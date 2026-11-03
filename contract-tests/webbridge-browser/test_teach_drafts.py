"""Teach drafts: capture from a paired browser, review and replay from the app."""

from __future__ import annotations

import uuid

import httpx

from wb_helpers import FakeExtension, T

ORIGIN = "https://example.com"
TABS = [{"id": 5, "url": f"{ORIGIN}/page", "title": "Page"}]
MISSING = "55555555-5555-5555-5555-555555555555"


def _bound(client, pairing, paired, make_session, tab: int = 5) -> str:
    sid = make_session(title="Teach")
    assert client.put(f"{T}/pairings/{pairing.id}/sessions/{sid}").status_code == 200
    bound = paired.put(
        f"{T}/bindings/{tab}", json={"session_id": sid, "origin": ORIGIN}
    )
    assert bound.status_code == 200
    return sid


def _draft_body(sid: str, **overrides) -> dict:
    body = {
        "session_id": sid,
        "tab_id": 5,
        "title": "Flow",
        "origin": ORIGIN,
        "start_url": f"{ORIGIN}/start?x=1#top",
        "actions": [
            {"kind": "click", "selector": " #a "},
            {
                "kind": "fill",
                "selector": "#p",
                "secret": True,
                "parameter": "pw",
                "value": "dropped",
            },
            {"kind": "fill", "selector": "#n", "value": "v"},
            {"kind": "select", "selector": "#s", "values": ["a", "", "b"]},
            {"kind": "set_checked", "selector": "#c", "checked": False},
            {"kind": "navigate", "url": f"{ORIGIN}/next?q=1"},
        ],
        "warnings": [" first ", "   ", "second"],
        "user_gesture": True,
    }
    body.update(overrides)
    return body


def _create(paired, sid: str, **overrides) -> dict:
    response = paired.post(f"{T}/teach-drafts", json=_draft_body(sid, **overrides))
    assert response.status_code == 201, response.text
    return response.json()


def test_create_normalises_the_recorded_trace(
    client, pairing, paired, make_session
) -> None:
    sid = _bound(client, pairing, paired, make_session)
    draft = _create(paired, sid)
    assert list(draft) == [
        "id",
        "pairing_id",
        "session_id",
        "tab_id",
        "title",
        "origin",
        "start_url",
        "actions",
        "parameter_names",
        "capture_warnings",
        "status",
        "replay_count",
        "created_at",
        "approved_at",
        "last_replayed_at",
        "last_error",
        "replay_execution_id",
        "replay_next_step",
        "replay_state",
        "replay_in_flight_step",
    ]
    assert draft["pairing_id"] == pairing.id
    assert draft["session_id"] == sid
    assert draft["start_url"] == f"{ORIGIN}/start"
    assert draft["actions"] == [
        {"kind": "click", "selector": "#a"},
        {"kind": "fill", "selector": "#p", "secret": True, "parameter": "pw"},
        {"kind": "fill", "selector": "#n", "value": "v"},
        {"kind": "select", "selector": "#s", "values": ["a", "b"]},
        {"kind": "set_checked", "selector": "#c", "checked": False},
        {"kind": "navigate", "url": f"{ORIGIN}/next"},
    ]
    assert draft["parameter_names"] == ["pw"]
    assert draft["capture_warnings"] == ["first", "second"]
    assert (draft["status"], draft["replay_count"], draft["replay_state"]) == (
        "draft",
        0,
        "idle",
    )
    assert draft["replay_next_step"] == 0
    assert draft["approved_at"] is None
    assert draft["replay_execution_id"] is None


def test_create_error_precedence(client, pairing, paired, make_session) -> None:
    unassigned = make_session()
    refused = paired.post(f"{T}/teach-drafts", json=_draft_body(unassigned))
    assert refused.status_code == 403
    assert refused.json()["detail"]["code"] == "session_not_pairing_assigned"
    sid = _bound(client, pairing, paired, make_session)
    scope = paired.post(f"{T}/teach-drafts", json=_draft_body(sid, origin="not-a-url"))
    assert scope.status_code == 422
    assert scope.json() == {
        "detail": {
            "code": "invalid_teach_scope",
            "message": "Teach drafts must target one HTTP(S) origin.",
        }
    }
    other_start = paired.post(
        f"{T}/teach-drafts",
        json=_draft_body(sid, start_url="https://other.example.org/"),
    )
    assert other_start.status_code == 422
    assert other_start.json()["detail"]["code"] == "invalid_teach_scope"
    gesture = paired.post(
        f"{T}/teach-drafts", json=_draft_body(sid, user_gesture=False)
    )
    assert gesture.status_code == 403
    assert gesture.json() == {
        "detail": {
            "code": "sharing_policy_refused",
            "message": "Browser interaction requires an explicit user gesture.",
        }
    }
    unbound_tab = paired.post(f"{T}/teach-drafts", json=_draft_body(sid, tab_id=99))
    assert unbound_tab.status_code == 409
    assert unbound_tab.json() == {
        "detail": {
            "code": "teach_binding_required",
            "message": "Bind the recorded tab to this session before saving a Teach draft.",
        }
    }
    # the refused capture was audited, a successful one is audited too
    audit = client.get(f"{T}/audit").json()["entries"]
    assert [(e["action"], e["success"], e["direction"]) for e in audit] == [
        ("teach.capture", False, "browser_in")
    ]
    assert audit[0]["error"] == "Browser interaction requires an explicit user gesture."
    assert audit[0]["url"] == ORIGIN
    assert audit[0]["session_id"] == sid
    assert audit[0]["extension_id"] == pairing.id


def test_create_rejects_bad_actions(client, pairing, paired, make_session) -> None:
    sid = _bound(client, pairing, paired, make_session)
    cases = {
        "navigate off origin": [
            {"kind": "navigate", "url": "https://evil.example.org/"}
        ],
        "navigate no url": [{"kind": "navigate"}],
        "click no selector": [{"kind": "click"}],
        "click blank selector": [{"kind": "click", "selector": "   "}],
        "fill no value": [{"kind": "fill", "selector": "#a"}],
        "secret without parameter": [
            {"kind": "fill", "selector": "#a", "secret": True}
        ],
        "select no values": [{"kind": "select", "selector": "#a", "values": ["", ""]}],
        "set_checked no checked": [{"kind": "set_checked", "selector": "#a"}],
    }
    for name, actions in cases.items():
        response = paired.post(
            f"{T}/teach-drafts", json=_draft_body(sid, actions=actions)
        )
        assert response.status_code == 422, name
        assert response.json()["detail"]["code"] == "invalid_teach_action", name
    assert client.get(f"{T}/teach-drafts/review").json() == []


def test_create_validation(client, pairing, paired, make_session) -> None:
    sid = _bound(client, pairing, paired, make_session)
    click = [{"kind": "click", "selector": "#a"}]
    for overrides in [
        {"actions": []},
        {"actions": click * 51},
        {"title": "   "},
        {"title": "x" * 256},
        {"tab_id": -1},
        {"warnings": ["w"] * 11},
        {"bogus": 1},
        {"actions": [{"kind": "hover", "selector": "#a"}]},
        {"actions": [{"kind": "click", "selector": "x" * 513}]},
        {"actions": [{"kind": "fill", "selector": "#a", "value": "x" * 4001}]},
        {
            "actions": [
                {"kind": "fill", "selector": "#a", "parameter": "1bad", "value": "x"}
            ]
        },
        {"actions": [{"kind": "select", "selector": "#a", "values": ["x" * 513]}]},
        {"actions": [{"kind": "select", "selector": "#a", "values": ["x"] * 21}]},
        {"actions": [{"kind": "click", "selector": "#a", "extra": 1}]},
    ]:
        response = paired.post(f"{T}/teach-drafts", json=_draft_body(sid, **overrides))
        assert response.status_code == 422, overrides
        assert isinstance(response.json()["detail"], list)


def test_review_list_approve_and_delete(client, pairing, paired, make_session) -> None:
    sid = _bound(client, pairing, paired, make_session)
    first = _create(paired, sid, title="First")
    second = _create(paired, sid, title="Second")
    listed = client.get(f"{T}/teach-drafts/review").json()
    assert [d["title"] for d in listed] == ["Second", "First"]
    approved = client.post(f"{T}/teach-drafts/{first['id']}/approve")
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert approved.json()["approved_at"] is not None
    assert approved.json()["replay_state"] == "idle"
    again = client.post(f"{T}/teach-drafts/{first['id']}/approve")
    assert again.status_code == 409
    assert again.json() == {
        "detail": "Teach draft is already approved or no longer replayable."
    }
    missing = client.post(f"{T}/teach-drafts/{MISSING}/approve")
    assert missing.status_code == 404
    assert missing.json() == {"detail": "Teach draft not found."}
    deleted = client.delete(f"{T}/teach-drafts/{second['id']}")
    assert deleted.status_code == 204
    assert deleted.content == b""
    assert [d["title"] for d in client.get(f"{T}/teach-drafts/review").json()] == [
        "First"
    ]
    gone = client.delete(f"{T}/teach-drafts/{second['id']}")
    assert gone.status_code == 404
    assert gone.json() == {"detail": "Teach draft not found."}
    assert client.post(f"{T}/teach-drafts/nope/approve").status_code == 422


def test_replay_precondition_order(client, pairing, paired, make_session) -> None:
    sid = _bound(client, pairing, paired, make_session)
    draft = _create(paired, sid)
    path = f"{T}/teach-drafts/{draft['id']}/replay"
    key = {"Idempotency-Key": "r1"}
    execution = str(uuid.uuid4())
    missing = client.post(f"{T}/teach-drafts/{MISSING}/replay", json={}, headers=key)
    assert missing.status_code == 404
    assert missing.json() == {"detail": "Teach draft not found."}
    unapproved = client.post(
        path, json={"execution_id": execution, "parameters": {"pw": "x"}}, headers=key
    )
    assert unapproved.status_code == 409
    assert unapproved.json() == {
        "detail": "Review and approve this Teach draft before replaying it."
    }
    assert client.post(f"{T}/teach-drafts/{draft['id']}/approve").status_code == 200
    unexpected = client.post(
        path,
        json={"execution_id": execution, "parameters": {"pw": "x", "zz": "y"}},
        headers=key,
    )
    assert (unexpected.status_code, unexpected.json()) == (
        422,
        {"detail": "Unexpected Teach replay parameter."},
    )
    absent = client.post(
        path, json={"execution_id": execution, "parameters": {}}, headers=key
    )
    assert (absent.status_code, absent.json()) == (
        422,
        {"detail": "Missing Teach replay parameter: pw."},
    )
    no_execution = client.post(path, json={"parameters": {"pw": "x"}}, headers=key)
    assert (no_execution.status_code, no_execution.json()) == (
        422,
        {"detail": "Teach replay execution_id is required."},
    )
    no_key = client.post(
        path, json={"execution_id": execution, "parameters": {"pw": "x"}}
    )
    assert (no_key.status_code, no_key.json()) == (
        422,
        {"detail": "Idempotency-Key is required and must be at most 128 characters."},
    )
    bad_body = client.post(
        path,
        json={"execution_id": execution, "parameters": {"pw": "x"}, "max_steps": 2},
        headers=key,
    )
    assert bad_body.status_code == 422
    assert isinstance(bad_body.json()["detail"], list)
    no_browser = client.post(
        path, json={"execution_id": execution, "parameters": {"pw": "x"}}, headers=key
    )
    assert no_browser.status_code == 409
    assert no_browser.json() == {
        "detail": "No browser extension connected. Install the EvoFlux WebBridge extension and open Chrome/Edge."
    }
    # The refused attempt still claimed the execution id, so another id is told to refresh.
    other_execution = client.post(
        path,
        json={"execution_id": str(uuid.uuid4()), "parameters": {"pw": "x"}},
        headers={"Idempotency-Key": "r2"},
    )
    assert other_execution.status_code == 409
    assert other_execution.json() == {
        "detail": "Refresh Teach drafts before continuing this replay."
    }
    listed = client.get(f"{T}/teach-drafts/review").json()[0]
    assert listed["replay_execution_id"] == execution
    assert listed["replay_state"] == "ready"
    assert listed["replay_next_step"] == 0


def test_replay_walks_the_flow_one_step_at_a_time(
    backend, client, pairing, paired, make_session
) -> None:
    sid = _bound(client, pairing, paired, make_session)
    draft = _create(
        paired,
        sid,
        actions=[
            {"kind": "click", "selector": "#a"},
            {"kind": "fill", "selector": "#p", "secret": True, "parameter": "pw"},
        ],
    )
    path = f"{T}/teach-drafts/{draft['id']}/replay"
    assert client.post(f"{T}/teach-drafts/{draft['id']}/approve").status_code == 200
    execution = str(uuid.uuid4())
    ticket = paired.post(f"{T}/relay-ticket").json()["ticket"]
    with FakeExtension(backend.base_url, ticket, tabs=TABS) as extension:
        body = {"execution_id": execution, "parameters": {"pw": "s3cret"}}
        steps = []
        for index in range(3):
            response = client.post(
                path, json=body, headers={"Idempotency-Key": f"step-{index}"}
            )
            assert response.status_code == 200, (index, response.text)
            result = response.json()
            assert list(result) == ["draft", "steps", "execution_id", "next_step"]
            assert result["execution_id"] == execution
            steps.append(result)
        assert [s["steps"] for s in steps] == [
            [{"kind": "navigate", "success": True, "error": None}],
            [{"kind": "click", "success": True, "error": None}],
            [{"kind": "fill", "success": True, "error": None}],
        ]
        assert [s["next_step"] for s in steps] == [1, 2, None]
        assert [s["draft"]["replay_state"] for s in steps] == [
            "ready",
            "ready",
            "completed",
        ]
        assert steps[-1]["draft"]["replay_count"] == 1
        assert steps[-1]["draft"]["last_replayed_at"] is not None
        scoped = {"tab_id": 5, "_webbridge_expected_origin": ORIGIN}
        assert [(c["action"], c["params"]) for c in extension.commands] == [
            ("navigate", {"url": f"{ORIGIN}/start", **scoped}),
            ("click_selector", {"selector": "#a", **scoped}),
            ("fill", {"selector": "#p", "value": "s3cret", **scoped}),
        ]
        # the same idempotency key replays the cached response without running the step again
        cached = client.post(path, json=body, headers={"Idempotency-Key": "step-2"})
        assert cached.status_code == 200
        assert cached.json() == steps[-1]
        assert len(extension.commands) == 3
        # parameter values are not part of the request hash: a different secret still gets the cache
        other_secret = client.post(
            path,
            json={**body, "parameters": {"pw": "other"}},
            headers={"Idempotency-Key": "step-2"},
        )
        assert other_secret.status_code == 200
        assert other_secret.json() == steps[-1]
        assert len(extension.commands) == 3
        reused = client.post(
            path,
            json={**body, "start_step": 2},
            headers={"Idempotency-Key": "step-2"},
        )
        assert reused.status_code == 409
        assert reused.json() == {
            "detail": "Idempotency-Key was already used for another Teach replay request."
        }
        done = client.post(path, json=body, headers={"Idempotency-Key": "after"})
        assert done.status_code == 409
        assert done.json() == {
            "detail": "This Teach replay is complete. Start a new replay to run it again."
        }
        other = client.post(
            path,
            json={"execution_id": str(uuid.uuid4()), "parameters": {"pw": "x"}},
            headers={"Idempotency-Key": "other-exec"},
        )
        assert other.status_code == 409
        assert other.json() == {
            "detail": "Refresh Teach drafts before continuing this replay."
        }
        restart = client.post(
            path,
            json={**body, "execution_id": str(uuid.uuid4()), "restart": True},
            headers={"Idempotency-Key": "restart"},
        )
        assert restart.status_code == 200
        assert restart.json()["steps"][0]["kind"] == "navigate"
        assert restart.json()["next_step"] == 1
    drafts = client.get(f"{T}/teach-drafts/review").json()
    assert drafts[0]["replay_count"] == 1
    assert drafts[0]["replay_state"] == "ready"


def test_a_failed_step_with_a_known_outcome_can_be_retried(
    backend, client, pairing, paired, make_session
) -> None:
    sid = _bound(client, pairing, paired, make_session)
    draft = _create(paired, sid, actions=[{"kind": "click", "selector": "#a"}])
    path = f"{T}/teach-drafts/{draft['id']}/replay"
    assert client.post(f"{T}/teach-drafts/{draft['id']}/approve").status_code == 200
    execution = str(uuid.uuid4())
    ticket = paired.post(f"{T}/relay-ticket").json()["ticket"]
    outcomes = iter(
        [
            {"success": False, "error": "element not found"},
            {"success": True, "data": {}},
        ]
    )
    with FakeExtension(
        backend.base_url, ticket, answer=lambda _command: next(outcomes), tabs=TABS
    ):
        body = {"execution_id": execution, "parameters": {}}
        failed = client.post(path, json=body, headers={"Idempotency-Key": "a"})
        assert failed.status_code == 409
        assert failed.json() == {
            "detail": "element not found The step may have run; inspect the browser and resolve its outcome before continuing."
        }
        listed = client.get(f"{T}/teach-drafts/review").json()[0]
        assert listed["replay_state"] == "ambiguous"
        assert listed["last_error"] == "element not found"
        assert listed["replay_in_flight_step"] == 0
        blocked = client.post(path, json=body, headers={"Idempotency-Key": "b"})
        assert blocked.status_code == 409
        assert blocked.json() == {
            "detail": "The last Teach step has an unknown outcome. Inspect the browser and resolve that step before continuing."
        }
        resolve = f"{T}/teach-drafts/{draft['id']}/replay/resolve"
        unconfirmed = client.post(
            resolve, json={"execution_id": execution, "outcome": "not_completed"}
        )
        assert unconfirmed.status_code == 422
        assert unconfirmed.json() == {
            "detail": "Confirm the browser outcome before resolving this Teach step."
        }
        wrong = client.post(
            resolve,
            json={
                "execution_id": str(uuid.uuid4()),
                "outcome": "completed",
                "user_confirmed": True,
            },
        )
        assert wrong.status_code == 409
        assert wrong.json() == {
            "detail": "This Teach step no longer needs outcome resolution."
        }
        resolved = client.post(
            resolve,
            json={
                "execution_id": execution,
                "outcome": "not_completed",
                "user_confirmed": True,
            },
        )
        assert resolved.status_code == 200
        assert resolved.json()["replay_state"] == "ready"
        assert resolved.json()["replay_next_step"] == 0
        assert resolved.json()["replay_in_flight_step"] is None
        assert resolved.json()["last_error"] is None
        again = client.post(
            resolve,
            json={
                "execution_id": execution,
                "outcome": "completed",
                "user_confirmed": True,
            },
        )
        assert again.status_code == 409
        retried = client.post(path, json=body, headers={"Idempotency-Key": "c"})
        assert retried.status_code == 200
        assert retried.json()["next_step"] == 1


def test_resolve_unknown_draft_and_bad_body(client) -> None:
    resolve = f"{T}/teach-drafts/{MISSING}/replay/resolve"
    missing = client.post(
        resolve, json={"execution_id": MISSING, "outcome": "completed"}
    )
    assert (missing.status_code, missing.json()) == (
        404,
        {"detail": "Teach draft not found."},
    )
    assert (
        client.post(
            resolve, json={"execution_id": MISSING, "outcome": "maybe"}
        ).status_code
        == 422
    )
    assert client.post(resolve, json={}).status_code == 422


def test_deleting_a_pairing_removes_its_drafts(
    backend, client, pairing, paired, make_session
) -> None:
    sid = _bound(client, pairing, paired, make_session)
    _create(paired, sid)
    assert len(client.get(f"{T}/teach-drafts/review").json()) == 1
    assert client.delete(f"{T}/pairings/{pairing.id}").status_code == 204
    assert client.get(f"{T}/teach-drafts/review").json() == []
    assert isinstance(httpx.__version__, str)
