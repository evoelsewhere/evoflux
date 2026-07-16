"""API DTOs for the Workflows engine (plan §8)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class WorkflowInputOut(BaseModel):
    name: str
    type: str
    required: bool
    default: Any | None = None
    options: list[str] | None = None
    description: str = ""


class WorkflowListItem(BaseModel):
    name: str
    description: str
    scope: str
    inputs: list[WorkflowInputOut]
    hash: str
    root: str
    source_path: str
    approved: bool
    valid: bool
    errors: list[str]
    node_count: int


class WorkflowListResponse(BaseModel):
    workflows: list[WorkflowListItem]


class WorkflowDetailResponse(BaseModel):
    name: str
    raw_yaml: str
    graph: dict
    hash: str
    root: str
    scope: str | None = None
    approved: bool
    manifest: dict
    lint_warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class WorkflowSaveRequest(BaseModel):
    raw_yaml: str | None = None
    graph: dict | None = None


class WorkflowApproveRequest(BaseModel):
    hash: str = Field(min_length=64, max_length=64)


class WorkflowRunRequest(BaseModel):
    session_id: str
    inputs: dict[str, Any] = Field(default_factory=dict)


class WorkflowRunResponse(BaseModel):
    execution_id: UUID
    session_id: str


class WorkflowNodeRunOut(BaseModel):
    id: UUID
    node_id: str
    iteration: int | None
    status: str
    output: dict | None
    error: str | None
    started_at: datetime
    ended_at: datetime | None


class WorkflowExecutionOut(BaseModel):
    id: UUID
    definition_name: str
    definition_hash: str
    session_id: UUID
    status: str
    error: str | None
    outputs: dict
    started_at: datetime
    ended_at: datetime | None
    # True while the in-memory runner is actually driving this execution.
    # A 'running'/'waiting_gate' row without it means the backend restarted
    # mid-run and the DB row is orphaned — readers should show "interrupted".
    live: bool = False


class WorkflowExecutionDetailResponse(BaseModel):
    execution: WorkflowExecutionOut
    node_runs: list[WorkflowNodeRunOut]


class WorkflowExecutionListResponse(BaseModel):
    executions: list[WorkflowExecutionOut]
