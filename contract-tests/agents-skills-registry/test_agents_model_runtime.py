"""``PATCH /api/agents/model`` and the Conductor-managed runtime settings routes."""

from __future__ import annotations

import json

import pytest

from provider_setup import configure_backend_provider
from mock_provider.server import MockProvider
from registry_helpers import agent_md, agent_settings_id, lf, managed_state, tree

PLACEHOLDER = "__PROVIDER_MODEL__"
MANAGED_RESOURCE = "res-team"


def bulk(client, names, model="openai:gpt-5"):
    response = client.patch("/api/agents/model", json={"names": names, "model": model})
    assert response.status_code == 200
    return response.json()["results"]


def read(path) -> str:
    return lf(path.read_bytes()).decode("utf-8")


# ── bulk model: file rewrite through yaml.safe_dump ─────────────────────────

EMITTER_INPUT = (
    "---\nname: emit\nrole: member\n# a comment\n"
    'description: "Caf\u00e9 \u2014 says: hello, it\'s a very long description that keeps '
    'going past the eighty column mark to force folding"\n'
    "tools: [read, grep]\nskills:\n  - one\n  - two\nversion: '1.0'\nflag: yes\n"
    "count: 007\nempty:\nquoted: \"a: b\"\nmulti: |\n  line one\n  line two\n"
    "model: __PROVIDER_MODEL__\n---\nBody text\nsecond line\n"
)
EMITTER_OUTPUT = r"""---
name: emit
role: member
description: "Caf\xE9 \u2014 says: hello, it's a very long description that keeps\
  \ going past the eighty column mark to force folding"
tools:
- read
- grep
skills:
- one
- two
version: '1.0'
flag: true
count: 7
empty: null
quoted: 'a: b'
multi: 'line one

  line two

  '
model: openai:gpt-5
---
Body text
second line
"""


def test_bulk_model_rewrites_the_frontmatter_with_pyyaml_safe_dump(client, agents_dir) -> None:
    """The emitter's observable rules: comments are lost, flow lists become block
    lists, non-ASCII is escaped (``\\xE9``, ``\\u2014``), long scalars fold at 80
    columns, YAML 1.1 scalars are resolved (``yes`` -> ``true``, ``007`` -> ``7``,
    empty -> ``null``), and the body after the closing ``---`` is kept verbatim."""
    created = client.post("/api/agents", json={"name": "emit", "content": EMITTER_INPUT})
    assert created.status_code == 201
    assert bulk(client, ["emit"]) == [{"name": "emit", "ok": True, "error": None}]
    assert read(agents_dir / "emit.md") == EMITTER_OUTPUT


def test_bulk_model_normalizes_crlf_files_and_an_unterminated_block(client, agents_dir) -> None:
    (agents_dir / "crlf.md").write_bytes(b"---\r\nname: crlf\r\nrole: member\r\n---\r\n\r\nBody\r\n")
    (agents_dir / "bare.md").write_bytes(b"---\nname: bare\n---")
    assert all(row["ok"] for row in bulk(client, ["crlf", "bare"]))
    # ``read_text`` folds CRLF, so the rewritten file is LF-only on every platform.
    assert read(agents_dir / "crlf.md") == "---\nname: crlf\nrole: member\nmodel: openai:gpt-5\n---\n\nBody\n"
    assert read(agents_dir / "bare.md") == "---\nname: bare\nmodel: openai:gpt-5\n---\n"


def test_bulk_model_reports_each_name_in_request_order(client, agents_dir) -> None:
    (agents_dir / "nofm.md").write_text("no frontmatter", encoding="utf-8")
    (agents_dir / "list.md").write_text("---\n- a\n---\nx", encoding="utf-8")
    (agents_dir / "yaml.md").write_text("---\n: :\n---\nx", encoding="utf-8")
    (agents_dir / "empty.md").write_text("---\n---\nx", encoding="utf-8")
    before = tree(agents_dir)
    results = bulk(client, ["nofm", "ghost", "list", "../x", "yaml", "coding/ghost", "empty"], "nocolon:")
    by_name = {r["name"]: r for r in results}
    assert [r["name"] for r in results] == ["nofm", "ghost", "list", "../x", "yaml", "coding/ghost", "empty"]
    assert all(r["ok"] is False for r in results)
    assert by_name["nofm"]["error"] == "Missing YAML frontmatter."
    assert by_name["ghost"]["error"] == "Agent 'ghost' not found."
    assert by_name["list"]["error"] == "Frontmatter must be a YAML mapping."
    assert by_name["../x"]["error"] == (
        "Invalid agent path '../x'. Use '<name>' for Work or 'coding/<name>' for Coding."
    )
    assert by_name["yaml"]["error"].startswith("Invalid YAML frontmatter: while parsing a block mapping")
    assert by_name["coding/ghost"]["error"] == "Agent 'ghost' not found.".replace("'ghost'", "'coding/ghost'")
    assert by_name["empty"]["error"] == "Missing YAML frontmatter."
    assert tree(agents_dir) == before


