"""``/api/agents``: list, read, create, update and delete of agent ``.md`` files."""

from __future__ import annotations

import pytest

from registry_helpers import agent_md, lf, tree

SEEDED = [
    "coding/architect",
    "coding/coder",
    "coding/evoflux",
    "coding/explorer",
    "consultant",
    "evoflux",
    "executor",
    "explorer",
]
SUMMARY_KEYS = {
    "name", "role", "lead", "description", "model", "tools", "mcp", "skills",
    "valid", "error", "editable", "provider", "runtime_model_editable",
    "bundle_model", "model_override", "extra_tools", "extra_skills", "extra_mcp",
}  # fmt: skip
DETAIL_KEYS = {
    "name", "path", "content", "config", "error", "editable", "provider",
    "runtime_model_editable", "bundle_model", "model_override", "extra_tools",
    "extra_skills", "extra_mcp",
}  # fmt: skip
PLACEHOLDER = "__PROVIDER_MODEL__"


def agent_files(agents_dir) -> dict[str, bytes | None]:
    return {k: (None if v is None else lf(v)) for k, v in tree(agents_dir).items()}


def listing(client):
    response = client.get("/api/agents")
    assert response.status_code == 200
    return {item["name"]: item for item in response.json()["agents"]}


# ── list ────────────────────────────────────────────────────────────────────


def test_first_run_lists_the_seeded_agents_sorted(client, snapshot) -> None:
    response = client.get("/api/agents")
    assert response.status_code == 200
    rows = response.json()["agents"]
    assert list(response.json()) == ["agents"]
    assert [row["name"] for row in rows] == SEEDED
    for row in rows:
        assert set(row) == SUMMARY_KEYS
        assert row["valid"] is True and row["error"] is None
        assert row["editable"] is True and row["provider"] is None
        assert row["runtime_model_editable"] is False
        assert row["model"] == PLACEHOLDER
        assert row["tools"]
        assert (row["extra_tools"], row["extra_skills"], row["extra_mcp"]) == ([], [], [])
    assert {r["name"]: r["role"] for r in rows if r["role"] == "lead"} == {
        "coding/evoflux": "lead",
        "evoflux": "lead",
    }
    snapshot.check(
        "agents_seeded_summaries.json",
        [{k: v for k, v in row.items() if k != "tools"} for row in rows],
    )
    snapshot.check(
        "agents_seeded_tools.json", {row["name"]: row["tools"] for row in rows}
    )


def test_list_order_is_plain_string_order_across_work_and_coding(client, agents_dir) -> None:
    (agents_dir / "Upper.md").write_text(agent_md("Upper"), encoding="utf-8")
    (agents_dir / "a-first.md").write_text(agent_md("a-first"), encoding="utf-8")
    (agents_dir / "coding" / "c2.md").write_text(agent_md("c2"), encoding="utf-8")
    names = list(listing(client))
    assert names == sorted(names)
    assert names[0] == "Upper"
    assert names.index("coding/c2") < names.index("consultant")


def test_only_top_level_md_files_and_one_coding_level_are_listed(client, agents_dir) -> None:
    (agents_dir / "notes.txt").write_text("x", encoding="utf-8")
    (agents_dir / "sub").mkdir()
    (agents_dir / "sub" / "deep.md").write_text(agent_md("deep"), encoding="utf-8")
    (agents_dir / "coding" / "sub").mkdir()
    (agents_dir / "coding" / "sub" / "deeper.md").write_text(agent_md("deeper"), encoding="utf-8")
    assert list(listing(client)) == SEEDED


def test_a_missing_agents_directory_lists_nothing(client, agents_dir) -> None:
    import shutil

    shutil.rmtree(agents_dir)
    assert client.get("/api/agents").json() == {"agents": []}


