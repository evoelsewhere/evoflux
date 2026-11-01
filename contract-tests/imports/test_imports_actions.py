"""``/api/import`` contract: preview actions (single and bulk)."""

from __future__ import annotations

from pathlib import Path

from import_sources import build_generic_dir, detect_ok, write


def _generic(client, tmp_path: Path) -> tuple[str, list[dict]]:
    body = detect_ok(client, build_generic_dir(tmp_path), "generic")
    return body["import_id"], body["items"]


def _index(items: list[dict], kind: str) -> int:
    return next(i for i, item in enumerate(items) if item["kind"] == kind)


def _external_skill(client, home: Path, tmp_path: Path) -> tuple[str, int]:
    """A generic SKILL.md whose name a Claude Code global Skill already owns."""
    write(
        home / ".claude" / "skills" / "pdf-tools" / "SKILL.md",
        "---\nname: pdf-tools\ndescription: Claude copy\n---\nx",
    )
    write(
        tmp_path / "skill-src" / "SKILL.md",
        "---\nname: pdf-tools\ndescription: Mine\n---\nbody",
    )
    body = detect_ok(client, tmp_path / "skill-src" / "SKILL.md")
    item = body["items"][0]
    assert item["conflicts"] == ["Skill already exists in Claude Code skills"]
    assert item["action"] == "skip"
    assert item["origin"] == "Claude Code skills"
    return body["import_id"], 0


# ── PATCH /preview/{id}/items/{index} ──────────────────────────────────────


def test_item_action_unknown_import_is_404(client) -> None:
    response = client.patch("/api/import/preview/nope/items/0", json={"action": "skip"})
    assert response.status_code == 404
    assert response.json() == {"detail": "Import not found"}


def test_item_action_validation(client, tmp_path, snapshot) -> None:
    import_id, items = _generic(client, tmp_path)
    base = f"/api/import/preview/{import_id}/items"
    for index in (len(items), -1):
        response = client.patch(f"{base}/{index}", json={"action": "skip"})
        assert response.status_code == 400
        assert response.json() == {"detail": "Invalid item index"}

    response = client.patch(f"{base}/0", json={"action": "delete"})
    assert response.status_code == 400
    detail = response.json()["detail"]
    # Python renders its ``allowed`` set, whose order depends on the hash seed.
    assert detail.startswith("Invalid action. Allowed: {") and detail.endswith("}")
    rendered = detail.removeprefix("Invalid action. Allowed: {").removesuffix("}")
    assert sorted(rendered.split(", ")) == sorted(
        ["'import'", "'skip'", "'replace'", "'reimport'", "'rename'"]
    )

    missing = client.patch(f"{base}/0", json={})
    assert missing.status_code == 422
    not_int = client.patch(f"{base}/x", json={"action": "skip"})
    assert not_int.status_code == 422
    snapshot.check(
        "item_action_422.json", {"missing": missing.json(), "not_int": not_int.json()}
    )


def test_item_action_rules(client, tmp_path) -> None:
    import_id, items = _generic(client, tmp_path)
    base = f"/api/import/preview/{import_id}/items"
    setting = _index(items, "setting")
    response = client.patch(f"{base}/{setting}", json={"action": "import"})
    assert response.status_code == 400
    assert response.json() == {"detail": "This item type cannot be imported"}
    response = client.patch(f"{base}/{setting}", json={"action": "skip"})
    assert response.json() == {
        "status": "ok",
        "target_name": "Credential: OPENAI_API_KEY",
    }

    agent = _index(items, "agent")
    response = client.patch(f"{base}/{agent}", json={"action": "rename"})
    assert response.status_code == 400
    assert response.json() == {
        "detail": "Keep both is available for Skills that conflict with another local source"
    }
    for action in ("skip", "import", "replace", "reimport"):
        response = client.patch(f"{base}/{agent}", json={"action": action})
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "target_name": "helper-bot"}
    preview = client.get(f"/api/import/preview/{import_id}").json()
    assert preview["items"][agent]["action"] == "reimport"


