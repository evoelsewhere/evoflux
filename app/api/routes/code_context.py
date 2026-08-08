"""HTTP boundary for the self-contained code-context index."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from app.api.schemas.code_context import (
    CodeContextIndexRequest,
    CodeContextQueryRequest,
    CodeContextQueryResponse,
    CodeContextStatusResponse,
)
from app.services.code_index.models import RepositoryScope
from app.services.code_index.project import repository_indexes
from app.services.code_index.service import query_code_context

router = APIRouter()


def _error_summary(errors: tuple[tuple[str, str], ...]) -> str | None:
    if not errors:
        return None
    path, error = errors[0]
    suffix = f" (+{len(errors) - 1} more)" if len(errors) > 1 else ""
    return f"{path}: {error}{suffix}"


def _workspace_path(workspace: str | None) -> Path:
    if workspace is None:
        raise HTTPException(status_code=422, detail="Workspace is required.")
    path = Path(workspace).expanduser().resolve()
    if not path.is_dir():
        raise HTTPException(
            status_code=422,
            detail=f"Workspace does not exist or is not a directory: {path}",
        )
    return path


def _scopes(primary: Path, repositories: list[str]) -> tuple[RepositoryScope, ...]:
    paths = [primary]
    for value in repositories:
        path = Path(value).expanduser().resolve()
        if not path.is_dir():
            raise HTTPException(
                status_code=422,
                detail=f"Repository does not exist or is not a directory: {path}",
            )
        paths.append(path)
    return tuple(
        RepositoryScope(root=path, label=path.name or str(path))
        for path in dict.fromkeys(paths)
    )


@router.get("/status")
async def status(
    workspace: str | None = Query(None, description="Coding workspace directory."),
) -> CodeContextStatusResponse:
    index = await repository_indexes.get(_workspace_path(workspace))
    stats = index.stats()
    return CodeContextStatusResponse(
        indexed=stats.files > 0,
        files=stats.files,
        chunks=stats.chunks,
        symbols=stats.symbols,
        relations=stats.relations,
        languages=list(stats.languages),
        graph_languages=list(stats.graph_languages),
        errors=list(stats.errors),
        version=stats.version,
        index_error=_error_summary(stats.errors),
    )


@router.post("/index")
async def index_repository(
    body: CodeContextIndexRequest | None = None,
    workspace: str | None = Query(None, description="Coding workspace directory."),
) -> CodeContextStatusResponse:
    index = await repository_indexes.get(_workspace_path(workspace))
    stats = await index.update(full=bool(body and body.full))
    return CodeContextStatusResponse(
        indexed=stats.files > 0,
        files=stats.files,
        chunks=stats.chunks,
        symbols=stats.symbols,
        relations=stats.relations,
        languages=list(stats.languages),
        graph_languages=list(stats.graph_languages),
        errors=list(stats.errors),
        version=stats.version,
        index_error=_error_summary(stats.errors),
    )


@router.post("/query")
async def query(
    body: CodeContextQueryRequest,
    workspace: str | None = Query(None, description="Primary workspace directory."),
) -> CodeContextQueryResponse:
    primary = _workspace_path(workspace)
    try:
        result = await query_code_context(
            scopes=_scopes(primary, body.repositories),
            action=body.action,
            query=body.query,
            repository=body.repository,
            paths=body.paths,
            languages=body.languages,
            depth=body.depth,
            limit=body.limit,
            refresh=body.refresh,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return CodeContextQueryResponse.model_validate(result, from_attributes=True)


__all__ = ["router"]