def test_unreadable_agent_files_are_listed_as_invalid_members(client, agents_dir, scrub) -> None:
    (agents_dir / "nofm.md").write_text("no frontmatter", encoding="utf-8")
    (agents_dir / "badyaml.md").write_text("---\n: : :\n---\nx", encoding="utf-8")
    (agents_dir / "badrole.md").write_text(agent_md("badrole", role="boss"), encoding="utf-8")
    (agents_dir / "nonutf.md").write_bytes(b"---\nname: n\n---\n\xff")
    (agents_dir / "dot.name.md").write_text(agent_md("dot.name"), encoding="utf-8")
    rows = listing(client)
    expected = {
        "nofm": "Agent definition is missing YAML frontmatter. Expected '---\\n<yaml>\\n---\\n<system prompt>'.",
        "badrole": "role: Input should be 'lead' or 'member'",
        "nonutf": "'utf-8' codec can't decode byte 0xff in position 16: invalid start byte",
        # The stem ``dot.name`` becomes ``dot.md`` when the file is looked up again.
        "dot.name": "Agent 'dot.name' not found.",
    }
    for name, error in expected.items():
        row = rows[name]
        assert (row["valid"], row["error"], row["role"]) == (False, error, "member"), name
        assert row["editable"] is True and row["tools"] == [] and row["model"] is None
    assert rows["badyaml"]["valid"] is False
    assert rows["badyaml"]["error"].startswith("Invalid YAML frontmatter: while parsing a block mapping")


# ── read ────────────────────────────────────────────────────────────────────


def test_get_returns_raw_content_and_the_effective_config(client, agents_dir, scrub) -> None:
    response = client.get("/api/agents/explorer")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == DETAIL_KEYS
    assert scrub(body["path"]) == "<tmp>/config/agents/explorer.md"
    assert body["content"] == (agents_dir / "explorer.md").read_text(encoding="utf-8")
    assert body["error"] is None and body["editable"] is True
    config = body["config"]
    assert config["name"] == "explorer" and config["role"] == "member"
    assert config["model"] == PLACEHOLDER
    assert config["tools"] == sorted(config["tools"])
    assert "None" not in str(config) and None not in config.values()  # exclude_none


def test_get_reads_the_coding_namespace(client, scrub) -> None:
    body = client.get("/api/agents/coding/coder").json()
    assert body["name"] == "coding/coder"
    assert scrub(body["path"]) == "<tmp>/config/agents/coding/coder.md"
    assert body["config"]["name"] == "coder"


def test_get_of_an_invalid_agent_is_200_with_the_error(client, agents_dir) -> None:
    (agents_dir / "nofm.md").write_text("no frontmatter", encoding="utf-8")
    body = client.get("/api/agents/nofm").json()
    assert body["content"] == "no frontmatter"
    assert body["config"] is None
    assert body["error"] == (
        "Agent definition is missing YAML frontmatter. Expected '---\\n<yaml>\\n---\\n<system prompt>'."
    )


def test_get_of_a_non_utf8_file_is_an_unhandled_500(client, agents_dir) -> None:
    (agents_dir / "nonutf.md").write_bytes(b"---\nname: n\n---\n\xff")
    response = client.get("/api/agents/nonutf")
    assert response.status_code == 500
    assert response.text == "Internal Server Error"


@pytest.mark.parametrize(
    ("path", "status", "detail"),
    [
        ("nope", 404, "Agent 'nope' not found."),
        ("coding", 404, "Agent 'coding' not found."),
        ("coding/nope", 404, "Agent 'nope' not found.".replace("'nope'", "'coding/nope'")),
        ("a/b/c", 400, "Invalid agent path 'a/b/c'. Use '<name>' for Work or 'coding/<name>' for Coding."),
        ("sub/deep", 400, "Invalid agent path 'sub/deep'. Use '<name>' for Work or 'coding/<name>' for Coding."),
        ("../x", 400, "Invalid agent path '../x'. Use '<name>' for Work or 'coding/<name>' for Coding."),
        ("coding/../x", 400, "Invalid agent path 'coding/../x'. Use '<name>' for Work or 'coding/<name>' for Coding."),
        ("coding%5Ccoder", 400, "Invalid name 'coding\\coder'. Use '/' for nested agents, not '\\'."),
        ("%20", 400, "Invalid name ' '. Use letters, digits, '.', '_', '-' only (1-64 chars, must start with letter/digit)."),
        ("-x", 400, "Invalid name '-x'. Use letters, digits, '.', '_', '-' only (1-64 chars, must start with letter/digit)."),
        ("a" * 65, 400, f"Invalid name '{'a' * 65}'. Use letters, digits, '.', '_', '-' only (1-64 chars, must start with letter/digit)."),
    ],
)
def test_get_errors(client, path, status, detail) -> None:
    response = client.get(f"/api/agents/{path.replace('../', '..%2F')}")
    assert response.status_code == status
    assert response.json() == {"detail": detail}


