from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class GitAIRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    action: Literal[
        "self_review",
        "generate_commit_message",
        "explain_commit",
        "generate_pr_description",
        "summarize_pull_request",
        "propose_conflict_resolution",
        "review_resolved_conflicts",
    ]
    reference: str | None = Field(default=None, max_length=512)
    remote_context: dict | None = None


class GitAIResponse(BaseModel):
    kind: Literal["review", "text", "pr", "changes"]
    summary: str
    message: str | None = None
    title: str | None = None
    body: str | None = None
    findings: list[str] = Field(default_factory=list)
    change_set: dict | None = None
    evidence_sha256: str
