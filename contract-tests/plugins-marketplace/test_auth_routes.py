"""Authentication in front of every ``/api/plugins`` route."""

from __future__ import annotations

import httpx
import pytest

from plugin_helpers import ID, PREVIEW, SOURCE, UNAUTHORIZED_BODY, tree

#: Every route of the unit as (method, path, JSON body). The bodies are valid,
#: so a 401 proves authentication runs before validation and before any work.
ROUTES: list[tuple[str, str, object]] = [
    ("GET", "/api/plugins", None),
    ("GET", "/api/plugins/inspect?path=x", None),
    ("POST", "/api/plugins/install", {"path": "x"}),
    ("POST", "/api/plugins/upload", None),
    ("POST", "/api/plugins/create", {"destination": "x", "name": "x"}),
    ("POST", "/api/plugins/pack", {"path": "x"}),
    ("GET", "/api/plugins/workspace/tree?root=x", None),
    ("GET", "/api/plugins/workspace/file?root=x&path=y", None),
    ("PUT", "/api/plugins/workspace/file", {"root": "x", "path": "y", "content": ""}),
    ("POST", "/api/plugins/workspace/entry", {"root": "x", "path": "y", "kind": "file"}),
    ("DELETE", "/api/plugins/workspace/entry", {"root": "x", "path": "y"}),
    ("GET", "/api/plugins/marketplaces", None),
    ("POST", "/api/plugins/marketplaces", {"kind": "claude_code", "name": "x", "url": "https://example.com/m"}),
    ("DELETE", f"/api/plugins/marketplaces/{SOURCE}", None),
    ("POST", f"/api/plugins/marketplaces/{SOURCE}/sync", None),
    ("GET", "/api/plugins/marketplaces/plugins", None),
    ("POST", f"/api/plugins/marketplaces/{SOURCE}/plugins/x/prepare", None),
    ("POST", "/api/plugins/marketplaces/install", {"preview_id": PREVIEW}),
    ("GET", f"/api/plugins/previews/{PREVIEW}/files", None),
    ("GET", f"/api/plugins/{ID}", None),
    ("GET", f"/api/plugins/{ID}/files", None),
    ("PATCH", f"/api/plugins/{ID}/enabled", {"enabled": True}),
    ("POST", f"/api/plugins/{ID}/update", {"path": "x"}),
    ("POST", f"/api/plugins/{ID}/update-upload", None),
    ("GET", f"/api/plugins/{ID}/credentials", None),
    ("PUT", f"/api/plugins/{ID}/credentials", {"values": {}}),
    ("DELETE", f"/api/plugins/{ID}/credentials", None),
    ("DELETE", f"/api/plugins/{ID}", None),
]
IDS = [f"{method} {path.split('?')[0]}" for method, path, _ in ROUTES]


def _state(tmp_path) -> dict:
    found = {f"data/{k}": v for k, v in tree(tmp_path / "data").items()}
    found |= {f"cache/{k}": v for k, v in tree(tmp_path / "cache").items()}
    return {k: v for k, v in found.items() if not k.startswith("data/evoflux.db")}


def _anonymous(backend, token: str | None) -> httpx.Client:
    headers = {} if token is None else {"Authorization": f"Bearer {token}"}
    return httpx.Client(base_url=backend.base_url, headers=headers, timeout=30.0)


@pytest.mark.parametrize(("method", "path", "body"), ROUTES, ids=IDS)
def test_missing_token_is_401(backend, method, path, body) -> None:
    with _anonymous(backend, None) as http:
        response = http.request(method, path, json=body)
    assert response.status_code == 401
    assert response.json() == UNAUTHORIZED_BODY


@pytest.mark.parametrize(("method", "path", "body"), ROUTES, ids=IDS)
def test_wrong_token_is_401(backend, method, path, body) -> None:
    with _anonymous(backend, "not-the-token") as http:
        response = http.request(method, path, json=body)
    assert response.status_code == 401
    assert response.json() == UNAUTHORIZED_BODY


def test_a_rejected_write_changes_nothing(backend, tmp_path, src) -> None:
    from plugin_helpers import write_plugin

    plugin = write_plugin(src / "p", "p", skills=("s",))
    before = _state(tmp_path)
    with _anonymous(backend, "not-the-token") as http:
        responses = [
            http.post("/api/plugins/install", json={"path": str(plugin)}),
            http.post("/api/plugins/create", json={"destination": str(src / "n"), "name": "n"}),
            http.post("/api/plugins/pack", json={"path": str(plugin)}),
            http.put(
                "/api/plugins/workspace/file",
                json={"root": str(plugin), "path": "plugin.json", "content": "{}"},
            ),
            http.post("/api/plugins/marketplaces", json={"kind": "claude_code", "name": "x", "url": "https://example.com/m"}),
        ]
    assert [r.status_code for r in responses] == [401] * 5
    after = _state(tmp_path)
    assert after == before
    assert not (src / "n").exists()
    assert not list(src.glob("*.evoplugin"))
