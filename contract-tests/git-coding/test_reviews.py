"""``/api/team/reviews``: Git server connections and the refusals that come before any server call.

No test reaches a real Git server: connections point at a ``.test`` domain that
never resolves, and the only routes called are the ones that answer from the
database, the validation or the saved ``.env``.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import httpx

R = "/api/team/reviews"
TOKEN = "tok-NOT-A-REAL-TOKEN-0123456789"


def create(client: httpx.Client, **body) -> httpx.Response:
    payload = {"name": "Gitea", "provider": "gitea", "domain": "git.example.test", "token": TOKEN}
    payload.update(body)
    return client.post(f"{R}/connections", json=payload)


def env_text(config_dir: Path) -> str:
    path = config_dir / ".env"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def test_create_list_update_and_delete_a_connection(client: httpx.Client, tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    assert client.get(f"{R}/connections").json() == []
    response = create(client, username="  bot  ")
    assert response.status_code == 201, response.text
    body = response.json()
    assert list(body) == [
        "id", "name", "provider", "domain", "base_url", "token_url", "host", "scope",
        "workspace_id", "token_env_var", "has_token", "username", "verify_ssl",
        "created_at", "updated_at",
    ]
    assert body["name"] == "Gitea" and body["provider"] == "gitea"
    assert body["domain"] == "https://git.example.test"
    assert body["base_url"] == "https://git.example.test/api/v1"
    assert body["host"] == "git.example.test"
    assert body["scope"] == "server" and body["workspace_id"] is None
    assert body["has_token"] is True and body["username"] == "bot" and body["verify_ssl"] is True
    # the token is stored in the config ``.env`` under a managed name and never echoed
    assert body["token_env_var"] == f"EVOFLUX_GIT_CONNECTION_{uuid.UUID(body['id']).hex.upper()}_TOKEN"
    assert f"{body['token_env_var']}={TOKEN}" in env_text(config_dir)
    assert TOKEN not in response.text
    listed = client.get(f"{R}/connections")
    assert listed.json() == [body] and TOKEN not in listed.text
    renamed = client.put(f"{R}/connections/{body['id']}", json={"name": "  Renamed  ", "username": ""})
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == "Renamed" and renamed.json()["username"] is None
    assert TOKEN not in renamed.text
    deleted = client.delete(f"{R}/connections/{body['id']}")
    assert deleted.status_code == 204 and deleted.content == b""
    assert client.get(f"{R}/connections").json() == []
    assert TOKEN not in env_text(config_dir)
    assert client.delete(f"{R}/connections/{body['id']}").status_code == 404


def test_create_validation(client: httpx.Client) -> None:
    cases = [
        ({"domain": "ftp://git.example.test"}, "Git server domain must be an HTTP(S) domain or root URL without credentials, query, or fragment."),
        ({"domain": "https://u:p@git.example.test"}, "Git server domain must be an HTTP(S) domain or root URL without credentials, query, or fragment."),
        ({"domain": "https://git.example.test/?x=1"}, "Git server domain must be an HTTP(S) domain or root URL without credentials, query, or fragment."),
        ({"domain": "http://git.example.test"}, "Insecure Git server connections are disabled in Git & reviews settings."),
        ({"verify_ssl": False}, "Insecure Git server connections are disabled in Git & reviews settings."),
        ({"scope": "repository"}, "Repository-scoped connections require a workspace."),
        ({"workspace_id": str(uuid.uuid4())}, "Shared server connections cannot target one workspace."),
        ({"token": ""}, "Provide an API key or an environment variable containing one."),
        ({"token_env_var": "lower"}, "Token environment variable must use uppercase letters, numbers, and underscores."),
        ({"token_env_var": "1BAD"}, "Token environment variable must use uppercase letters, numbers, and underscores."),
        ({"token_env_var": "A-B"}, "Token environment variable must use uppercase letters, numbers, and underscores."),
        ({"token_env_var": "A\nB"}, "Token environment variable must use uppercase letters, numbers, and underscores."),
    ]
    for extra, detail in cases:
        response = create(client, **extra)
        assert response.status_code == 422, extra
        assert response.json() == {"detail": detail}, extra
    assert client.get(f"{R}/connections").json() == []
    for body in [{"provider": "svn"}, {"name": "   "}, {"name": ""}]:
        response = create(client, **body)
        assert response.status_code == 422, body
        assert isinstance(response.json()["detail"], list)
    no_domain = client.post(f"{R}/connections", json={"name": "n", "provider": "gitea", "token": "t"})
    assert no_domain.status_code == 422 and isinstance(no_domain.json()["detail"], list)
    unknown_workspace = create(client, scope="repository", workspace_id=str(uuid.uuid4()))
    assert unknown_workspace.status_code == 404
    assert unknown_workspace.json() == {"detail": "Coding repository not found."}


def test_one_connection_per_server_and_per_token_variable(client: httpx.Client) -> None:
    first = create(client)
    assert first.status_code == 201
    duplicate = create(client, name="Other")
    assert duplicate.status_code == 409 or duplicate.status_code == 422
    assert TOKEN not in duplicate.text
    taken = create(client, domain="other.example.test", token_env_var=first.json()["token_env_var"])
    assert taken.status_code in (409, 422)
    assert TOKEN not in taken.text


def test_provider_domains_are_normalised(client: httpx.Client) -> None:
    for provider, domain, expect_domain, expect_api in [
        ("github", "api.github.com", "https://github.com", "https://api.github.com"),
        ("gitlab", "https://gitlab.example.test/", "https://gitlab.example.test", "https://gitlab.example.test/api/v4"),
        ("github", "ghe.example.test", "https://ghe.example.test", "https://ghe.example.test/api/v3"),
    ]:
        response = create(client, provider=provider, domain=domain, name=f"{provider}-{domain}")
        assert response.status_code == 201, (provider, domain, response.text)
        body = response.json()
        assert (body["domain"], body["base_url"]) == (expect_domain, expect_api), (provider, domain)
        assert client.delete(f"{R}/connections/{body['id']}").status_code == 204


def test_changing_the_domain_needs_a_new_token(client: httpx.Client) -> None:
    body = create(client).json()
    response = client.put(f"{R}/connections/{body['id']}", json={"domain": "moved.example.test"})
    assert response.status_code == 422
    assert response.json() == {"detail": "Provide a new access token when changing the Git provider or domain."}
    moved = client.put(
        f"{R}/connections/{body['id']}", json={"domain": "moved.example.test", "token": "x" * 12}
    )
    assert moved.status_code == 200 and moved.json()["host"] == "moved.example.test"
    unknown = client.put(f"{R}/connections/{uuid.uuid4()}", json={"name": "n"})
    assert unknown.status_code == 404 and unknown.json() == {"detail": "Connection not found."}


def test_connection_test_validates_before_it_reaches_a_server(client: httpx.Client) -> None:
    http = client.post(
        f"{R}/connections/test",
        json={"provider": "gitea", "domain": "http://git.example.test", "token": TOKEN},
    )
    assert http.status_code == 422
    assert http.json() == {"detail": "Insecure Git server connections are disabled in Git & reviews settings."}
    assert TOKEN not in http.text
    bad = client.post(
        f"{R}/connections/test",
        json={"provider": "gitea", "domain": "ftp://git.example.test", "token": TOKEN},
    )
    assert bad.status_code == 422 and TOKEN not in bad.text
    missing = client.post(f"{R}/connections/test", json={"provider": "gitea", "domain": "x.test"})
    assert missing.status_code == 422 and isinstance(missing.json()["detail"], list)


def test_list_reviews_without_repositories_and_filter_conflicts(client: httpx.Client) -> None:
    both = client.get(R, params={"workspace": "x", "project_id": str(uuid.uuid4())})
    assert both.status_code == 422
    assert both.json() == {"detail": "Filter reviews by workspace or project, not both."}
    empty = client.get(R)
    assert empty.status_code == 200, empty.text
    bad_state = client.get(R, params={"state": "weird"})
    assert bad_state.status_code == 422 and isinstance(bad_state.json()["detail"], list)


def test_review_routes_for_an_unknown_repository_and_bad_numbers(client: httpx.Client) -> None:
    ghost = uuid.uuid4()
    for number in (0, -1):
        response = client.get(f"{R}/{ghost}/{number}")
        assert response.status_code == 422
        assert response.json() == {"detail": "Review number must be positive."}
        action = client.post(f"{R}/{ghost}/{number}/actions", json={"action": "comment", "body": "x"})
        assert action.status_code == 422
    unknown = client.get(f"{R}/{ghost}/1")
    assert unknown.status_code == 404
    bad_id = client.get(f"{R}/not-a-uuid/1")
    assert bad_id.status_code == 422