def test_a_dot_md_suffix_in_the_name_reads_the_same_file(client) -> None:
    body = client.get("/api/agents/explorer.md").json()
    assert body["name"] == "explorer.md"
    assert body["path"].endswith("explorer.md")


# ── create ──────────────────────────────────────────────────────────────────


def test_create_writes_the_file_and_strips_the_retired_temperature_setting(
    client, agents_dir, scrub
) -> None:
    content = (
        "---\nname: helper\nrole: member\n# keep this comment\ndescription: Helps.\n"
        "temperature: 0.2\nmodel: openai:gpt-5\n---\nYou help.\ntemperature: 0.5\n"
    )
    response = client.post("/api/agents", json={"name": "helper", "content": content})
    assert response.status_code == 201
    stored = (
        "---\nname: helper\nrole: member\n# keep this comment\ndescription: Helps.\n"
        "model: openai:gpt-5\n---\nYou help.\ntemperature: 0.5\n"
    )
    body = response.json()
    assert set(body) == DETAIL_KEYS
    assert scrub(body["path"]) == "<tmp>/config/agents/helper.md"
    assert body["content"] == stored
    assert body["config"] == {
        "name": "helper", "role": "member", "description": "Helps.",
        "system_prompt": "You help.\ntemperature: 0.5", "tools": [],
        "tools_opt_out": [], "mcp": [], "skills": [], "model": "openai:gpt-5",
    }  # fmt: skip
    assert body["editable"] is True and body["provider"] is None
    assert lf((agents_dir / "helper.md").read_bytes()) == stored.encode("utf-8")


def test_create_in_the_coding_namespace(client, agents_dir) -> None:
    response = client.post(
        "/api/agents", json={"name": "coding/zed", "content": agent_md("zed")}
    )
    assert response.status_code == 201
    assert response.json()["name"] == "coding/zed"
    assert lf((agents_dir / "coding" / "zed.md").read_bytes()) == agent_md("zed").encode()


def test_create_preserves_crlf_input_without_doubling_it(client, agents_dir) -> None:
    """On Windows the text-mode write turns ``\\r\\n`` into ``\\r\\r\\n``; ``lf`` folds
    that back so the same bytes are expected everywhere (NOTES finding B2)."""
    content = "---\r\nname: crlf\r\ntemperature: 1\r\n---\r\nbody\r\n"
    assert client.post("/api/agents", json={"name": "crlf", "content": content}).status_code == 201
    assert lf((agents_dir / "crlf.md").read_bytes()) == b"---\r\nname: crlf\r\n---\r\nbody\r\n"


def test_create_accepts_a_missing_frontmatter_name_and_unknown_tools_and_a_second_lead(
    client, agents_dir
) -> None:
    nameless = client.post("/api/agents", json={"name": "nn", "content": "---\nrole: member\n---\nx"})
    assert nameless.status_code == 201
    assert nameless.json()["config"]["name"] == "nn"
    assert lf((agents_dir / "nn.md").read_bytes()) == b"---\nrole: member\n---\nx"
    tools = client.post(
        "/api/agents",
        json={"name": "tu", "content": agent_md("tu", extra="tools: [not_a_tool]\n")},
    )
    assert tools.status_code == 201
    assert tools.json()["config"]["tools"] == ["not_a_tool"]
    lead = client.post("/api/agents", json={"name": "lead2", "content": agent_md("lead2", role="lead")})
    assert lead.status_code == 201
    assert listing(client)["lead2"]["role"] == "lead"