def test_bulk_model_validates_the_model_per_agent_without_writing(client, agents_dir) -> None:
    before = tree(agents_dir)
    [result] = bulk(client, ["explorer"], "nocolon")
    assert result == {
        "name": "explorer",
        "ok": False,
        "error": ": Value error, Agent 'explorer': invalid model 'nocolon' "
        "(expected 'provider:model', e.g. 'googlegenai:gemini-3.1-flash').",
    }
    assert tree(agents_dir) == before


def test_bulk_model_accepts_any_provider_model_pair_for_unmanaged_agents(client, agents_dir) -> None:
    """The model is not checked against the registry for files EvoFlux owns."""
    assert bulk(client, ["explorer"], "nosuchprovider:nosuchmodel")[0]["ok"] is True
    assert "model: nosuchprovider:nosuchmodel" in read(agents_dir / "explorer.md")


def test_bulk_model_edge_cases(client) -> None:
    assert bulk(client, []) == []
    twice = bulk(client, ["explorer", "explorer"])
    assert [r["ok"] for r in twice] == [True, True]
    for body in ({}, {"names": ["x"]}, {"model": "a:b"}, {"names": "x", "model": "a:b"}):
        response = client.patch("/api/agents/model", json=body)
        assert response.status_code == 422
        assert isinstance(response.json()["detail"], list)


def test_a_non_utf8_agent_file_makes_bulk_model_an_unhandled_500(client, agents_dir) -> None:
    (agents_dir / "nonutf.md").write_bytes(b"---\nname: n\n---\n\xff")
    response = client.patch("/api/agents/model", json={"names": ["nonutf"], "model": "a:b"})
    assert response.status_code == 500
    assert response.text == "Internal Server Error"


def test_bulk_model_fills_placeholders_after_the_first_success_only(client, agents_dir) -> None:
    assert not any(r["ok"] for r in bulk(client, ["ghost"]))
    assert PLACEHOLDER in read(agents_dir / "explorer.md")
    assert bulk(client, ["evoflux"])[0]["ok"] is True
    for path in sorted(agents_dir.rglob("*.md")):
        assert PLACEHOLDER not in read(path), path.name
        assert "model: openai:gpt-5" in read(path), path.name


def test_the_placeholder_fill_replaces_the_token_anywhere_in_the_file(client, agents_dir) -> None:
    body = f"Use {PLACEHOLDER} wisely.\n"
    client.post("/api/agents", json={"name": "talker", "content": agent_md("talker", body=body)})
    bulk(client, ["evoflux"])
    assert read(agents_dir / "talker.md").endswith("Use openai:gpt-5 wisely.\n")


# ── Conductor-managed agents ────────────────────────────────────────────────


@pytest.fixture
def provider():
    mock = MockProvider(model_ids=("mock-model", "other-model"))
    try:
        yield mock
    finally:
        mock.close()


@pytest.fixture
def managed(client, provider, config_dir, state_dir):
    """A configured provider and a Conductor Team that owns ``explorer``."""
    configure_backend_provider(client, provider)
    managed_state(state_dir, config_dir, agent_targets=["explorer"])


def settings_json(config_dir):
    path = config_dir / "agent-settings.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def record_id() -> str:
    return agent_settings_id("proj-1", MANAGED_RESOURCE, "explorer")


def test_managed_agents_carry_provenance_and_are_not_editable(client, managed, config_dir) -> None:
    rows = {r["name"]: r for r in client.get("/api/agents").json()["agents"]}
    explorer = rows["explorer"]
    assert explorer["editable"] is False and explorer["runtime_model_editable"] is True
    assert explorer["bundle_model"] == "router9:mock-model"
    assert explorer["model_override"] is None
    assert explorer["provider"]["project_name"] == "Acme"
    assert explorer["provider"]["resource_id"] == MANAGED_RESOURCE
    assert explorer["provider"]["modes"] == ["work", "coding"]
    assert explorer["provider"]["version"] == "1.0.0"
    assert rows["consultant"]["editable"] is True and rows["consultant"]["provider"] is None
    assert rows["consultant"]["runtime_model_editable"] is False
    detail = client.get("/api/agents/explorer").json()
    assert (detail["editable"], detail["runtime_model_editable"]) == (False, True)
    assert detail["provider"]["observed_state"] == "applied"


