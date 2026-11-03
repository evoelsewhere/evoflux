"""Appearance handoff and the WebBridge, agent-browsing and computer-app settings."""

from __future__ import annotations

import httpx
import pytest

from wb_helpers import T

APPEARANCE = {
    "theme_preference": "dark",
    "resolved_theme": "dark",
    "accent": "blue",
    "font_family": "mono",
    "font_scale": 1.1,
    "motion_intensity": "subtle",
}
DEFAULT_APPEARANCE = {
    "schema_version": 1,
    "theme_preference": "system",
    "resolved_theme": "light",
    "accent": "default",
    "font_family": "system",
    "font_scale": 1.0,
    "motion_intensity": "standard",
    "synced": False,
    "revision": 0,
}
WEBBRIDGE_DEFAULTS = {
    "enabled": True,
    "allow_evaluate": True,
    "require_tab_binding": True,
    "built_in_allowed_domains": [],
    "built_in_blocked_domains": [],
    "built_in_allow_evaluate": True,
    "built_in_allow_storage": True,
    "built_in_allow_cookie_values": False,
    "built_in_allow_http_requests": True,
    "built_in_allow_clipboard_read": False,
    "built_in_allow_clipboard_write": True,
    "built_in_allow_file_uploads": False,
    "built_in_allow_downloads": True,
    "built_in_allow_agent_permission_accept": False,
}


def test_appearance_defaults_and_revisions(client, paired) -> None:
    assert paired.get(f"{T}/appearance").json() == DEFAULT_APPEARANCE
    first = client.put(f"{T}/appearance", json=APPEARANCE)
    assert first.status_code == 200
    assert first.json() == {
        **APPEARANCE,
        "schema_version": 1,
        "synced": True,
        "revision": 1,
    }
    # an identical snapshot does not advance the revision
    assert client.put(f"{T}/appearance", json=APPEARANCE).json()["revision"] == 1
    changed = client.put(f"{T}/appearance", json={**APPEARANCE, "accent": "red"})
    assert changed.json()["revision"] == 2
    assert changed.json()["accent"] == "red"
    assert paired.get(f"{T}/appearance").json() == changed.json()


@pytest.mark.parametrize(
    "override",
    [
        {"theme_preference": "blue"},
        {"resolved_theme": "system"},
        {"accent": "teal"},
        {"font_family": "comic"},
        {"font_scale": 0.89},
        {"font_scale": 1.21},
        {"motion_intensity": "wild"},
        {"schema_version": 2},
        {"extra": 1},
    ],
)
def test_appearance_validation(client, paired, override) -> None:
    response = client.put(f"{T}/appearance", json={**APPEARANCE, **override})
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
    assert paired.get(f"{T}/appearance").json() == DEFAULT_APPEARANCE


def test_appearance_boundaries_are_inclusive(client) -> None:
    for scale in (0.9, 1.2):
        assert (
            client.put(
                f"{T}/appearance", json={**APPEARANCE, "font_scale": scale}
            ).status_code
            == 200
        )


def test_appearance_publish_needs_the_access_key_in_the_route(backend) -> None:
    """The route is outside the middleware: it checks the desktop token itself, after validation."""
    with httpx.Client(base_url=backend.base_url, timeout=30.0) as anonymous:
        invalid = anonymous.put(f"{T}/appearance", json={})
        assert invalid.status_code == 422
        refused = anonymous.put(f"{T}/appearance", json=APPEARANCE)
        assert refused.status_code == 401
        assert refused.json() == {"detail": "Desktop authentication required."}
        assert "www-authenticate" not in refused.headers
    with httpx.Client(
        base_url=backend.base_url,
        headers={"Authorization": "Bearer wrong"},
        timeout=30.0,
    ) as wrong:
        assert wrong.put(f"{T}/appearance", json=APPEARANCE).status_code == 401
    # the query token that other routes accept is not read here
    with httpx.Client(base_url=backend.base_url, timeout=30.0) as anonymous:
        assert (
            anonymous.put(
                f"{T}/appearance", params={"_token": backend.token}, json=APPEARANCE
            ).status_code
            == 401
        )


