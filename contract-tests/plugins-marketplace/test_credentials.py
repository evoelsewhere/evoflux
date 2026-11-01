"""``/api/plugins/{id}/credentials``: host-mediated plugin settings."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from plugin_helpers import ID, install, write_plugin

NAMESPACE = "org.evoelsewhere.evoflux.credentials"
FIELDS = [
    {"key": "api_token", "label": "API token", "type": "secret", "env": "MY_TOKEN", "required": True},
    {
        "key": "base_url",
        "label": "Base URL",
        "type": "url",
        "env": "MY_URL",
        "default": "https://example.com/api",
        "description": "Where.",
        "placeholder": "https://...",
    },
    {"key": "verbose", "label": "Verbose", "type": "boolean", "env": "MY_VERBOSE"},
    {"key": "note", "label": "Note", "type": "text", "env": "MY_NOTE"},
]


def make(client, src, fields=None, namespace=NAMESPACE, name="cred") -> dict:
    root = write_plugin(
        src / name,
        name,
        manifest_extra={"extensions": {namespace: {"fields": FIELDS if fields is None else fields}}},
    )
    return install(client, root)["installation"]


def url(installation: dict) -> str:
    return f"/api/plugins/{installation['id']}/credentials"


def stored(platform_dir: Path, installation: dict) -> dict:
    path = platform_dir / "data" / installation["id"] / "credentials.json"
    return json.loads(path.read_text(encoding="utf-8"))


def by_key(state: dict) -> dict[str, dict]:
    return {field["key"]: field for field in state["fields"]}


def test_unsupported_when_the_plugin_declares_nothing(client, src) -> None:
    created = install(client, write_plugin(src / "plain", "plain"))["installation"]
    response = client.get(url(created))
    assert response.status_code == 200
    assert response.json() == {"supported": False, "configured": True, "fields": [], "error": None}
    put = client.put(url(created), json={"values": {}})
    assert put.status_code == 422
    assert put.json() == {"detail": "This plugin does not declare an EvoFlux credential schema."}
    assert client.delete(url(created)).json() == response.json()


def test_state_before_anything_is_saved(client, src) -> None:
    state = client.get(url(make(client, src))).json()
    assert state["supported"] is True
    assert state["configured"] is False
    assert state["error"] is None
    assert [f["key"] for f in state["fields"]] == ["api_token", "base_url", "verbose", "note"]
    assert state["fields"][0] == {
        "key": "api_token",
        "label": "API token",
        "type": "secret",
        "env": "MY_TOKEN",
        "required": True,
        "description": "",
        "placeholder": "",
        "configured": False,
        "value": None,
    }
    base = by_key(state)["base_url"]
    assert base["configured"] is True
    assert base["value"] == "https://example.com/api"
    assert base["description"] == "Where."
    assert base["placeholder"] == "https://..."


def test_save_masks_secrets_and_writes_the_store(client, src, platform_dir) -> None:
    created = make(client, src)
    response = client.put(
        url(created),
        json={"values": {"api_token": "s3cret", "note": "hi", "verbose": True, "base_url": "http://localhost:9/x"}},
    )
    assert response.status_code == 200
    state = response.json()
    assert state["configured"] is True
    fields = by_key(state)
    assert fields["api_token"]["value"] == "********"
    assert fields["api_token"]["configured"] is True
    assert fields["note"]["value"] == "hi"
    assert fields["verbose"]["value"] is True
    assert fields["base_url"]["value"] == "http://localhost:9/x"
    assert stored(platform_dir, created) == {
        "api_token": "s3cret",
        "base_url": "http://localhost:9/x",
        "note": "hi",
        "verbose": True,
    }
    raw = (platform_dir / "data" / created["id"] / "credentials.json").read_bytes().replace(b"\r\n", b"\n")
    assert raw == (json.dumps(stored(platform_dir, created), indent=2, sort_keys=True) + "\n").encode()
    assert "s3cret" not in client.get(url(created)).text
    assert "s3cret" not in client.get("/api/plugins").text


def test_masked_value_keeps_the_stored_secret_and_blank_clears(client, src, platform_dir) -> None:
    created = make(client, src)
    client.put(url(created), json={"values": {"api_token": "s3cret", "note": "hi"}})
    again = client.put(url(created), json={"values": {"api_token": "********", "note": ""}})
    assert again.status_code == 200
    assert stored(platform_dir, created) == {"api_token": "s3cret"}
    cleared = client.put(url(created), json={"values": {"api_token": None}})
    assert cleared.json()["configured"] is False
    assert stored(platform_dir, created) == {}


def test_a_masked_placeholder_is_stored_literally_for_non_secret_fields(client, src, platform_dir) -> None:
    created = make(client, src)
    client.put(url(created), json={"values": {"note": "********"}})
    assert stored(platform_dir, created) == {"note": "********"}


def test_save_validation_errors_change_nothing(client, src, platform_dir) -> None:
    created = make(client, src)
    client.put(url(created), json={"values": {"note": "keep"}})
    cases = [
        ({"nope": "x"}, "Unknown plugin credential fields: nope"),
        ({"b": "x", "a": "x"}, "Unknown plugin credential fields: a, b"),
        ({"verbose": "yes"}, "Credential 'verbose' must be a boolean."),
        ({"note": True}, "Credential 'note' must be text."),
        (
            {"base_url": "ftp://example.com"},
            "Credential 'base_url' must be an absolute HTTP(S) URL without user information or a fragment.",
        ),
        (
            {"base_url": "https://u:p@example.com"},
            "Credential 'base_url' must be an absolute HTTP(S) URL without user information or a fragment.",
        ),
        (
            {"base_url": "https://example.com/#x"},
            "Credential 'base_url' must be an absolute HTTP(S) URL without user information or a fragment.",
        ),
        ({"base_url": "https://example.com:notaport"}, "Credential 'base_url' must be a valid URL."),
    ]
    for values, detail in cases:
        response = client.put(url(created), json={"values": values})
        assert response.status_code == 422, values
        assert response.json() == {"detail": detail}
    assert stored(platform_dir, created) == {"note": "keep"}


def test_save_body_validation(client, src) -> None:
    created = make(client, src)
    for body in ({}, {"values": "x"}, {"values": {"note": {"a": 1}}}, {"values": {}, "extra": 1}):
        assert client.put(url(created), json=body).status_code == 422


def test_delete_clears_the_store(client, src, platform_dir) -> None:
    created = make(client, src)
    client.put(url(created), json={"values": {"api_token": "s3cret"}})
    response = client.delete(url(created))
    assert response.status_code == 200
    assert response.json()["configured"] is False
    assert not (platform_dir / "data" / created["id"] / "credentials.json").exists()
    assert client.delete(url(created)).status_code == 200


def test_the_legacy_extension_namespace_still_works(client, src) -> None:
    created = make(client, src, namespace="evoflux.credentials", name="legacy")
    state = client.get(url(created)).json()
    assert state["supported"] is True
    assert [f["key"] for f in state["fields"]] == ["api_token", "base_url", "verbose", "note"]


@pytest.mark.parametrize(
    ("fields", "fragment"),
    [
        ([{"key": "k", "label": "K", "env": "PATH"}], "credential env name is invalid or reserved"),
        ([{"key": "k", "label": "K", "env": "PLUGIN_ROOT"}], "credential env name is invalid or reserved"),
        ([{"key": "k", "label": "K", "env": "lower"}], "credential env name is invalid or reserved"),
        ([{"key": "K", "label": "K", "env": "OK"}], "credential key must be a lowercase identifier"),
        (
            [{"key": "a", "label": "A", "env": "SAME"}, {"key": "b", "label": "B", "env": "SAME"}],
            "Plugin credential field keys and env names must be unique.",
        ),
    ],
)
def test_invalid_definitions_surface_as_errors(client, src, fields, fragment) -> None:
    """Pinned: the install succeeds (extensions are not validated); reads report it."""
    created = make(client, src, fields=fields)
    get = client.get(url(created))
    assert get.status_code == 422
    assert fragment in get.json()["detail"]
    listing = client.get("/api/plugins").json()["plugins"][0]["credentials"]
    assert listing["supported"] is True
    assert listing["configured"] is False
    assert listing["fields"] == []
    assert fragment in listing["error"]
    assert client.put(url(created), json={"values": {}}).status_code == 422


def test_other_reserved_environment_names_are_allowed(client, src) -> None:
    """Suspected bug S3: only PATH, PLUGIN_ROOT and PLUGIN_DATA are reserved.

    A plugin may declare ``LD_PRELOAD``, ``PYTHONPATH`` or ``NODE_OPTIONS`` as a
    credential env name; the host passes it to the server process.
    """
    fields = [{"key": f"k{i}", "label": "K", "env": env} for i, env in enumerate(["LD_PRELOAD", "PYTHONPATH", "NODE_OPTIONS", "PYTHONSTARTUP"])]
    created = make(client, src, fields=fields)
    state = client.get(url(created))
    assert state.status_code == 200
    assert [f["env"] for f in state.json()["fields"]] == [
        "LD_PRELOAD", "PYTHONPATH", "NODE_OPTIONS", "PYTHONSTARTUP",
    ]  # fmt: skip


@pytest.mark.parametrize("method", ["GET", "PUT", "DELETE"])
def test_unknown_installation_is_404(client, method) -> None:
    response = client.request(method, f"/api/plugins/{ID}/credentials", json={"values": {}} if method == "PUT" else None)
    assert response.status_code == 404
    assert response.json() == {"detail": "Plugin installation not found."}


def test_a_corrupt_store_is_reported(client, src, platform_dir) -> None:
    created = make(client, src)
    store = platform_dir / "data" / created["id"] / "credentials.json"
    store.parent.mkdir(parents=True)
    store.write_text("[1]", encoding="utf-8")
    get = client.get(url(created))
    assert get.status_code == 422
    assert get.json() == {"detail": "Plugin credential store must be a JSON object."}
    listing = client.get("/api/plugins").json()["plugins"][0]["credentials"]
    assert listing["error"] == "Plugin credential store must be a JSON object."
    assert listing["supported"] is True
