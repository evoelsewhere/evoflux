"""Secrets must never leave ``<config>/.env``.

Every key in this file is a dummy made up per test. A failure names the
secret's label, never its value. The sweeps cover every response of the unit,
every other file the backend wrote, and the backend's log.
"""

from __future__ import annotations

import httpx

from settings_helpers import GET_PATHS, env_values


def sweep(client, secrets, where: str) -> None:
    """Every read-only endpoint of the unit, after something secret was saved."""
    for path in GET_PATHS:
        response = client.get(path)
        secrets.assert_response_clean(f"{where}: GET {path}", response)


def files_outside_env(root):
    for path in root.rglob("*"):
        if path.is_file() and path.name != ".env":
            yield path


def assert_files_clean(root, secrets) -> None:
    for path in files_outside_env(root):
        secrets.assert_clean(f"file {path.name}", path.read_bytes())


def test_secrets_stay_in_the_env_file(client, backend, mock_provider, secrets, tmp_path, config_dir) -> None:
    anthropic = secrets.new("anthropic")
    aws_secret = secrets.new("aws-secret")
    foundry = secrets.new("foundry")
    router = secrets.new("router9")
    calls = [
        client.put(
            "/api/settings/providers/anthropic",
            json={"api_key": anthropic, "extra": {"ANTHROPIC_BASE_URL": mock_provider.base_url}},
        ),
        client.put(
            "/api/settings/providers/bedrock",
            json={"extra": {"AWS_ACCESS_KEY_ID": "AKIAEXAMPLEEXAMPLE", "AWS_SECRET_ACCESS_KEY": aws_secret}},
        ),
        client.put(
            "/api/settings/providers/foundry",
            json={"extra": {"FOUNDRY_API_KEY": foundry, "FOUNDRY_RESOURCE_NAME": "res"}},
        ),
        client.put(
            "/api/settings/providers/router9",
            json={"api_key": router, "extra": {"ROUTER9_BASE_URL": f"{mock_provider.base_url}/v1"}},
        ),
        client.post(
            "/api/settings/providers/anthropic/models",
            json={"api_key": anthropic, "extra": {"ANTHROPIC_BASE_URL": mock_provider.base_url}},
        ),
        client.post(
            "/api/settings/providers/anthropic/test",
            json={"api_key": anthropic, "model": "mock-model", "extra": {"ANTHROPIC_BASE_URL": mock_provider.base_url}},
        ),
        client.put("/api/settings/providers/anthropic/visible-models", json={"models": ["mock-model"]}),
        client.post("/api/settings/seed", json={"provider_model": "anthropic:mock-model"}),
    ]
    for index, response in enumerate(calls):
        assert response.status_code == 200, index
        secrets.assert_response_clean(f"call {index}", response)
    sweep(client, secrets, "after saving")

    # The sweep is not vacuous: the secrets really are on disk, in .env only.
    values = env_values(config_dir)
    assert values["ANTHROPIC_API_KEY"] == anthropic
    assert values["AWS_SECRET_ACCESS_KEY"] == aws_secret
    assert values["FOUNDRY_API_KEY"] == foundry
    assert values["ROUTER9_API_KEY"] == router
    assert_files_clean(tmp_path, secrets)
    secrets.assert_clean("backend log", backend.log_tail())

    client.delete("/api/settings/providers/anthropic")
    client.delete("/api/settings/providers/bedrock")
    assert "ANTHROPIC_API_KEY" not in env_values(config_dir)
    assert "AWS_SECRET_ACCESS_KEY" not in env_values(config_dir)
    secrets.assert_clean("backend log after delete", backend.log_tail())


def test_the_provider_list_echoes_only_credentials_the_catalog_calls_non_secret(
    client, mock_provider, secrets
) -> None:
    secret = secrets.new("aws-secret")
    client.put(
        "/api/settings/providers/bedrock",
        json={
            "extra": {
                "AWS_BEDROCK_REGION": "us-east-1",
                "AWS_ACCESS_KEY_ID": "AKIAEXAMPLEEXAMPLE",
                "AWS_SECRET_ACCESS_KEY": secret,
            }
        },
    )
    response = client.get("/api/settings/providers")
    secrets.assert_response_clean("GET /providers", response)
    item = {p["id"]: p for p in response.json()["providers"]}["bedrock"]
    flags = {c["name"]: c["secret"] for c in item["credentials"]}
    assert flags == {
        "AWS_BEDROCK_REGION": False,
        "AWS_BEDROCK_PROFILE": False,
        "AWS_ACCESS_KEY_ID": False,
        "AWS_SECRET_ACCESS_KEY": True,
    }
    # The access key id is declared non-secret, so it is shown; the secret
    # access key is declared secret, so it never is.
    assert item["saved_credentials"] == {
        "AWS_BEDROCK_REGION": "us-east-1",
        "AWS_ACCESS_KEY_ID": "AKIAEXAMPLEEXAMPLE",
    }


