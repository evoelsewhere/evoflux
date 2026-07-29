"""Schemas for Git server connections and provider-neutral code reviews."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

GitProvider = Literal[
    "github",
    "gitlab",
    "bitbucket_cloud",
    "bitbucket_server",
    "gitea",
    "azure_devops",
]
ConnectionScope = Literal["server", "repository"]


class GitServerConnectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    provider: GitProvider
    domain: str | None = Field(default=None, min_length=1, max_length=2048)
    base_url: str | None = Field(default=None, min_length=1, max_length=2048)
    scope: ConnectionScope = "server"
    workspace_id: UUID | None = None
    token: str = Field(default="", max_length=10000)
    token_env_var: str | None = Field(default=None, max_length=255)
    username: str | None = Field(default=None, max_length=255)
    verify_ssl: bool = True

    @field_validator("name")
    @classmethod
    def strip_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Value cannot be blank.")
        return value

    @model_validator(mode="after")
    def require_domain(self) -> GitServerConnectionCreate:
        if not (self.domain or self.base_url):
            raise ValueError("Git server domain is required.")
        return self


class GitServerConnectionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    provider: GitProvider | None = None
    domain: str | None = Field(default=None, min_length=1, max_length=2048)
    base_url: str | None = Field(default=None, min_length=1, max_length=2048)
    scope: ConnectionScope | None = None
    workspace_id: UUID | None = None
    token: str | None = Field(default=None, max_length=10000)
    token_env_var: str | None = Field(default=None, max_length=255)
    username: str | None = Field(default=None, max_length=255)
    verify_ssl: bool | None = None


class GitServerConnectionTest(BaseModel):
    provider: GitProvider
    domain: str | None = Field(default=None, min_length=1, max_length=2048)
    base_url: str | None = Field(default=None, min_length=1, max_length=2048)
    token: str = Field(min_length=1, max_length=10000)
    username: str | None = Field(default=None, max_length=255)
    verify_ssl: bool = True

    @model_validator(mode="after")
    def require_domain(self) -> GitServerConnectionTest:
        if not (self.domain or self.base_url):
            raise ValueError("Git server domain is required.")
        return self


class GitServerConnectionOut(BaseModel):
    id: UUID
    name: str
    provider: GitProvider
    domain: str
    base_url: str
    token_url: str
    host: str
    scope: ConnectionScope
    workspace_id: UUID | None
    token_env_var: str
    has_token: bool
    username: str | None
    verify_ssl: bool
    created_at: datetime
    updated_at: datetime


class ReviewItemOut(BaseModel):
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
    labels: list[str]
    review_status: str | None
    pipeline_status: str | None
    comment_count: int | None


class RepositoryReviewsOut(BaseModel):
    workspace_id: UUID
    project_id: UUID | None
    workspace: str
    name: str
    remote_url: str | None
    repository: str | None
    detected_provider: GitProvider | None
    suggested_domain: str | None
    suggested_base_url: str | None
    connection_id: UUID | None
    provider: GitProvider | None
    items: list[ReviewItemOut]
    error: str | None


class ReviewsOut(BaseModel):
    repositories: list[RepositoryReviewsOut]
    total: int


ReviewAction = Literal[
    "comment",
    "inline_comment",
    "reply",
    "resolve_thread",
    "reopen_thread",
    "approve",
    "request_changes",
    "update",
    "checks",
    "merge",
    "close",
    "reopen",
]


class ReviewActionRequest(BaseModel):
    action: ReviewAction
    body: str | None = Field(default=None, max_length=100_000)
    thread_id: str | None = Field(default=None, max_length=512)
    path: str | None = Field(default=None, max_length=4096)
    line: int | None = Field(default=None, gt=0)
    side: Literal["LEFT", "RIGHT"] = "RIGHT"
    commit_id: str | None = Field(default=None, max_length=512)
    base_commit_id: str | None = Field(default=None, max_length=512)
    start_commit_id: str | None = Field(default=None, max_length=512)
    reviewer_id: str | None = Field(default=None, max_length=512)
    idempotency_key: str | None = Field(default=None, max_length=255)
    updates: dict[str, Any] = Field(default_factory=dict)
    merge_method: str | None = Field(default=None, max_length=64)
    commit_title: str | None = Field(default=None, max_length=1000)
