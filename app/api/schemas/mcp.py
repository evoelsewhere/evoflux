"""Request and response schemas for ``/api/mcp`` endpoints."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agent.mcp.config import HttpServerConfig, OAuthConfig, StdioServerConfig


class StdioServerBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transport: Literal["stdio"] = "stdio"
    command: Annotated[str, Field(min_length=1)]
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True

    def to_config(self) -> StdioServerConfig:
        return StdioServerConfig(
            command=self.command,
            args=self.args,
            env=self.env,
            enabled=self.enabled,
        )


class OAuthBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_id: str | None = None
    client_secret: str | None = None

    def to_config(self) -> OAuthConfig:
        return OAuthConfig(
            client_id=self.client_id,
            client_secret=self.client_secret,
        )


class HttpServerBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transport: Literal["http"] = "http"
    url: Annotated[str, Field(min_length=1)]
    headers: dict[str, str] = Field(default_factory=dict)
    oauth: OAuthBody | None = None
    enabled: bool = True

    def to_config(self) -> HttpServerConfig:
        return HttpServerConfig(
            url=self.url,
            headers=self.headers,
            oauth=self.oauth.to_config() if self.oauth else None,
            enabled=self.enabled,
        )


ServerBody = StdioServerBody | HttpServerBody


class CreateServerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(min_length=1)]
    server: ServerBody = Field(discriminator="transport")


class UpdateServerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    server: ServerBody = Field(discriminator="transport")


class ServerStatusResponse(BaseModel):
    """Live runner state plus the saved config from ``mcp.json``."""

    name: str
    transport: str
    enabled: bool
    state: str
    error: str | None = None
    tool_names: list[str] = Field(default_factory=list)
    started_at: str | None = None
    config: ServerBody | None = Field(default=None, discriminator="transport")


class ServerListResponse(BaseModel):
    servers: list[ServerStatusResponse]


class ServerDeleteResponse(BaseModel):
    name: str


class MCPAppToolCallRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    tool_call_id: str
    server: Annotated[str, Field(min_length=1)]
    tool: Annotated[str, Field(min_length=1)]
    arguments: dict[str, Any] = Field(default_factory=dict)


class MCPAppToolCallResponse(BaseModel):
    result: dict[str, Any]