def test_webbridge_settings_defaults_and_round_trip(client) -> None:
    got = client.get("/api/settings/webbridge")
    assert got.status_code == 200
    assert got.json() == WEBBRIDGE_DEFAULTS
    assert list(got.json()) == list(WEBBRIDGE_DEFAULTS)
    update = {
        **WEBBRIDGE_DEFAULTS,
        "allow_evaluate": False,
        "require_tab_binding": False,
        "built_in_allowed_domains": ["example.com"],
        "built_in_blocked_domains": ["bank.test"],
        "built_in_allow_cookie_values": True,
        "built_in_allow_file_uploads": True,
    }
    saved = client.put("/api/settings/webbridge", json=update)
    assert saved.status_code == 200
    assert saved.json() == update
    assert client.get("/api/settings/webbridge").json() == update


def test_webbridge_settings_put_defaults_missing_fields_and_rejects_unknown(
    client,
) -> None:
    client.put("/api/settings/webbridge", json={**WEBBRIDGE_DEFAULTS, "enabled": False})
    reset = client.put("/api/settings/webbridge", json={})
    assert reset.status_code == 200
    assert reset.json() == WEBBRIDGE_DEFAULTS
    for body in [
        {"extra": 1},
        {"enabled": "maybe"},
        {"built_in_allowed_domains": "a.com"},
    ]:
        response = client.put("/api/settings/webbridge", json=body)
        assert response.status_code == 422, body
    assert client.get("/api/settings/webbridge").json() == WEBBRIDGE_DEFAULTS


def test_webbridge_put_keeps_the_agent_browsing_toggle(client) -> None:
    assert (
        client.put(
            "/api/settings/webbridge/agent-browsing", json={"enabled": False}
        ).status_code
        == 200
    )
    client.put("/api/settings/webbridge", json=WEBBRIDGE_DEFAULTS)
    assert client.get("/api/settings/webbridge/agent-browsing").json() == {
        "enabled": False
    }


def test_agent_browsing_toggle(client) -> None:
    assert client.get("/api/settings/webbridge/agent-browsing").json() == {
        "enabled": True
    }
    off = client.put("/api/settings/webbridge/agent-browsing", json={"enabled": False})
    assert (off.status_code, off.json()) == (200, {"enabled": False})
    assert client.get("/api/settings/webbridge/agent-browsing").json() == {
        "enabled": False
    }
    on = client.put("/api/settings/webbridge/agent-browsing", json={"enabled": True})
    assert on.json() == {"enabled": True}
    for body in [{}, {"enabled": "perhaps"}, {"enabled": True, "extra": 1}]:
        assert (
            client.put("/api/settings/webbridge/agent-browsing", json=body).status_code
            == 422
        ), body


def test_agent_browsing_off_does_not_need_an_extension(client) -> None:
    """Turning it off broadcasts a release, which must not fail the write."""
    assert (
        client.put(
            "/api/settings/webbridge/agent-browsing", json={"enabled": False}
        ).status_code
        == 200
    )


def test_computer_app_settings(client) -> None:
    defaults = {
        "enabled": False,
        "allowed_apps": [],
        "blocked_apps": [],
        "keep_hidden": True,
        "permission": "ask",
    }
    assert client.get("/api/settings/computer-app").json() == defaults
    saved = client.put(
        "/api/settings/computer-app",
        json={
            "enabled": True,
            "allowed_apps": ["  Notepad ", "Notepad", "", "calc.exe", "  "],
            "blocked_apps": ["Keepass", " Keepass "],
            "keep_hidden": False,
            "permission": "allow",
        },
    )
    assert saved.status_code == 200
    assert saved.json() == {
        "enabled": True,
        "allowed_apps": ["Notepad", "calc.exe"],
        "blocked_apps": ["Keepass"],
        "keep_hidden": False,
        "permission": "allow",
    }
    assert client.get("/api/settings/computer-app").json() == saved.json()
    assert client.put("/api/settings/computer-app", json={}).json() == defaults
    for body in [
        {"permission": "deny"},
        {"extra": 1},
        {"allowed_apps": "x"},
        {"enabled": "?"},
    ]:
        assert client.put("/api/settings/computer-app", json=body).status_code == 422, (
            body
        )


def test_disabling_webbridge_blocks_pairing_gated_session_work(
    client, pairing, paired, make_session
) -> None:
    sid = make_session()
    assert client.put(f"{T}/pairings/{pairing.id}/sessions/{sid}").status_code == 200
    client.put("/api/settings/webbridge", json={**WEBBRIDGE_DEFAULTS, "enabled": False})
    bound = paired.put(
        f"{T}/bindings/1", json={"session_id": sid, "origin": "https://example.com"}
    )
    assert bound.status_code == 403
    assert bound.json()["detail"]["code"] == "webbridge_disabled"
    # listing sessions only needs the pairing
    assert paired.get(f"{T}/sessions").status_code == 200
