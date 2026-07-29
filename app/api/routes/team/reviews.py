"""Git server connections and aggregate pull/merge request routes."""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import RedirectResponse
from sqlmodel import col, select

from app.api.deps import DbSession
from app.api.schemas.reviews import (
    ConnectionScope,
    GitProvider,
    GitServerConnectionCreate,
    GitServerConnectionOut,
    GitServerConnectionTest,
    GitServerConnectionUpdate,
    RepositoryReviewsOut,
    ReviewActionRequest,
    ReviewItemOut,
    ReviewsOut,
)
from app.cli.seed import write_env_credentials
from app.core.config import settings
from app.models.chat import (
    CodingProjectWorkspace,
    CodingWorkspace,
    GitServerConnection,
)
from app.services.code_review_service import (
    GitServerApiError,
    ReviewImageRedirect,
    SUPPORTED_PROVIDERS,
    aggregate_reviews,
    add_code_review_comment,
    add_code_review_inline_comment,
    api_base_from_domain,
    connection_host,
    connection_token,
    default_api_base,
    fetch_code_review_image,
    inspect_repository,
    get_repository_review_checks,
    get_repository_review_context,
    merge_code_review,
    reply_code_review_thread,
    resolve_connection,
    server_domain,
    set_code_review_state,
    set_code_review_thread_resolved,
    submit_code_review,
    test_connection,
    token_creation_url,
    update_code_review,
)
from app.services.coding_workspace_service import list_visible_coding_workspaces

router = APIRouter(prefix="/reviews", tags=["code-reviews"])

_ENV_NAME_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")
_MANAGED_ENV_PREFIX = "EVOFLUX_GIT_CONNECTION_"


def _normalize_base_url(value: str) -> str:
    value = value.strip().rstrip("/")
    connection_host(value)
    return value


def _derive_connection_urls(provider: str, value: str) -> tuple[str, str]:
    try:
        domain = server_domain(provider, value)
        return domain, _normalize_base_url(api_base_from_domain(provider, domain))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _validate_scope(scope: str, workspace_id: UUID | None) -> None:
    if scope == "repository" and workspace_id is None:
        raise HTTPException(
            status_code=422,
            detail="Repository-scoped connections require a workspace.",
        )
    if scope == "server" and workspace_id is not None:
        raise HTTPException(
            status_code=422,
            detail="Shared server connections cannot target one workspace.",
        )


def _validate_env_name(value: str) -> str:
    value = value.strip()
    if not _ENV_NAME_RE.fullmatch(value):
        raise HTTPException(
            status_code=422,
            detail="Token environment variable must use uppercase letters, numbers, and underscores.",
        )
    return value


def _save_token(env_name: str, token: str) -> None:
    env_file = Path(settings.EVOFLUX_CONFIG_DIR) / ".env"
    write_env_credentials(
        env_file,
        {env_name: token},
        comments={env_name: "# Git server API token managed by EvoFlux"},
    )
    if token:
        os.environ[env_name] = token
    else:
        os.environ.pop(env_name, None)


def _connection_out(connection: GitServerConnection) -> GitServerConnectionOut:
    domain = server_domain(connection.provider, connection.base_url)
    return GitServerConnectionOut(
        id=connection.id,
        name=connection.name,
        provider=cast(GitProvider, connection.provider),
        domain=domain,
        base_url=connection.base_url,
        token_url=token_creation_url(connection.provider, domain),
        host=connection.host,
        scope=cast(ConnectionScope, connection.scope),
        workspace_id=connection.workspace_id,
        token_env_var=connection.token_env_var,
        has_token=bool(connection_token(connection)),
        username=connection.username,
        verify_ssl=connection.verify_ssl,
        created_at=connection.created_at,
        updated_at=connection.updated_at,
    )


async def _require_workspace(db: DbSession, workspace_id: UUID) -> CodingWorkspace:
    workspace = await db.get(CodingWorkspace, workspace_id)
    if workspace is None or workspace.hidden or workspace.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Coding repository not found.")
    return workspace


