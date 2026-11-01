"""Marketplace sources, cached catalog search, prepare and install.

The host only fetches from public HTTPS hosts (it resolves the name and refuses
private addresses), so no local fixture server can stand in for one. These tests
therefore seed ``marketplaces.json`` and ``marketplace-cache/<id>.json`` the way a
sync would have written them, and never trigger a fetch.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from plugin_helpers import PREVIEW, SOURCE, tree

ADD = "/api/plugins/marketplaces"
SOURCE_KEYS = {"id", "kind", "name", "url", "added_at", "last_synced_at", "last_error"}
PLUGIN_KEYS = {
    "id", "marketplace_id", "name", "description", "version", "author", "source_type",
    "source_url", "source_path", "source_ref", "components", "categories", "keywords",
    "compatibility", "installable", "verification", "artifact_sha256", "artifact_size",
}  # fmt: skip
STAMP = "2026-01-01T00:00:00Z"


def add(client, url="https://example.com/registry.json", name="Reg", kind="agent_plugins"):
    return client.post(ADD, json={"kind": kind, "name": name, "url": url})


def seed_sources(platform_dir: Path, *sources: dict) -> None:
    platform_dir.mkdir(parents=True, exist_ok=True)
    document = {
        "version": 1,
        "sources": [
            {
                "kind": "agent_plugins",
                "added_at": STAMP,
                "last_synced_at": None,
                "last_error": None,
                **source,
            }
            for source in sources
        ],
    }
    (platform_dir / "marketplaces.json").write_text(json.dumps(document), encoding="utf-8")


def seed_catalog(platform_dir: Path, source_id: str, *plugins: dict) -> None:
    target = platform_dir / "marketplace-cache"
    target.mkdir(parents=True, exist_ok=True)
    entries = [
        {"marketplace_id": source_id, "id": f"{source_id}:{p['name']}", "source_type": "artifact", **p}
        for p in plugins
    ]
    (target / f"{source_id}.json").write_text(json.dumps({"version": 1, "plugins": entries}), encoding="utf-8")


def test_empty_listing(client) -> None:
    response = client.get(ADD)
    assert response.status_code == 200
    assert response.json() == []
    assert client.get(f"{ADD}/plugins").json() == []


def test_add_persists_without_fetching(client, platform_dir) -> None:
    response = add(client, "https://example.com/registry.json", " Reg ")
    assert response.status_code == 201
    body = response.json()
    assert set(body) == SOURCE_KEYS
    assert re.fullmatch(r"[0-9a-f]{16}", body["id"])
    assert body["name"] == "Reg"
    assert body["kind"] == "agent_plugins"
    assert body["url"] == "https://example.com/registry.json"
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z", body["added_at"])
    assert body["last_synced_at"] is None
    assert body["last_error"] is None
    stored = json.loads((platform_dir / "marketplaces.json").read_text(encoding="utf-8"))
    assert stored["version"] == 1
    assert [s["id"] for s in stored["sources"]] == [body["id"]]
    assert not (platform_dir / "marketplace-cache").exists()
    assert client.get(ADD).json() == [body]


def test_add_normalizes_the_url_through_urlsplit(client) -> None:
    body = add(client, "HTTPS://Example.COM/Registry.json?x=1").json()
    assert body["url"] == "https://Example.COM/Registry.json?x=1"


def test_listing_is_sorted_by_name_then_id(client) -> None:
    add(client, "https://a.example.com/r", "zulu")
    add(client, "https://b.example.com/r", "Alpha")
    add(client, "https://c.example.com/r", "alpha", kind="claude_code")
    names = [s["name"] for s in client.get(ADD).json()]
    assert names[-1] == "zulu"
    assert sorted(names[:2]) == ["Alpha", "alpha"]


@pytest.mark.parametrize(
    ("url", "detail"),
    [
        ("http://example.com/r.json", "Marketplace URL must use HTTPS."),
        ("ftp://example.com/r.json", "Marketplace URL must use HTTPS."),
        ("example.com/r.json", "Marketplace URL must use HTTPS."),
        ("https://", "Marketplace URL must have a public hostname and no credentials."),
        ("https://user:pw@example.com/r", "Marketplace URL must have a public hostname and no credentials."),
        ("https://user@example.com/r", "Marketplace URL must have a public hostname and no credentials."),
        ("https://example.com/r#frag", "Marketplace URL must not contain a fragment."),
        ("https://localhost/r", "Marketplace URL must resolve to a public host."),
        ("https://LOCALHOST./r", "Marketplace URL must resolve to a public host."),
        ("https://app.localhost/r", "Marketplace URL must resolve to a public host."),
        ("https://printer.local/r", "Marketplace URL must resolve to a public host."),
        ("https://db.internal/r", "Marketplace URL must resolve to a public host."),
        ("https://127.0.0.1/r", "Marketplace URL must resolve to a public host."),
        ("https://10.0.0.5/r", "Marketplace URL must resolve to a public host."),
        ("https://192.168.1.1/r", "Marketplace URL must resolve to a public host."),
        ("https://169.254.169.254/latest", "Marketplace URL must resolve to a public host."),
        ("https://[::1]/r", "Marketplace URL must resolve to a public host."),
    ],
)
def test_add_rejects_non_public_or_malformed_urls(client, platform_dir, url, detail) -> None:
    response = add(client, url)
    assert response.status_code == 422
    assert response.json() == {"detail": detail}
    assert not (platform_dir / "marketplaces.json").exists()


def test_add_url_that_is_a_decimal_or_short_ip_is_not_screened(client) -> None:
    """Suspected bug S4: only dotted/colon literals are parsed as addresses.

    ``https://2130706433/`` (127.0.0.1 as a decimal) passes validation because
    ``ipaddress.ip_address`` rejects it, so it is treated as a DNS name. The
    fetch-time ``getaddrinfo`` check is what stops it; the stored source is kept.
    """
    response = add(client, "https://2130706433/registry.json")
    assert response.status_code == 201
    assert response.json()["url"] == "https://2130706433/registry.json"


def test_add_url_longer_than_the_limit(client) -> None:
    too_long = "https://example.com/" + "a" * 2040
    assert add(client, too_long).status_code == 422
    assert add(client, "https://example.com/" + "a" * 2020).status_code == 201


def test_add_duplicate_is_409_ignoring_case_and_trailing_slash(client, platform_dir) -> None:
    assert add(client, "https://example.com/registry/").status_code == 201
    for url in ("https://example.com/registry", "https://EXAMPLE.com/Registry/"):
        response = add(client, url)
        assert response.status_code == 409
        assert response.json() == {"detail": "This marketplace URL was already added."}
    other_kind = add(client, "https://example.com/registry", kind="claude_code")
    assert other_kind.status_code == 201
    assert len(json.loads((platform_dir / "marketplaces.json").read_text())["sources"]) == 2


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"kind": "agent_plugins", "name": "x"},
        {"kind": "other", "name": "x", "url": "https://example.com/r"},
        {"kind": "agent_plugins", "name": "", "url": "https://example.com/r"},
        {"kind": "agent_plugins", "name": "x" * 121, "url": "https://example.com/r"},
        {"kind": "agent_plugins", "name": "x", "url": ""},
        {"kind": "agent_plugins", "name": "x", "url": "https://example.com/r", "extra": 1},
    ],
)
def test_add_request_validation(client, body) -> None:
    response = client.post(ADD, json=body)
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)


def test_add_blank_name_is_422_after_stripping(client) -> None:
    response = add(client, name="   ")
    assert response.status_code == 422
    assert response.json() == {"detail": "Marketplace name is required."}


def test_delete_removes_the_source_and_its_cache_only(client, platform_dir) -> None:
    source = add(client).json()
    seed_catalog(platform_dir, source["id"], {"name": "p"})
    keep = platform_dir / "installed" / "keep.txt"
    keep.parent.mkdir(parents=True)
    keep.write_text("x", encoding="utf-8")
    response = client.delete(f"{ADD}/{source['id']}")
    assert response.status_code == 200
    assert response.json() == source
    assert client.get(ADD).json() == []
    assert not (platform_dir / "marketplace-cache" / f"{source['id']}.json").exists()
    assert keep.exists()


@pytest.mark.parametrize("identifier", [SOURCE, "short", "UPPERCASE0000000"])
def test_delete_unknown_is_404(client, identifier) -> None:
    response = client.delete(f"{ADD}/{identifier}")
    assert response.status_code == 404
    assert response.json() == {"detail": f"Marketplace not found: {identifier}"}


def test_sync_unknown_and_malformed_ids(client) -> None:
    unknown = client.post(f"{ADD}/{SOURCE}/sync")
    assert unknown.status_code == 404
    assert unknown.json() == {"detail": f"Marketplace not found: {SOURCE}"}
    malformed = client.post(f"{ADD}/short/sync")
    assert malformed.status_code == 422
    assert malformed.json() == {"detail": "Marketplace id is invalid."}


def test_sync_failure_is_recorded_without_a_network_call(client, platform_dir) -> None:
    """A stored source with a refused URL fails validation before any fetch."""
    seed_sources(platform_dir, {"id": SOURCE, "name": "Local", "url": "http://localhost/registry.json"})
    response = client.post(f"{ADD}/{SOURCE}/sync")
    assert response.status_code == 422
    assert response.json() == {"detail": "Marketplace URL must use HTTPS."}
    listed = client.get(ADD).json()[0]
    assert listed["last_error"] == "Marketplace URL must use HTTPS."
    assert listed["last_synced_at"] is None
    assert not (platform_dir / "marketplace-cache").exists()


def test_sync_failure_keeps_the_stale_catalog(client, platform_dir) -> None:
    seed_sources(platform_dir, {"id": SOURCE, "name": "Local", "url": "https://localhost/registry.json"})
    seed_catalog(platform_dir, SOURCE, {"name": "kept", "compatibility": "compatible", "installable": True})
    before = tree(platform_dir / "marketplace-cache")
    assert client.post(f"{ADD}/{SOURCE}/sync").status_code == 422
    assert tree(platform_dir / "marketplace-cache") == before
    assert [p["name"] for p in client.get(f"{ADD}/plugins").json()] == ["kept"]


def test_search_reads_only_the_cache_and_filters(client, platform_dir) -> None:
    other = "c" * 16
    seed_sources(
        platform_dir,
        {"id": SOURCE, "name": "One", "url": "https://one.example.com/r"},
        {"id": other, "name": "Two", "url": "https://two.example.com/r"},
    )
    seed_catalog(
        platform_dir,
        SOURCE,
        {"name": "Zebra", "description": "Stripes", "author": "Ann"},
        {"name": "alpha", "description": "First letter"},
    )
    seed_catalog(platform_dir, other, {"name": "Alpha", "description": "Other source", "author": "Bob"})
    everything = client.get(f"{ADD}/plugins").json()
    assert [(p["name"], p["marketplace_id"]) for p in everything] == [
        ("alpha", SOURCE),
        ("Alpha", other),
        ("Zebra", SOURCE),
    ]
    assert set(everything[0]) == PLUGIN_KEYS
    assert everything[0] == {
        "id": f"{SOURCE}:alpha",
        "marketplace_id": SOURCE,
        "name": "alpha",
        "description": "First letter",
        "version": None,
        "author": None,
        "source_type": "artifact",
        "source_url": None,
        "source_path": None,
        "source_ref": None,
        "components": [],
        "categories": [],
        "keywords": [],
        "compatibility": "unknown",
        "installable": False,
        "verification": "unknown",
        "artifact_sha256": None,
        "artifact_size": None,
    }
    by_text = client.get(f"{ADD}/plugins", params={"q": "  STRIPES "}).json()
    assert [p["name"] for p in by_text] == ["Zebra"]
    by_author = client.get(f"{ADD}/plugins", params={"q": "bob"}).json()
    assert [p["name"] for p in by_author] == ["Alpha"]
    scoped = client.get(f"{ADD}/plugins", params={"marketplace_id": other}).json()
    assert [p["marketplace_id"] for p in scoped] == [other]
    assert client.get(f"{ADD}/plugins", params={"marketplace_id": "d" * 16}).json() == []


def test_search_query_limits(client) -> None:
    assert client.get(f"{ADD}/plugins", params={"q": "a" * 200}).status_code == 200
    assert client.get(f"{ADD}/plugins", params={"q": "a" * 201}).status_code == 422
    assert client.get(f"{ADD}/plugins", params={"marketplace_id": "a" * 17}).status_code == 422


def test_search_with_a_corrupt_cache_is_a_500(client, platform_dir) -> None:
    """Suspected bug B3: ``search_marketplaces`` does not catch the cache's ``ValueError``."""
    seed_sources(platform_dir, {"id": SOURCE, "name": "One", "url": "https://one.example.com/r"})
    (platform_dir / "marketplace-cache").mkdir()
    (platform_dir / "marketplace-cache" / f"{SOURCE}.json").write_text("{", encoding="utf-8")
    response = client.get(f"{ADD}/plugins")
    assert response.status_code == 500


