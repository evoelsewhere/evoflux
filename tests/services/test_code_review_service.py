from __future__ import annotations

import asyncio
import subprocess
from uuid import uuid4

import pytest

from app.models.chat import GitServerConnection
from app.services import code_review_service as service


@pytest.mark.parametrize(
    ("remote", "host", "repository"),
    [
        (
            "git@github.com:openai/codex.git",
            "github.com",
            "openai/codex",
        ),
        (
            "https://oauth2:secret@gitlab.example.com/group/sub/repo.git",
            "gitlab.example.com",
            "group/sub/repo",
        ),
        (
            "ssh://git@bitbucket.example.com:7999/scm/TEAM/repo.git",
            "bitbucket.example.com",
            "scm/TEAM/repo",
        ),
        (
            "https://dev.azure.com/acme/payments/_git/api",
            "dev.azure.com",
            "acme/payments/_git/api",
        ),
        (
            "git@ssh.dev.azure.com:v3/acme/payments/api",
            "dev.azure.com",
            "acme/payments/_git/api",
        ),
    ],
)
def test_parse_remote_url(remote, host, repository):
    parsed_host, parsed_repository, sanitized = service.parse_remote_url(remote)

    assert parsed_host == host
    assert parsed_repository == repository
    assert "secret" not in sanitized


@pytest.mark.parametrize(
    ("host", "repository", "provider"),
    [
        ("github.com", "org/repo", "github"),
        ("gitlab.com", "group/repo", "gitlab"),
        ("gitlab.corp.test", "group/repo", None),
        ("bitbucket.org", "workspace/repo", "bitbucket_cloud"),
        ("bitbucket.corp.test", "scm/TEAM/repo", "bitbucket_server"),
        ("dev.azure.com", "org/project/_git/repo", "azure_devops"),
        ("forgejo.corp.test", "org/repo", None),
        ("github-mirror.corp.test", "org/repo", None),
        ("git.corp.test", "org/repo", None),
    ],
)
def test_infer_provider(host, repository, provider):
    assert service.infer_provider(host, repository) == provider


def test_resolve_connection_prefers_repository_override():
    workspace_id = uuid4()
    target = service.RepositoryTarget(
        workspace_id=str(workspace_id),
        workspace="/repo",
        name="repo",
        remote_url="git@github.com:org/repo.git",
        host="github.com",
        repository="org/repo",
        detected_provider="github",
    )
    shared = GitServerConnection(
        name="Shared",
        provider="github",
        base_url="https://api.github.com",
        host="github.com",
        scope="server",
        token_env_var="SHARED_TOKEN",
    )
    override = GitServerConnection(
        name="Override",
        provider="github",
        base_url="https://api.github.com",
        host="github.com",
        scope="repository",
        workspace_id=workspace_id,
        token_env_var="OVERRIDE_TOKEN",
    )

    assert service.resolve_connection(target, [shared, override]) is override


@pytest.mark.asyncio
async def test_inspect_repository_reports_unavailable_folder(tmp_path):
    target = await service.inspect_repository(
        str(uuid4()),
        str(tmp_path / "deleted-repository"),
        "deleted-repository",
    )

    assert target.remote_url is None
    assert target.inspection_error == (
        "Repository folder is unavailable. Re-add it to Coding mode."
    )


@pytest.mark.asyncio
async def test_inspect_repository_reports_missing_remote(tmp_path):
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(
        ["git", "init", str(repository)],
        check=True,
        capture_output=True,
        text=True,
    )

    target = await service.inspect_repository(
        str(uuid4()),
        str(repository),
        "repository",
    )

    assert target.remote_url is None
    assert target.inspection_error == (
        "No Git remote is configured. Add a remote, then refresh reviews."
    )