def test_managed_agents_cannot_be_edited_or_deleted_locally(client, managed, agents_dir) -> None:
    before = tree(agents_dir)
    message = "Agent 'explorer' is managed by Conductor project 'Acme' and cannot be {} locally."
    put = client.put("/api/agents/explorer", json={"name": "explorer", "content": agent_md("explorer")})
    assert (put.status_code, put.json()) == (403, {"detail": message.format("edited")})
    delete = client.delete("/api/agents/explorer")
    assert (delete.status_code, delete.json()) == (403, {"detail": message.format("deleted")})
    # The managed check comes before any file or name validation.
    other = client.put("/api/agents/explorer", json={"name": "other", "content": "x"})
    assert other.status_code == 422
    assert tree(agents_dir) == before


def test_runtime_model_sets_and_resets_the_installation_override(
    client, managed, config_dir, agents_dir
) -> None:
    before = tree(agents_dir)
    response = client.patch("/api/agents/runtime-model/explorer", json={"model": "router9:other-model"})
    assert response.status_code == 200
    body = response.json()
    assert body["model_override"] == "router9:other-model"
    assert body["bundle_model"] == "router9:mock-model"
    assert body["config"]["model"] == "router9:other-model"
    assert (body["editable"], body["runtime_model_editable"]) == (False, True)
    assert lf((config_dir / "agent-settings.json").read_bytes()) == (
        '{\n  "agents": {\n    "' + record_id() + '": {\n'
        '      "extra_mcp": [],\n      "extra_skills": [],\n      "extra_tools": [],\n'
        '      "model": "router9:other-model",\n      "name": "explorer",\n'
        '      "project_id": "proj-1",\n      "resource_id": "res-team"\n    }\n  },\n'
        '  "version": 1\n}\n'
    ).encode()
    listed = {r["name"]: r for r in client.get("/api/agents").json()["agents"]}["explorer"]
    assert (listed["model"], listed["model_override"]) == ("router9:other-model", "router9:other-model")
    reset = client.patch("/api/agents/runtime-model/explorer", json={"model": None})
    assert reset.status_code == 200 and reset.json()["model_override"] is None
    assert not (config_dir / "agent-settings.json").exists()  # last record gone, file removed
    assert client.patch("/api/agents/runtime-model/explorer", json={"model": None}).status_code == 200
    assert tree(agents_dir) == before  # the bundle itself is never rewritten


@pytest.mark.parametrize(
    ("path", "body", "status", "detail"),
    [
        ("consultant", {"model": None}, 409, "Agent 'consultant' is not managed by Conductor."),
        ("ghost", {"model": None}, 404, "Agent 'ghost' not found."),
        ("a/b/c", {"model": None}, 400, "Invalid agent path 'a/b/c'. Use '<name>' for Work or 'coding/<name>' for Coding."),
        ("explorer", {"model": "openai:gpt-5"}, 422, "Model 'openai:gpt-5' is not configured or selectable."),
        ("explorer", {"model": "nocolon"}, 422, "Model 'nocolon' is not configured or selectable."),
        ("explorer", {"model": "router9:ghost-model"}, 422, "Model 'router9:ghost-model' is not configured or selectable."),
    ],
)
def test_runtime_model_errors(client, managed, config_dir, path, body, status, detail) -> None:
    response = client.patch(f"/api/agents/runtime-model/{path}", json=body)
    assert (response.status_code, response.json()) == (status, {"detail": detail})
    assert not (config_dir / "agent-settings.json").exists()


def test_runtime_model_requires_the_model_key(client, managed) -> None:
    response = client.patch("/api/agents/runtime-model/explorer", json={})
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "model"]