@router.get("/connections", response_model=list[GitServerConnectionOut])
async def list_connections(db: DbSession) -> list[GitServerConnectionOut]:
    rows = list(
        (
            await db.exec(
                select(GitServerConnection).order_by(
                    col(GitServerConnection.created_at).asc()
                )
            )
        ).all()
    )
    return [_connection_out(row) for row in rows]


@router.post(
    "/connections",
    response_model=GitServerConnectionOut,
    status_code=201,
)
async def create_connection(
    body: GitServerConnectionCreate,
    db: DbSession,
) -> GitServerConnectionOut:
    _validate_scope(body.scope, body.workspace_id)
    if body.workspace_id is not None:
        await _require_workspace(db, body.workspace_id)
    if body.provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=422, detail="Unsupported Git provider.")
    connection_id = uuid4()
    if body.token_env_var:
        env_name = _validate_env_name(body.token_env_var)
    else:
        env_name = f"{_MANAGED_ENV_PREFIX}{connection_id.hex.upper()}_TOKEN"
    domain, base_url = _derive_connection_urls(
        body.provider,
        body.domain or body.base_url or "",
    )
    connection = GitServerConnection(
        id=connection_id,
        name=body.name.strip(),
        provider=body.provider,
        base_url=base_url,
        host=connection_host(domain),
        scope=body.scope,
        workspace_id=body.workspace_id,
        token_env_var=env_name,
        username=body.username.strip() if body.username else None,
        verify_ssl=body.verify_ssl,
    )
    if not body.token and not os.environ.get(env_name):
        env_file = Path(settings.EVOFLUX_CONFIG_DIR) / ".env"
        from dotenv import dotenv_values

        if not dotenv_values(env_file).get(env_name):
            raise HTTPException(
                status_code=422,
                detail="Provide an API key or an environment variable containing one.",
            )
    if body.token:
        _save_token(env_name, body.token)
    db.add(connection)
    await db.commit()
    await db.refresh(connection)
    return _connection_out(connection)


@router.put(
    "/connections/{connection_id}",
    response_model=GitServerConnectionOut,
)
async def update_connection(
    connection_id: UUID,
    body: GitServerConnectionUpdate,
    db: DbSession,
) -> GitServerConnectionOut:
    connection = await db.get(GitServerConnection, connection_id)
    if connection is None:
        raise HTTPException(status_code=404, detail="Connection not found.")
    scope = body.scope if body.scope is not None else connection.scope
    workspace_id = (
        body.workspace_id
        if "workspace_id" in body.model_fields_set
        else connection.workspace_id
    )
    _validate_scope(scope, workspace_id)
    if workspace_id is not None:
        await _require_workspace(db, workspace_id)
    if body.name is not None:
        connection.name = body.name.strip()
    previous_provider = connection.provider
    previous_domain = server_domain(previous_provider, connection.base_url)
    next_provider = body.provider or previous_provider
    if (
        body.provider is not None
        or body.domain is not None
        or body.base_url is not None
    ):
        requested_domain = body.domain or body.base_url or previous_domain
        domain, base_url = _derive_connection_urls(
            next_provider,
            requested_domain,
        )
        if (
            next_provider != previous_provider or domain != previous_domain
        ) and not body.token:
            raise HTTPException(
                status_code=422,
                detail="Provide a new access token when changing the Git provider or domain.",
            )
        connection.provider = next_provider
        connection.base_url = base_url
        connection.host = connection_host(domain)
    connection.scope = scope
    connection.workspace_id = workspace_id
    if body.token_env_var is not None:
        connection.token_env_var = _validate_env_name(body.token_env_var)
    if body.username is not None:
        connection.username = body.username.strip() or None
    if body.verify_ssl is not None:
        connection.verify_ssl = body.verify_ssl
    if body.token is not None:
        _save_token(connection.token_env_var, body.token)
    db.add(connection)
    await db.commit()
    await db.refresh(connection)
    return _connection_out(connection)


