"""Provider-neutral pull/merge request integration over Git server REST APIs."""

from __future__ import annotations

import asyncio
import base64
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse, urlunparse

import httpx
from dotenv import dotenv_values

from app.core.config import settings
from app.core.runtime_settings import load_runtime_settings
from app.models.chat import GitServerConnection
from app.services.git_ops import run_git

SUPPORTED_PROVIDERS = {
    "github",
    "gitlab",
    "bitbucket_cloud",
    "bitbucket_server",
    "gitea",
    "azure_devops",
}

REVIEW_CAPABILITIES: dict[str, dict[str, bool]] = {
    "github": {
        "comment": True,
        "inline_comment": True,
        "reply_thread": True,
        "resolve_thread": False,  # GitHub exposes this through GraphQL only.
        "submit_approve": True,
        "submit_request_changes": True,
        "update": True,
        "draft": False,  # draft/ready transitions are GraphQL-only.
        "labels": True,
        "reviewers": True,
        "assignees": True,
        "checks": True,
        "merge": True,
        "close": True,
        "reopen": True,
    },
    "gitlab": {
        "comment": True,
        "inline_comment": True,
        "reply_thread": True,
        "resolve_thread": True,
        "submit_approve": True,
        "submit_request_changes": False,
        "update": True,
        "draft": True,
        "labels": True,
        "reviewers": True,
        "assignees": True,
        "checks": True,
        "merge": True,
        "close": True,
        "reopen": True,
    },
    "bitbucket_cloud": {
        "comment": True,
        "inline_comment": True,
        "reply_thread": True,
        "resolve_thread": True,
        "submit_approve": True,
        "submit_request_changes": True,
        "update": True,
        "draft": False,
        "labels": False,
        "reviewers": True,
        "assignees": False,
        "checks": True,
        "merge": True,
        "close": True,
        "reopen": True,
    },
    "bitbucket_server": {
        "comment": True,
        "inline_comment": True,
        "reply_thread": True,
        "resolve_thread": True,
        "submit_approve": True,
        "submit_request_changes": False,
        "update": True,
        "draft": False,
        "labels": False,
        "reviewers": True,
        "assignees": False,
        "checks": False,
        "merge": True,
        "close": True,
        "reopen": True,
    },
    "gitea": {
        "comment": True,
        "inline_comment": True,
        "reply_thread": False,
        "resolve_thread": False,
        "submit_approve": True,
        "submit_request_changes": True,
        "update": True,
        "draft": False,
        "labels": True,
        "reviewers": True,
        "assignees": True,
        "checks": True,
        "merge": True,
        "close": True,
        "reopen": True,
    },
    "azure_devops": {
        "comment": True,
        "inline_comment": True,
        "reply_thread": True,
        "resolve_thread": True,
        "submit_approve": True,
        "submit_request_changes": True,
        "update": True,
        "draft": True,
        "labels": True,
        "reviewers": True,
        "assignees": False,
        "checks": True,
        "merge": True,
        "close": True,
        "reopen": True,
    },
}

_SCP_REMOTE_RE = re.compile(r"^(?:[^@]+@)?(?P<host>[^:]+):(?P<path>.+)$")
_GITHUB_ATTACHMENT_PATH_RE = re.compile(
    r"^/user-attachments/assets/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/?$",
    re.IGNORECASE,
)
_GITHUB_ATTACHMENT_REDIRECT_HOSTS = {
    "objects.githubusercontent.com",
    "private-user-images.githubusercontent.com",
    "user-images.githubusercontent.com",
}
_GITHUB_RENDERED_IMAGE_HOSTS = {
    "private-user-images.githubusercontent.com",
    "user-images.githubusercontent.com",
}
_GITHUB_RENDERED_IMAGE_PATH_RE = re.compile(
    r"^/[0-9]+/[0-9]+-[0-9a-f-]+(?:\.[a-z0-9]+)?$",
    re.IGNORECASE,
)
_GITHUB_ATTACHMENT_S3_HOST_RE = re.compile(
    r"^github-production-[a-z0-9-]+\.s3(?:\.[a-z0-9-]+)?\.amazonaws\.com$"
)
_MAX_REVIEW_IMAGE_BYTES = 25 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class RepositoryTarget:
    workspace_id: str
    workspace: str
    name: str
    remote_url: str | None
    host: str | None
    repository: str | None
    detected_provider: str | None
    inspection_error: str | None = None
    remote_name: str | None = None


@dataclass(frozen=True, slots=True)
class ReviewImage:
    content: bytes
    media_type: str


@dataclass(frozen=True, slots=True)
class ReviewImageRedirect:
    url: str


@dataclass(frozen=True, slots=True)
class ReviewItem:
    number: int
    title: str
    state: str
    draft: bool
    author: str | None
    author_avatar_url: str | None
    source_branch: str
    target_branch: str
    updated_at: str
    web_url: str
    labels: list[str] = field(default_factory=list)
    review_status: str | None = None
    pipeline_status: str | None = None
    comment_count: int | None = None


@dataclass(frozen=True, slots=True)
class RepositoryReviews:
    target: RepositoryTarget
    connection_id: str | None
    provider: str | None
    items: list[ReviewItem] = field(default_factory=list)
    error: str | None = None


class GitServerApiError(RuntimeError):
    """A sanitized provider API failure safe to expose to the desktop UI."""


def provider_capabilities(provider: str) -> dict[str, bool]:
    return dict(REVIEW_CAPABILITIES.get(provider, {}))


def require_capability(provider: str, capability: str) -> None:
    if not REVIEW_CAPABILITIES.get(provider, {}).get(capability, False):
        raise GitServerApiError(
            f"{capability.replace('_', ' ').title()} is not supported by the "
            f"{provider.replace('_', ' ')} REST adapter."
        )


def require_review_mutations_enabled() -> None:
    if not load_runtime_settings().code_reviews.allow_mutations:
        raise GitServerApiError(
            "Pull/merge request mutations are disabled in Git & reviews settings."
        )


def sanitize_remote_url(remote_url: str) -> str:
    """Remove embedded HTTPS credentials before persisting or returning a URL."""
    parsed = urlparse(remote_url)
    if not parsed.hostname or (parsed.username is None and parsed.password is None):
        return remote_url
    host = parsed.hostname
    if parsed.port:
        host = f"{host}:{parsed.port}"
    return urlunparse(
        (parsed.scheme, host, parsed.path, parsed.params, parsed.query, parsed.fragment)
    )


def parse_remote_url(remote_url: str) -> tuple[str | None, str | None, str]:
    """Return host, repository path, and a credential-free remote URL."""
    sanitized = sanitize_remote_url(remote_url.strip())
    scp_match = _SCP_REMOTE_RE.match(sanitized)
    if "://" not in sanitized and scp_match:
        host = scp_match.group("host").lower()
        path = scp_match.group("path")
    else:
        parsed = urlparse(sanitized)
        host = parsed.hostname.lower() if parsed.hostname else None
        path = parsed.path
    repository = path.strip("/").removesuffix(".git")
    parts = repository.split("/")
    if (
        (host in {"ssh.dev.azure.com"} or (host and host.endswith("visualstudio.com")))
        and parts[:1] == ["v3"]
        and len(parts) >= 4
    ):
        repository = f"{parts[1]}/{parts[2]}/_git/{parts[3]}"
        host = "dev.azure.com"
    elif host and host.endswith("visualstudio.com") and "/_git/" in repository:
        organization = host.split(".", 1)[0]
        repository = f"{organization}/{repository}"
        host = "dev.azure.com"
    return host, repository or None, sanitized


def infer_provider(host: str | None, repository: str | None = None) -> str | None:
    host = (host or "").lower()
    if host == "github.com":
        return "github"
    if host == "gitlab.com":
        return "gitlab"
    if host == "bitbucket.org":
        return "bitbucket_cloud"
    if (repository or "").lower().startswith("scm/"):
        return "bitbucket_server"
    if host in {"dev.azure.com", "ssh.dev.azure.com"} or host.endswith(
        "visualstudio.com"
    ):
        return "azure_devops"
    return None


def default_api_base(provider: str, host: str, repository: str | None = None) -> str:
    origin = f"https://{host}"
    if provider == "github":
        return "https://api.github.com" if host == "github.com" else f"{origin}/api/v3"
    if provider == "gitlab":
        return f"{origin}/api/v4"
    if provider == "bitbucket_cloud":
        return "https://api.bitbucket.org/2.0"
    if provider == "bitbucket_server":
        return f"{origin}/rest/api/1.0"
    if provider == "gitea":
        return f"{origin}/api/v1"
    if provider == "azure_devops":
        parts = (repository or "").split("/")
        organization = parts[0] if parts else ""
        return f"https://dev.azure.com/{organization}".rstrip("/")
    raise ValueError(f"Unsupported Git provider: {provider}")


def server_domain(provider: str, value: str) -> str:
    """Return the user-facing Git server root for a domain or API URL."""
    raw = value.strip().rstrip("/")
    if "://" not in raw:
        raw = f"https://{raw}"
    parsed = urlparse(raw)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "Git server domain must be an HTTP(S) domain or root URL without credentials, query, or fragment."
        )

    host = parsed.hostname.lower()
    if provider == "github" and host == "api.github.com":
        return "https://github.com"
    if provider == "bitbucket_cloud" and host == "api.bitbucket.org":
        return "https://bitbucket.org"
    if provider == "azure_devops" and host.endswith(".visualstudio.com"):
        organization = host.split(".", 1)[0]
        return f"https://dev.azure.com/{organization}"

    suffixes = {
        "github": "/api/v3",
        "gitlab": "/api/v4",
        "bitbucket_cloud": "/2.0",
        "bitbucket_server": "/rest/api/1.0",
        "gitea": "/api/v1",
    }
    path = parsed.path.rstrip("/")
    suffix = suffixes.get(provider)
    if suffix and path.lower().endswith(suffix):
        path = path[: -len(suffix)].rstrip("/")
    return urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))


