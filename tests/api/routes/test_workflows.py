"""Workflows API — CRUD/approve contracts (plan M2)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import app.models.workflow  # noqa: F401 — register tables before setup_db
from app.api.routes.workflows import router as workflows_router

VALID = """
schema_version: 1
name: {name}
description: test workflow
scope: work
nodes:
  - id: only
    kind: notify
    message: hi
"""


@pytest.fixture
async def client(tmp_path, monkeypatch):
    from app.core.config import settings as app_settings

    monkeypatch.setattr(app_settings, "EVOFLUX_CONFIG_DIR", str(tmp_path / "config"))
    app = FastAPI()
    app.include_router(workflows_router, prefix="/api/workflows")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        yield c


@pytest.mark.asyncio
async def test_list_includes_builtins_with_hash_and_approval_state(client, setup_db):
    resp = await client.get("/api/workflows")
    assert resp.status_code == 200
    workflows = {wf["name"]: wf for wf in resp.json()["workflows"]}
    assert "second-opinion" in workflows
    entry = workflows["second-opinion"]
    assert entry["scope"] == "work"
    assert entry["root"] == "builtin"
    assert entry["approved"] is False
    assert len(entry["hash"]) == 64
    assert "aim-test-compare" not in workflows
    assert "aim-design-unit" not in workflows


@pytest.mark.asyncio
async def test_save_get_delete_roundtrip(client, setup_db):
    raw = VALID.format(name="my-flow")
    resp = await client.put("/api/workflows/my-flow", json={"raw_yaml": raw})
    assert resp.status_code == 200
    body = resp.json()
    assert body["root"] == "global"
    assert body["approved"] is False
    assert body["errors"] == []

    got = await client.get("/api/workflows/my-flow")
    assert got.status_code == 200
    assert got.json()["raw_yaml"] == raw

    gone = await client.delete("/api/workflows/my-flow")
    assert gone.status_code == 204
    assert (await client.get("/api/workflows/my-flow")).status_code == 404


@pytest.mark.asyncio
async def test_save_rejects_invalid_definition_with_field_errors(client, setup_db):
    resp = await client.put(
        "/api/workflows/bad",
        json={
            "raw_yaml": "schema_version: 1\nname: bad\nnodes:\n  - {id: g, kind: gate, title: t, choices: []}\n"
        },
    )
    assert resp.status_code == 422
    assert any("choices" in str(err) for err in resp.json()["detail"])


@pytest.mark.asyncio
async def test_save_rejects_name_mismatch_and_cycles(client, setup_db):
    resp = await client.put(
        "/api/workflows/other", json={"raw_yaml": VALID.format(name="my-flow")}
    )
    assert resp.status_code == 422
    assert any("must match" in str(err) for err in resp.json()["detail"])

    cyclic = """
schema_version: 1
name: loopy
nodes:
  - { id: a, kind: notify, message: m }
  - { id: b, kind: notify, message: m }
edges:
  - { from: a, to: b }
  - { from: b, to: a }
"""
    resp = await client.put("/api/workflows/loopy", json={"raw_yaml": cyclic})
    assert resp.status_code == 422
    assert any("cycle" in str(err) for err in resp.json()["detail"])


@pytest.mark.asyncio
async def test_save_rejects_unknown_tool(client, setup_db):
    raw = """
schema_version: 1
name: toolless
nodes:
  - { id: t, kind: tool, tool: not_a_real_tool, args: {} }
"""
    resp = await client.put("/api/workflows/toolless", json={"raw_yaml": raw})
    assert resp.status_code == 422
    assert any("not_a_real_tool" in str(err) for err in resp.json()["detail"])


@pytest.mark.asyncio
async def test_approve_flow_and_hash_mismatch_409(client, setup_db):
    raw = VALID.format(name="approvable")
    saved = await client.put("/api/workflows/approvable", json={"raw_yaml": raw})
    file_hash = saved.json()["hash"]

    stale = await client.post(
        "/api/workflows/approvable/approve", json={"hash": "0" * 64}
    )
    assert stale.status_code == 409

    ok = await client.post(
        "/api/workflows/approvable/approve", json={"hash": file_hash}
    )
    assert ok.status_code == 204

    detail = await client.get("/api/workflows/approvable")
    assert detail.json()["approved"] is True

    # Editing the file invalidates the approval (hash changes).
    await client.put(
        "/api/workflows/approvable",
        json={"raw_yaml": raw.replace("hi", "hello")},
    )
    detail2 = await client.get("/api/workflows/approvable")
    assert detail2.json()["approved"] is False


@pytest.mark.asyncio
async def test_workspace_root_shadows_global_and_needs_own_approval(
    client, setup_db, tmp_path
):
    workspace = tmp_path / "repo"
    (workspace / ".evoflux" / "workflows").mkdir(parents=True)

    raw_global = VALID.format(name="shadowed")
    saved = await client.put("/api/workflows/shadowed", json={"raw_yaml": raw_global})
    await client.post(
        "/api/workflows/shadowed/approve", json={"hash": saved.json()["hash"]}
    )

    raw_ws = raw_global.replace("hi", "workspace override")
    ws_saved = await client.put(
        f"/api/workflows/shadowed?workspace={workspace}", json={"raw_yaml": raw_ws}
    )
    assert ws_saved.json()["root"] == "workspace"
    # Same name, different content/root → NOT approved.
    assert ws_saved.json()["approved"] is False

    listed = await client.get(f"/api/workflows?workspace={workspace}")
    entry = next(w for w in listed.json()["workflows"] if w["name"] == "shadowed")
    assert entry["root"] == "workspace"
    assert entry["approved"] is False


@pytest.mark.asyncio
async def test_delete_builtin_is_404(client, setup_db):
    resp = await client.delete("/api/workflows/second-opinion")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_detail_exposes_manifest_and_lint(client, setup_db):
    raw = """
schema_version: 1
name: risky
scope: work
nodes:
  - { id: run, kind: tool, tool: shell, args: { command: "echo hi" } }
"""
    saved = await client.put("/api/workflows/risky", json={"raw_yaml": raw})
    body = saved.json()
    assert body["manifest"]["tools"] == ["shell"]
    assert any("destructive" in w or "shell" in w for w in body["lint_warnings"])
