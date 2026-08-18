"""Resolve saved Git-server connections for command-line Git operations."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.chat import CodingWorkspace, GitServerConnection
from app.services.code_review_service import (
    RepositoryTarget,
    connection_token,
    inspect_repository,
    parse_remote_url,
    resolve_connection,
)
from app.services.git_ops import GitCredential


_PROVIDER_USERNAMES = {
    "github": "x-access-token",
    "gitlab": "oauth2",
    "bitbucket_cloud": "x-token-auth",
    "bitbucket_server": "x-token-auth",
    "gitea": "oauth2",
    "azure_devops": "pat",
}


def git_credential_from_connection(
    connection: GitServerConnection,
) -> GitCredential | None:
    token = connection_token(connection)
    if not token:
        return None
    return GitCredential(
        host=connection.host,
        username=(
            connection.username or _PROVIDER_USERNAMES.get(connection.provider) or "git"
        ),
        token=token,
        verify_ssl=connection.verify_ssl,
    )


async def resolve_workspace_git_credential(
    db: AsyncSession,
    workspace: str,
) -> GitCredential | None:
    """Return the saved credential matching a workspace's selected Git remote.

    Repository-scoped connections take precedence over shared host
    connections, matching the pull-request API. Worktrees inherit the
    connection of their source repository.
    """
    resolved = str(Path(workspace).expanduser().resolve())
    row = (
        await db.exec(select(CodingWorkspace).where(CodingWorkspace.path == resolved))
    ).first()
    connection_row = row
    if row is not None and row.source_path:
        connection_row = (
            await db.exec(
                select(CodingWorkspace).where(CodingWorkspace.path == row.source_path)
            )
        ).first() or row

    target = await inspect_repository(
        str(connection_row.id) if connection_row is not None else "",
        resolved,
        (
            connection_row.name
            if connection_row is not None and connection_row.name
            else Path(resolved).name
        ),
    )
    connections = list(
        (
            await db.exec(
                select(GitServerConnection).order_by(
                    col(GitServerConnection.created_at).desc()
                )
            )
        ).all()
    )
    connection = resolve_connection(target, connections)
    if connection is None:
        return None
    return git_credential_from_connection(connection)


async def resolve_remote_git_credential(
    db: AsyncSession,
    remote_url: str,
) -> GitCredential | None:
    """Resolve a shared host credential before a repository has been cloned."""
    if urlparse(remote_url).scheme.lower() not in {"http", "https"}:
        return None
    try:
        host, repository, sanitized_url = parse_remote_url(remote_url)
    except ValueError:
        return None
    if not repository:
        return None
    target = RepositoryTarget(
        workspace_id="",
        workspace="",
        name=repository.rsplit("/", 1)[-1],
        remote_url=sanitized_url,
        host=host,
        repository=repository,
        detected_provider=None,
    )
    connections = list(
        (
            await db.exec(
                select(GitServerConnection).order_by(
                    col(GitServerConnection.created_at).desc()
                )
            )
        ).all()
    )
    connection = resolve_connection(target, connections)
    if connection is None or connection.scope != "server":
        return None
    return git_credential_from_connection(connection)
