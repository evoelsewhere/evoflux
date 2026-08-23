"""HTTP boundary for the self-contained code-context index."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Response

from app.api.schemas.code_context import (
    CodeContextIndexRequest,
    CodeContextQueryRequest,
    CodeContextQueryResponse,
    CodeContextStatusResponse,
)
from app.services.code_index.models import GraphSnapshot, IndexStats, RepositoryScope
from app.services.code_index.pipeline import stable_id
from app.services.code_index.project import repository_indexes
from app.services.code_index.query import snapshot_graph
from app.services.code_index.service import query_code_context

router = APIRouter()


def _render_graph_payload(
    *,
    workspace_id: str,
    label: str,
    stats: IndexStats,
    snapshot: GraphSnapshot,
    node_limit_per_repo: int,
    edge_limit_per_repo: int,
) -> bytes:
    global_id = {
        symbol.identity: stable_id(workspace_id, symbol.id)
        for symbol in snapshot.symbols
    }
    nodes = [
        {
            "id": global_id[symbol.identity],
            "workspace_id": workspace_id,
            "kind": symbol.kind,
            "name": symbol.name,
            "qualified_name": symbol.qualified_name,
            "file_path": symbol.file_path,
            "language": symbol.language,
            "line_start": symbol.line_start,
            "line_end": symbol.line_end,
            "signature": symbol.signature,
            "docstring": symbol.docstring,
        }
        for symbol in snapshot.symbols
    ]
    edges = [
        {
            "id": stable_id(
                relation.source.repository,
                relation.source.id,
                relation.kind,
                relation.target.id,
                relation.callsite_line,
            ),
            "src_id": global_id[relation.source.identity],
            "dst_id": global_id[relation.target.identity],
            "kind": relation.kind,
            "file_path": relation.callsite_file,
            "line": relation.callsite_line,
        }
        for relation in snapshot.relations
    ]
    payload = {
        "repos": [
            {
                "workspace_id": workspace_id,
                "path": workspace_id,
                "name": label,
                "indexed": stats.files > 0,
                "files": stats.files,
                "nodes": stats.symbols,
                "edges": stats.relations,
                "indexing": False,
                "index_phase": None,
                "index_progress": None,
                "index_message": None,
                "index_error": _error_summary(stats.errors),
            }
        ],
        "nodes": nodes,
        "edges": edges,
        "cross_repo_edges": [],
        "node_limit_per_repo": node_limit_per_repo,
        "edge_limit_per_repo": edge_limit_per_repo,
        "total_node_count": snapshot.total_symbols,
        "total_edge_count": snapshot.total_relations,
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()


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
    stats = await asyncio.to_thread(index.stats)
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
    try:
        stats = await index.update(full=bool(body and body.full))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
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


@router.get("/graph-data", response_model=dict[str, object])
async def graph_data(
    workspace: str | None = Query(None, description="Coding workspace directory."),
    node_limit_per_repo: int = Query(500, ge=1, le=5_000),
    edge_limit_per_repo: int = Query(2_000, ge=1, le=10_000),
) -> Response:
    """Return the same bounded spatial projection used by project graphs."""
    root = _workspace_path(workspace)
    label = root.name or str(root)
    index = await repository_indexes.get(root)
    stats = await asyncio.to_thread(index.stats)
    snapshot = await snapshot_graph(
        [(label, index)] if stats.files > 0 else [],
        node_limit_per_repository=node_limit_per_repo,
        relation_limit_per_repository=edge_limit_per_repo,
        stats={label: stats} if stats.files > 0 else {},
    )
    workspace_id = str(root)
    content = await asyncio.to_thread(
        _render_graph_payload,
        workspace_id=workspace_id,
        label=label,
        stats=stats,
        snapshot=snapshot,
        node_limit_per_repo=node_limit_per_repo,
        edge_limit_per_repo=edge_limit_per_repo,
    )
    return Response(content=content, media_type="application/json")


__all__ = ["router"]