@pytest.mark.parametrize(
    ("name", "content", "status", "detail"),
    [
        ("helper", agent_md("other"), 422, "Frontmatter name 'other' must match the request name 'helper'."),
        ("he lper", agent_md("helper"), 422, "Frontmatter name 'helper' must match the request name 'he lper'."),
        ("coding/helper", agent_md("other"), 422, "Frontmatter name 'other' must match the request name 'helper'."),
        ("x", "plain text", 422, "Agent definition is missing YAML frontmatter. Expected '---\\n<yaml>\\n---\\n<system prompt>'."),
        ("x", "---\n- a\n---\nx", 422, "Agent definition frontmatter must be a YAML mapping."),
        ("x", agent_md("x", role="boss"), 422, "role: Input should be 'lead' or 'member'"),
        ("x", agent_md("x", extra="model: nocolon\n"), 422, ": Value error, Agent 'x': invalid model 'nocolon' (expected 'provider:model', e.g. 'googlegenai:gemini-3.1-flash')."),
        ("x", agent_md("x", role="lead", extra="lead: boss\n"), 422, ": Value error, Lead agent 'x' cannot be owned by another lead."),
        ("x", agent_md("x", extra="lead: ' '\n"), 422, ": Value error, Agent 'x': lead owner cannot be blank."),
        ("evil/x", agent_md("x"), 400, "Invalid agent path 'evil/x'. Use '<name>' for Work or 'coding/<name>' for Coding."),
        ("../x", agent_md("x"), 400, "Invalid agent path '../x'. Use '<name>' for Work or 'coding/<name>' for Coding."),
        ("coding/../x", agent_md("x"), 400, "Invalid agent path 'coding/../x'. Use '<name>' for Work or 'coding/<name>' for Coding."),
        ("..", agent_md(".."), 400, "Invalid name '..'. Use letters, digits, '.', '_', '-' only (1-64 chars, must start with letter/digit)."),
        ("coding/..", agent_md(".."), 400, "Invalid name '..'. Use letters, digits, '.', '_', '-' only (1-64 chars, must start with letter/digit)."),
        ("-x", agent_md("-x"), 400, "Invalid name '-x'. Use letters, digits, '.', '_', '-' only (1-64 chars, must start with letter/digit)."),
    ],
)
def test_create_errors_write_nothing(client, agents_dir, tmp_path, name, content, status, detail) -> None:
    before = agent_files(agents_dir)
    response = client.post("/api/agents", json={"name": name, "content": content})
    assert (response.status_code, response.json()) == (status, {"detail": detail})
    assert agent_files(agents_dir) == before
    assert not (tmp_path / "config" / "x.md").exists() and not (tmp_path / "x.md").exists()


def test_create_conflicts_with_an_existing_agent(client, agents_dir) -> None:
    before = agent_files(agents_dir)
    response = client.post("/api/agents", json={"name": "explorer", "content": agent_md("explorer")})
    assert (response.status_code, response.json()) == (409, {"detail": "Agent 'explorer' already exists."})
    assert agent_files(agents_dir) == before


def test_a_dot_in_the_name_replaces_the_suffix_of_the_file_name(client, agents_dir) -> None:
    """``Path.with_suffix`` turns ``foo.bar`` into ``foo.md`` (NOTES finding B1)."""
    first = client.post("/api/agents", json={"name": "foo.bar", "content": agent_md("foo.bar")})
    assert first.status_code == 201
    assert first.json()["path"].endswith("foo.md")
    assert (agents_dir / "foo.md").is_file() and not (agents_dir / "foo.bar.md").exists()
    second = client.post("/api/agents", json={"name": "foo.baz", "content": agent_md("foo.baz")})
    assert (second.status_code, second.json()) == (409, {"detail": "Agent 'foo.baz' already exists."})
    assert "foo" in listing(client)


def test_create_validates_the_request_body(client) -> None:
    for body in ({}, {"name": "a"}, {"content": "x"}, {"name": 1, "content": "x"}):
        response = client.post("/api/agents", json=body)
        assert response.status_code == 422
        assert isinstance(response.json()["detail"], list)


def test_a_broken_agent_file_blocks_every_write_and_the_new_file_is_removed(
    client, agents_dir, scrub
) -> None:
    (agents_dir / "nofm.md").write_text("no frontmatter", encoding="utf-8")
    response = client.post("/api/agents", json={"name": "helper", "content": agent_md("helper")})
    assert response.status_code == 422
    assert scrub(response.json()["detail"]) == (
        "Failed to parse 1 agent file(s) in '<tmp>/config/agents':\n"
        "  nofm.md: Agent file '<tmp>/config/agents/nofm.md' is missing YAML frontmatter. "
        "Expected '---\\n<yaml>\\n---\\n<system prompt>'."
    )
    assert not (agents_dir / "helper.md").exists()