def test_item_action_external_skill_rename_and_reimport(client, home, tmp_path) -> None:
    import_id, index = _external_skill(client, home, tmp_path)
    url = f"/api/import/preview/{import_id}/items/{index}"
    for action in ("reimport", "replace"):
        response = client.patch(url, json={"action": action})
        assert response.status_code == 400
        assert response.json() == {
            "detail": "This Skill exists outside EvoFlux; choose Keep both or skip it"
        }
    response = client.patch(url, json={"action": "rename"})
    assert response.json() == {"status": "ok", "target_name": "pdf-tools-evoflux"}
    preview = client.get(f"/api/import/preview/{import_id}").json()
    assert preview["items"][0]["target_name"] == "pdf-tools-evoflux"
    assert preview["items"][0]["action"] == "rename"
    # Going back restores the original name.
    response = client.patch(url, json={"action": "skip"})
    assert response.json() == {"status": "ok", "target_name": "pdf-tools"}


def test_item_action_rename_skips_taken_evoflux_names(
    client, home, tmp_path, config_dir
) -> None:
    (config_dir / "skills" / "pdf-tools-evoflux").mkdir(parents=True)
    import_id, index = _external_skill(client, home, tmp_path)
    response = client.patch(
        f"/api/import/preview/{import_id}/items/{index}", json={"action": "rename"}
    )
    assert response.json() == {"status": "ok", "target_name": "pdf-tools-evoflux-2"}


# ── PATCH /preview/{id}/items ──────────────────────────────────────────────


def test_bulk_action_unknown_import_is_404(client) -> None:
    response = client.patch(
        "/api/import/preview/nope/items", json={"indexes": [0], "action": "skip"}
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "Import not found"}


def test_bulk_action_validation(client, tmp_path, snapshot) -> None:
    import_id, items = _generic(client, tmp_path)
    url = f"/api/import/preview/{import_id}/items"
    errors = {}
    for name, body in {
        "empty": {"indexes": [], "action": "skip"},
        "bad_action": {"indexes": [0], "action": "rename"},
        "missing": {"action": "skip"},
        "not_ints": {"indexes": ["a"], "action": "skip"},
    }.items():
        response = client.patch(url, json=body)
        assert response.status_code == 422, name
        errors[name] = response.json()
    snapshot.check("bulk_action_422.json", errors)

    cases = [
        ({"indexes": [0, 0], "action": "skip"}, "Item indexes must be unique"),
        ({"indexes": [0, len(items)], "action": "skip"}, "Invalid item index"),
        ({"indexes": [-1], "action": "skip"}, "Invalid item index"),
        (
            {"indexes": [_index(items, "setting")], "action": "import"},
            "Selected item types cannot be imported",
        ),
        (
            {"indexes": [_index(items, "agent")], "action": "reimport"},
            "Re-import can only be applied to items with detected conflicts",
        ),
    ]
    for body, detail in cases:
        response = client.patch(url, json=body)
        assert response.status_code == 400, body
        assert response.json() == {"detail": detail}
    # Nothing changed after the failed validations.
    preview = client.get(f"/api/import/preview/{import_id}").json()
    assert [item["action"] for item in preview["items"]] == [
        item["action"] for item in items
    ]


def test_bulk_action_updates_every_index(client, tmp_path) -> None:
    import_id, items = _generic(client, tmp_path)
    indexes = [i for i, item in enumerate(items) if item["kind"] != "setting"]
    response = client.patch(
        f"/api/import/preview/{import_id}/items",
        json={"indexes": indexes, "action": "skip"},
    )
    assert response.json() == {"status": "ok", "updated": len(indexes)}
    preview = client.get(f"/api/import/preview/{import_id}").json()
    assert all(item["action"] == "skip" for item in preview["items"])
    assert preview["summary"]["new_items"] == 0


def test_bulk_reimport_rejects_external_skill(client, home, tmp_path) -> None:
    import_id, index = _external_skill(client, home, tmp_path)
    response = client.patch(
        f"/api/import/preview/{import_id}/items",
        json={"indexes": [index], "action": "reimport"},
    )
    assert response.status_code == 400
    assert response.json() == {
        "detail": "External Skill conflicts must be skipped or kept as an EvoFlux copy"
    }