@pytest.mark.asyncio
async def test_inspect_repository_uses_only_remote_when_origin_is_absent(tmp_path):
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(
        ["git", "init", str(repository)],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "remote",
            "add",
            "github",
            "git@github.com:acme/repository.git",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    target = await service.inspect_repository(
        str(uuid4()),
        str(repository),
        "repository",
    )

    assert target.remote_url == "git@github.com:acme/repository.git"
    assert target.host == "github.com"
    assert target.repository == "acme/repository"
    assert target.detected_provider == "github"
    assert target.inspection_error is None


def test_default_public_api_bases_and_server_hosts():
    assert service.default_api_base("github", "github.com") == "https://api.github.com"
    assert service.server_host("github", "https://api.github.com") == "github.com"
    assert (
        service.default_api_base("gitlab", "gitlab.corp.test")
        == "https://gitlab.corp.test/api/v4"
    )
    assert (
        service.server_host(
            "bitbucket_cloud",
            "https://api.bitbucket.org/2.0",
        )
        == "bitbucket.org"
    )


@pytest.mark.parametrize(
    ("provider", "domain", "repository", "api_base", "token_url"),
    [
        (
            "github",
            "github.com",
            "acme/repo",
            "https://api.github.com",
            "https://github.com/settings/tokens/new",
        ),
        (
            "github",
            "https://github.corp.test",
            "acme/repo",
            "https://github.corp.test/api/v3",
            "https://github.corp.test/settings/tokens/new",
        ),
        (
            "gitlab",
            "https://git.corp.test/gitlab",
            "group/repo",
            "https://git.corp.test/gitlab/api/v4",
            "https://git.corp.test/gitlab/-/user_settings/personal_access_tokens",
        ),
        (
            "bitbucket_cloud",
            "bitbucket.org",
            "team/repo",
            "https://api.bitbucket.org/2.0",
            "https://id.atlassian.com/manage-profile/security/api-tokens",
        ),
        (
            "bitbucket_server",
            "https://git.corp.test/bitbucket",
            "scm/TEAM/repo",
            "https://git.corp.test/bitbucket/rest/api/1.0",
            "https://git.corp.test/bitbucket/plugins/servlet/access-tokens/manage",
        ),
        (
            "gitea",
            "https://code.corp.test",
            "acme/repo",
            "https://code.corp.test/api/v1",
            "https://code.corp.test/user/settings/applications",
        ),
        (
            "azure_devops",
            "https://dev.azure.com/acme",
            "acme/project/_git/repo",
            "https://dev.azure.com/acme",
            "https://dev.azure.com/acme/_usersSettings/tokens",
        ),
    ],
)
def test_domain_derives_api_and_token_urls(
    provider,
    domain,
    repository,
    api_base,
    token_url,
):
    assert service.api_base_from_domain(provider, domain, repository) == api_base
    assert service.token_creation_url(provider, domain, repository) == token_url


def test_domain_accepts_existing_api_url_and_rejects_embedded_credentials():
    assert (
        service.server_domain(
            "gitlab",
            "https://gitlab.corp.test/api/v4",
        )
        == "https://gitlab.corp.test"
    )

    with pytest.raises(ValueError, match="without credentials"):
        service.server_domain(
            "gitlab",
            "https://oauth2:secret@gitlab.corp.test",
        )


def test_bitbucket_cloud_supports_bearer_and_basic_tokens():
    bearer = GitServerConnection(
        name="Workspace token",
        provider="bitbucket_cloud",
        base_url="https://api.bitbucket.org/2.0",
        host="bitbucket.org",
        token_env_var="BITBUCKET_TOKEN",
    )
    basic = GitServerConnection(
        name="API token",
        provider="bitbucket_cloud",
        base_url="https://api.bitbucket.org/2.0",
        host="bitbucket.org",
        token_env_var="BITBUCKET_TOKEN",
        username="dev@example.com",
    )

    assert service._auth_headers(bearer, "secret") == {"Authorization": "Bearer secret"}
    assert service._auth_headers(basic, "secret") == {
        "Authorization": "Basic ZGV2QGV4YW1wbGUuY29tOnNlY3JldA=="
    }


@pytest.mark.parametrize(
    ("parser", "payload", "expected_url"),
    [
        (
            service._github_items,
            [
                {
                    "number": 1,
                    "user": {
                        "login": "octocat",
                        "avatar_url": "https://avatars.githubusercontent.com/u/1?v=4",
                    },
                }
            ],
            "https://avatars.githubusercontent.com/u/1?v=4",
        ),
        (
            service._gitlab_items,
            [
                {
                    "iid": 1,
                    "author": {
                        "username": "gitlab-user",
                        "avatar_url": "https://gitlab.example.com/uploads/avatar.png",
                    },
                }
            ],
            "https://gitlab.example.com/uploads/avatar.png",
        ),
        (
            service._bitbucket_cloud_items,
            {
                "values": [
                    {
                        "id": 1,
                        "author": {
                            "display_name": "Bitbucket User",
                            "links": {
                                "avatar": {
                                    "href": "https://avatar-management.example/avatar.png"
                                }
                            },
                        },
                    }
                ]
            },
            "https://avatar-management.example/avatar.png",
        ),
        (
            service._bitbucket_server_items,
            {
                "values": [
                    {
                        "id": 1,
                        "author": {
                            "user": {
                                "displayName": "Bitbucket User",
                                "avatarUrl": "https://bitbucket.example.com/avatar.png",
                            }
                        },
                    }
                ]
            },
            "https://bitbucket.example.com/avatar.png",
        ),
        (
            service._gitea_items,
            [
                {
                    "number": 1,
                    "user": {
                        "login": "gitea-user",
                        "avatar_url": "https://gitea.example.com/avatars/1",
                    },
                }
            ],
            "https://gitea.example.com/avatars/1",
        ),
        (
            service._azure_items,
            {
                "value": [
                    {
                        "pullRequestId": 1,
                        "createdBy": {
                            "displayName": "Azure User",
                            "imageUrl": "https://dev.azure.com/acme/_apis/graph/avatars/1",
                        },
                    }
                ]
            },
            "https://dev.azure.com/acme/_apis/graph/avatars/1",
        ),
    ],
)
def test_review_items_keep_provider_avatar_urls(parser, payload, expected_url):
    items = parser(payload)

    assert len(items) == 1
    assert items[0].author_avatar_url == expected_url


def test_person_avatar_url_rejects_unsafe_urls():
    assert service._person_avatar_url({"avatar_url": "javascript:alert(1)"}) is None
    assert (
        service._person_avatar_url(
            {"avatar_url": "https://user:secret@example.com/avatar.png"}
        )
        is None
    )


@pytest.mark.asyncio
async def test_github_review_image_uses_connection_token(monkeypatch):
    monkeypatch.setenv("GITHUB_IMAGE_TOKEN", "secret")
    real_async_client = service.httpx.AsyncClient
    seen = {}

    def handle_request(request):
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers.get("authorization")
        return service.httpx.Response(
            200,
            headers={"Content-Type": "image/png"},
            content=b"\x89PNG\r\n\x1a\nimage",
        )

    transport = service.httpx.MockTransport(handle_request)
    monkeypatch.setattr(
        service.httpx,
        "AsyncClient",
        lambda **kwargs: real_async_client(transport=transport, **kwargs),
    )
    connection = GitServerConnection(
        name="GitHub",
        provider="github",
        base_url="https://api.github.com",
        host="github.com",
        scope="server",
        token_env_var="GITHUB_IMAGE_TOKEN",
    )
    url = "https://github.com/user-attachments/assets/74005370-eae1-4552-afb1-0a1dfdd56924"

    image = await service.fetch_code_review_image(connection, url)

    assert image.media_type == "image/png"
    assert image.content.startswith(b"\x89PNG")
    assert seen == {"url": url, "authorization": "Bearer secret"}


@pytest.mark.asyncio
async def test_github_review_image_accepts_signed_asset_redirect(monkeypatch):
    monkeypatch.setenv("GITHUB_IMAGE_TOKEN", "secret")
    real_async_client = service.httpx.AsyncClient
    signed_url = (
        "https://github-production-user-asset-6210df.s3.amazonaws.com/"
        "signed/image.png?X-Amz-Signature=value"
    )

    def handle_request(request):
        return service.httpx.Response(302, headers={"Location": signed_url})

    transport = service.httpx.MockTransport(handle_request)
    monkeypatch.setattr(
        service.httpx,
        "AsyncClient",
        lambda **kwargs: real_async_client(transport=transport, **kwargs),
    )
    connection = GitServerConnection(
        name="GitHub",
        provider="github",
        base_url="https://api.github.com",
        host="github.com",
        scope="server",
        token_env_var="GITHUB_IMAGE_TOKEN",
    )

    image = await service.fetch_code_review_image(
        connection,
        "https://github.com/user-attachments/assets/74005370-eae1-4552-afb1-0a1dfdd56924",
    )

    assert image == service.ReviewImageRedirect(url=signed_url)


@pytest.mark.asyncio
async def test_github_rendered_review_image_does_not_forward_token(monkeypatch):
    monkeypatch.setenv("GITHUB_IMAGE_TOKEN", "secret")
    real_async_client = service.httpx.AsyncClient
    seen = {}

    def handle_request(request):
        seen["authorization"] = request.headers.get("authorization")
        return service.httpx.Response(
            200,
            headers={"Content-Type": "image/png"},
            content=b"\x89PNG\r\n\x1a\nimage",
        )

    transport = service.httpx.MockTransport(handle_request)
    monkeypatch.setattr(
        service.httpx,
        "AsyncClient",
        lambda **kwargs: real_async_client(transport=transport, **kwargs),
    )
    connection = GitServerConnection(
        name="GitHub",
        provider="github",
        base_url="https://api.github.com",
        host="github.com",
        scope="server",
        token_env_var="GITHUB_IMAGE_TOKEN",
    )
    url = (
        "https://private-user-images.githubusercontent.com/123747604/"
        "626907679-74005370-eae1-4552-afb1-0a1dfdd56924.png?jwt=signed"
    )

    image = await service.fetch_code_review_image(connection, url)

    assert image.media_type == "image/png"
    assert seen["authorization"] is None


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/user-attachments/assets/74005370-eae1-4552-afb1-0a1dfdd56924",
        "https://github.com.evil.test/user-attachments/assets/74005370-eae1-4552-afb1-0a1dfdd56924",
        "https://github.com/acme/repo/raw/main/image.png",
    ],
)
def test_github_review_image_rejects_untrusted_urls(url):
    connection = GitServerConnection(
        name="GitHub",
        provider="github",
        base_url="https://api.github.com",
        host="github.com",
        scope="server",
        token_env_var="GITHUB_IMAGE_TOKEN",
    )

    with pytest.raises(service.GitServerApiError, match="Unsupported"):
        service._validated_review_image_url(connection, url)