def test_listing_with_a_corrupt_registry_is_a_500(client, platform_dir) -> None:
    """Suspected bug B3: the same uncaught ``ValueError`` on ``GET /marketplaces``."""
    platform_dir.mkdir(parents=True)
    (platform_dir / "marketplaces.json").write_text("not json", encoding="utf-8")
    assert client.get(ADD).status_code == 500
    assert add(client).status_code == 422


def test_prepare_unknown_marketplace_and_plugin(client, platform_dir) -> None:
    unknown = client.post(f"{ADD}/{SOURCE}/plugins/x/prepare")
    assert unknown.status_code == 404
    assert unknown.json() == {"detail": f"Marketplace not found: {SOURCE}"}
    malformed = client.post(f"{ADD}/short/plugins/x/prepare")
    assert malformed.status_code == 422
    assert malformed.json() == {"detail": "Marketplace id is invalid."}
    seed_sources(platform_dir, {"id": SOURCE, "name": "One", "url": "https://one.example.com/r"})
    seed_catalog(platform_dir, SOURCE, {"name": "there"})
    missing = client.post(f"{ADD}/{SOURCE}/plugins/absent/prepare")
    assert missing.status_code == 404
    assert missing.json() == {"detail": "Marketplace plugin not found: absent"}


def test_prepare_refuses_unsupported_entries_before_downloading(client, platform_dir, staging_dir) -> None:
    seed_sources(
        platform_dir,
        {"id": SOURCE, "name": "One", "url": "https://one.example.com/r"},
        {"id": "e" * 16, "name": "Claude", "kind": "claude_code", "url": "https://raw.githubusercontent.com/o/r/main/.claude-plugin/marketplace.json"},
    )
    seed_catalog(platform_dir, SOURCE, {"name": "notportable", "installable": False})
    refused = client.post(f"{ADD}/{SOURCE}/plugins/notportable/prepare")
    assert refused.status_code == 422
    assert refused.json() == {"detail": "This Agent Plugin is not portable to EvoFlux."}
    seed_catalog(
        platform_dir,
        "e" * 16,
        {"name": "viacmd", "source_type": "command", "compatibility": "unsupported"},
        {"name": "vianpm", "source_type": "npm", "compatibility": "unknown", "installable": True},
    )
    for name in ("viacmd", "vianpm"):
        response = client.post(f"{ADD}/{'e' * 16}/plugins/{name}/prepare")
        assert response.status_code == 422
        assert response.json() == {"detail": "This Claude plugin source is not supported by EvoFlux."}
    assert not staging_dir.exists() or not (staging_dir / "marketplace-previews").exists() or list((staging_dir / "marketplace-previews").iterdir()) == []


