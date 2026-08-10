"""MCP server CRUD: writes ``mcp.json`` and reconciles live runners."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

from fastapi import APIRouter, HTTPException
from sqlmodel import col, select

from app.agent.mcp import mcp_manager
from app.agent.mcp.config import (
    HttpServerConfig,
    StdioServerConfig,
    load_config,
    save_config,
    validate_server_name,
)
from app.api.schemas.mcp import (
    CreateServerRequest,
    HttpServerBody,
    MCPAppToolCallRequest,
    MCPAppToolCallResponse,
    OAuthBody,
    ServerDeleteResponse,
    ServerListResponse,
    ServerStatusResponse,
    StdioServerBody,
    UpdateServerRequest,
)
from app.api.deps import DbSession
from app.core.config import settings
from app.models.chat import SessionMessage

if TYPE_CHECKING:
    from app.agent.mcp.manager import MCPServerStatus

router = APIRouter()
_MASKED_SECRET = "********"
_ENV_REF_RE = re.compile(r"^\$\{[A-Za-z_][A-Za-z0-9_]*\}$")
# ── Helpers ─────────────────────────────────────────────────────────────────


def allow_interactive_oauth(name: str) -> None:
    from app.agent.mcp.oauth import allow_interactive_oauth as allow

    allow(name)


def clear_cached_oauth(name: str) -> None:
    from app.agent.mcp.oauth import clear_cached_oauth as clear

    clear(name)


def disallow_interactive_oauth(name: str) -> None:
    from app.agent.mcp.oauth import disallow_interactive_oauth as disallow

    disallow(name)


def _config_to_body(
    cfg: StdioServerConfig | HttpServerConfig | None,
) -> StdioServerBody | HttpServerBody | None:
    if cfg is None:
        return None
    if isinstance(cfg, StdioServerConfig):
        return StdioServerBody(
            command=cfg.command,
            args=list(cfg.args),
            env=dict(cfg.env),
            cwd=cfg.cwd,
            capabilities=list(cfg.capabilities),
            enabled=cfg.enabled,
        )
    oauth = None
    if cfg.oauth:
        oauth = OAuthBody(
            client_id=_MASKED_SECRET if cfg.oauth.client_id else None,
            client_secret=_MASKED_SECRET if cfg.oauth.client_secret else None,
        )
    return HttpServerBody(
        url=cfg.url,
        headers={key: _MASKED_SECRET for key in cfg.headers},
        oauth=oauth,
        capabilities=list(cfg.capabilities),
        enabled=cfg.enabled,
    )


def _merge_masked_http_headers(
    new: HttpServerConfig,
    existing: StdioServerConfig | HttpServerConfig | None,
) -> HttpServerConfig:
    if not isinstance(existing, HttpServerConfig):
        return new
    return HttpServerConfig(
        url=new.url,
        headers={
            key: existing.headers[key]
            if value == _MASKED_SECRET and key in existing.headers
            else value
            for key, value in new.headers.items()
        },
        oauth=new.oauth,
        capabilities=new.capabilities,
        enabled=new.enabled,
    )


def _merge_masked_oauth(
    new: HttpServerConfig,
    existing: StdioServerConfig | HttpServerConfig | None,
) -> HttpServerConfig:
    if (
        not isinstance(existing, HttpServerConfig)
        or not new.oauth
        or not existing.oauth
    ):
        return new
    return HttpServerConfig(
        url=new.url,
        headers=new.headers,
        oauth=OAuthBody(
            client_id=existing.oauth.client_id
            if new.oauth.client_id == _MASKED_SECRET
            else new.oauth.client_id,
            client_secret=existing.oauth.client_secret
            if new.oauth.client_secret == _MASKED_SECRET
            else new.oauth.client_secret,
        ).to_config(),
        capabilities=new.capabilities,
        enabled=new.enabled,
    )


def _oauth_env_key(name: str, field: str) -> str:
    prefix = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").upper() or "MCP"
    return f"{prefix}_MCP_{field}"


def _quote_env_value(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _save_env_values(values: dict[str, str]) -> None:
    if not values:
        return
    env_path = Path(settings.EVOFLUX_CONFIG_DIR) / ".env"
    env_path.parent.mkdir(parents=True, exist_ok=True)
    lines = (
        env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    )
    seen: set[str] = set()
    next_lines: list[str] = []
    for line in lines:
        key = (
            line.split("=", 1)[0].strip()
            if "=" in line and not line.lstrip().startswith("#")
            else ""
        )
        if key in values:
            next_lines.append(f"{key}={_quote_env_value(values[key])}")
            seen.add(key)
        else:
            next_lines.append(line)
    for key, value in values.items():
        if key not in seen:
            next_lines.append(f"{key}={_quote_env_value(value)}")
        os.environ[key] = value
    env_path.write_text("\n".join(next_lines) + "\n", encoding="utf-8")
    os.chmod(env_path, 0o600)


def _store_oauth_secrets(name: str, cfg: HttpServerConfig) -> HttpServerConfig:
    if not cfg.oauth:
        return cfg
    env_values: dict[str, str] = {}
    client_id = cfg.oauth.client_id
    client_secret = cfg.oauth.client_secret
    if client_id and client_id != _MASKED_SECRET and not _ENV_REF_RE.match(client_id):
        key = _oauth_env_key(name, "CLIENT_ID")
        env_values[key] = client_id
        client_id = f"${{{key}}}"
    if (
        client_secret
        and client_secret != _MASKED_SECRET
        and not _ENV_REF_RE.match(client_secret)
    ):
        key = _oauth_env_key(name, "CLIENT_SECRET")
        env_values[key] = client_secret
        client_secret = f"${{{key}}}"
    _save_env_values(env_values)
    return HttpServerConfig(
        url=cfg.url,
        headers=cfg.headers,
        oauth=OAuthBody(client_id=client_id, client_secret=client_secret).to_config(),
        capabilities=cfg.capabilities,
        enabled=cfg.enabled,
    )


def _store_stdio_env_secrets(name: str, cfg: StdioServerConfig) -> StdioServerConfig:
    """Write literal env values to .env and replace with ${VAR} refs in config.

    Called when the user enters a real secret value in the Settings UI.
    Values that already look like ${VAR} refs are passed through unchanged.
    """
    env_values: dict[str, str] = {}
    new_env: dict[str, str] = {}
    for key, value in cfg.env.items():
        if value and not _ENV_REF_RE.match(value):
            env_values[key] = value
            new_env[key] = f"${{{key}}}"
        else:
            new_env[key] = value
    _save_env_values(env_values)
    return StdioServerConfig(
        command=cfg.command,
        args=list(cfg.args),
        env=new_env,
        cwd=cfg.cwd,
        capabilities=cfg.capabilities,
        enabled=cfg.enabled,
    )


def _to_response(
    status: MCPServerStatus,
    config: StdioServerConfig | HttpServerConfig | None = None,
) -> ServerStatusResponse:
    return ServerStatusResponse(
        name=status.name,
        transport=status.transport,
        enabled=status.enabled,
        state=status.state,
        error=status.error,
        tool_names=list(status.tool_names),
        started_at=status.started_at,
        config=_config_to_body(config),
    )


def _plugin_to_response(status: dict[str, object]) -> ServerStatusResponse:
    """Adapt the isolated plugin runtime for the unified Settings surface."""

    raw_tool_names = status.get("tool_names")
    tool_names = (
        [str(value) for value in raw_tool_names]
        if isinstance(raw_tool_names, list)
        else []
    )
    return ServerStatusResponse(
        name=str(status["runtime_name"]),
        transport=str(status["transport"]),
        enabled=bool(status["enabled"]),
        state=str(status["state"]),
        error=str(status["error"]) if status.get("error") else None,
        tool_names=tool_names,
        started_at=(
            str(status["started_at"]) if status.get("started_at") else None
        ),
        config=None,
        source="plugin",
        plugin_installation_id=(
            str(status["installation_id"])
            if status.get("installation_id")
            else None
        ),
        plugin_name=(
            str(status["plugin_name"]) if status.get("plugin_name") else None
        ),
        plugin_server_name=(
            str(status["server_name"]) if status.get("server_name") else None
        ),
    )


def _dump_mcp_result(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="json", by_alias=True, exclude_none=True)
        return dumped if isinstance(dumped, dict) else {"content": dumped}
    return value if isinstance(value, dict) else {"content": value}


async def _load_bound_mcp_app(
    db: DbSession, session_id: str, tool_call_id: str
) -> dict[str, Any]:
    try:
        session_uuid = UUID(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid session_id.") from exc

    stmt = (
        select(SessionMessage)
        .where(col(SessionMessage.session_id) == session_uuid)
        .where(col(SessionMessage.role) == "tool")
        .where(col(SessionMessage.tool_call_id) == tool_call_id)
    )
    row = (await db.exec(stmt)).first()
    if row is None:
        raise HTTPException(status_code=404, detail="MCP app artifact not found.")
    extra = row.extra if isinstance(row.extra, dict) else {}
    mcp_app = extra.get("mcp_app")
    if not isinstance(mcp_app, dict):
        raise HTTPException(status_code=404, detail="MCP app artifact not found.")
    return mcp_app


# ── Routes ──────────────────────────────────────────────────────────────────


@router.get("/servers")
async def list_servers() -> ServerListResponse:
    from app.plugin_platform.runtime import plugin_mcp_runtime

    cfg = load_config()
    return ServerListResponse(
        servers=[
            *(
                _to_response(s, cfg.servers.get(s.name))
                for s in mcp_manager.list_status()
            ),
            *(
                _plugin_to_response(status)
                for status in plugin_mcp_runtime.list_status()
            ),
        ]
    )


@router.get("/servers/{name}")
async def get_server(name: str) -> ServerStatusResponse:
    status = mcp_manager.get_status(name)
    if status is not None:
        cfg = load_config()
        return _to_response(status, cfg.servers.get(name))

    from app.plugin_platform.runtime import plugin_mcp_runtime

    plugin_status = next(
        (
            item
            for item in plugin_mcp_runtime.list_status()
            if item.get("runtime_name") == name
        ),
        None,
    )
    if plugin_status is not None:
        return _plugin_to_response(plugin_status)
    raise HTTPException(status_code=404, detail=f"MCP server '{name}' not found.")


@router.post("/app-tools/call")
async def call_mcp_app_tool(
    body: MCPAppToolCallRequest, db: DbSession
) -> MCPAppToolCallResponse:
    mcp_app = await _load_bound_mcp_app(db, body.session_id, body.tool_call_id)
    if mcp_app.get("server") != body.server:
        raise HTTPException(status_code=403, detail="MCP app server mismatch.")

    try:
        try:
            result = await mcp_manager.call_app_tool(
                body.server,
                body.tool,
                body.arguments,
            )
        except KeyError:
            from app.plugin_platform.runtime import plugin_mcp_runtime

            result = await plugin_mcp_runtime.call_app_tool(
                body.server,
                body.tool,
                body.arguments,
            )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="MCP server not found.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail="MCP app tool call failed."
        ) from exc

    return MCPAppToolCallResponse(result=_dump_mcp_result(result))


@router.post("/servers", status_code=201)
async def create_server(body: CreateServerRequest) -> ServerStatusResponse:
    try:
        validate_server_name(body.name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    cfg = load_config()
    if body.name in cfg.servers:
        raise HTTPException(
            status_code=409, detail=f"MCP server '{body.name}' already exists."
        )

    server_cfg: StdioServerConfig | HttpServerConfig = body.server.to_config()
    if isinstance(server_cfg, StdioServerConfig):
        server_cfg = _store_stdio_env_secrets(body.name, server_cfg)
    elif isinstance(server_cfg, HttpServerConfig):
        server_cfg = _store_oauth_secrets(body.name, server_cfg)
    cfg.servers[body.name] = server_cfg
    save_config(cfg)

    status = await mcp_manager.restart_server(body.name)
    return _to_response(status, server_cfg)


@router.put("/servers/{name}")
async def update_server(name: str, body: UpdateServerRequest) -> ServerStatusResponse:
    cfg = load_config()
    if name not in cfg.servers:
        raise HTTPException(status_code=404, detail=f"MCP server '{name}' not found.")

    server_cfg = body.server.to_config()
    if isinstance(server_cfg, StdioServerConfig):
        server_cfg = _store_stdio_env_secrets(name, server_cfg)
    elif isinstance(server_cfg, HttpServerConfig):
        server_cfg = _merge_masked_http_headers(server_cfg, cfg.servers[name])
        server_cfg = _merge_masked_oauth(server_cfg, cfg.servers[name])
        server_cfg = _store_oauth_secrets(name, server_cfg)
    cfg.servers[name] = server_cfg
    save_config(cfg)

    status = await mcp_manager.restart_server(name)
    return _to_response(status, server_cfg)


@router.delete("/servers/{name}")
async def delete_server(name: str) -> ServerDeleteResponse:
    cfg = load_config()
    if name not in cfg.servers:
        raise HTTPException(status_code=404, detail=f"MCP server '{name}' not found.")

    cfg.servers.pop(name)
    save_config(cfg)

    await mcp_manager.remove_runner(name)
    return ServerDeleteResponse(name=name)


@router.post("/servers/{name}/restart")
async def restart_server(name: str) -> ServerStatusResponse:
    try:
        status = await mcp_manager.restart_server(name)
    except KeyError as exc:
        raise HTTPException(
            status_code=404, detail=f"MCP server '{name}' not found."
        ) from exc
    cfg = load_config()
    return _to_response(status, cfg.servers.get(name))


@router.post("/servers/{name}/oauth/connect")
async def connect_oauth(name: str) -> ServerStatusResponse:
    cfg = load_config()
    server_cfg = cfg.servers.get(name)
    if server_cfg is None:
        raise HTTPException(status_code=404, detail=f"MCP server '{name}' not found.")
    if not isinstance(server_cfg, HttpServerConfig) or server_cfg.oauth is None:
        raise HTTPException(
            status_code=400, detail=f"MCP server '{name}' is not configured for OAuth."
        )

    allow_interactive_oauth(name)
    try:
        clear_cached_oauth(name)
        status = await mcp_manager.restart_server(name, ready_timeout=300.0)
    finally:
        disallow_interactive_oauth(name)
    if status.state != "ready":
        raise HTTPException(
            status_code=409,
            detail=status.error or f"MCP server '{name}' did not connect.",
        )
    save_config(cfg)
    return _to_response(status, server_cfg)


@router.post("/apply")
async def apply_config() -> ServerListResponse:
    """Re-read ``mcp.json`` and reconcile every runner."""
    try:
        load_config()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    await mcp_manager.reload_from_config()

    cfg = load_config()
    return ServerListResponse(
        servers=[
            _to_response(s, cfg.servers.get(s.name)) for s in mcp_manager.list_status()
        ]
    )
