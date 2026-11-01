"""``/api/settings``: sandbox, context, version-control and the small toggles.

Every section except sandbox lives in ``settings.yaml``, and every PUT loads the
whole file, replaces one section and rewrites the whole file.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
import yaml

SIMPLE = {
    "team-spawn": {
        "default": {"work": "ask", "coding": "ask"},
        "put": {"work": "auto", "coding": "ask"},
        "yaml": ("team_spawn", {"work": "auto", "coding": "ask"}),
        "invalid": [{"work": "x"}, {"coding": 1}, {"other": "ask"}],
    },
    "follow-up": {
        "default": {"delivery": "queue"},
        "put": {"delivery": "steer"},
        "yaml": ("follow_up", {"delivery": "steer"}),
        "invalid": [{"delivery": "x"}, {"delivery": None}, {"delivery": "queue", "x": 1}],
    },
    "background-tasks": {
        "default": {"wake_idle": True},
        "put": {"wake_idle": False},
        "yaml": ("background_tasks", {"wake_idle": False}),
        "invalid": [{"wake_idle": "maybe"}, {"wake_idle": 2}, {"x": True}],
    },
    "response-style": {
        "default": {"style": "visual"},
        "put": {"style": "simple"},
        "yaml": ("response_style", {"style": "simple"}),
        "invalid": [{"style": "fancy"}, {"style": 3}, {"style": "simple", "x": 1}],
    },
}


def saved(config_dir) -> dict:
    return yaml.safe_load((config_dir / "settings.yaml").read_text(encoding="utf-8"))


# ── team-spawn, follow-up, background-tasks, response-style ────────────────


@pytest.mark.parametrize("name", SIMPLE)
def test_simple_section_defaults_without_a_settings_file(client, config_dir, name) -> None:
    (config_dir / "settings.yaml").unlink()
    response = client.get(f"/api/settings/{name}")
    assert response.status_code == 200
    assert response.json() == SIMPLE[name]["default"]
    assert not (config_dir / "settings.yaml").exists()  # reading never writes


@pytest.mark.parametrize("name", SIMPLE)
def test_simple_section_put_round_trips_and_persists(client, config_dir, name) -> None:
    case = SIMPLE[name]
    response = client.put(f"/api/settings/{name}", json=case["put"])
    assert response.status_code == 200
    assert response.json() == case["put"]
    assert client.get(f"/api/settings/{name}").json() == case["put"]
    section, expected = case["yaml"]
    assert saved(config_dir)[section] == expected


@pytest.mark.parametrize("name", SIMPLE)
def test_simple_section_rejects_invalid_bodies_and_writes_nothing(
    client, config_dir, name
) -> None:
    before = (config_dir / "settings.yaml").read_bytes()
    for body in SIMPLE[name]["invalid"]:
        response = client.put(f"/api/settings/{name}", json=body)
        assert response.status_code == 422, body
        assert isinstance(response.json()["detail"], list)
    assert (config_dir / "settings.yaml").read_bytes() == before
    assert client.get(f"/api/settings/{name}").json() == SIMPLE[name]["default"]


def test_simple_section_validation_bodies(client, snapshot) -> None:
    bodies = {}
    for name, case in SIMPLE.items():
        bodies[name] = [
            client.put(f"/api/settings/{name}", json=body).json()
            for body in case["invalid"]
        ]
        bodies[f"{name}-no-body"] = client.put(f"/api/settings/{name}").json()
    snapshot.check("simple_sections_422.json", bodies)


def test_team_spawn_fields_default_when_omitted(client) -> None:
    client.put("/api/settings/team-spawn", json={"work": "auto", "coding": "auto"})
    response = client.put("/api/settings/team-spawn", json={"work": "ask"})
    # A PUT replaces the section: the omitted field returns to its default.
    assert response.json() == {"work": "ask", "coding": "ask"}


def test_sections_only_allow_get_and_put(client) -> None:
    for name in SIMPLE:
        for method in ("POST", "DELETE", "PATCH"):
            response = client.request(method, f"/api/settings/{name}")
            assert response.status_code == 405, (name, method)


def test_a_hand_edited_invalid_value_reads_as_the_default(client, config_dir) -> None:
    (config_dir / "settings.yaml").write_text(
        "follow_up:\n  delivery: bogus\nresponse_style:\n  style: simple\n",
        encoding="utf-8",
    )
    assert client.get("/api/settings/follow-up").json() == {"delivery": "queue"}
    assert client.get("/api/settings/response-style").json() == {"style": "simple"}


# ── the whole-file rewrite ─────────────────────────────────────────────────


def test_put_rewrites_the_whole_file_and_drops_unknown_keys(client, config_dir) -> None:
    (config_dir / "settings.yaml").write_text(
        "# my notes\nfuture_key: 1\nresponse_style:\n  style: simple\n"
        "follow_up:\n  delivery: steer\n",
        encoding="utf-8",
    )
    response = client.put("/api/settings/background-tasks", json={"wake_idle": False})
    assert response.status_code == 200
    text = (config_dir / "settings.yaml").read_text(encoding="utf-8")
    assert "future_key" not in text
    assert "my notes" not in text
    data = yaml.safe_load(text)
    assert data["response_style"] == {"style": "simple"}
    assert data["follow_up"] == {"delivery": "steer"}
    assert data["background_tasks"] == {"wake_idle": False}


def test_put_from_an_empty_state_writes_every_section(client, config_dir, snapshot) -> None:
    (config_dir / "settings.yaml").unlink()
    client.put("/api/settings/follow-up", json={"delivery": "steer"})
    snapshot.check("settings_yaml_full_dump.json", saved(config_dir))


def test_put_does_not_replace_a_file_it_cannot_load(client, config_dir) -> None:
    (config_dir / "settings.yaml").write_text("a: [", encoding="utf-8")
    response = client.put("/api/settings/follow-up", json={"delivery": "steer"})
    assert response.status_code == 422
    assert response.json()["detail"].startswith("settings.yaml YAML parse error:")
    assert (config_dir / "settings.yaml").read_text(encoding="utf-8") == "a: ["


def test_the_file_is_replaced_atomically_without_leftovers(client, config_dir) -> None:
    client.put("/api/settings/follow-up", json={"delivery": "steer"})
    leftovers = [p.name for p in config_dir.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


@pytest.mark.parametrize(
    "content", ["a: [", "- 1\n", "just text\n"], ids=["bad-yaml", "list", "scalar"]
)
def test_unreadable_settings_file_is_422_on_guarded_routes(
    client, config_dir, content
) -> None:
    (config_dir / "settings.yaml").write_text(content, encoding="utf-8")
    expected = (
        "settings.yaml YAML parse error:"
        if content == "a: ["
        else "settings.yaml must contain a YAML mapping."
    )
    for path in ("context", "version-control", "webbridge", "computer-app"):
        response = client.get(f"/api/settings/{path}")
        assert response.status_code == 422, path
        assert response.json()["detail"].startswith(expected), path
    response = client.put("/api/settings/response-style", json={"style": "simple"})
    assert response.status_code == 422
    assert response.json()["detail"].startswith(expected)


def test_unreadable_settings_file_is_500_on_unguarded_reads(client, config_dir) -> None:
    # Suspected Python bug (NOTES, "Odd behaviour"): these GETs do not catch the
    # ValueError the other sections turn into 422.
    (config_dir / "settings.yaml").write_text("a: [", encoding="utf-8")
    for path in ("team-spawn", "follow-up", "background-tasks", "response-style", "providers"):
        # uvicorn drops the connection after an unhandled error: do not reuse it.
        response = client.get(f"/api/settings/{path}", headers={"Connection": "close"})
        assert response.status_code == 500, path
        assert response.text == "Internal Server Error", path


# ── context ────────────────────────────────────────────────────────────────

CONTEXT_FIELDS = (
    "summary_trigger_tokens",
    "summary_max_tokens",
    "keep_recent_turns",
    "tool_result_offload_chars",
    "keep_recent_tool_batches",
)


def test_context_defaults_shape(client) -> None:
    body = client.get("/api/settings/context").json()
    assert set(body) == {
        *CONTEXT_FIELDS,
        "defaults",
        "coding_defaults",
        "ignored",
        "max_tokens",
        "context_ratio",
    }
    assert all(body[name] is None for name in CONTEXT_FIELDS)
    assert set(body["defaults"]) == set(CONTEXT_FIELDS)
    assert all(isinstance(v, int) for v in body["defaults"].values())
    # The built-ins the hooks fall back to; the trigger is derived (see NOTES).
    assert body["defaults"]["summary_max_tokens"] == 30000
    assert body["defaults"]["keep_recent_turns"] == 3
    assert body["defaults"]["tool_result_offload_chars"] == 40000
    assert body["coding_defaults"] == {
        "keep_recent_turns": 2,
        "keep_recent_tool_batches": 3,
    }
    assert body["ignored"] == []
    assert isinstance(body["max_tokens"], int) and body["max_tokens"] > 0
    assert 0 < body["context_ratio"] <= 1


def test_context_put_persists_overrides_and_ignores_derived_fields(
    client, config_dir
) -> None:
    sent = {
        "summary_trigger_tokens": 100_000,
        "summary_max_tokens": 5_000,
        "keep_recent_turns": 0,
        "tool_result_offload_chars": 10_000,
        "keep_recent_tool_batches": 5,
        "defaults": {"summary_max_tokens": 1},
        "max_tokens": 5,
    }
    derived = client.get("/api/settings/context").json()
    response = client.put("/api/settings/context", json=sent)
    assert response.status_code == 200
    body = response.json()
    for name in CONTEXT_FIELDS:
        assert body[name] == sent[name]
    assert body["defaults"] == derived["defaults"]
    assert body["max_tokens"] == derived["max_tokens"]
    assert saved(config_dir)["context"] == {name: sent[name] for name in CONTEXT_FIELDS}


def test_context_put_null_restores_the_default(client, config_dir) -> None:
    client.put("/api/settings/context", json={"summary_trigger_tokens": 100_000})
    response = client.put("/api/settings/context", json={})
    assert response.json()["summary_trigger_tokens"] is None
    assert "summary_trigger_tokens" not in saved(config_dir)["context"]


@pytest.mark.parametrize(
    "body",
    [
        {"summary_trigger_tokens": 19_999},
        {"summary_trigger_tokens": 2_000_001},
        {"summary_max_tokens": 1_999},
        {"summary_max_tokens": 120_001},
        {"keep_recent_turns": -1},
        {"keep_recent_turns": 11},
        {"tool_result_offload_chars": 1_999},
        {"tool_result_offload_chars": 500_001},
        {"keep_recent_tool_batches": 0},
        {"keep_recent_tool_batches": 13},
        {"keep_recent_turns": "three"},
        {"keep_recent_turns": 2.5},
        {"unknown": 1},
        {"ignored": [{"field": "x", "message": "y", "extra": 1}]},
    ],
    ids=lambda body: next(iter(body)) + "=" + repr(next(iter(body.values()))),
)
def test_context_put_rejects_out_of_range(client, config_dir, body) -> None:
    before = (config_dir / "settings.yaml").read_bytes()
    response = client.put("/api/settings/context", json=body)
    assert response.status_code == 422
    assert (config_dir / "settings.yaml").read_bytes() == before


def test_context_bounds_are_inclusive(client) -> None:
    low = {
        "summary_trigger_tokens": 20_000,
        "summary_max_tokens": 2_000,
        "keep_recent_turns": 0,
        "tool_result_offload_chars": 2_000,
        "keep_recent_tool_batches": 1,
    }
    high = {
        "summary_trigger_tokens": 2_000_000,
        "summary_max_tokens": 120_000,
        "keep_recent_turns": 10,
        "tool_result_offload_chars": 500_000,
        "keep_recent_tool_batches": 12,
    }
    for body in (low, high):
        response = client.put("/api/settings/context", json=body)
        assert response.status_code == 200
        assert {name: response.json()[name] for name in CONTEXT_FIELDS} == body


def test_context_reports_a_hand_edited_value_it_had_to_ignore(client, config_dir) -> None:
    (config_dir / "settings.yaml").write_text(
        "context:\n  summary_trigger_tokens: 5\n  keep_recent_turns: 4\n"
        "git:\n  network_timeout_seconds: 1\n",
        encoding="utf-8",
    )
    body = client.get("/api/settings/context").json()
    assert body["summary_trigger_tokens"] is None
    assert body["keep_recent_turns"] == 4
    # Only this section's rejects; the git one is not shown here.
    assert [item["field"] for item in body["ignored"]] == ["summary_trigger_tokens"]
    assert body["ignored"][0]["message"] == "Input should be greater than or equal to 20000"
    assert client.get("/api/settings/version-control").json()["network_timeout_seconds"] == 120.0


def test_context_put_repairs_a_file_with_an_invalid_value(client, config_dir) -> None:
    (config_dir / "settings.yaml").write_text(
        "context:\n  summary_trigger_tokens: 5\n", encoding="utf-8"
    )
    response = client.put("/api/settings/context", json={"keep_recent_turns": 1})
    assert response.status_code == 200
    assert response.json()["ignored"] == []
    assert saved(config_dir)["context"] == {"keep_recent_turns": 1}


# ── version-control ────────────────────────────────────────────────────────

VERSION_CONTROL = {
    "network_timeout_seconds": 30.0,
    "max_diff_bytes": 1_000_000,
    "default_pull_strategy": "rebase",
    "prune_on_fetch": False,
    "allow_force_push": True,
    "review_request_timeout_seconds": 45.0,
    "review_retry_attempts": 3,
    "review_retry_backoff_seconds": 1.5,
    "review_max_concurrent_repositories": 8,
    "review_max_pages_per_repository": 10,
    "allow_review_mutations": True,
    "allow_insecure_connections": True,
    "require_successful_checks_before_merge": True,
}


def test_version_control_defaults(client, snapshot) -> None:
    response = client.get("/api/settings/version-control")
    assert response.status_code == 200
    snapshot.check("version_control_defaults.json", response.json())


def test_version_control_round_trip_splits_into_git_and_code_reviews(
    client, config_dir
) -> None:
    response = client.put("/api/settings/version-control", json=VERSION_CONTROL)
    assert response.status_code == 200
    assert response.json() == VERSION_CONTROL
    assert client.get("/api/settings/version-control").json() == VERSION_CONTROL
    data = saved(config_dir)
    assert data["git"] == {
        "network_timeout_seconds": 30.0,
        "max_diff_bytes": 1_000_000,
        "default_pull_strategy": "rebase",
        "prune_on_fetch": False,
        "allow_force_push": True,
    }
    assert data["code_reviews"]["request_timeout_seconds"] == 45.0
    assert data["code_reviews"]["allow_mutations"] is True


def test_version_control_every_field_is_required(client, snapshot) -> None:
    response = client.put("/api/settings/version-control", json={})
    assert response.status_code == 422
    assert len(response.json()["detail"]) == len(VERSION_CONTROL)
    snapshot.check("version_control_422_empty.json", response.json())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("network_timeout_seconds", 9.9),
        ("network_timeout_seconds", 1800.1),
        ("max_diff_bytes", 63_999),
        ("max_diff_bytes", 50_000_001),
        ("default_pull_strategy", "squash"),
        ("review_request_timeout_seconds", 1.9),
        ("review_request_timeout_seconds", 300.1),
        ("review_retry_attempts", -1),
        ("review_retry_attempts", 6),
        ("review_retry_backoff_seconds", -0.1),
        ("review_retry_backoff_seconds", 10.1),
        ("review_max_concurrent_repositories", 0),
        ("review_max_concurrent_repositories", 33),
        ("review_max_pages_per_repository", 0),
        ("review_max_pages_per_repository", 21),
        ("prune_on_fetch", "maybe"),
    ],
)
def test_version_control_rejects_out_of_range(client, config_dir, field, value) -> None:
    before = (config_dir / "settings.yaml").read_bytes()
    response = client.put(
        "/api/settings/version-control", json={**VERSION_CONTROL, field: value}
    )
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", field]
    assert (config_dir / "settings.yaml").read_bytes() == before


def test_version_control_rejects_unknown_fields(client) -> None:
    response = client.put(
        "/api/settings/version-control", json={**VERSION_CONTROL, "extra": 1}
    )
    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "extra_forbidden"


# ── sandbox (sandbox.yaml, not settings.yaml) ──────────────────────────────

SANDBOX_DEFAULT = {
    "denied_patterns": ["**/.env", "**/.env.*"],
    "worktree_location": "repository",
    "inherit_shell_environment": False,
    "load_shell_profile": False,
    "outbound_data_policy": "off",
    "outbound_pii_policy": "off",
    "max_execution_seconds": 600,
    "max_output_bytes": 131072,
}


def test_sandbox_defaults_are_served_without_creating_the_file(client, config_dir) -> None:
    response = client.get("/api/settings/sandbox")
    assert response.status_code == 200
    assert response.json() == SANDBOX_DEFAULT
    assert not (config_dir / "sandbox.yaml").exists()


def test_sandbox_put_strips_blank_patterns_and_persists(client, config_dir) -> None:
    body = {
        **SANDBOX_DEFAULT,
        "denied_patterns": [" **/secret ", "", "   ", "b/*", "b/*"],
        "worktree_location": "user_data",
        "inherit_shell_environment": True,
        "load_shell_profile": True,
        "outbound_data_policy": "redact",
        "outbound_pii_policy": "strict",
        "max_execution_seconds": 5,
        "max_output_bytes": 1_048_576,
    }
    response = client.put("/api/settings/sandbox", json=body)
    assert response.status_code == 200
    expected = {**body, "denied_patterns": ["**/secret", "b/*", "b/*"]}
    assert response.json() == expected
    assert client.get("/api/settings/sandbox").json() == expected
    assert yaml.safe_load((config_dir / "sandbox.yaml").read_text(encoding="utf-8")) == expected


def test_sandbox_put_without_patterns_writes_the_empty_deny_list(client) -> None:
    response = client.put("/api/settings/sandbox", json={})
    assert response.status_code == 200
    # Unlike a missing file, an explicit PUT without patterns means "none".
    assert response.json() == {**SANDBOX_DEFAULT, "denied_patterns": []}
    assert client.get("/api/settings/sandbox").json()["denied_patterns"] == []


def test_sandbox_does_not_touch_settings_yaml(client, config_dir) -> None:
    before = (config_dir / "settings.yaml").read_bytes()
    client.put("/api/settings/sandbox", json={"denied_patterns": ["x"]})
    assert (config_dir / "settings.yaml").read_bytes() == before


@pytest.mark.parametrize(
    "body",
    [
        {"max_execution_seconds": 4},
        {"max_execution_seconds": 3601},
        {"max_output_bytes": 4095},
        {"max_output_bytes": 1_048_577},
        {"worktree_location": "elsewhere"},
        {"outbound_data_policy": "drop"},
        {"outbound_pii_policy": "loose"},
        {"denied_patterns": "**/.env"},
        {"inherit_shell_environment": "nope"},
        {"unknown": 1},
    ],
    ids=lambda body: next(iter(body)),
)
def test_sandbox_put_rejects_invalid_bodies(client, config_dir, body) -> None:
    response = client.put("/api/settings/sandbox", json=body)
    assert response.status_code == 422
    assert not (config_dir / "sandbox.yaml").exists()


def test_sandbox_validation_bodies(client, snapshot) -> None:
    snapshot.check(
        "sandbox_422.json",
        {
            "range": client.put("/api/settings/sandbox", json={"max_execution_seconds": 1}).json(),
            "literal": client.put("/api/settings/sandbox", json={"worktree_location": "x"}).json(),
            "extra": client.put("/api/settings/sandbox", json={"unknown": 1}).json(),
            "no_body": client.put("/api/settings/sandbox").json(),
        },
    )


def test_sandbox_unreadable_file_is_422_on_get_and_repaired_by_put(client, config_dir) -> None:
    (config_dir / "sandbox.yaml").write_text("denied_patterns: [", encoding="utf-8")
    response = client.get("/api/settings/sandbox")
    assert response.status_code == 422
    assert response.json()["detail"].startswith("Invalid YAML in ")
    assert "sandbox.yaml" in response.json()["detail"]
    # PUT never reads the old file, so it repairs it.
    assert client.put("/api/settings/sandbox", json={}).status_code == 200
    assert client.get("/api/settings/sandbox").status_code == 200


def test_sandbox_legacy_removed_controls_are_dropped_on_read(client, config_dir) -> None:
    (config_dir / "sandbox.yaml").write_text(
        "denied_patterns: [a]\nnative_process_isolation: true\nallow_network: false\n",
        encoding="utf-8",
    )
    response = client.get("/api/settings/sandbox")
    assert response.status_code == 200
    assert response.json()["denied_patterns"] == ["a"]


# ── pydantic lax parsing (the Rust port must reproduce it) ────────────────


def test_bodies_are_parsed_leniently_like_pydantic(client, config_dir) -> None:
    # Strings that spell a number or a boolean, and whole floats, are accepted.
    context = client.put(
        "/api/settings/context",
        json={"keep_recent_turns": "3", "keep_recent_tool_batches": 2.0},
    )
    assert context.status_code == 200
    assert context.json()["keep_recent_turns"] == 3
    assert context.json()["keep_recent_tool_batches"] == 2
    wake = client.put("/api/settings/background-tasks", json={"wake_idle": "no"})
    assert wake.status_code == 200
    assert wake.json() == {"wake_idle": False}
    assert saved(config_dir)["background_tasks"] == {"wake_idle": False}
    sandbox = client.put(
        "/api/settings/sandbox",
        json={"inherit_shell_environment": "yes", "max_execution_seconds": "30"},
    )
    assert sandbox.status_code == 200
    assert sandbox.json()["inherit_shell_environment"] is True
    assert sandbox.json()["max_execution_seconds"] == 30
    review = client.put(
        "/api/settings/version-control",
        json={**VERSION_CONTROL, "prune_on_fetch": "yes", "max_diff_bytes": "1000000"},
    )
    assert review.status_code == 200
    assert review.json()["prune_on_fetch"] is True
    assert review.json()["max_diff_bytes"] == 1_000_000


# ── concurrent writers ─────────────────────────────────────────────────────


def test_concurrent_section_puts_all_persist(client, config_dir) -> None:
    puts = [
        ("team-spawn", {"work": "auto", "coding": "auto"}),
        ("follow-up", {"delivery": "steer"}),
        ("background-tasks", {"wake_idle": False}),
        ("response-style", {"style": "simple"}),
        ("context", {"keep_recent_turns": 7}),
        ("version-control", VERSION_CONTROL),
    ] * 4

    def send(item):
        name, body = item
        return client.put(f"/api/settings/{name}", json=body).status_code

    with ThreadPoolExecutor(max_workers=8) as pool:
        statuses = list(pool.map(send, puts))
    assert statuses == [200] * len(puts)
    data = saved(config_dir)
    assert data["team_spawn"] == {"work": "auto", "coding": "auto"}
    assert data["follow_up"] == {"delivery": "steer"}
    assert data["background_tasks"] == {"wake_idle": False}
    assert data["response_style"] == {"style": "simple"}
    assert data["context"] == {"keep_recent_turns": 7}
    assert data["git"]["default_pull_strategy"] == "rebase"


def test_concurrent_sandbox_puts_leave_one_writers_whole_body(client) -> None:
    def send(index: int) -> int:
        body = {"denied_patterns": [f"p{index}"], "max_execution_seconds": 5 + index}
        return client.put("/api/settings/sandbox", json=body).status_code

    with ThreadPoolExecutor(max_workers=8) as pool:
        statuses = list(pool.map(send, range(16)))
    assert statuses == [200] * 16
    final = client.get("/api/settings/sandbox").json()
    index = final["max_execution_seconds"] - 5
    assert final["denied_patterns"] == [f"p{index}"]