def test_team_invariants_are_checked_after_the_write_and_rolled_back(client, agents_dir, scrub) -> None:
    response = client.post(
        "/api/agents",
        json={"name": "orphan", "content": agent_md("orphan", extra="lead: ghostlead\n")},
    )
    assert response.status_code == 422
    assert response.json() == {"detail": "Member 'orphan' in 'orphan.md' references unknown lead 'ghostlead'."}
    assert not (agents_dir / "orphan.md").exists()


# ── update ──────────────────────────────────────────────────────────────────


def test_update_overwrites_the_file(client, agents_dir) -> None:
    client.post("/api/agents", json={"name": "helper", "content": agent_md("helper")})
    new = agent_md("helper", extra="description: Changed.\ntemperature: 1\n", body="New.\n")
    response = client.put("/api/agents/helper", json={"name": "helper", "content": new})
    assert response.status_code == 200
    stored = agent_md("helper", extra="description: Changed.\n", body="New.\n")
    assert response.json()["content"] == stored
    assert response.json()["config"]["description"] == "Changed."
    assert lf((agents_dir / "helper.md").read_bytes()) == stored.encode()


def test_update_works_for_the_coding_namespace(client, agents_dir) -> None:
    text = agent_md("coder", extra="description: Mine.\n")
    response = client.put("/api/agents/coding/coder", json={"name": "coding/coder", "content": text})
    assert response.status_code == 200
    assert lf((agents_dir / "coding" / "coder.md").read_bytes()) == text.encode()


@pytest.mark.parametrize(
    ("url", "body", "status", "detail"),
    [
        ("helper", {"name": "zzz", "content": agent_md("helper")}, 422, "URL name 'helper' does not match body name 'zzz'."),
        ("ghost", {"name": "ghost", "content": agent_md("ghost")}, 404, "Agent 'ghost' not found."),
        ("helper", {"name": "helper", "content": "plain"}, 422, "Agent definition is missing YAML frontmatter. Expected '---\\n<yaml>\\n---\\n<system prompt>'."),
        ("helper", {"name": "helper", "content": agent_md("other")}, 422, "Frontmatter name 'other' does not match URL name 'helper'."),
        ("helper", {"name": "helper", "content": agent_md("helper", role="boss")}, 422, "role: Input should be 'lead' or 'member'"),
        ("../x", {"name": "../x", "content": agent_md("x")}, 400, "Invalid agent path '../x'. Use '<name>' for Work or 'coding/<name>' for Coding."),
    ],
)
def test_update_errors_keep_the_file(client, agents_dir, url, body, status, detail) -> None:
    client.post("/api/agents", json={"name": "helper", "content": agent_md("helper")})
    before = agent_files(agents_dir)
    response = client.put(f"/api/agents/{url.replace('../', '..%2F')}", json=body)
    assert (response.status_code, response.json()) == (status, {"detail": detail})
    assert agent_files(agents_dir) == before


def test_update_that_breaks_the_team_restores_the_previous_text(client, agents_dir) -> None:
    client.post("/api/agents", json={"name": "helper", "content": agent_md("helper", body="Original.\n")})
    before = agent_files(agents_dir)
    broken = agent_md("helper", extra="lead: ghostlead\n", body="Changed.\n")
    response = client.put("/api/agents/helper", json={"name": "helper", "content": broken})
    assert response.status_code == 422
    assert response.json() == {"detail": "Member 'helper' in 'helper.md' references unknown lead 'ghostlead'."}
    assert agent_files(agents_dir) == before


def test_demoting_the_only_lead_is_refused_and_rolled_back(client, agents_dir, scrub) -> None:
    before = agent_files(agents_dir)
    # The work lead is not the only lead in the file system, but the Work team
    # directory has exactly one: ``agents/*.md``.
    demoted = agent_md("evoflux", role="member")
    response = client.put("/api/agents/evoflux", json={"name": "evoflux", "content": demoted})
    assert response.status_code == 422
    assert scrub(response.json()["detail"]) == (
        "No agent with 'role: lead' found in '<tmp>/config/agents'. At least one lead is required."
    )
    assert agent_files(agents_dir) == before