def test_github_review_image_rejects_untrusted_redirect():
    with pytest.raises(service.GitServerApiError, match="unsafe image redirect"):
        service._validated_review_image_redirect_url(
            "https://github-production-user-asset.evil.test/image.png"
        )


@pytest.mark.asyncio
async def test_github_list_is_normalized_and_uses_api_not_cli(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("GITHUB_TEST_TOKEN", "secret")
    calls = []

    async def fake_request(connection, token, path, *, params=None):
        calls.append((connection, token, path, params))
        return [
            {
                "number": 42,
                "title": "Ship the feature",
                "state": "open",
                "draft": False,
                "user": {"login": "octocat"},
                "head": {"ref": "feature"},
                "base": {"ref": "main"},
                "updated_at": "2026-07-27T00:00:00Z",
                "html_url": "https://github.com/acme/repo/pull/42",
                "labels": [{"name": "feature"}],
                "comments": 3,
            }
        ]

    monkeypatch.setattr(service, "_request_json", fake_request)
    connection = GitServerConnection(
        name="GitHub",
        provider="github",
        base_url="https://api.github.com",
        host="github.com",
        scope="server",
        token_env_var="GITHUB_TEST_TOKEN",
    )
    target = service.RepositoryTarget(
        workspace_id=str(uuid4()),
        workspace="/repo",
        name="repo",
        remote_url="git@github.com:acme/repo.git",
        host="github.com",
        repository="acme/repo",
        detected_provider="github",
    )

    result = await service.list_repository_reviews(target, connection)

    assert result.error is None
    assert result.items[0].number == 42
    assert result.items[0].source_branch == "feature"
    assert result.items[0].labels == ["feature"]
    assert calls[0][1:] == (
        "secret",
        "repos/acme/repo/pulls",
        {
            "state": "open",
            "per_page": 100,
            "page": 1,
            "sort": "updated",
            "direction": "desc",
        },
    )


@pytest.mark.asyncio
async def test_gitlab_nested_repository_path_is_url_encoded(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("GITLAB_TEST_TOKEN", "secret")
    seen_path = ""

    async def fake_request(connection, token, path, *, params=None):
        nonlocal seen_path
        seen_path = path
        return []

    monkeypatch.setattr(service, "_request_json", fake_request)
    connection = GitServerConnection(
        name="GitLab",
        provider="gitlab",
        base_url="https://gitlab.example.com/api/v4",
        host="gitlab.example.com",
        token_env_var="GITLAB_TEST_TOKEN",
    )
    target = service.RepositoryTarget(
        workspace_id=str(uuid4()),
        workspace="/repo",
        name="repo",
        remote_url="git@gitlab.example.com:group/sub/repo.git",
        host="gitlab.example.com",
        repository="group/sub/repo",
        detected_provider="gitlab",
    )

    result = await service.list_repository_reviews(target, connection)

    assert result.error is None
    assert seen_path == "projects/group%2Fsub%2Frepo/merge_requests"


@pytest.mark.asyncio
async def test_github_review_context_reads_files_and_both_comment_streams(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("GITHUB_CONTEXT_TOKEN", "secret")
    paths: list[str] = []
    review_headers = {}
    comment_headers: dict[str, dict[str, str]] = {}

    async def fake_request(
        connection,
        token,
        path,
        *,
        params=None,
        method="GET",
        json_body=None,
        extra_headers=None,
    ):
        paths.append(path)
        if path.endswith("/files"):
            return [
                {
                    "filename": "app.py",
                    "patch": "+fixed",
                    "additions": 4,
                    "deletions": 2,
                }
            ]
        if path.endswith("/reviews"):
            return [{"id": 7, "state": "APPROVED", "user": {"login": "reviewer"}}]
        if path.endswith("/check-runs"):
            return {"check_runs": [{"id": 9, "name": "tests", "conclusion": "success"}]}
        if path.endswith("/comments"):
            comment_headers[path] = extra_headers or {}
            return [
                {
                    "id": 3,
                    "body": "Looks **good**",
                    "body_html": "<p>Looks <strong>good</strong></p>",
                    "user": {"login": "octocat"},
                }
            ]
        review_headers.update(extra_headers or {})
        return {
            "number": 42,
            "title": "Ship it",
            "body": "Adds the release workflow.",
            "body_html": "<p>Adds the <strong>release</strong> workflow.</p>",
            "state": "open",
            "user": {"login": "author"},
            "created_at": "2026-07-20T08:00:00Z",
            "updated_at": "2026-07-21T09:30:00Z",
            "head": {"sha": "abc123", "ref": "release"},
            "base": {"ref": "main"},
            "commits": 3,
            "requested_reviewers": [{"login": "reviewer"}],
            "assignees": [{"login": "maintainer"}],
        }

    monkeypatch.setattr(service, "_request_json", fake_request)
    connection = GitServerConnection(
        name="GitHub",
        provider="github",
        base_url="https://api.github.com",
        host="github.com",
        token_env_var="GITHUB_CONTEXT_TOKEN",
    )
    target = service.RepositoryTarget(
        workspace_id=str(uuid4()),
        workspace="/repo",
        name="repo",
        remote_url="git@github.com:acme/repo.git",
        host="github.com",
        repository="acme/repo",
        detected_provider="github",
    )

    context = await service.get_repository_review_context(target, connection, 42)

    assert context["review"]["number"] == 42
    assert context["changes"][0]["filename"] == "app.py"
    assert context["summary"] == {
        "description": "<p>Adds the <strong>release</strong> workflow.</p>",
        "author": "author",
        "created_at": "2026-07-20T08:00:00Z",
        "updated_at": "2026-07-21T09:30:00Z",
        "source_branch": "release",
        "target_branch": "main",
        "reviewers": ["reviewer"],
        "assignees": ["maintainer"],
        "commit_count": 3,
        "changed_files": 1,
        "additions": 4,
        "deletions": 2,
    }
    assert len(context["comments"]) == 2
    assert context["comments"][0]["stable_id"].startswith("github:")
    assert context["comments"][0]["author"] == "octocat"
    assert context["comments"][0]["body"] == "<p>Looks <strong>good</strong></p>"
    assert context["approvals"][0]["state"] == "approved"
    assert context["checks"]["summary"] == "success"
    assert context["capabilities"]["resolve_thread"] is False
    assert review_headers == {"Accept": "application/vnd.github.full+json"}
    assert comment_headers == {
        "repos/acme/repo/issues/42/comments": {
            "Accept": "application/vnd.github.full+json"
        },
        "repos/acme/repo/pulls/42/comments": {
            "Accept": "application/vnd.github.full+json"
        },
    }
    assert paths == [
        "repos/acme/repo/pulls/42",
        "repos/acme/repo/pulls/42/files",
        "repos/acme/repo/issues/42/comments",
        "repos/acme/repo/pulls/42/comments",
        "repos/acme/repo/pulls/42/reviews",
        "repos/acme/repo/commits/abc123/check-runs",
    ]


@pytest.mark.asyncio
async def test_gitlab_create_review_uses_saved_api_connection(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("GITLAB_CREATE_TOKEN", "secret")
    seen: dict = {}

    async def fake_request(
        connection,
        token,
        path,
        *,
        params=None,
        method="GET",
        json_body=None,
    ):
        seen.update(
            token=token,
            path=path,
            method=method,
            json_body=json_body,
        )
        return {
            "iid": 17,
            "title": json_body["title"],
            "web_url": "https://gitlab.example.com/group/repo/-/merge_requests/17",
        }

    monkeypatch.setattr(service, "_request_json", fake_request)
    connection = GitServerConnection(
        name="GitLab",
        provider="gitlab",
        base_url="https://gitlab.example.com/api/v4",
        host="gitlab.example.com",
        token_env_var="GITLAB_CREATE_TOKEN",
    )
    target = service.RepositoryTarget(
        workspace_id=str(uuid4()),
        workspace="/repo",
        name="repo",
        remote_url="git@gitlab.example.com:group/repo.git",
        host="gitlab.example.com",
        repository="group/repo",
        detected_provider="gitlab",
    )

    created = await service.create_repository_review(
        target,
        connection,
        title="API review",
        body="Details",
        source_branch="feature",
        target_branch="main",
    )

    assert created["number"] == 17
    assert seen == {
        "token": "secret",
        "path": "projects/group%2Frepo/merge_requests",
        "method": "POST",
        "json_body": {
            "title": "API review",
            "description": "Details",
            "source_branch": "feature",
            "target_branch": "main",
        },
    }


@pytest.mark.asyncio
async def test_bitbucket_server_create_review_reads_self_link(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("BITBUCKET_SERVER_CREATE_TOKEN", "secret")

    async def fake_request(
        connection,
        token,
        path,
        *,
        params=None,
        method="GET",
        json_body=None,
    ):
        assert path == "projects/TEAM/repos/repo/pull-requests"
        assert method == "POST"
        return {
            "id": 23,
            "title": json_body["title"],
            "links": {
                "self": [
                    {
                        "href": (
                            "https://bitbucket.example.com/projects/TEAM/"
                            "repos/repo/pull-requests/23"
                        )
                    }
                ]
            },
        }

    monkeypatch.setattr(service, "_request_json", fake_request)
    connection = GitServerConnection(
        name="Bitbucket Data Center",
        provider="bitbucket_server",
        base_url="https://bitbucket.example.com/rest/api/1.0",
        host="bitbucket.example.com",
        token_env_var="BITBUCKET_SERVER_CREATE_TOKEN",
    )
    target = service.RepositoryTarget(
        workspace_id=str(uuid4()),
        workspace="/repo",
        name="repo",
        remote_url="ssh://git@bitbucket.example.com:7999/TEAM/repo.git",
        host="bitbucket.example.com",
        repository="TEAM/repo",
        detected_provider="bitbucket_server",
    )

    created = await service.create_repository_review(
        target,
        connection,
        title="API review",
        body="Details",
        source_branch="feature",
        target_branch="main",
    )

    assert created["number"] == 23
    assert created["web_url"].endswith("/pull-requests/23")


@pytest.mark.asyncio
async def test_gitlab_resolve_thread_uses_discussion_endpoint(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("GITLAB_ACTION_TOKEN", "secret")
    seen: dict = {}

    async def fake_request(
        connection,
        token,
        path,
        *,
        params=None,
        method="GET",
        json_body=None,
        extra_headers=None,
    ):
        seen.update(path=path, method=method, json_body=json_body)
        return {"id": "discussion-1", "resolved": True}

    monkeypatch.setattr(service, "_request_json", fake_request)
    connection = GitServerConnection(
        name="GitLab",
        provider="gitlab",
        base_url="https://gitlab.example.com/api/v4",
        host="gitlab.example.com",
        token_env_var="GITLAB_ACTION_TOKEN",
    )
    target = service.RepositoryTarget(
        workspace_id=str(uuid4()),
        workspace="/repo",
        name="repo",
        remote_url="git@gitlab.example.com:group/repo.git",
        host="gitlab.example.com",
        repository="group/repo",
        detected_provider="gitlab",
    )

    await service.set_code_review_thread_resolved(
        target, connection, 8, "discussion-1", resolved=True
    )

    assert seen == {
        "path": "projects/group%2Frepo/merge_requests/8/discussions/discussion-1",
        "method": "PUT",
        "json_body": {"resolved": True},
    }


@pytest.mark.asyncio
async def test_github_inline_comment_maps_position_and_idempotency(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("GITHUB_ACTION_TOKEN", "secret")
    seen: list[dict] = []

    async def fake_request(
        connection,
        token,
        path,
        *,
        params=None,
        method="GET",
        json_body=None,
        extra_headers=None,
    ):
        seen.append(
            {
                "path": path,
                "method": method,
                "json_body": json_body,
                "extra_headers": extra_headers,
            }
        )
        return {"id": 11}

    monkeypatch.setattr(service, "_request_json", fake_request)
    connection = GitServerConnection(
        name="GitHub",
        provider="github",
        base_url="https://api.github.com",
        host="github.com",
        token_env_var="GITHUB_ACTION_TOKEN",
    )
    target = service.RepositoryTarget(
        workspace_id=str(uuid4()),
        workspace="/repo",
        name="repo",
        remote_url="git@github.com:acme/repo.git",
        host="github.com",
        repository="acme/repo",
        detected_provider="github",
    )

    await service.add_code_review_comment(
        target, connection, 5, "General", idempotency_key="call-1"
    )
    await service.add_code_review_inline_comment(
        target,
        connection,
        5,
        "Inline",
        path="app.py",
        line=12,
        commit_id="abc",
    )

    assert seen[0]["extra_headers"] == {"Idempotency-Key": "call-1"}
    assert seen[1]["path"] == "repos/acme/repo/pulls/5/comments"
    assert seen[1]["json_body"] == {
        "body": "Inline",
        "path": "app.py",
        "line": 12,
        "side": "RIGHT",
        "commit_id": "abc",
    }


@pytest.mark.asyncio
async def test_read_requests_retry_transient_server_failures(monkeypatch):
    from app.core.runtime_settings import CodeReviewSettings, RuntimeSettings

    attempts = 0
    real_async_client = service.httpx.AsyncClient

    def handle_request(request):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return service.httpx.Response(503, request=request)
        return service.httpx.Response(200, request=request, json={"login": "octocat"})

    transport = service.httpx.MockTransport(handle_request)
    monkeypatch.setattr(
        service.httpx,
        "AsyncClient",
        lambda **kwargs: real_async_client(transport=transport, **kwargs),
    )
    monkeypatch.setattr(
        service,
        "load_runtime_settings",
        lambda: RuntimeSettings(
            code_reviews=CodeReviewSettings(
                retry_attempts=1,
                retry_backoff_seconds=0,
            )
        ),
    )
    connection = GitServerConnection(
        name="GitHub",
        provider="github",
        base_url="https://api.github.com",
        host="github.com",
        token_env_var="GITHUB_RETRY_TOKEN",
    )

    payload = await service._request_json(connection, "secret", "user")

    assert payload == {"login": "octocat"}
    assert attempts == 2


@pytest.mark.asyncio
async def test_review_aggregation_respects_configured_concurrency(monkeypatch):
    from app.core.runtime_settings import CodeReviewSettings, RuntimeSettings

    active = 0
    peak = 0

    async def fake_list(target, connection):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return service.RepositoryReviews(
            target=target,
            connection_id=str(connection.id),
            provider=connection.provider,
        )

    monkeypatch.setattr(service, "list_repository_reviews", fake_list)
    monkeypatch.setattr(
        service,
        "load_runtime_settings",
        lambda: RuntimeSettings(
            code_reviews=CodeReviewSettings(max_concurrent_repositories=2)
        ),
    )
    connection = GitServerConnection(
        name="GitHub",
        provider="github",
        base_url="https://api.github.com",
        host="github.com",
        token_env_var="GITHUB_CONCURRENCY_TOKEN",
    )
    targets = [
        service.RepositoryTarget(
            workspace_id=str(uuid4()),
            workspace=f"/repo-{index}",
            name=f"repo-{index}",
            remote_url=f"git@github.com:acme/repo-{index}.git",
            host="github.com",
            repository=f"acme/repo-{index}",
            detected_provider="github",
        )
        for index in range(5)
    ]

    results = await service.aggregate_reviews(targets, [connection])

    assert len(results) == 5
    assert peak == 2


def test_review_mutations_can_be_disabled_globally(monkeypatch):
    from app.core.runtime_settings import CodeReviewSettings, RuntimeSettings

    monkeypatch.setattr(
        service,
        "load_runtime_settings",
        lambda: RuntimeSettings(code_reviews=CodeReviewSettings(allow_mutations=False)),
    )

    with pytest.raises(service.GitServerApiError, match="mutations are disabled"):
        service.require_review_mutations_enabled()


def test_provider_capability_reports_rest_only_limitations():
    github = service.provider_capabilities("github")
    gitlab = service.provider_capabilities("gitlab")

    assert github["inline_comment"] is True
    assert github["resolve_thread"] is False
    assert github["draft"] is False
    assert gitlab["resolve_thread"] is True