@router.delete(
    "/connections/{connection_id}",
    status_code=204,
    response_class=Response,
)
async def delete_connection(
    connection_id: UUID,
    db: DbSession,
) -> Response:
    connection = await db.get(GitServerConnection, connection_id)
    if connection is None:
        raise HTTPException(status_code=404, detail="Connection not found.")
    env_name = connection.token_env_var
    await db.delete(connection)
    await db.commit()
    if env_name.startswith(_MANAGED_ENV_PREFIX):
        _save_token(env_name, "")
    return Response(status_code=204)


@router.post("/connections/test")
async def check_connection(body: GitServerConnectionTest) -> dict[str, bool]:
    try:
        domain, base_url = _derive_connection_urls(
            body.provider,
            body.domain or body.base_url or "",
        )
        connection = GitServerConnection(
            name="Connection test",
            provider=body.provider,
            base_url=base_url,
            host=connection_host(domain),
            token_env_var="EVOFLUX_GIT_CONNECTION_TEST_TOKEN",
            username=body.username,
            verify_ssl=body.verify_ssl,
        )
        await test_connection(connection, body.token)
    except (GitServerApiError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"ok": True}


@router.get("", response_model=ReviewsOut)
async def list_reviews(
    db: DbSession,
    workspace: str | None = Query(default=None),
    project_id: UUID | None = Query(default=None),
) -> ReviewsOut:
    if workspace and project_id:
        raise HTTPException(
            status_code=422,
            detail="Filter reviews by workspace or project, not both.",
        )
    all_workspace_rows = await list_visible_coding_workspaces(db)
    workspace_rows = [row for row in all_workspace_rows if row.kind == "repo"]
    project_membership = {
        link.workspace_id: link.project_id
        for link in (await db.exec(select(CodingProjectWorkspace))).all()
    }
    if project_id is not None:
        workspace_rows = [
            row
            for row in workspace_rows
            if project_membership.get(row.id) == project_id
        ]
    elif workspace:
        requested_path = str(Path(workspace).expanduser().resolve())
        scoped_path = requested_path
        worktree = next(
            (
                row
                for row in all_workspace_rows
                if row.kind == "worktree" and row.path == requested_path
            ),
            None,
        )
        if worktree and worktree.source_path:
            scoped_path = worktree.source_path
        workspace_rows = [row for row in workspace_rows if row.path == scoped_path]
    targets = list(
        await asyncio.gather(
            *(
                inspect_repository(
                    str(row.id),
                    row.path,
                    row.name or Path(row.path).name,
                )
                for row in workspace_rows
            )
        )
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
    repositories = await aggregate_reviews(targets, connections)
    output: list[RepositoryReviewsOut] = []
    for repository in repositories:
        target = repository.target
        suggested_base_url = None
        suggested_domain = None
        if target.host and target.detected_provider:
            try:
                suggested_base_url = default_api_base(
                    target.detected_provider,
                    target.host,
                    target.repository,
                )
                suggested_domain = server_domain(
                    target.detected_provider,
                    suggested_base_url,
                )
            except ValueError:
                pass
        output.append(
            RepositoryReviewsOut(
                workspace_id=UUID(target.workspace_id),
                project_id=project_membership.get(UUID(target.workspace_id)),
                workspace=target.workspace,
                name=target.name,
                remote_url=target.remote_url,
                repository=target.repository,
                detected_provider=cast(
                    GitProvider | None,
                    target.detected_provider,
                ),
                suggested_domain=suggested_domain,
                suggested_base_url=suggested_base_url,
                connection_id=(
                    UUID(repository.connection_id) if repository.connection_id else None
                ),
                provider=cast(GitProvider | None, repository.provider),
                items=[
                    ReviewItemOut(
                        number=item.number,
                        title=item.title,
                        state=item.state,
                        draft=item.draft,
                        author=item.author,
                        author_avatar_url=item.author_avatar_url,
                        source_branch=item.source_branch,
                        target_branch=item.target_branch,
                        updated_at=item.updated_at,
                        web_url=item.web_url,
                        labels=item.labels,
                        review_status=item.review_status,
                        pipeline_status=item.pipeline_status,
                        comment_count=item.comment_count,
                    )
                    for item in repository.items
                ],
                error=repository.error,
            )
        )
    return ReviewsOut(
        repositories=output,
        total=sum(len(repository.items) for repository in repositories),
    )


async def _review_target_connection(
    db: DbSession,
    workspace_id: UUID,
):
    workspace = await _require_workspace(db, workspace_id)
    target = await inspect_repository(
        str(workspace.id),
        workspace.path,
        workspace.name or Path(workspace.path).name,
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
        raise HTTPException(
            status_code=422,
            detail="No configured Git server connection matches this repository.",
        )
    return target, connection


@router.get("/{workspace_id}/media", response_class=Response)
async def get_review_media(
    workspace_id: UUID,
    db: DbSession,
    url: str = Query(min_length=1, max_length=4096),
) -> Response:
    _, connection = await _review_target_connection(db, workspace_id)
    try:
        image = await fetch_code_review_image(connection, url)
    except GitServerApiError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if isinstance(image, ReviewImageRedirect):
        return RedirectResponse(
            image.url,
            status_code=302,
            headers={
                "Cache-Control": "private, no-store",
                "Referrer-Policy": "no-referrer",
            },
        )
    return Response(
        content=image.content,
        media_type=image.media_type,
        headers={
            "Cache-Control": "private, max-age=300",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/{workspace_id}/{number}")
async def get_review(
    workspace_id: UUID,
    number: int,
    db: DbSession,
) -> dict:
    target, connection = await _review_target_connection(db, workspace_id)
    try:
        return await get_repository_review_context(target, connection, number)
    except GitServerApiError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{workspace_id}/{number}/actions")
async def mutate_review(
    workspace_id: UUID,
    number: int,
    body: ReviewActionRequest,
    db: DbSession,
) -> dict:
    target, connection = await _review_target_connection(db, workspace_id)
    try:
        if body.action == "comment":
            return await add_code_review_comment(
                target,
                connection,
                number,
                body.body or "",
                idempotency_key=body.idempotency_key,
            )
        if body.action == "inline_comment":
            if not body.path or body.line is None:
                raise GitServerApiError("Inline comments require path and line.")
            return await add_code_review_inline_comment(
                target,
                connection,
                number,
                body.body or "",
                path=body.path,
                line=body.line,
                side=body.side,
                commit_id=body.commit_id,
                base_commit_id=body.base_commit_id,
                start_commit_id=body.start_commit_id,
            )
        if body.action == "reply":
            if not body.thread_id:
                raise GitServerApiError("Replies require a thread ID.")
            return await reply_code_review_thread(
                target, connection, number, body.thread_id, body.body or ""
            )
        if body.action in {"resolve_thread", "reopen_thread"}:
            if not body.thread_id:
                raise GitServerApiError("Thread updates require a thread ID.")
            return await set_code_review_thread_resolved(
                target,
                connection,
                number,
                body.thread_id,
                resolved=body.action == "resolve_thread",
            )
        if body.action in {"approve", "request_changes"}:
            return await submit_code_review(
                target,
                connection,
                number,
                body.action,
                body=body.body or "",
                reviewer_id=body.reviewer_id,
            )
        if body.action == "update":
            return await update_code_review(target, connection, number, body.updates)
        if body.action == "checks":
            return await get_repository_review_checks(target, connection, number)
        if body.action == "merge":
            return await merge_code_review(
                target,
                connection,
                number,
                method=body.merge_method,
                commit_title=body.commit_title,
            )
        if body.action in {"close", "reopen"}:
            return await set_code_review_state(
                target,
                connection,
                number,
                open=body.action == "reopen",
            )
        raise GitServerApiError(f"Unsupported review action: {body.action}")
    except GitServerApiError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
