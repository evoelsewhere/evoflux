"""Git operation request/response schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class WorkspaceRequest(BaseModel):
    workspace: str


class GitInitRequest(BaseModel):
    workspace: str
    default_branch: str = "main"


class GitIdentityRequest(BaseModel):
    workspace: str
    name: str = Field(min_length=1, max_length=512)
    email: str = Field(min_length=1, max_length=512)


class StageRequest(BaseModel):
    workspace: str
    paths: list[str] | None = None


class CommitRequest(BaseModel):
    workspace: str
    message: str = Field(max_length=10000)
    paths: list[str] | None = None
    amend: bool = False


class BranchCreateRequest(BaseModel):
    workspace: str
    name: str
    start_point: str | None = None
    checkout: bool = True


class BranchDeleteRequest(BaseModel):
    workspace: str
    name: str
    force: bool = False


class CheckoutRequest(BaseModel):
    workspace: str
    name: str
    track: bool = False


class MergeRequest(BaseModel):
    workspace: str
    branch: str


class PushRequest(BaseModel):
    workspace: str
    remote: str | None = None
    branch: str | None = None
    set_upstream: bool = False
    force_with_lease: bool = False


class PullRequest(BaseModel):
    workspace: str
    remote: str | None = None
    branch: str | None = None
    rebase: bool = False


class FetchRequest(BaseModel):
    workspace: str
    remote: str | None = None
    prune: bool = False


class GitRemoteRequest(BaseModel):
    workspace: str
    name: str
    url: str = Field(min_length=1, max_length=4096)


class GitRemoteDeleteRequest(BaseModel):
    workspace: str
    name: str


class GitTagRequest(BaseModel):
    workspace: str
    name: str
    target: str | None = None
    message: str | None = Field(default=None, max_length=10000)


class GitTagDeleteRequest(BaseModel):
    workspace: str
    name: str


class GitTagsPushRequest(BaseModel):
    workspace: str
    remote: str | None = None
    tag: str | None = None


class StashRequest(BaseModel):
    workspace: str
    message: str | None = Field(default=None, max_length=10000)
    include_untracked: bool = False


class StashApplyRequest(BaseModel):
    workspace: str
    index: int = 0


class RebaseRequest(BaseModel):
    workspace: str
    onto: str


class CherryPickRequest(BaseModel):
    workspace: str
    shas: list[str]


class RevertRequest(BaseModel):
    workspace: str
    sha: str


class ChangedFileOut(BaseModel):
    path: str
    status: str
    staged: bool
    old_path: str | None = None


class GitChangesOut(BaseModel):
    is_git_repo: bool = True
    branch: str | None
    ahead: int
    behind: int
    files: list[ChangedFileOut]


class GitRepositoryOut(BaseModel):
    is_git_repo: bool
    root: str | None = None
    branch: str | None = None
    detached: bool = False
    upstream: str | None = None
    head_sha: str | None = None
    head_subject: str | None = None
    user_name: str | None = None
    user_email: str | None = None


class GitRemoteOut(BaseModel):
    name: str
    fetch_url: str
    push_url: str


class GitTagOut(BaseModel):
    name: str
    sha: str
    subject: str
    date: str


class GitCommitOut(BaseModel):
    sha: str
    message: str


class GitBranchOut(BaseModel):
    name: str
    current: bool
    remote: str | None
    ahead: int
    behind: int


class GitMergeOut(BaseModel):
    success: bool
    conflicts: list[str]
    message: str


class GitJobOut(BaseModel):
    workspace: str
    op: str
    status: str
    message: str
    error: str | None = None


class GitLogEntryOut(BaseModel):
    sha: str
    short_sha: str
    parent_shas: list[str]
    refs: list[str]
    author: str
    date: str
    message: str


class GitLogOut(BaseModel):
    entries: list[GitLogEntryOut]
    has_more: bool
    next_skip: int | None = None


class GitLogFileOut(BaseModel):
    path: str
    status: str


class GitStashOut(BaseModel):
    index: int
    message: str
    sha: str


class ConflictedFileOut(BaseModel):
    path: str
    status: str


class GitConflictsOut(BaseModel):
    conflicted: bool
    operation: str | None
    files: list[ConflictedFileOut]