def api_base_from_domain(
    provider: str,
    domain: str,
    repository: str | None = None,
) -> str:
    """Derive the provider REST base from a Git server domain/root URL."""
    root = server_domain(provider, domain)
    parsed = urlparse(root)
    host = parsed.hostname.lower() if parsed.hostname else ""
    if provider == "github":
        return "https://api.github.com" if host == "github.com" else f"{root}/api/v3"
    if provider == "gitlab":
        return f"{root}/api/v4"
    if provider == "bitbucket_cloud":
        return "https://api.bitbucket.org/2.0"
    if provider == "bitbucket_server":
        return f"{root}/rest/api/1.0"
    if provider == "gitea":
        return f"{root}/api/v1"
    if provider == "azure_devops":
        path_parts = [part for part in parsed.path.split("/") if part]
        organization = path_parts[0] if path_parts else ""
        if not organization:
            organization = ((repository or "").split("/") or [""])[0]
        if not organization:
            raise ValueError(
                "Azure DevOps domain must include the organization, for example https://dev.azure.com/acme."
            )
        return f"https://dev.azure.com/{organization}"
    raise ValueError(f"Unsupported Git provider: {provider}")


def token_creation_url(
    provider: str,
    domain: str,
    repository: str | None = None,
) -> str:
    """Return the provider's browser page for creating a personal token."""
    root = server_domain(provider, domain)
    if provider == "github":
        return f"{root}/settings/tokens/new"
    if provider == "gitlab":
        return f"{root}/-/user_settings/personal_access_tokens"
    if provider == "bitbucket_cloud":
        return "https://id.atlassian.com/manage-profile/security/api-tokens"
    if provider == "bitbucket_server":
        return f"{root}/plugins/servlet/access-tokens/manage"
    if provider == "gitea":
        return f"{root}/user/settings/applications"
    if provider == "azure_devops":
        return (
            f"{api_base_from_domain(provider, root, repository)}/_usersSettings/tokens"
        )
    raise ValueError(f"Unsupported Git provider: {provider}")


def connection_host(base_url: str) -> str:
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("API base URL must be an absolute HTTP(S) URL.")
    return parsed.hostname.lower()


def server_host(provider: str, base_url: str) -> str:
    """Map a public API hostname back to the hostname used by Git remotes."""
    host = connection_host(base_url)
    if provider == "github" and host == "api.github.com":
        return "github.com"
    if provider == "bitbucket_cloud" and host == "api.bitbucket.org":
        return "bitbucket.org"
    return host


def connection_token(connection: GitServerConnection) -> str | None:
    value = os.environ.get(connection.token_env_var)
    if value:
        return value
    env_file = Path(settings.EVOFLUX_CONFIG_DIR) / ".env"
    if env_file.is_file():
        raw = dotenv_values(env_file).get(connection.token_env_var)
        if raw:
            return str(raw)
    return None


async def inspect_repository(
    workspace_id: str, workspace: str, name: str
) -> RepositoryTarget:
    workspace_path = Path(workspace).expanduser()
    if not workspace_path.is_dir():
        return RepositoryTarget(
            workspace_id=workspace_id,
            workspace=workspace,
            name=name,
            remote_url=None,
            host=None,
            repository=None,
            detected_provider=None,
            inspection_error=(
                "Repository folder is unavailable. Re-add it to Coding mode."
            ),
        )

    remotes_result = await run_git(workspace, "remote", timeout=5.0)
    if not remotes_result.ok:
        return RepositoryTarget(
            workspace_id=workspace_id,
            workspace=workspace,
            name=name,
            remote_url=None,
            host=None,
            repository=None,
            detected_provider=None,
            inspection_error="Repository folder is not a Git repository.",
        )

    remotes = [
        remote.strip()
        for remote in remotes_result.stdout.splitlines()
        if remote.strip()
    ]
    if not remotes:
        return RepositoryTarget(
            workspace_id=workspace_id,
            workspace=workspace,
            name=name,
            remote_url=None,
            host=None,
            repository=None,
            detected_provider=None,
            inspection_error=(
                "No Git remote is configured. Add a remote, then refresh reviews."
            ),
        )

    remote_name: str | None = "origin" if "origin" in remotes else None
    if remote_name is None:
        branch_result = await run_git(
            workspace,
            "symbolic-ref",
            "--quiet",
            "--short",
            "HEAD",
            timeout=5.0,
        )
        if branch_result.ok and branch_result.stdout.strip():
            tracking_result = await run_git(
                workspace,
                "config",
                "--get",
                f"branch.{branch_result.stdout.strip()}.remote",
                timeout=5.0,
            )
            tracking_remote = tracking_result.stdout.strip()
            if tracking_result.ok and tracking_remote in remotes:
                remote_name = tracking_remote
    if remote_name is None and len(remotes) == 1:
        remote_name = remotes[0]
    if remote_name is None and "upstream" in remotes:
        remote_name = "upstream"
    if remote_name is None:
        return RepositoryTarget(
            workspace_id=workspace_id,
            workspace=workspace,
            name=name,
            remote_url=None,
            host=None,
            repository=None,
            detected_provider=None,
            inspection_error=(
                "No origin remote is configured and no fallback remote could "
                "be selected. Set the branch tracking remote, then refresh reviews."
            ),
        )

    result = await run_git(
        workspace,
        "remote",
        "get-url",
        remote_name,
        timeout=5.0,
    )
    if not result.ok or not result.stdout.strip():
        return RepositoryTarget(
            workspace_id=workspace_id,
            workspace=workspace,
            name=name,
            remote_url=None,
            host=None,
            repository=None,
            detected_provider=None,
            inspection_error=(
                f"Git remote '{remote_name}' has no usable URL. "
                "Update the remote, then refresh reviews."
            ),
        )

    try:
        host, repository, remote_url = parse_remote_url(result.stdout.strip())
    except ValueError:
        return RepositoryTarget(
            workspace_id=workspace_id,
            workspace=workspace,
            name=name,
            remote_url=None,
            host=None,
            repository=None,
            detected_provider=None,
            inspection_error=(
                f"Git remote '{remote_name}' has an invalid URL. Update the remote, "
                "then refresh reviews."
            ),
            remote_name=remote_name,
        )
    return RepositoryTarget(
        workspace_id=workspace_id,
        workspace=workspace,
        name=name,
        remote_url=remote_url,
        host=host,
        repository=repository,
        detected_provider=infer_provider(host, repository),
        remote_name=remote_name,
    )


def resolve_connection(
    target: RepositoryTarget,
    connections: list[GitServerConnection],
) -> GitServerConnection | None:
    for connection in connections:
        if (
            connection.scope == "repository"
            and connection.workspace_id is not None
            and str(connection.workspace_id) == target.workspace_id
        ):
            return connection
    for connection in connections:
        if connection.scope == "server" and connection.host == target.host:
            return connection
    return None


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _branch_name(value: Any) -> str:
    text = str(value or "")
    for prefix in ("refs/heads/", "refs/"):
        if text.startswith(prefix):
            return text[len(prefix) :]
    return text


def _auth_headers(connection: GitServerConnection, token: str) -> dict[str, str]:
    if connection.provider == "github":
        return {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
    if connection.provider == "gitlab":
        return {"PRIVATE-TOKEN": token}
    if connection.provider == "bitbucket_cloud" and connection.username:
        credentials = f"{connection.username}:{token}".encode()
        encoded = base64.b64encode(credentials).decode()
        return {"Authorization": f"Basic {encoded}"}
    if connection.provider in {"bitbucket_cloud", "bitbucket_server"}:
        return {"Authorization": f"Bearer {token}"}
    if connection.provider == "gitea":
        return {"Authorization": f"token {token}"}
    if connection.provider == "azure_devops":
        credentials = f"{connection.username or ''}:{token}".encode()
        encoded = base64.b64encode(credentials).decode()
        return {"Authorization": f"Basic {encoded}"}
    raise ValueError(f"Unsupported Git provider: {connection.provider}")


def _require_secure_connection(connection: GitServerConnection) -> None:
    review_cfg = load_runtime_settings().code_reviews
    parsed_base = urlparse(connection.base_url)
    if not review_cfg.allow_insecure_connections and (
        parsed_base.scheme != "https" or not connection.verify_ssl
    ):
        raise GitServerApiError(
            "Insecure Git server connections are disabled in Git & reviews settings."
        )


async def _request_json(
    connection: GitServerConnection,
    token: str,
    path: str,
    *,
    params: dict[str, str | int] | None = None,
    method: str = "GET",
    json_body: dict[str, Any] | None = None,
    extra_headers: dict[str, str] | None = None,
) -> Any:
    review_cfg = load_runtime_settings().code_reviews
    _require_secure_connection(connection)
    url = f"{connection.base_url.rstrip('/')}/{path.lstrip('/')}"
    try:
        async with httpx.AsyncClient(
            verify=connection.verify_ssl,
            timeout=httpx.Timeout(review_cfg.request_timeout_seconds),
            follow_redirects=False,
        ) as client:
            headers = _auth_headers(connection, token)
            headers.update(extra_headers or {})
            response: httpx.Response | None = None
            max_attempts = (
                review_cfg.retry_attempts + 1
                if method.upper() in {"GET", "HEAD"}
                else 1
            )
            for attempt in range(max_attempts):
                try:
                    response = await client.request(
                        method,
                        url,
                        params=params,
                        json=json_body,
                        headers=headers,
                    )
                except (httpx.TimeoutException, httpx.TransportError):
                    if attempt + 1 >= max_attempts:
                        raise
                    await asyncio.sleep(
                        min(review_cfg.retry_backoff_seconds * (2**attempt), 30.0)
                    )
                    continue
                if response.status_code not in {408, 429, 500, 502, 503, 504}:
                    break
                if attempt + 1 >= max_attempts:
                    break
                retry_after = response.headers.get("retry-after", "").strip()
                try:
                    delay = float(retry_after) if retry_after else 0.0
                except ValueError:
                    delay = 0.0
                if delay <= 0:
                    delay = review_cfg.retry_backoff_seconds * (2**attempt)
                await asyncio.sleep(min(delay, 30.0))
            assert response is not None
    except httpx.TimeoutException as exc:
        raise GitServerApiError("The Git server timed out.") from exc
    except httpx.HTTPError as exc:
        raise GitServerApiError(f"Could not reach the Git server: {exc}") from exc
    if response.status_code >= 300:
        if 300 <= response.status_code < 400:
            detail = "The Git server returned an unexpected redirect."
        elif response.status_code in {401, 403}:
            detail = "The API key is invalid or lacks repository permissions."
        elif response.status_code == 429:
            detail = "The Git server rate limit was exceeded. Retry later."
        elif response.status_code == 404:
            detail = "Repository or code review not found through this connection."
        else:
            detail = f"Git server returned HTTP {response.status_code}."
        raise GitServerApiError(detail)
    if response.status_code == 204 or not response.content:
        return {}
    try:
        return response.json()
    except ValueError as exc:
        raise GitServerApiError("The Git server returned invalid JSON.") from exc


def _validated_review_image_url(
    connection: GitServerConnection,
    url: str,
) -> str:
    parsed = urlparse(url.strip())
    server = urlparse(server_domain(connection.provider, connection.base_url))
    is_attachment = (
        parsed.scheme == server.scheme
        and parsed.hostname == server.hostname
        and bool(_GITHUB_ATTACHMENT_PATH_RE.fullmatch(parsed.path))
    )
    is_rendered_image = (
        parsed.scheme == "https"
        and parsed.hostname in _GITHUB_RENDERED_IMAGE_HOSTS
        and bool(_GITHUB_RENDERED_IMAGE_PATH_RE.fullmatch(parsed.path))
    )
    if (
        connection.provider != "github"
        or parsed.username is not None
        or parsed.password is not None
        or (not is_attachment and not is_rendered_image)
    ):
        raise GitServerApiError("Unsupported code review image URL.")
    return urlunparse(parsed._replace(fragment=""))


def _validated_review_image_redirect_url(url: str) -> str:
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or (
            hostname not in _GITHUB_ATTACHMENT_REDIRECT_HOSTS
            and not _GITHUB_ATTACHMENT_S3_HOST_RE.fullmatch(hostname)
        )
    ):
        raise GitServerApiError("The Git server returned an unsafe image redirect.")
    return urlunparse(parsed._replace(fragment=""))