def test_updating_a_lead_with_a_model_fills_the_placeholder_of_every_other_agent(
    client, agents_dir
) -> None:
    lead = (agents_dir / "evoflux.md").read_text(encoding="utf-8").replace(PLACEHOLDER, "openai:gpt-5")
    response = client.put("/api/agents/evoflux", json={"name": "evoflux", "content": lead})
    assert response.status_code == 200
    files = agent_files(agents_dir)
    # Work and Coding files alike; the coding lead follows the work lead's model.
    for name, data in files.items():
        if data is not None:
            assert PLACEHOLDER.encode() not in data, name
            assert b"model: openai:gpt-5" in data, name


def test_updating_a_member_does_not_fill_placeholders(client, agents_dir) -> None:
    member = (agents_dir / "explorer.md").read_text(encoding="utf-8").replace(PLACEHOLDER, "openai:gpt-5")
    assert client.put("/api/agents/explorer", json={"name": "explorer", "content": member}).status_code == 200
    assert PLACEHOLDER.encode() in lf((agents_dir / "evoflux.md").read_bytes())


def test_a_second_lead_is_accepted_on_update(client, agents_dir) -> None:
    client.post("/api/agents", json={"name": "helper", "content": agent_md("helper")})
    response = client.put(
        "/api/agents/helper", json={"name": "helper", "content": agent_md("helper", role="lead")}
    )
    assert response.status_code == 200
    assert listing(client)["helper"]["role"] == "lead"


# ── delete ──────────────────────────────────────────────────────────────────


def test_delete_removes_the_file(client, agents_dir) -> None:
    response = client.delete("/api/agents/explorer")
    assert response.status_code == 200
    assert response.json() == {"name": "explorer"}
    assert not (agents_dir / "explorer.md").exists()
    assert "explorer" not in listing(client)
    coding = client.delete("/api/agents/coding/explorer")
    assert coding.json() == {"name": "coding/explorer"}
    assert not (agents_dir / "coding" / "explorer.md").exists()
    assert (agents_dir / "coding" / "coder.md").exists()


@pytest.mark.parametrize(
    ("path", "status", "detail"),
    [
        ("ghost", 404, "Agent 'ghost' not found."),
        ("a/b/c", 400, "Invalid agent path 'a/b/c'. Use '<name>' for Work or 'coding/<name>' for Coding."),
        ("../x", 400, "Invalid agent path '../x'. Use '<name>' for Work or 'coding/<name>' for Coding."),
    ],
)
def test_delete_errors(client, agents_dir, path, status, detail) -> None:
    before = agent_files(agents_dir)
    response = client.delete(f"/api/agents/{path.replace('../', '..%2F')}")
    assert (response.status_code, response.json()) == (status, {"detail": detail})
    assert agent_files(agents_dir) == before


def test_deleting_the_only_lead_is_422_and_the_file_comes_back(client, agents_dir, scrub) -> None:
    before = agent_files(agents_dir)
    response = client.delete("/api/agents/evoflux")
    assert response.status_code == 422
    assert scrub(response.json()["detail"]) == (
        "No agent with 'role: lead' found in '<tmp>/config/agents'. At least one lead is required."
    )
    assert agent_files(agents_dir) == before
    coding = client.delete("/api/agents/coding/evoflux")
    assert coding.status_code == 422
    assert scrub(coding.json()["detail"]) == (
        "No agent with 'role: lead' found in '<tmp>/config/agents/coding'. At least one lead is required."
    )
    assert agent_files(agents_dir) == before


def test_a_lead_can_be_deleted_when_another_lead_exists(client, agents_dir) -> None:
    client.post("/api/agents", json={"name": "lead2", "content": agent_md("lead2", role="lead")})
    assert client.delete("/api/agents/evoflux").status_code == 200
    assert not (agents_dir / "evoflux.md").exists()


def test_deleting_a_member_of_a_broken_team_is_refused_and_restored(client, agents_dir) -> None:
    (agents_dir / "nofm.md").write_text("no frontmatter", encoding="utf-8")
    before = agent_files(agents_dir)
    response = client.delete("/api/agents/explorer")
    assert response.status_code == 422
    assert response.json()["detail"].startswith("Failed to parse 1 agent file(s)")
    assert agent_files(agents_dir) == before