def test_no_saved_credential_in_any_provider_is_a_declared_secret(client, secrets) -> None:
    catalog = client.get("/api/settings/providers").json()["providers"]
    saved: dict[str, str] = {}
    for item in catalog:
        if item["kind"] != "api_key" or not item["env_var"]:
            continue
        key = secrets.new(item["id"])
        response = client.put(f"/api/settings/providers/{item['id']}", json={"api_key": key})
        assert response.status_code == 200, item["id"]
        saved[item["id"]] = key
    assert len(saved) > 50
    listing = client.get("/api/settings/providers")
    secrets.assert_response_clean("GET /providers", listing)
    for item in listing.json()["providers"]:
        if item["id"] not in saved:
            continue
        secret_names = {c["name"] for c in item["credentials"] if c["secret"]}
        assert not secret_names & set(item["saved_credentials"]), item["id"]
    sweep(client, secrets, "after saving every api-key provider")


def test_a_rejected_request_does_not_echo_the_secrets_it_carried(client, secrets) -> None:
    key = secrets.new("sibling")
    bodies = [
        ("PUT", "/api/settings/providers/anthropic", {"api_key": key, "unknown_field": 1}),
        ("PUT", "/api/settings/providers/anthropic", {"api_key": key, "extra": {"A": 1}}),
        ("PUT", "/api/settings/providers/nope", {"api_key": key}),
        ("DELETE", "/api/settings/providers/nope", None),
        ("POST", "/api/settings/providers/nope/models", {"api_key": key}),
        ("POST", "/api/settings/providers/nope/test", {"api_key": key, "model": "m"}),
        ("POST", "/api/settings/providers/anthropic/models", {"api_key": key, "bogus": True}),
    ]
    statuses = []
    for method, path, body in bodies:
        response = client.request(method, path, json=body)
        statuses.append(response.status_code)
        secrets.assert_response_clean(f"{method} {path}", response)
    assert statuses == [422, 422, 404, 404, 404, 404, 422]


def test_known_leak_a_missing_model_422_echoes_the_whole_request_body(client, secrets) -> None:
    """Pins a Python behaviour that NOTES lists as security finding S1.

    FastAPI reports a missing field with the whole body as ``input``, so the key
    in ``POST /providers/{id}/test`` without a ``model`` comes back to the caller
    that sent it. A Rust port that redacts it is a ``KNOWN_DIFFERENCES.md`` entry
    for the owner to approve, not a silent change.
    """
    key = secrets.new("sibling")
    response = client.post("/api/settings/providers/anthropic/test", json={"api_key": key})
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "model"]
    assert response.json()["detail"][0]["input"] == {"api_key": key}
    assert secrets.leaked_in(response.content) == ["sibling"]


def test_candidate_credentials_never_outlive_the_request(
    client, config_dir, cache_dir, mock_provider, secrets
) -> None:
    key = secrets.new("candidate")
    extra = {"ANTHROPIC_BASE_URL": mock_provider.base_url}
    client.post("/api/settings/providers/anthropic/models", json={"api_key": key, "extra": extra})
    client.post(
        "/api/settings/providers/anthropic/test",
        json={"api_key": key, "model": "mock-model", "extra": extra},
    )
    assert not (config_dir / ".env").exists()
    item = {p["id"]: p for p in client.get("/api/settings/providers").json()["providers"]}["anthropic"]
    assert item["is_saved"] is False
    assert item["saved_credentials"] == {}
    sweep(client, secrets, "after candidate use")


def test_a_failed_provider_test_does_not_reveal_the_key(client, secrets) -> None:
    key = secrets.new("candidate")
    for base in ("http://127.0.0.1:9", "http://127.0.0.1:9/v1", "not a url"):
        response = client.post(
            "/api/settings/providers/anthropic/test",
            json={"api_key": key, "model": "mock-model", "extra": {"ANTHROPIC_BASE_URL": base}},
        )
        assert response.status_code == 200
        assert response.json()["ok"] is False
        secrets.assert_response_clean(f"test failure ({base})", response)


def test_oauth_token_files_are_deleted_without_being_read_back(client, cache_dir, secrets) -> None:
    token = secrets.new("oauth-token")
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "codex_oauth.json").write_text(
        f'{{"access_token": "{token}", "refresh_token": "{token}"}}', encoding="utf-8"
    )
    (cache_dir / "copilot_oauth.json").write_text(f'{{"token": "{token}"}}', encoding="utf-8")
    # A listing or usage call with a token file present would send the dummy
    # token to the real provider, so only the local delete is exercised here.
    response = client.delete("/api/settings/providers/codex")
    secrets.assert_response_clean("DELETE codex", response)
    assert not (cache_dir / "codex_oauth.json").exists()
    assert token in (cache_dir / "copilot_oauth.json").read_text(encoding="utf-8")


def test_the_desktop_token_is_not_echoed(client, backend, secrets) -> None:
    secrets._values["desktop-token"] = backend.token
    for path in GET_PATHS:
        response = client.get(path)
        secrets.assert_response_clean(f"GET {path}", response)
    # An error caused by a wrong token does not repeat the token either.
    with httpx.Client(
        base_url=backend.base_url, headers={"Authorization": f"Bearer {backend.token}x"}
    ) as wrong:
        response = wrong.get("/api/settings/providers")
    assert response.status_code == 401
    secrets.assert_response_clean("401", response)