async def fetch_code_review_image(
    connection: GitServerConnection,
    url: str,
) -> ReviewImage | ReviewImageRedirect:
    """Fetch a private GitHub review attachment without exposing its token."""
    _require_secure_connection(connection)
    token = connection_token(connection)
    if not token:
        raise GitServerApiError("No API key is configured for this Git server.")
    image_url = _validated_review_image_url(connection, url)
    image_host = urlparse(image_url).hostname
    server = urlparse(server_domain(connection.provider, connection.base_url))
    headers: dict[str, str] = {}
    if image_host == server.hostname:
        headers.update(_auth_headers(connection, token))
        headers["Accept"] = "image/*"
    try:
        async with httpx.AsyncClient(
            verify=connection.verify_ssl,
            timeout=httpx.Timeout(
                load_runtime_settings().code_reviews.request_timeout_seconds
            ),
            follow_redirects=False,
        ) as client:
            async with client.stream("GET", image_url, headers=headers) as response:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise GitServerApiError(
                            "The Git server returned an empty image redirect."
                        )
                    return ReviewImageRedirect(
                        url=_validated_review_image_redirect_url(location)
                    )
                if response.status_code >= 400:
                    if response.status_code in {401, 403, 404}:
                        detail = "The code review image is unavailable through this connection."
                    else:
                        detail = f"The Git server returned HTTP {response.status_code}."
                    raise GitServerApiError(detail)
                media_type = (
                    response.headers.get("content-type", "").partition(";")[0].lower()
                )
                if not media_type.startswith("image/"):
                    raise GitServerApiError(
                        "The code review attachment is not an image."
                    )
                content_length = response.headers.get("content-length")
                if content_length:
                    try:
                        if int(content_length) > _MAX_REVIEW_IMAGE_BYTES:
                            raise GitServerApiError(
                                "The code review image is too large."
                            )
                    except ValueError:
                        pass
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > _MAX_REVIEW_IMAGE_BYTES:
                        raise GitServerApiError("The code review image is too large.")
                    chunks.append(chunk)
    except httpx.TimeoutException as exc:
        raise GitServerApiError(
            "The Git server timed out while loading the image."
        ) from exc
    except httpx.HTTPError as exc:
        raise GitServerApiError(f"Could not load the code review image: {exc}") from exc
    return ReviewImage(content=b"".join(chunks), media_type=media_type)


def _bounded_payload(value: Any, *, depth: int = 0) -> Any:
    """Keep API-backed tool context useful without flooding the model."""
    if depth >= 8:
        return "[nested data omitted]"
    if isinstance(value, str):
        return value if len(value) <= 12_000 else f"{value[:12_000]}\n[truncated]"
    if isinstance(value, list):
        bounded = [_bounded_payload(item, depth=depth + 1) for item in value[:100]]
        if len(value) > 100:
            bounded.append(f"[{len(value) - 100} more items omitted]")
        return bounded
    if isinstance(value, dict):
        return {
            str(key): _bounded_payload(item, depth=depth + 1)
            for key, item in value.items()
        }
    return value


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _person_name(value: Any) -> str | None:
    row = _dict(value)
    nested_user = _dict(row.get("user"))
    for candidate in (row, nested_user):
        name = (
            candidate.get("login")
            or candidate.get("username")
            or candidate.get("nickname")
            or candidate.get("display_name")
            or candidate.get("displayName")
            or candidate.get("uniqueName")
            or candidate.get("name")
        )
        if name:
            return str(name)
    return None


def _person_avatar_url(value: Any) -> str | None:
    """Extract a safe absolute avatar URL across supported Git providers."""
    row = _dict(value)
    nested_user = _dict(row.get("user"))
    for candidate in (row, nested_user):
        links = _dict(candidate.get("links") or candidate.get("_links"))
        avatar_link = _dict(links.get("avatar"))
        raw_url = (
            candidate.get("avatar_url")
            or candidate.get("avatarUrl")
            or candidate.get("imageUrl")
            or avatar_link.get("href")
        )
        if not raw_url:
            continue
        parsed = urlparse(str(raw_url).strip())
        if (
            parsed.scheme in {"http", "https"}
            and parsed.hostname
            and parsed.username is None
            and parsed.password is None
        ):
            return urlunparse(parsed._replace(fragment=""))
    return None


def _people(values: Any) -> list[str]:
    names: list[str] = []
    for value in _list(values):
        name = _person_name(value)
        if name and name not in names:
            names.append(name)
    return names


def _change_rows(changes: Any) -> list[dict[str, Any]]:
    if isinstance(changes, list):
        return [_dict(value) for value in changes if isinstance(value, dict)]
    payload = _dict(changes)
    for key in ("values", "value", "changeEntries"):
        rows = _list(payload.get(key))
        if rows:
            return [_dict(value) for value in rows if isinstance(value, dict)]
    return []


def _sum_change_metric(rows: list[dict[str, Any]], *keys: str) -> int | None:
    values: list[int] = []
    for row in rows:
        for key in keys:
            number = _optional_int(row.get(key))
            if number is not None:
                values.append(number)
                break
    return sum(values) if values else None


def _review_summary(review: Any, changes: Any) -> dict[str, Any]:
    row = _dict(review)
    source = _dict(row.get("source"))
    destination = _dict(row.get("destination"))
    head = _dict(row.get("head"))
    base = _dict(row.get("base"))
    from_ref = _dict(row.get("fromRef"))
    to_ref = _dict(row.get("toRef"))
    author = _person_name(row.get("user") or row.get("author") or row.get("createdBy"))
    description = row.get("body_html") or row.get("body") or row.get("description")
    if not description:
        description = _dict(row.get("summary")).get("raw")
    reviewers = _people(
        row.get("requested_reviewers")
        or row.get("reviewers")
        or row.get("participants")
    )
    assignee_values = row.get("assignees")
    if not _list(assignee_values) and row.get("assignee"):
        assignee_values = [row.get("assignee")]
    change_rows = _change_rows(changes)
    changed_files = _optional_int(row.get("changed_files") or row.get("changes_count"))
    if changed_files is None and changes is not None:
        changed_files = len(change_rows)
    additions = _optional_int(row.get("additions"))
    if additions is None:
        additions = _sum_change_metric(change_rows, "additions", "lines_added")
    deletions = _optional_int(row.get("deletions"))
    if deletions is None:
        deletions = _sum_change_metric(change_rows, "deletions", "lines_removed")

    return {
        "description": str(description).strip() if description else None,
        "author": author,
        "created_at": str(
            row.get("created_at")
            or row.get("created_on")
            or row.get("createdDate")
            or row.get("creationDate")
            or ""
        )
        or None,
        "updated_at": str(
            row.get("updated_at")
            or row.get("updated_on")
            or row.get("updatedDate")
            or row.get("lastUpdatedDate")
            or ""
        )
        or None,
        "source_branch": _branch_name(
            head.get("ref")
            or row.get("source_branch")
            or _dict(source.get("branch")).get("name")
            or from_ref.get("displayId")
            or row.get("sourceRefName")
        )
        or None,
        "target_branch": _branch_name(
            base.get("ref")
            or row.get("target_branch")
            or _dict(destination.get("branch")).get("name")
            or to_ref.get("displayId")
            or row.get("targetRefName")
        )
        or None,
        "reviewers": reviewers,
        "assignees": _people(assignee_values),
        "commit_count": _optional_int(
            row.get("commits") or row.get("commits_count") or row.get("commit_count")
        ),
        "changed_files": changed_files,
        "additions": additions,
        "deletions": deletions,
    }


def _github_items(payload: Any) -> list[ReviewItem]:
    items: list[ReviewItem] = []
    for raw in _list(payload):
        row = _dict(raw)
        user = _dict(row.get("user"))
        head = _dict(row.get("head"))
        base = _dict(row.get("base"))
        items.append(
            ReviewItem(
                number=int(row.get("number") or 0),
                title=str(row.get("title") or "Untitled pull request"),
                state=str(row.get("state") or "open").lower(),
                draft=bool(row.get("draft")),
                author=str(user.get("login") or "") or None,
                author_avatar_url=_person_avatar_url(user),
                source_branch=str(head.get("ref") or ""),
                target_branch=str(base.get("ref") or ""),
                updated_at=str(row.get("updated_at") or ""),
                web_url=str(row.get("html_url") or ""),
                labels=[
                    str(_dict(label).get("name"))
                    for label in _list(row.get("labels"))
                    if _dict(label).get("name")
                ],
                comment_count=int(row.get("comments") or 0),
            )
        )
    return items


