"""Session listing and creation, the model catalogue and the per-session model choice."""

from __future__ import annotations

import uuid

import httpx

from provider_setup import configure_backend_provider
from wa_helpers import T

OPTION_KEYS = ["id", "title", "mode", "running", "model", "thinking_level"]


def test_listing_is_empty_until_a_session_is_assigned(paired) -> None:
    assert paired.get(f"{T}/sessions").json() == []
    assert paired.get(f"{T}/models").json() == []


def test_create_session_is_deterministic_and_idempotent(pairing, paired) -> None:
    created = paired.post(
        f"{T}/sessions",
        json={"title": "  Research  "},
        headers={"Idempotency-Key": "abc"},
    )
    assert created.status_code == 201
    body = created.json()
    assert list(body) == OPTION_KEYS
    assert body["id"] == str(
        uuid.uuid5(uuid.NAMESPACE_URL, f"evoflux:webbridge-session:{pairing.id}:abc")
    )
    assert body["title"] == "Research"
    assert (body["mode"], body["running"], body["model"], body["thinking_level"]) == (
        "work",
        False,
        None,
        None,
    )
    again = paired.post(
        f"{T}/sessions",
        json={"title": "Other title"},
        headers={"Idempotency-Key": "abc"},
    )
    assert again.status_code == 201
    assert again.json() == body
    other = paired.post(
        f"{T}/sessions", json={"title": "Research"}, headers={"Idempotency-Key": "abd"}
    )
    assert other.json()["id"] != body["id"]
    listed = paired.get(f"{T}/sessions").json()
    assert sorted(s["id"] for s in listed) == sorted([body["id"], other.json()["id"]])


def test_create_session_tags_it_for_the_creating_pairing_only(
    backend, pairing, paired, insert_pairing
) -> None:
    body = paired.post(
        f"{T}/sessions", json={"title": "Mine"}, headers={"Idempotency-Key": "x"}
    ).json()
    other = insert_pairing(
        ["sessions:list", "session-stream:read", "custom:scope"], credential="other"
    )
    with httpx.Client(
        base_url=backend.base_url, headers=other.bearer, timeout=30.0
    ) as http:
        assert http.get(f"{T}/sessions").json() == []
        refused = http.get(f"{T}/sessions/{body['id']}/history")
        assert refused.status_code == 403
    assert paired.get(f"{T}/sessions/{body['id']}/history").status_code == 200


def test_create_session_errors(paired) -> None:
    key = {"Idempotency-Key": "k"}
    missing = paired.post(f"{T}/sessions", json={"title": "t"})
    assert missing.status_code == 422
    assert missing.json() == {
        "detail": {
            "code": "invalid_idempotency_key",
            "message": "Idempotency-Key is required and must be at most 128 characters.",
        }
    }
    too_long = paired.post(
        f"{T}/sessions", json={"title": "t"}, headers={"Idempotency-Key": "k" * 129}
    )
    assert too_long.status_code == 422
    assert too_long.json()["detail"]["code"] == "invalid_idempotency_key"
    assert (
        paired.post(
            f"{T}/sessions", json={"title": "t"}, headers={"Idempotency-Key": "k" * 128}
        ).status_code
        == 201
    )
    for body in [
        {},
        {"title": ""},
        {"title": "   "},
        {"title": "x" * 256},
        {"title": "t", "extra": 1},
        {"title": 5},
    ]:
        response = paired.post(f"{T}/sessions", json=body, headers=key)
        assert response.status_code == 422, body
        assert isinstance(response.json()["detail"], list)
    # validation is answered before the idempotency key
    both = paired.post(f"{T}/sessions", json={})
    assert isinstance(both.json()["detail"], list)


def test_create_session_ignores_webbridge_disabled(client, paired) -> None:
    current = client.get("/api/settings/webbridge").json()
    client.put("/api/settings/webbridge", json={**current, "enabled": False})
    created = paired.post(
        f"{T}/sessions", json={"title": "t"}, headers={"Idempotency-Key": "k"}
    )
    assert created.status_code == 201


def test_models_come_from_the_configured_registry(
    client, paired, mock_provider
) -> None:
    configure_backend_provider(client, mock_provider)
    models = paired.get(f"{T}/models").json()
    assert models == [
        {
            "id": "router9:mock-model",
            "provider": "router9",
            "model": "mock-model",
            "thinking_levels": ["none", "low", "medium", "high"],
        }
    ]


def test_model_choice_validation_and_persistence(
    client, paired, panel, mock_provider
) -> None:
    path = f"{T}/sessions/{panel}/model"
    assert paired.patch(path, json={}).json()["model"] is None
    unknown = paired.patch(path, json={"model": "nope:nothing"})
    assert (unknown.status_code, unknown.json()) == (
        422,
        {"detail": "Choose a model from the registry."},
    )
    needs_model = paired.patch(path, json={"thinking_level": "high"})
    assert (needs_model.status_code, needs_model.json()) == (
        422,
        {"detail": "Choose an explicit model before setting thinking effort."},
    )
    for body in [
        {"model": "x" * 256},
        {"thinking_level": "x" * 51},
        {"bogus": 1},
        {"model": 5},
    ]:
        assert paired.patch(path, json=body).status_code == 422, body
    configure_backend_provider(client, mock_provider)
    chosen = paired.patch(
        path, json={"model": "  router9:mock-model  ", "thinking_level": " high "}
    )
    assert chosen.status_code == 200
    assert chosen.json() == {
        "id": panel,
        "title": "Panel",
        "mode": "work",
        "running": False,
        "model": "router9:mock-model",
        "thinking_level": "high",
    }
    assert paired.get(f"{T}/sessions").json()[0]["model"] == "router9:mock-model"
    # a blank level clears it; an empty model clears both
    cleared_level = paired.patch(
        path, json={"model": "router9:mock-model", "thinking_level": "  "}
    )
    assert cleared_level.json()["thinking_level"] is None
    cleared = paired.patch(path, json={"model": "  "})
    assert (cleared.json()["model"], cleared.json()["thinking_level"]) == (None, None)


def test_model_choice_accepts_any_thinking_level_for_this_model(
    client, paired, panel, mock_provider
) -> None:
    """The level is only validated against the wire when the provider has a table for it."""
    configure_backend_provider(client, mock_provider)
    response = paired.patch(
        f"{T}/sessions/{panel}/model",
        json={"model": "router9:mock-model", "thinking_level": "zzz"},
    )
    assert response.status_code == 200
    assert response.json()["thinking_level"] == "zzz"