def test_prepare_ambiguous_name(client, platform_dir) -> None:
    seed_sources(platform_dir, {"id": SOURCE, "name": "One", "url": "https://one.example.com/r"})
    seed_catalog(platform_dir, SOURCE, {"name": "dup"}, {"name": "dup"})
    response = client.post(f"{ADD}/{SOURCE}/plugins/dup/prepare")
    assert response.status_code == 422
    assert response.json() == {"detail": "Marketplace plugin id is ambiguous; use its exact name."}


@pytest.mark.skip(
    reason="prepare downloads from a public HTTPS host (DNS-checked, no loopback or proxy seam); "
    "the artifact, repository-archive and normalization paths are covered by NOTES and need Rust unit tests"
)
def test_prepare_and_install_a_downloaded_package() -> None:
    raise AssertionError("unreachable")


def test_install_prepared_unknown_and_malformed_previews(client) -> None:
    unknown = client.post(f"{ADD}/install", json={"preview_id": PREVIEW})
    assert unknown.status_code == 404
    assert unknown.json() == {"detail": "Marketplace preview expired or does not exist."}
    for body in (
        {},
        {"preview_id": "short"},
        {"preview_id": "A" * 32},
        {"preview_id": PREVIEW, "allow_partial": "maybe"},
        {"preview_id": PREVIEW, "extra": 1},
    ):
        response = client.post(f"{ADD}/install", json=body)
        assert response.status_code == 422
        assert isinstance(response.json()["detail"], list)


def test_marketplace_routes_are_not_shadowed_by_the_installation_id_routes(client) -> None:
    """``/marketplaces/plugins`` and ``/marketplaces/install`` are static routes."""
    assert client.get(f"{ADD}/plugins").status_code == 200
    assert client.post(f"{ADD}/install", json={"preview_id": PREVIEW}).status_code == 404
    assert client.get("/api/plugins/marketplaces/x/files").status_code == 404