def _gitlab_items(payload: Any) -> list[ReviewItem]:
    items: list[ReviewItem] = []
    for raw in _list(payload):
        row = _dict(raw)
        author = _dict(row.get("author"))
        pipeline = _dict(row.get("head_pipeline"))
        items.append(
            ReviewItem(
                number=int(row.get("iid") or 0),
                title=str(row.get("title") or "Untitled merge request"),
                state=str(row.get("state") or "opened").lower(),
                draft=bool(row.get("draft") or row.get("work_in_progress")),
                author=str(author.get("username") or author.get("name") or "") or None,
                author_avatar_url=_person_avatar_url(author),
                source_branch=str(row.get("source_branch") or ""),
                target_branch=str(row.get("target_branch") or ""),
                updated_at=str(row.get("updated_at") or ""),
                web_url=str(row.get("web_url") or ""),
                labels=[str(label) for label in _list(row.get("labels"))],
                review_status=(str(row.get("detailed_merge_status") or "") or None),
                pipeline_status=str(pipeline.get("status") or "") or None,
                comment_count=int(row.get("user_notes_count") or 0),
            )
        )
    return items


def _bitbucket_cloud_items(payload: Any) -> list[ReviewItem]:
    items: list[ReviewItem] = []
    for raw in _list(_dict(payload).get("values")):
        row = _dict(raw)
        author = _dict(row.get("author"))
        source = _dict(_dict(row.get("source")).get("branch"))
        target = _dict(_dict(row.get("destination")).get("branch"))
        links = _dict(row.get("links"))
        items.append(
            ReviewItem(
                number=int(row.get("id") or 0),
                title=str(row.get("title") or "Untitled pull request"),
                state=str(row.get("state") or "OPEN").lower(),
                draft=bool(row.get("draft")),
                author=str(author.get("display_name") or author.get("nickname") or "")
                or None,
                author_avatar_url=_person_avatar_url(author),
                source_branch=str(source.get("name") or ""),
                target_branch=str(target.get("name") or ""),
                updated_at=str(row.get("updated_on") or ""),
                web_url=str(_dict(links.get("html")).get("href") or ""),
                comment_count=int(row.get("comment_count") or 0),
            )
        )
    return items


def _bitbucket_server_items(payload: Any) -> list[ReviewItem]:
    items: list[ReviewItem] = []
    for raw in _list(_dict(payload).get("values")):
        row = _dict(raw)
        author = _dict(_dict(row.get("author")).get("user"))
        source = _dict(row.get("fromRef"))
        target = _dict(row.get("toRef"))
        links = _dict(row.get("links"))
        self_links = _list(links.get("self"))
        web_url = str(_dict(self_links[0]).get("href") or "") if self_links else ""
        updated = row.get("updatedDate")
        items.append(
            ReviewItem(
                number=int(row.get("id") or 0),
                title=str(row.get("title") or "Untitled pull request"),
                state=str(row.get("state") or "OPEN").lower(),
                draft=bool(row.get("draft")),
                author=str(author.get("displayName") or author.get("name") or "")
                or None,
                author_avatar_url=_person_avatar_url(author),
                source_branch=_branch_name(source.get("displayId")),
                target_branch=_branch_name(target.get("displayId")),
                updated_at=str(updated or ""),
                web_url=web_url,
                review_status="approved" if row.get("approved") else None,
            )
        )
    return items


def _gitea_items(payload: Any) -> list[ReviewItem]:
    items: list[ReviewItem] = []
    for raw in _list(payload):
        row = _dict(raw)
        user = _dict(row.get("user"))
        head = _dict(row.get("head"))
        base = _dict(row.get("base"))
        items.append(
            ReviewItem(
                number=int(row.get("number") or 0),
                title=str(row.get("title") or "Untitled pull request"),
                state=str(row.get("state") or "open").lower(),
                draft=bool(row.get("draft")),
                author=str(user.get("login") or user.get("full_name") or "") or None,
                author_avatar_url=_person_avatar_url(user),
                source_branch=str(head.get("ref") or ""),
                target_branch=str(base.get("ref") or ""),
                updated_at=str(row.get("updated_at") or ""),
                web_url=str(row.get("html_url") or ""),
                labels=[
                    str(_dict(label).get("name"))
                    for label in _list(row.get("labels"))
                    if _dict(label).get("name")
                ],
                comment_count=int(row.get("comments") or 0),
            )
        )
    return items


def _azure_items(payload: Any) -> list[ReviewItem]:
    items: list[ReviewItem] = []
    for raw in _list(_dict(payload).get("value")):
        row = _dict(raw)
        author = _dict(row.get("createdBy"))
        links = _dict(row.get("_links"))
        web_url = str(_dict(links.get("web")).get("href") or "")
        reviewers = [_dict(value) for value in _list(row.get("reviewers"))]
        approved = any(int(value.get("vote") or 0) >= 10 for value in reviewers)
        items.append(
            ReviewItem(
                number=int(row.get("pullRequestId") or 0),
                title=str(row.get("title") or "Untitled pull request"),
                state=str(row.get("status") or "active").lower(),
                draft=bool(row.get("isDraft")),
                author=str(author.get("displayName") or "") or None,
                author_avatar_url=_person_avatar_url(author),
                source_branch=_branch_name(row.get("sourceRefName")),
                target_branch=_branch_name(row.get("targetRefName")),
                updated_at=str(row.get("closedDate") or row.get("creationDate") or ""),
                web_url=web_url,
                labels=[
                    str(_dict(label).get("name"))
                    for label in _list(row.get("labels"))
                    if _dict(label).get("name")
                ],
                review_status="approved" if approved else None,
            )
        )
    return items


def _bitbucket_server_coordinates(repository: str) -> tuple[str, str]:
    parts = repository.strip("/").split("/")
    if parts and parts[0].lower() == "scm":
        parts = parts[1:]
    if len(parts) < 2:
        raise GitServerApiError(
            "Bitbucket Data Center remote must contain a project and repository."
        )
    return parts[-2], parts[-1]


def _azure_coordinates(repository: str) -> tuple[str, str]:
    parts = repository.strip("/").split("/")
    if "_git" not in parts:
        raise GitServerApiError(
            "Azure DevOps remote must contain a project/_git/repository path."
        )
    git_index = parts.index("_git")
    if git_index < 1 or git_index + 1 >= len(parts):
        raise GitServerApiError("Could not determine the Azure DevOps project.")
    return parts[git_index - 1], parts[git_index + 1]


def _comment_row(
    provider: str,
    raw: Any,
    *,
    kind: str = "conversation",
    thread_id: Any = None,
    resolved: bool | None = None,
) -> dict[str, Any]:
    row = _dict(raw)
    author = _dict(row.get("user") or row.get("author") or row.get("createdBy"))
    content = _dict(row.get("content"))
    inline = _dict(row.get("inline"))
    anchor = _dict(row.get("anchor"))
    thread_context = _dict(row.get("threadContext"))
    pull_context = _dict(row.get("pullRequestThreadContext"))
    parent = _dict(row.get("parent"))
    raw_id = row.get("id") or row.get("commentId") or row.get("noteable_id")
    parent_id = (
        row.get("in_reply_to_id") or parent.get("id") or row.get("parentCommentId")
    )
    path = (
        row.get("path")
        or inline.get("path")
        or anchor.get("path")
        or pull_context.get("filePath")
    )
    line = (
        row.get("line")
        or row.get("original_line")
        or inline.get("to")
        or inline.get("from")
        or _dict(thread_context.get("rightFileStart")).get("line")
        or _dict(thread_context.get("leftFileStart")).get("line")
        or anchor.get("line")
    )
    side = row.get("side")
    if not side and thread_context:
        side = "RIGHT" if thread_context.get("rightFileStart") else "LEFT"
    body = (
        row.get("body_html")
        or row.get("body")
        or row.get("body_text")
        or row.get("text")
        or content.get("raw")
        or row.get("content")
        or ""
    )
    if isinstance(body, dict):
        body = body.get("raw") or body.get("text") or ""
    stable_thread = str(
        thread_id
        or row.get("discussion_id")
        or row.get("in_reply_to_id")
        or raw_id
        or ""
    )
    stable_id = f"{provider}:{kind}:{raw_id or stable_thread}"
    return {
        "stable_id": stable_id,
        "id": str(raw_id or ""),
        "thread_id": stable_thread,
        "parent_id": str(parent_id) if parent_id is not None else None,
        "kind": "inline" if path else kind,
        "body": str(body),
        "author": str(
            author.get("login")
            or author.get("username")
            or author.get("nickname")
            or author.get("display_name")
            or author.get("displayName")
            or author.get("name")
            or ""
        )
        or None,
        "created_at": str(
            row.get("created_at")
            or row.get("created_on")
            or row.get("createdDate")
            or row.get("publishedDate")
            or ""
        ),
        "updated_at": str(
            row.get("updated_at")
            or row.get("updated_on")
            or row.get("updatedDate")
            or row.get("lastUpdatedDate")
            or ""
        ),
        "resolved": resolved,
        "path": str(path) if path else None,
        "line": int(line) if isinstance(line, int) else None,
        "side": str(side) if side else None,
        "commit_id": str(
            row.get("commit_id")
            or row.get("original_commit_id")
            or anchor.get("fromHash")
            or pull_context.get("changeTrackingId")
            or ""
        )
        or None,
    }