def test_runtime_settings_store_a_deduplicated_additive_layer(client, managed, config_dir) -> None:
    response = client.patch(
        "/api/agents/runtime-settings/explorer",
        json={
            "model": "router9:other-model",
            "extra_tools": ["date", "date", "glob"],
            "extra_skills": ["browser-use"],
            "extra_mcp": ["my-server", "my-server"],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert (body["extra_tools"], body["extra_skills"], body["extra_mcp"]) == (
        ["date", "glob"], ["browser-use"], ["my-server"],
    )
    assert body["model_override"] == "router9:other-model"
    assert {"date", "glob"} <= set(body["config"]["tools"])
    assert body["config"]["skills"] == ["browser-use"]
    assert body["config"]["mcp"] == ["my-server"]
    stored = settings_json(config_dir)
    assert stored == {
        "version": 1,
        "agents": {
            record_id(): {
                "project_id": "proj-1", "resource_id": "res-team", "name": "explorer",
                "model": "router9:other-model", "extra_tools": ["date", "glob"],
                "extra_skills": ["browser-use"], "extra_mcp": ["my-server"],
            }
        },
    }  # fmt: skip
    raw = lf((config_dir / "agent-settings.json").read_bytes()).decode()
    assert raw.index('"extra_mcp"') < raw.index('"extra_skills"') < raw.index('"extra_tools"')
    # Without a model the record keeps no ``model`` key; resetting only the model keeps the additions.
    client.patch("/api/agents/runtime-settings/explorer", json={"extra_tools": ["date"]})
    assert "model" not in settings_json(config_dir)["agents"][record_id()]
    client.patch("/api/agents/runtime-model/explorer", json={"model": "router9:mock-model"})
    client.patch("/api/agents/runtime-model/explorer", json={"model": None})
    assert settings_json(config_dir)["agents"][record_id()]["extra_tools"] == ["date"]


def test_runtime_settings_errors(client, managed, config_dir) -> None:
    unknown = client.patch(
        "/api/agents/runtime-settings/explorer",
        json={"extra_tools": ["zz-tool", "aa-tool"], "extra_skills": ["zz-skill", "aa-skill"], "extra_mcp": ["whatever"]},
    )
    assert unknown.status_code == 422
    assert unknown.json() == {"detail": "unknown tools: aa-tool, zz-tool; unknown skills: aa-skill, zz-skill"}
    only_skills = client.patch("/api/agents/runtime-settings/explorer", json={"extra_skills": ["nope"]})
    assert only_skills.json() == {"detail": "unknown skills: nope"}
    assert client.patch("/api/agents/runtime-settings/consultant", json={}).status_code == 409
    assert client.patch("/api/agents/runtime-settings/ghost", json={}).status_code == 404
    assert client.patch("/api/agents/runtime-settings/explorer", json={"model": "openai:gpt-5"}).json() == {
        "detail": "Model 'openai:gpt-5' is not configured or selectable."
    }
    too_many = client.patch(
        "/api/agents/runtime-settings/explorer", json={"extra_mcp": [f"m{i}" for i in range(201)]}
    )
    assert too_many.status_code == 422
    assert too_many.json()["detail"][0]["type"] == "too_long"
    long_name = client.patch("/api/agents/runtime-settings/explorer", json={"extra_mcp": ["m" * 129]})
    assert long_name.status_code == 422
    assert long_name.json() == {"detail": "extra_mcp contains an invalid name."}
    assert not (config_dir / "agent-settings.json").exists()


def test_runtime_settings_refuse_to_overwrite_a_corrupt_store(client, managed, config_dir, scrub) -> None:
    (config_dir / "agent-settings.json").write_bytes(b"{nope")
    response = client.patch("/api/agents/runtime-settings/explorer", json={})
    assert response.status_code == 422
    assert scrub(response.json()["detail"]).startswith(
        "<tmp>/config/agent-settings.json is not valid JSON:"
    )
    assert (config_dir / "agent-settings.json").read_bytes() == b"{nope"


def test_bulk_model_on_managed_agents_writes_the_runtime_store_not_the_file(
    client, managed, config_dir, agents_dir
) -> None:
    before = tree(agents_dir)
    results = bulk(client, ["explorer", "consultant", "explorer"], "router9:other-model")
    assert results == [
        {"name": "explorer", "ok": True, "error": None},
        {"name": "consultant", "ok": True, "error": None},
        {"name": "explorer", "ok": True, "error": None},
    ]
    assert settings_json(config_dir)["agents"][record_id()]["model"] == "router9:other-model"
    changed = {k for k in tree(agents_dir) if tree(agents_dir)[k] != before[k]}
    assert changed == {"consultant.md"}  # only the unmanaged file was rewritten
    rejected = bulk(client, ["explorer", "consultant"], "openai:gpt-5")
    assert rejected[0] == {
        "name": "explorer", "ok": False,
        "error": "Model 'openai:gpt-5' is not configured or selectable.",
    }  # fmt: skip
    assert rejected[1]["ok"] is True  # an unmanaged agent takes any provider:model


def test_the_placeholder_fill_skips_managed_files(client, config_dir, state_dir, agents_dir) -> None:
    managed_state(state_dir, config_dir, agent_targets=["explorer"])
    before = (agents_dir / "explorer.md").read_bytes()
    assert bulk(client, ["evoflux"])[0]["ok"] is True
    assert (agents_dir / "explorer.md").read_bytes() == before
    assert PLACEHOLDER not in read(agents_dir / "consultant.md")