def _normalize_comments(provider: str, payload: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if provider == "github":
        grouped = _dict(payload)
        for raw in _list(grouped.get("conversation")):
            rows.append(_comment_row(provider, raw))
        for raw in _list(grouped.get("inline")):
            rows.append(_comment_row(provider, raw, kind="inline"))
    elif provider == "gitlab":
        for discussion in _list(payload):
            discussion_row = _dict(discussion)
            thread_id = discussion_row.get("id")
            for note in _list(discussion_row.get("notes")):
                note_row = _dict(note)
                position = _dict(note_row.get("position"))
                normalized = _comment_row(
                    provider,
                    {
                        **note_row,
                        "path": position.get("new_path") or position.get("old_path"),
                        "line": position.get("new_line") or position.get("old_line"),
                        "side": "RIGHT" if position.get("new_line") else "LEFT",
                        "commit_id": position.get("head_sha"),
                    },
                    thread_id=thread_id,
                    resolved=(
                        bool(note_row.get("resolved"))
                        if note_row.get("resolvable")
                        else None
                    ),
                )
                rows.append(normalized)
    elif provider == "bitbucket_cloud":
        for raw in _list(_dict(payload).get("values")):
            row = _dict(raw)
            rows.append(
                _comment_row(
                    provider,
                    row,
                    thread_id=_dict(row.get("parent")).get("id") or row.get("id"),
                    resolved=(bool(row.get("resolved")) if "resolved" in row else None),
                )
            )
    elif provider == "bitbucket_server":
        for activity in _list(_dict(payload).get("values")):
            comment = _dict(_dict(activity).get("comment"))
            if comment:
                rows.append(
                    _comment_row(
                        provider,
                        comment,
                        thread_id=_dict(comment.get("parent")).get("id")
                        or comment.get("id"),
                        resolved=(
                            str(comment.get("state") or "").upper() == "RESOLVED"
                            if "state" in comment
                            else None
                        ),
                    )
                )
    elif provider == "gitea":
        rows = [_comment_row(provider, raw) for raw in _list(payload)]
    elif provider == "azure_devops":
        for thread in _list(_dict(payload).get("value")):
            thread_row = _dict(thread)
            status = str(thread_row.get("status") or "").lower()
            resolved = status in {"fixed", "closed", "wontfix", "bydesign"}
            for comment in _list(thread_row.get("comments")):
                rows.append(
                    _comment_row(
                        provider,
                        {
                            **_dict(comment),
                            "threadContext": thread_row.get("threadContext"),
                            "pullRequestThreadContext": thread_row.get(
                                "pullRequestThreadContext"
                            ),
                        },
                        thread_id=thread_row.get("id"),
                        resolved=resolved,
                    )
                )
    capabilities = provider_capabilities(provider)
    for row in rows:
        row["can_reply"] = capabilities.get("reply_thread", False) and not (
            provider == "github" and row["kind"] != "inline"
        )
        row["can_resolve"] = capabilities.get("resolve_thread", False)
    return rows


def _normalize_approvals(provider: str, review: Any) -> list[dict[str, Any]]:
    row = _dict(review)
    if provider == "azure_devops":
        candidates = _list(row.get("reviewers"))
    elif provider in {"bitbucket_cloud", "bitbucket_server"}:
        candidates = _list(row.get("participants") or row.get("reviewers"))
    elif provider == "gitlab":
        candidates = _list(_dict(row.get("approvals") or row).get("approved_by"))
    else:
        candidates = _list(row.get("reviews"))
    approvals: list[dict[str, Any]] = []
    for raw in candidates:
        candidate = _dict(raw)
        user = _dict(candidate.get("user") or candidate)
        vote = int(candidate.get("vote") or 0)
        state = str(candidate.get("state") or candidate.get("status") or "")
        approved = bool(
            candidate.get("approved") or vote >= 10 or state.upper() == "APPROVED"
        )
        approvals.append(
            {
                "id": str(
                    user.get("id")
                    or user.get("uuid")
                    or user.get("accountId")
                    or user.get("uniqueName")
                    or ""
                ),
                "author": str(
                    user.get("login")
                    or user.get("username")
                    or user.get("nickname")
                    or user.get("display_name")
                    or user.get("displayName")
                    or user.get("name")
                    or ""
                )
                or None,
                "state": "approved" if approved else state.lower() or "pending",
            }
        )
    return approvals


async def list_repository_reviews(
    target: RepositoryTarget,
    connection: GitServerConnection,
) -> RepositoryReviews:
    max_pages = load_runtime_settings().code_reviews.max_pages_per_repository
    token = connection_token(connection)
    if not token:
        return RepositoryReviews(
            target=target,
            connection_id=str(connection.id),
            provider=connection.provider,
            error="The connection has no API key.",
        )
    repository = target.repository
    if not repository:
        return RepositoryReviews(
            target=target,
            connection_id=str(connection.id),
            provider=connection.provider,
            error=target.inspection_error or "No Git remote is configured.",
        )
    try:
        if connection.provider == "github":
            items = []
            for page in range(1, max_pages + 1):
                payload = await _request_json(
                    connection,
                    token,
                    f"repos/{quote(repository, safe='/')}/pulls",
                    params={
                        "state": "open",
                        "per_page": 100,
                        "page": page,
                        "sort": "updated",
                        "direction": "desc",
                    },
                )
                page_items = _github_items(payload)
                items.extend(page_items)
                if len(page_items) < 100:
                    break
        elif connection.provider == "gitlab":
            items = []
            for page in range(1, max_pages + 1):
                payload = await _request_json(
                    connection,
                    token,
                    f"projects/{quote(repository, safe='')}/merge_requests",
                    params={
                        "state": "opened",
                        "per_page": 100,
                        "page": page,
                        "order_by": "updated_at",
                        "sort": "desc",
                        "scope": "all",
                    },
                )
                page_items = _gitlab_items(payload)
                items.extend(page_items)
                if len(page_items) < 100:
                    break
        elif connection.provider == "bitbucket_cloud":
            items = []
            for page in range(1, max_pages + 1):
                payload = await _request_json(
                    connection,
                    token,
                    f"repositories/{quote(repository, safe='/')}/pullrequests",
                    params={"state": "OPEN", "pagelen": 50, "page": page},
                )
                page_items = _bitbucket_cloud_items(payload)
                items.extend(page_items)
                if not _dict(payload).get("next") or len(page_items) < 50:
                    break
        elif connection.provider == "bitbucket_server":
            project, repo = _bitbucket_server_coordinates(repository)
            items = []
            start = 0
            for _page in range(max_pages):
                payload = await _request_json(
                    connection,
                    token,
                    f"projects/{quote(project)}/repos/{quote(repo)}/pull-requests",
                    params={"state": "OPEN", "limit": 100, "start": start},
                )
                page_items = _bitbucket_server_items(payload)
                items.extend(page_items)
                page_data = _dict(payload)
                if page_data.get("isLastPage", True) or len(page_items) < 100:
                    break
                start = int(page_data.get("nextPageStart") or start + 100)
        elif connection.provider == "gitea":
            items = []
            for page in range(1, max_pages + 1):
                payload = await _request_json(
                    connection,
                    token,
                    f"repos/{quote(repository, safe='/')}/pulls",
                    params={"state": "open", "limit": 50, "page": page},
                )
                page_items = _gitea_items(payload)
                items.extend(page_items)
                if len(page_items) < 50:
                    break
        elif connection.provider == "azure_devops":
            project, repo = _azure_coordinates(repository)
            items = []
            for page in range(max_pages):
                payload = await _request_json(
                    connection,
                    token,
                    (
                        f"{quote(project)}/_apis/git/repositories/{quote(repo)}"
                        "/pullrequests"
                    ),
                    params={
                        "searchCriteria.status": "active",
                        "$top": 100,
                        "$skip": page * 100,
                        "api-version": "7.1",
                    },
                )
                page_items = _azure_items(payload)
                items.extend(page_items)
                if len(page_items) < 100:
                    break
        else:
            raise GitServerApiError(f"Provider {connection.provider} is not supported.")
    except GitServerApiError as exc:
        return RepositoryReviews(
            target=target,
            connection_id=str(connection.id),
            provider=connection.provider,
            error=str(exc),
        )
    return RepositoryReviews(
        target=target,
        connection_id=str(connection.id),
        provider=connection.provider,
        items=items,
    )


async def get_repository_review_context(
    target: RepositoryTarget,
    connection: GitServerConnection,
    number: int,
    *,
    include_changes: bool = True,
    include_comments: bool = True,
) -> dict[str, Any]:
    """Fetch review metadata, changes, and comments with the saved API key."""
    token = connection_token(connection)
    if not token:
        raise GitServerApiError("The connection has no API key.")
    repository = target.repository
    if not repository:
        raise GitServerApiError(
            target.inspection_error or "No Git remote is configured."
        )

    changes: Any = []
    comments: Any = []
    approvals_payload: Any = None
    provider = connection.provider
    if provider == "github":
        root = f"repos/{quote(repository, safe='/')}"
        review = await _request_json(
            connection,
            token,
            f"{root}/pulls/{number}",
            extra_headers={"Accept": "application/vnd.github.full+json"},
        )
        if include_changes:
            changes = await _request_json(
                connection,
                token,
                f"{root}/pulls/{number}/files",
                params={"per_page": 100},
            )
        if include_comments:
            conversation, inline, approvals_payload = await asyncio.gather(
                _request_json(
                    connection,
                    token,
                    f"{root}/issues/{number}/comments",
                    params={"per_page": 100},
                    extra_headers={"Accept": "application/vnd.github.full+json"},
                ),
                _request_json(
                    connection,
                    token,
                    f"{root}/pulls/{number}/comments",
                    params={"per_page": 100},
                    extra_headers={"Accept": "application/vnd.github.full+json"},
                ),
                _request_json(
                    connection,
                    token,
                    f"{root}/pulls/{number}/reviews",
                    params={"per_page": 100},
                ),
            )
            comments = {"conversation": conversation, "inline": inline}
    elif provider == "gitlab":
        root = f"projects/{quote(repository, safe='')}/merge_requests/{number}"
        review = await _request_json(connection, token, root)
        if include_changes:
            changes = await _request_json(
                connection,
                token,
                f"{root}/diffs",
                params={"per_page": 100},
            )
        if include_comments:
            comments, approvals_payload = await asyncio.gather(
                _request_json(
                    connection,
                    token,
                    f"{root}/discussions",
                    params={"per_page": 100},
                ),
                _request_json(connection, token, f"{root}/approvals"),
            )
    elif provider == "bitbucket_cloud":
        root = f"repositories/{quote(repository, safe='/')}/pullrequests/{number}"
        review = await _request_json(connection, token, root)
        if include_changes:
            changes = await _request_json(
                connection,
                token,
                f"{root}/diffstat",
                params={"pagelen": 100},
            )
        if include_comments:
            comments = await _request_json(
                connection,
                token,
                f"{root}/comments",
                params={"pagelen": 100},
            )
    elif provider == "bitbucket_server":
        project, repo = _bitbucket_server_coordinates(repository)
        root = f"projects/{quote(project)}/repos/{quote(repo)}/pull-requests/{number}"
        review = await _request_json(connection, token, root)
        if include_changes:
            changes = await _request_json(
                connection,
                token,
                f"{root}/changes",
                params={"limit": 100},
            )
        if include_comments:
            comments = await _request_json(
                connection,
                token,
                f"{root}/activities",
                params={"limit": 100},
            )
    elif provider == "gitea":
        root = f"repos/{quote(repository, safe='/')}"
        review = await _request_json(connection, token, f"{root}/pulls/{number}")
        if include_changes:
            changes = await _request_json(
                connection,
                token,
                f"{root}/pulls/{number}/files",
                params={"limit": 100},
            )
        if include_comments:
            comments = await _request_json(
                connection,
                token,
                f"{root}/issues/{number}/comments",
                params={"limit": 100},
            )
    elif provider == "azure_devops":
        project, repo = _azure_coordinates(repository)
        root = (
            f"{quote(project)}/_apis/git/repositories/{quote(repo)}"
            f"/pullrequests/{number}"
        )
        params: dict[str, str | int] = {"api-version": "7.1"}
        review = await _request_json(connection, token, root, params=params)
        if include_changes:
            iterations = await _request_json(
                connection,
                token,
                f"{root}/iterations",
                params=params,
            )
            iteration_rows = _list(_dict(iterations).get("value"))
            if iteration_rows:
                iteration_id = int(_dict(iteration_rows[-1]).get("id") or 1)
                changes = await _request_json(
                    connection,
                    token,
                    f"{root}/iterations/{iteration_id}/changes",
                    params={"$top": 200, "api-version": "7.1"},
                )
        if include_comments:
            comments = await _request_json(
                connection,
                token,
                f"{root}/threads",
                params=params,
            )
    else:
        raise GitServerApiError(f"Provider {provider} is not supported.")

    review_row = _dict(review)
    if approvals_payload is not None:
        if provider == "github":
            review_row["reviews"] = approvals_payload
        elif provider == "gitlab":
            review_row["approvals"] = approvals_payload
    try:
        checks = await get_repository_review_checks(
            target,
            connection,
            number,
            review=review_row,
        )
    except GitServerApiError as exc:
        checks = {"summary": "unavailable", "items": [], "error": str(exc)}
    normalized_comments = (
        _normalize_comments(provider, comments) if include_comments else None
    )
    state = str(
        review_row.get("state")
        or review_row.get("status")
        or review_row.get("merge_status")
        or ""
    ).lower()
    mergeable_raw = review_row.get("mergeable")
    if mergeable_raw is None:
        mergeable_raw = review_row.get("merge_status") or review_row.get(
            "detailed_merge_status"
        )
    return {
        "provider": provider,
        "repository": repository,
        "number": number,
        "summary": _review_summary(review_row, changes if include_changes else None),
        "review": _bounded_payload(review_row),
        "changes": _bounded_payload(changes) if include_changes else None,
        "comments": _bounded_payload(normalized_comments),
        "approvals": _normalize_approvals(provider, review_row),
        "checks": _bounded_payload(checks),
        "state": state,
        "draft": bool(
            review_row.get("draft")
            or review_row.get("work_in_progress")
            or review_row.get("isDraft")
        ),
        "mergeability": {
            "mergeable": mergeable_raw,
            "conflicts": bool(
                review_row.get("hasConflicts")
                or str(mergeable_raw).lower()
                in {"cannot_be_merged", "conflicts", "dirty", "false"}
            ),
            "merged": bool(
                review_row.get("merged")
                or review_row.get("merged_at")
                or state in {"merged", "completed", "fulfilled"}
            ),
        },
        "permissions": {
            "connection_scope": connection.scope,
            "credential_configured": True,
        },
        "capabilities": provider_capabilities(provider),
    }


async def get_repository_review_checks(
    target: RepositoryTarget,
    connection: GitServerConnection,
    number: int,
    *,
    review: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return provider checks/pipelines normalized to one small contract."""
    require_capability(connection.provider, "checks")
    token = connection_token(connection)
    repository = target.repository
    if not token or not repository:
        raise GitServerApiError("The connection or repository is not configured.")
    provider = connection.provider
    review = review or {}
    if provider == "github":
        sha = str(_dict(review.get("head")).get("sha") or "")
        if not sha:
            root = f"repos/{quote(repository, safe='/')}/pulls/{number}"
            review = _dict(await _request_json(connection, token, root))
            sha = str(_dict(review.get("head")).get("sha") or "")
        payload = await _request_json(
            connection,
            token,
            f"repos/{quote(repository, safe='/')}/commits/{quote(sha)}/check-runs",
            params={"per_page": 100},
        )
        candidates = _list(_dict(payload).get("check_runs"))
    elif provider == "gitlab":
        root = f"projects/{quote(repository, safe='')}/merge_requests/{number}"
        payload = await _request_json(
            connection, token, f"{root}/pipelines", params={"per_page": 100}
        )
        candidates = _list(payload)
    elif provider == "bitbucket_cloud":
        sha = str(_dict(_dict(review.get("source")).get("commit")).get("hash") or "")
        if not sha:
            root = f"repositories/{quote(repository, safe='/')}/pullrequests/{number}"
            review = _dict(await _request_json(connection, token, root))
            sha = str(
                _dict(_dict(review.get("source")).get("commit")).get("hash") or ""
            )
        payload = await _request_json(
            connection,
            token,
            f"repositories/{quote(repository, safe='/')}/commit/{quote(sha)}/statuses/build",
            params={"pagelen": 100},
        )
        candidates = _list(_dict(payload).get("values"))
    elif provider == "gitea":
        sha = str(_dict(review.get("head")).get("sha") or "")
        if not sha:
            root = f"repos/{quote(repository, safe='/')}/pulls/{number}"
            review = _dict(await _request_json(connection, token, root))
            sha = str(_dict(review.get("head")).get("sha") or "")
        payload = await _request_json(
            connection,
            token,
            f"repos/{quote(repository, safe='/')}/commits/{quote(sha)}/status",
        )
        candidates = _list(_dict(payload).get("statuses"))
    elif provider == "azure_devops":
        project, repo = _azure_coordinates(repository)
        root = (
            f"{quote(project)}/_apis/git/repositories/{quote(repo)}"
            f"/pullrequests/{number}/statuses"
        )
        payload = await _request_json(
            connection, token, root, params={"api-version": "7.1"}
        )
        candidates = _list(_dict(payload).get("value"))
    else:
        require_capability(provider, "checks")
        candidates = []
    checks: list[dict[str, Any]] = []
    for raw in candidates:
        row = _dict(raw)
        links = _dict(row.get("links") or row.get("_links"))
        checks.append(
            {
                "id": str(row.get("id") or row.get("key") or row.get("context") or ""),
                "name": str(
                    row.get("name")
                    or row.get("key")
                    or row.get("context")
                    or row.get("description")
                    or "Check"
                ),
                "status": str(
                    row.get("conclusion") or row.get("state") or row.get("status") or ""
                ).lower(),
                "url": str(
                    row.get("details_url")
                    or row.get("url")
                    or row.get("target_url")
                    or _dict(links.get("web")).get("href")
                    or ""
                ),
            }
        )
    failing = {
        "failure",
        "failed",
        "error",
        "stopped",
        "cancelled",
        "canceled",
    }
    pending = {"queued", "pending", "in_progress", "running", "notset"}
    states = {str(check["status"]) for check in checks}
    summary = (
        "failure"
        if states & failing
        else "pending"
        if states & pending
        else "success"
        if checks
        else "unknown"
    )
    return {"summary": summary, "items": checks}


def _review_root(provider: str, repository: str, number: int) -> str:
    if provider == "github":
        return f"repos/{quote(repository, safe='/')}/pulls/{number}"
    if provider == "gitlab":
        return f"projects/{quote(repository, safe='')}/merge_requests/{number}"
    if provider == "bitbucket_cloud":
        return f"repositories/{quote(repository, safe='/')}/pullrequests/{number}"
    if provider == "bitbucket_server":
        project, repo = _bitbucket_server_coordinates(repository)
        return f"projects/{quote(project)}/repos/{quote(repo)}/pull-requests/{number}"
    if provider == "gitea":
        return f"repos/{quote(repository, safe='/')}/pulls/{number}"
    if provider == "azure_devops":
        project, repo = _azure_coordinates(repository)
        return (
            f"{quote(project)}/_apis/git/repositories/{quote(repo)}"
            f"/pullrequests/{number}"
        )
    raise GitServerApiError(f"Provider {provider} is not supported.")


async def add_code_review_comment(
    target: RepositoryTarget,
    connection: GitServerConnection,
    number: int,
    body: str,
    *,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    require_review_mutations_enabled()
    require_capability(connection.provider, "comment")
    token = connection_token(connection)
    repository = target.repository
    if not token or not repository:
        raise GitServerApiError("The connection or repository is not configured.")
    provider = connection.provider
    root = _review_root(provider, repository, number)
    if provider in {"github", "gitea"}:
        root = f"repos/{quote(repository, safe='/')}/issues/{number}/comments"
        payload = {"body": body}
    elif provider == "gitlab":
        root = f"{root}/notes"
        payload = {"body": body}
    elif provider == "bitbucket_cloud":
        root = f"{root}/comments"
        payload = {"content": {"raw": body}}
    elif provider == "bitbucket_server":
        root = f"{root}/comments"
        payload = {"text": body}
    else:
        root = f"{root}/threads"
        payload = {
            "comments": [{"parentCommentId": 0, "content": body, "commentType": 1}],
            "status": "active",
        }
    result = await _request_json(
        connection,
        token,
        root,
        params={"api-version": "7.1"} if provider == "azure_devops" else None,
        method="POST",
        json_body=payload,
        extra_headers={"Idempotency-Key": idempotency_key} if idempotency_key else None,
    )
    return {
        "action": "comment",
        "provider": provider,
        "result": _bounded_payload(result),
    }


async def add_code_review_inline_comment(
    target: RepositoryTarget,
    connection: GitServerConnection,
    number: int,
    body: str,
    *,
    path: str,
    line: int,
    side: str = "RIGHT",
    commit_id: str | None = None,
    base_commit_id: str | None = None,
    start_commit_id: str | None = None,
) -> dict[str, Any]:
    require_review_mutations_enabled()
    require_capability(connection.provider, "inline_comment")
    token = connection_token(connection)
    repository = target.repository
    if not token or not repository:
        raise GitServerApiError("The connection or repository is not configured.")
    provider = connection.provider
    root = _review_root(provider, repository, number)
    params: dict[str, str | int] | None = None
    if provider == "github":
        endpoint = f"{root}/comments"
        payload = {
            "body": body,
            "path": path,
            "line": line,
            "side": side.upper(),
            "commit_id": commit_id,
        }
    elif provider == "gitlab":
        if not all((commit_id, base_commit_id, start_commit_id)):
            raise GitServerApiError(
                "GitLab inline comments require head, base, and start commit IDs "
                "from get_code_review."
            )
        endpoint = f"{root}/discussions"
        payload = {
            "body": body,
            "position": {
                "position_type": "text",
                "new_path": path,
                "new_line": line,
                "head_sha": commit_id,
                "base_sha": base_commit_id,
                "start_sha": start_commit_id,
            },
        }
    elif provider == "bitbucket_cloud":
        endpoint = f"{root}/comments"
        payload = {"content": {"raw": body}, "inline": {"path": path, "to": line}}
    elif provider == "bitbucket_server":
        endpoint = f"{root}/comments"
        payload = {
            "text": body,
            "anchor": {
                "path": path,
                "line": line,
                "lineType": "ADDED" if side.upper() == "RIGHT" else "REMOVED",
                "fileType": "TO" if side.upper() == "RIGHT" else "FROM",
            },
        }
    elif provider == "gitea":
        endpoint = f"{root}/reviews"
        payload = {
            "body": body,
            "event": "COMMENT",
            "comments": [{"path": path, "new_position": line, "body": body}],
            "commit_id": commit_id,
        }
    else:
        endpoint = f"{root}/threads"
        params = {"api-version": "7.1"}
        key = "rightFileStart" if side.upper() == "RIGHT" else "leftFileStart"
        payload = {
            "comments": [{"parentCommentId": 0, "content": body, "commentType": 1}],
            "status": "active",
            "threadContext": {key: {"line": line, "offset": 1}},
            "pullRequestThreadContext": {"filePath": path},
        }
    result = await _request_json(
        connection,
        token,
        endpoint,
        params=params,
        method="POST",
        json_body={key: value for key, value in payload.items() if value is not None},
    )
    return {
        "action": "inline_comment",
        "provider": provider,
        "result": _bounded_payload(result),
    }


async def reply_code_review_thread(
    target: RepositoryTarget,
    connection: GitServerConnection,
    number: int,
    thread_id: str,
    body: str,
) -> dict[str, Any]:
    require_review_mutations_enabled()
    require_capability(connection.provider, "reply_thread")
    token = connection_token(connection)
    repository = target.repository
    if not token or not repository:
        raise GitServerApiError("The connection or repository is not configured.")
    provider = connection.provider
    root = _review_root(provider, repository, number)
    params: dict[str, str | int] | None = None
    if provider == "github":
        endpoint = f"{root}/comments/{quote(thread_id)}/replies"
        payload = {"body": body}
    elif provider == "gitlab":
        endpoint = f"{root}/discussions/{quote(thread_id)}/notes"
        payload = {"body": body}
    elif provider == "bitbucket_cloud":
        endpoint = f"{root}/comments"
        payload = {"content": {"raw": body}, "parent": {"id": int(thread_id)}}
    elif provider == "bitbucket_server":
        endpoint = f"{root}/comments"
        payload = {"text": body, "parent": {"id": int(thread_id)}}
    else:
        endpoint = f"{root}/threads/{quote(thread_id)}/comments"
        params = {"api-version": "7.1"}
        payload = {"parentCommentId": 0, "content": body, "commentType": 1}
    result = await _request_json(
        connection, token, endpoint, params=params, method="POST", json_body=payload
    )
    return {"action": "reply", "provider": provider, "result": _bounded_payload(result)}


async def set_code_review_thread_resolved(
    target: RepositoryTarget,
    connection: GitServerConnection,
    number: int,
    thread_id: str,
    *,
    resolved: bool,
) -> dict[str, Any]:
    require_review_mutations_enabled()
    require_capability(connection.provider, "resolve_thread")
    token = connection_token(connection)
    repository = target.repository
    if not token or not repository:
        raise GitServerApiError("The connection or repository is not configured.")
    provider = connection.provider
    root = _review_root(provider, repository, number)
    params: dict[str, str | int] | None = None
    if provider == "gitlab":
        endpoint = f"{root}/discussions/{quote(thread_id)}"
        payload = {"resolved": resolved}
        method = "PUT"
    elif provider == "bitbucket_cloud":
        endpoint = f"{root}/comments/{quote(thread_id)}"
        payload = {"resolved": resolved}
        method = "PUT"
    elif provider == "bitbucket_server":
        endpoint = f"{root}/comments/{quote(thread_id)}"
        payload = {"state": "RESOLVED" if resolved else "OPEN"}
        method = "PUT"
    else:
        endpoint = f"{root}/threads/{quote(thread_id)}"
        payload = {"status": "fixed" if resolved else "active"}
        params = {"api-version": "7.1"}
        method = "PATCH"
    result = await _request_json(
        connection, token, endpoint, params=params, method=method, json_body=payload
    )
    return {
        "action": "resolve_thread" if resolved else "reopen_thread",
        "provider": provider,
        "result": _bounded_payload(result),
    }


async def submit_code_review(
    target: RepositoryTarget,
    connection: GitServerConnection,
    number: int,
    event: str,
    *,
    body: str = "",
    reviewer_id: str | None = None,
) -> dict[str, Any]:
    require_review_mutations_enabled()
    event = event.lower()
    if event not in {"approve", "request_changes", "comment"}:
        raise GitServerApiError(
            "Review event must be approve, request_changes, or comment."
        )
    if event == "comment":
        return await add_code_review_comment(target, connection, number, body)
    require_capability(connection.provider, f"submit_{event}")
    token = connection_token(connection)
    repository = target.repository
    if not token or not repository:
        raise GitServerApiError("The connection or repository is not configured.")
    provider = connection.provider
    root = _review_root(provider, repository, number)
    params: dict[str, str | int] | None = None
    method = "POST"
    if provider == "github":
        endpoint = f"{root}/reviews"
        payload = {
            "body": body,
            "event": "APPROVE" if event == "approve" else "REQUEST_CHANGES",
        }
    elif provider == "gitlab":
        endpoint = f"{root}/approve"
        payload = {}
    elif provider == "bitbucket_cloud":
        endpoint = f"{root}/{'approve' if event == 'approve' else 'request-changes'}"
        payload = {}
    elif provider == "bitbucket_server":
        endpoint = f"{root}/approve"
        payload = {}
    elif provider == "gitea":
        endpoint = f"{root}/reviews"
        payload = {
            "body": body,
            "event": "APPROVE" if event == "approve" else "REQUEST_CHANGES",
        }
    else:
        if not reviewer_id:
            raise GitServerApiError(
                "Azure DevOps approve/request changes requires reviewer_id from "
                "get_code_review approvals."
            )
        endpoint = f"{root}/reviewers/{quote(reviewer_id)}"
        params = {"api-version": "7.1"}
        method = "PUT"
        payload = {"vote": 10 if event == "approve" else -10}
    result = await _request_json(
        connection, token, endpoint, params=params, method=method, json_body=payload
    )
    return {"action": event, "provider": provider, "result": _bounded_payload(result)}


async def update_code_review(
    target: RepositoryTarget,
    connection: GitServerConnection,
    number: int,
    updates: dict[str, Any],
) -> dict[str, Any]:
    require_review_mutations_enabled()
    require_capability(connection.provider, "update")
    token = connection_token(connection)
    repository = target.repository
    if not token or not repository:
        raise GitServerApiError("The connection or repository is not configured.")
    provider = connection.provider
    root = _review_root(provider, repository, number)
    title = updates.get("title")
    body = updates.get("body")
    draft = updates.get("draft")
    if draft is not None:
        require_capability(provider, "draft")
    payload: dict[str, Any]
    params: dict[str, str | int] | None = None
    method = "PATCH"
    if provider == "github":
        payload = {"title": title, "body": body}
    elif provider == "gitlab":
        method = "PUT"
        if title and draft is not None:
            clean = re.sub(r"^(?:draft:|wip:)\s*", "", str(title), flags=re.I)
            title = f"Draft: {clean}" if draft else clean
        payload = {
            "title": title,
            "description": body,
            "labels": ",".join(updates.get("labels") or [])
            if updates.get("labels") is not None
            else None,
            "reviewer_ids": updates.get("reviewers"),
            "assignee_ids": updates.get("assignees"),
        }
    elif provider == "bitbucket_cloud":
        method = "PUT"
        payload = {
            "title": title,
            "description": body,
            "reviewers": [{"uuid": value} for value in updates.get("reviewers") or []]
            if updates.get("reviewers") is not None
            else None,
        }
    elif provider == "bitbucket_server":
        current = _dict(await _request_json(connection, token, root))
        method = "PUT"
        payload = {
            "version": current.get("version"),
            "title": title or current.get("title"),
            "description": body if body is not None else current.get("description"),
            "reviewers": updates.get("reviewers") or current.get("reviewers"),
        }
    elif provider == "gitea":
        payload = {"title": title, "body": body}
    else:
        payload = {"title": title, "description": body, "isDraft": draft}
        params = {"api-version": "7.1"}
    payload = {key: value for key, value in payload.items() if value is not None}
    result = await _request_json(
        connection, token, root, params=params, method=method, json_body=payload
    )
    # Provider-specific secondary metadata endpoints.
    if provider in {"github", "gitea"} and updates.get("labels") is not None:
        issue_root = f"repos/{quote(repository, safe='/')}/issues/{number}"
        await _request_json(
            connection,
            token,
            f"{issue_root}/labels",
            method="POST" if provider == "gitea" else "PUT",
            json_body={"labels": updates["labels"]},
        )
    if provider == "github" and updates.get("reviewers") is not None:
        await _request_json(
            connection,
            token,
            f"{root}/requested_reviewers",
            method="POST",
            json_body={"reviewers": updates["reviewers"]},
        )
    if provider == "github" and updates.get("assignees") is not None:
        await _request_json(
            connection,
            token,
            f"repos/{quote(repository, safe='/')}/issues/{number}/assignees",
            method="POST",
            json_body={"assignees": updates["assignees"]},
        )
    return {
        "action": "update",
        "provider": provider,
        "result": _bounded_payload(result),
    }


async def merge_code_review(
    target: RepositoryTarget,
    connection: GitServerConnection,
    number: int,
    *,
    method: str | None = None,
    commit_title: str | None = None,
) -> dict[str, Any]:
    require_review_mutations_enabled()
    require_capability(connection.provider, "merge")
    token = connection_token(connection)
    repository = target.repository
    if not token or not repository:
        raise GitServerApiError("The connection or repository is not configured.")
    provider = connection.provider
    if load_runtime_settings().code_reviews.require_successful_checks_before_merge:
        checks = await get_repository_review_checks(target, connection, number)
        if checks.get("summary") != "success":
            raise GitServerApiError(
                "Merge blocked because required checks are not successful."
            )
    root = _review_root(provider, repository, number)
    params: dict[str, str | int] | None = None
    http_method = "POST"
    if provider == "github":
        endpoint = f"{root}/merge"
        http_method = "PUT"
        payload = {"merge_method": method, "commit_title": commit_title}
    elif provider == "gitlab":
        endpoint = f"{root}/merge"
        http_method = "PUT"
        payload = {
            "merge_commit_message": commit_title,
            "squash": method == "squash" if method else None,
        }
    elif provider in {"bitbucket_cloud", "bitbucket_server"}:
        endpoint = f"{root}/merge"
        payload = {"message": commit_title, "merge_strategy": method}
    elif provider == "gitea":
        endpoint = f"{root}/merge"
        payload = {
            "Do": method or "merge",
            "MergeTitleField": commit_title,
        }
    else:
        current = _dict(
            await _request_json(connection, token, root, params={"api-version": "7.1"})
        )
        endpoint = root
        http_method = "PATCH"
        params = {"api-version": "7.1"}
        payload = {
            "status": "completed",
            "lastMergeSourceCommit": current.get("lastMergeSourceCommit"),
            "completionOptions": {
                "mergeStrategy": method or "noFastForward",
            },
        }
    payload = {key: value for key, value in payload.items() if value is not None}
    result = await _request_json(
        connection,
        token,
        endpoint,
        params=params,
        method=http_method,
        json_body=payload,
    )
    return {"action": "merge", "provider": provider, "result": _bounded_payload(result)}


async def set_code_review_state(
    target: RepositoryTarget,
    connection: GitServerConnection,
    number: int,
    *,
    open: bool,
) -> dict[str, Any]:
    require_review_mutations_enabled()
    capability = "reopen" if open else "close"
    require_capability(connection.provider, capability)
    token = connection_token(connection)
    repository = target.repository
    if not token or not repository:
        raise GitServerApiError("The connection or repository is not configured.")
    provider = connection.provider
    root = _review_root(provider, repository, number)
    current = _dict(
        await _request_json(
            connection,
            token,
            root,
            params={"api-version": "7.1"} if provider == "azure_devops" else None,
        )
    )
    state = str(current.get("state") or current.get("status") or "").lower()
    already = (
        state in {"open", "opened", "active"}
        if open
        else state in {"closed", "declined", "abandoned"}
    )
    if already:
        return {"action": capability, "provider": provider, "unchanged": True}
    params: dict[str, str | int] | None = None
    if provider in {"github", "gitea"}:
        endpoint = root
        method = "PATCH"
        payload = {"state": "open" if open else "closed"}
    elif provider == "gitlab":
        endpoint = root
        method = "PUT"
        payload = {"state_event": "reopen" if open else "close"}
    elif provider == "bitbucket_cloud":
        endpoint = f"{root}/{'reopen' if open else 'decline'}"
        method = "POST"
        payload = {}
    elif provider == "bitbucket_server":
        endpoint = f"{root}/{'reopen' if open else 'decline'}"
        method = "POST"
        payload = {"version": current.get("version")}
    else:
        endpoint = root
        method = "PATCH"
        params = {"api-version": "7.1"}
        payload = {"status": "active" if open else "abandoned"}
    result = await _request_json(
        connection, token, endpoint, params=params, method=method, json_body=payload
    )
    return {
        "action": capability,
        "provider": provider,
        "result": _bounded_payload(result),
    }


async def create_repository_review(
    target: RepositoryTarget,
    connection: GitServerConnection,
    *,
    title: str,
    body: str,
    source_branch: str,
    target_branch: str,
) -> dict[str, Any]:
    """Create a pull/merge request through the configured provider REST API."""
    require_review_mutations_enabled()
    token = connection_token(connection)
    if not token:
        raise GitServerApiError("The connection has no API key.")
    repository = target.repository
    if not repository:
        raise GitServerApiError(
            target.inspection_error or "No Git remote is configured."
        )

    provider = connection.provider
    params: dict[str, str | int] | None = None
    if provider == "github":
        path = f"repos/{quote(repository, safe='/')}/pulls"
        payload = {
            "title": title,
            "body": body,
            "head": source_branch,
            "base": target_branch,
        }
    elif provider == "gitlab":
        path = f"projects/{quote(repository, safe='')}/merge_requests"
        payload = {
            "title": title,
            "description": body,
            "source_branch": source_branch,
            "target_branch": target_branch,
        }
    elif provider == "bitbucket_cloud":
        path = f"repositories/{quote(repository, safe='/')}/pullrequests"
        payload = {
            "title": title,
            "description": body,
            "source": {"branch": {"name": source_branch}},
            "destination": {"branch": {"name": target_branch}},
        }
    elif provider == "bitbucket_server":
        project, repo = _bitbucket_server_coordinates(repository)
        path = f"projects/{quote(project)}/repos/{quote(repo)}/pull-requests"
        payload = {
            "title": title,
            "description": body,
            "fromRef": {"id": f"refs/heads/{source_branch}"},
            "toRef": {"id": f"refs/heads/{target_branch}"},
        }
    elif provider == "gitea":
        path = f"repos/{quote(repository, safe='/')}/pulls"
        payload = {
            "title": title,
            "body": body,
            "head": source_branch,
            "base": target_branch,
        }
    elif provider == "azure_devops":
        project, repo = _azure_coordinates(repository)
        path = f"{quote(project)}/_apis/git/repositories/{quote(repo)}/pullrequests"
        params = {"api-version": "7.1"}
        payload = {
            "title": title,
            "description": body,
            "sourceRefName": f"refs/heads/{source_branch}",
            "targetRefName": f"refs/heads/{target_branch}",
        }
    else:
        raise GitServerApiError(f"Provider {provider} is not supported.")

    result = await _request_json(
        connection,
        token,
        path,
        params=params,
        method="POST",
        json_body=payload,
    )
    row = _dict(result)
    links = _dict(row.get("links") or row.get("_links"))
    self_links = _list(links.get("self"))
    self_url = (
        str(_dict(self_links[0]).get("href") or "")
        if self_links
        else str(_dict(links.get("self")).get("href") or "")
    )
    web_url = str(
        row.get("html_url")
        or row.get("web_url")
        or _dict(links.get("html") or links.get("web")).get("href")
        or self_url
        or ""
    )
    number = int(
        row.get("number")
        or row.get("iid")
        or row.get("id")
        or row.get("pullRequestId")
        or 0
    )
    if number <= 0:
        raise GitServerApiError(
            "The Git server created a review but returned no usable review number."
        )
    return {
        "provider": provider,
        "repository": repository,
        "number": number,
        "web_url": web_url,
        "title": str(row.get("title") or title),
    }


async def aggregate_reviews(
    targets: list[RepositoryTarget],
    connections: list[GitServerConnection],
) -> list[RepositoryReviews]:
    semaphore = asyncio.Semaphore(
        load_runtime_settings().code_reviews.max_concurrent_repositories
    )

    async def load(target: RepositoryTarget) -> RepositoryReviews:
        if target.inspection_error:
            return RepositoryReviews(
                target=target,
                connection_id=None,
                provider=None,
                error=target.inspection_error,
            )
        if not target.remote_url:
            return RepositoryReviews(
                target=target,
                connection_id=None,
                provider=None,
                error="No Git remote is configured.",
            )
        connection = resolve_connection(target, connections)
        if connection is None:
            return RepositoryReviews(
                target=target,
                connection_id=None,
                provider=target.detected_provider,
                error="Connect this repository to a Git server API.",
            )
        async with semaphore:
            return await list_repository_reviews(target, connection)

    return list(await asyncio.gather(*(load(target) for target in targets)))


async def test_connection(connection: GitServerConnection, token: str) -> None:
    """Validate authentication without persisting or logging the supplied token."""
    if connection.provider == "github":
        await _request_json(connection, token, "user")
    elif connection.provider == "gitlab":
        await _request_json(connection, token, "user")
    elif connection.provider == "bitbucket_cloud":
        await _request_json(connection, token, "user")
    elif connection.provider == "gitea":
        await _request_json(connection, token, "user")
    elif connection.provider == "azure_devops":
        await _request_json(
            connection,
            token,
            "_apis/projects",
            params={"$top": 1, "api-version": "7.1"},
        )
    elif connection.provider == "bitbucket_server":
        await _request_json(connection, token, "application-properties")
    else:
        raise GitServerApiError(f"Provider {connection.provider} is not supported.")
