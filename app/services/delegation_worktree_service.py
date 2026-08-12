"""Git worktree isolation for durable team delegations.

The lead owns policy and merge decisions. Members only receive a sandbox
already bound to their task worktree (or worktree set); they never manipulate
the orchestration branches directly.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
from typing import Literal

from app.agent.sandbox_config import selected_worktree_root

Isolation = Literal["shared", "worktree"]

_SESSION_CHARS = 12
_locks: dict[str, asyncio.Lock] = {}


class DelegationWorktreeError(RuntimeError):
    """A managed delegation worktree operation could not complete safely."""


@dataclass(frozen=True)
class TaskSandboxBinding:
    workspace: str
    extra_workspace_paths: list[str]
    read_only_paths: list[str]
    write_allowed_paths: list[str]


def resolve_isolation(
    *,
    requested: str,
    team_mode: str,
    target_paths: list[str],
    target_repos: list[str],
) -> Isolation:
    """Resolve the lead policy without consulting mutable filesystem state."""
    if requested == "shared":
        return "shared"
    if requested == "worktree":
        if team_mode != "coding":
            raise ValueError("Worktree isolation is only available in coding teams.")
        return "worktree"
    if requested != "auto":
        raise ValueError(f"Unknown delegation isolation policy: {requested!r}.")
    if team_mode == "coding" and (target_paths or target_repos):
        return "worktree"
    return "shared"


def allocation_from_spec(spec: dict) -> dict | None:
    value = spec.get("worktree_allocation")
    return value if isinstance(value, dict) else None


def sandbox_binding(
    *,
    primary_workspace: str,
    extra_workspace_paths: list[str],
    read_only_paths: list[str],
    active_specs: list[dict],
) -> TaskSandboxBinding:
    """Translate a member's repository map to its active worktree set."""
    primary = Path(primary_workspace).resolve()
    extras = [Path(path).resolve() for path in extra_workspace_paths]
    read_only = [Path(path).resolve() for path in read_only_paths]
    allocations = [
        allocation
        for spec in active_specs
        if (allocation := allocation_from_spec(spec)) is not None
        and allocation.get("state") in {"active", "review", "conflict"}
    ]
    if not allocations:
        claims = sorted(
            {
                str(path)
                for spec in active_specs
                for path in spec.get("target_paths", [])
                if isinstance(path, str) and path
            }
        )
        return TaskSandboxBinding(
            workspace=str(primary),
            extra_workspace_paths=[str(path) for path in extras],
            read_only_paths=[str(path) for path in read_only],
            write_allowed_paths=claims,
        )
    if len(allocations) > 1:
        raise DelegationWorktreeError(
            "One member has multiple active isolated delegations. "
            "Use one spawned member per parallel worktree task."
        )

    allocation = allocations[0]
    mapped: dict[Path, Path] = {}
    for item in allocation.get("repositories", []):
        if not isinstance(item, dict):
            continue
        source = item.get("source")
        workspace = item.get("workspace")
        if isinstance(source, str) and isinstance(workspace, str):
            mapped[Path(source).resolve()] = Path(workspace).resolve()

    mapped_primary = mapped.get(primary, primary)
    mapped_extras = [mapped.get(path, path) for path in extras]
    unallocated_sources = [
        path
        for path in [primary, *extras]
        if path not in mapped and path not in read_only
    ]
    mapped_read_only = [
        *(mapped.get(path, path) for path in read_only),
        *unallocated_sources,
    ]
    claims = [str(path) for path in mapped.values()]
    return TaskSandboxBinding(
        workspace=str(mapped_primary),
        extra_workspace_paths=[
            str(path) for path in mapped_extras if path != mapped_primary
        ],
        read_only_paths=[str(path) for path in mapped_read_only],
        write_allowed_paths=claims,
    )


async def allocate(
    *,
    task_id: str,
    recipient: str,
    session_id: str,
    primary_workspace: str,
    extra_workspace_paths: list[str],
    read_only_paths: list[str],
    spec: dict,
) -> dict:
    """Create one task worktree in every selected writable repository."""
    existing = allocation_from_spec(spec)
    if existing is not None:
        return existing
    if spec.get("resolved_isolation") != "worktree":
        raise DelegationWorktreeError("Task does not request worktree isolation.")

    repositories = _resolve_target_repositories(
        primary_workspace=primary_workspace,
        extra_workspace_paths=extra_workspace_paths,
        read_only_paths=read_only_paths,
        selectors=[
            str(item) for item in spec.get("target_repos", []) if isinstance(item, str)
        ],
    )
    created: list[dict] = []
    try:
        for source in repositories:
            created.append(
                await _allocate_repository(
                    source=source,
                    task_id=task_id,
                    recipient=recipient,
                    session_id=session_id,
                )
            )
    except Exception:
        for item in reversed(created):
            await _remove_task_worktree(item, delete_branch=True, force=True)
        raise
    return {
        "version": 1,
        "state": "active",
        "task_id": task_id,
        "recipient": recipient,
        "repositories": created,
    }


async def snapshot(allocation: dict) -> tuple[dict, dict]:
    """Commit every dirty task worktree and return review metadata."""
    if allocation.get("state") not in {"active", "conflict"}:
        raise DelegationWorktreeError(
            "Only active or rejected-conflict worktrees can be snapshotted."
        )
    updated = _copy_allocation(allocation)
    reviews: list[dict] = []
    for item in updated.get("repositories", []):
        workspace = Path(str(item["workspace"]))
        await _git(workspace, "add", "--all")
        staged = await _git(workspace, "diff", "--cached", "--quiet", check=False)
        if staged.returncode not in {0, 1}:
            raise DelegationWorktreeError(_git_detail(staged))
        if staged.returncode == 1:
            await _git(
                workspace,
                "-c",
                "user.name=EvoFlux",
                "-c",
                "user.email=evoflux@localhost",
                "commit",
                "--no-verify",
                "-m",
                f"chore(evoflux): delegation {allocation.get('task_id', 'task')}",
            )
        head = (await _git(workspace, "rev-parse", "HEAD")).stdout.strip()
        base = str(item["base_commit"])
        stat = (
            await _git(workspace, "diff", "--stat", f"{base}..{head}")
        ).stdout.strip()
        names = (
            await _git(workspace, "diff", "--name-only", f"{base}..{head}")
        ).stdout.splitlines()
        item["snapshot_commit"] = head
        item["state"] = "review"
        reviews.append(
            {
                "source": item["source"],
                "branch": item["branch"],
                "commit": head,
                "changed_files": names,
                "diff_stat": stat,
            }
        )
    updated["state"] = "review"
    return updated, {"state": "review", "repositories": reviews}


async def review(allocation: dict) -> str:
    """Render deterministic per-repository diff summaries."""
    lines = [
        f"Delegation worktree {allocation.get('task_id', '')}",
        f"state: {allocation.get('state', 'unknown')}",
    ]
    for item in allocation.get("repositories", []):
        source = Path(str(item["source"]))
        integration = str(item["integration_branch"])
        snapshot_commit = await _validated_snapshot_commit(item)
        result = await _git(
            source, "diff", "--stat", f"{integration}...{snapshot_commit}"
        )
        names = await _git(
            source, "diff", "--name-status", f"{integration}...{snapshot_commit}"
        )
        lines.extend(
            [
                "",
                f"repo: {source}",
                f"branch: {item['branch']}",
                f"commit: {snapshot_commit}",
                result.stdout.strip() or "(no diff)",
                names.stdout.strip() or "(no changed files)",
            ]
        )
    return "\n".join(lines)


async def merge(allocation: dict) -> tuple[dict, str]:
    """Merge a worktree set into session integration branches atomically."""
    if allocation.get("state") not in {"review", "conflict"}:
        raise DelegationWorktreeError("Only reviewed worktrees can be merged.")
    updated = _copy_allocation(allocation)
    repositories = [
        item for item in updated.get("repositories", []) if isinstance(item, dict)
    ]
    lock_sources = sorted(
        {str(Path(str(item["source"])).resolve()) for item in repositories}
    )
    locks = [_repo_lock(source) for source in lock_sources]
    for lock in locks:
        await lock.acquire()
    original_heads: dict[str, str] = {}
    snapshot_commits: dict[str, str] = {}
    merged: list[dict] = []
    try:
        for item in repositories:
            integration_ws = Path(str(item["integration_workspace"]))
            status = await _git(integration_ws, "status", "--porcelain")
            if status.stdout.strip():
                raise DelegationWorktreeError(
                    f"Integration worktree is dirty: {integration_ws}"
                )
            original_heads[str(item["source"])] = (
                await _git(integration_ws, "rev-parse", "HEAD")
            ).stdout.strip()
            snapshot_commit = await _validated_snapshot_commit(item)
            snapshot_commits[str(item["source"])] = snapshot_commit
            already_merged = await _git(
                integration_ws,
                "merge-base",
                "--is-ancestor",
                snapshot_commit,
                "HEAD",
                check=False,
            )
            workspace = Path(str(item["workspace"]))
            if workspace.exists():
                task_status = await _git(workspace, "status", "--porcelain")
                if task_status.stdout.strip():
                    raise DelegationWorktreeError(
                        "Task worktree changed after its final handoff; reject/reopen "
                        f"the task before merging: {workspace}"
                    )
            elif already_merged.returncode != 0:
                raise DelegationWorktreeError(
                    f"Task worktree is missing before merge: {workspace}"
                )

        for item in repositories:
            integration_ws = Path(str(item["integration_workspace"]))
            result = await _git(
                integration_ws,
                "-c",
                "user.name=EvoFlux",
                "-c",
                "user.email=evoflux@localhost",
                "merge",
                "--no-ff",
                "--no-edit",
                snapshot_commits[str(item["source"])],
                check=False,
            )
            if result.returncode != 0:
                await _git(integration_ws, "merge", "--abort", check=False)
                raise DelegationWorktreeError(
                    f"Merge conflict in {item['source']}: {_git_detail(result)}"
                )
            item["integration_commit"] = (
                await _git(integration_ws, "rev-parse", "HEAD")
            ).stdout.strip()
            item["state"] = "merged"
            merged.append(item)
    except Exception as exc:
        for item in repositories:
            old_head = original_heads.get(str(item["source"]))
            if old_head:
                integration_ws = Path(str(item["integration_workspace"]))
                await _git(integration_ws, "merge", "--abort", check=False)
                await _git(integration_ws, "reset", "--hard", old_head, check=False)
        updated["state"] = "conflict"
        updated["last_error"] = str(exc)
        return updated, str(exc)
    finally:
        for lock in reversed(locks):
            lock.release()

    for item in merged:
        await _remove_task_worktree(item, delete_branch=False, force=False)
    updated["state"] = "merged"
    updated.pop("last_error", None)
    summary = "\n".join(
        f"{item['source']}: {item['integration_commit']}" for item in merged
    )
    return updated, summary


async def discard(allocation: dict) -> dict:
    """Remove an unmerged task worktree set and its branches."""
    if allocation.get("state") == "merged":
        raise DelegationWorktreeError(
            "Merged work cannot be discarded; finalize or keep the integration branch."
        )
    updated = _copy_allocation(allocation)
    for item in updated.get("repositories", []):
        await _remove_task_worktree(item, delete_branch=True, force=True)
        item["state"] = "discarded"
    updated["state"] = "discarded"
    return updated


async def finalize(
    allocations: list[dict],
    *,
    target_repos: list[str] | None = None,
) -> tuple[list[dict], str]:
    """Fast-forward clean source branches to their session integrations."""
    repo_items: dict[str, dict] = {}
    items_by_source: dict[str, list[dict]] = {}
    for allocation in allocations:
        for item in allocation.get("repositories", []):
            if not isinstance(item, dict) or item.get("state") != "merged":
                continue
            source = str(Path(str(item["source"])).resolve())
            items_by_source.setdefault(source, []).append(item)
            repo_items[source] = item
    selected_sources = _resolve_finalize_selectors(
        set(repo_items), target_repos=target_repos
    )
    repo_items = {
        source: item
        for source, item in repo_items.items()
        if source in selected_sources
    }
    if not repo_items:
        raise DelegationWorktreeError("No merged integration repositories found.")

    originals: dict[str, str] = {}
    integration_heads: dict[str, str] = {}
    needs_fast_forward: set[str] = set()
    locks = [_repo_lock(source) for source in sorted(repo_items)]
    for lock in locks:
        await lock.acquire()
    try:
        for source_raw, item in repo_items.items():
            _validate_repository_allocation_consistency(
                source_raw, items_by_source[source_raw]
            )
            source = Path(source_raw)
            if (await _git(source, "status", "--porcelain")).stdout.strip():
                raise DelegationWorktreeError(f"Source repository is dirty: {source}")
            branch = (await _git(source, "branch", "--show-current")).stdout.strip()
            if not branch or branch != item.get("source_branch"):
                raise DelegationWorktreeError(
                    f"Source branch changed for {source}: expected "
                    f"{item.get('source_branch')!r}, found {branch!r}."
                )
            head = (await _git(source, "rev-parse", "HEAD")).stdout.strip()
            integration_branch = str(item["integration_branch"])
            branch_available = await _branch_exists(source, integration_branch)
            if branch_available:
                integration_head = (
                    await _git(source, "rev-parse", integration_branch)
                ).stdout.strip()
            else:
                recorded_integration_heads = {
                    str(candidate.get("integration_commit"))
                    for candidate in items_by_source[source_raw]
                    if candidate.get("integration_commit")
                }
                if head not in recorded_integration_heads:
                    raise DelegationWorktreeError(
                        f"Integration branch is missing for {source} and source HEAD "
                        "does not match a recorded integration commit."
                    )
                integration_head = head
            integration_heads[source_raw] = integration_head
            if head == item.get("source_base_commit"):
                if not branch_available:
                    raise DelegationWorktreeError(
                        f"Integration branch is missing before finalize: "
                        f"{integration_branch}"
                    )
                needs_fast_forward.add(source_raw)
            elif head != integration_head:
                raise DelegationWorktreeError(
                    f"Source HEAD changed for {source}; expected the original base or "
                    "the already-finalized integration commit."
                )
            if branch_available:
                ancestor = await _git(
                    source,
                    "merge-base",
                    "--is-ancestor",
                    head,
                    integration_branch,
                    check=False,
                )
                if ancestor.returncode != 0:
                    raise DelegationWorktreeError(
                        f"Integration branch is not a descendant of {source} HEAD."
                    )
            originals[source_raw] = head

        finalized: list[str] = []
        try:
            for source_raw, item in repo_items.items():
                if source_raw not in needs_fast_forward:
                    continue
                source = Path(source_raw)
                await _git(
                    source, "merge", "--ff-only", str(item["integration_branch"])
                )
                finalized.append(source_raw)
        except Exception:
            for source_raw in finalized:
                await _git(
                    Path(source_raw),
                    "reset",
                    "--hard",
                    originals[source_raw],
                    check=False,
                )
            raise
    finally:
        for lock in reversed(locks):
            lock.release()

    updated_allocations = [_copy_allocation(value) for value in allocations]
    for allocation in updated_allocations:
        touched = False
        for item in allocation.get("repositories", []):
            source = str(Path(str(item["source"])).resolve())
            if source not in repo_items:
                continue
            item["state"] = "finalized"
            item["finalized_commit"] = integration_heads[source]
            touched = True
        if touched and all(
            item.get("state") == "finalized"
            for item in allocation.get("repositories", [])
        ):
            allocation["state"] = "finalized"
    return updated_allocations, "\n".join(
        f"{source}: finalized {item['integration_branch']}"
        for source, item in repo_items.items()
    )


async def cleanup_finalized(allocations: list[dict]) -> list[str]:
    """Best-effort cleanup after finalized allocation state is durable."""
    warnings: list[str] = []
    integrations: dict[tuple[str, str], str] = {}
    task_branches: set[tuple[str, str]] = set()
    for allocation in allocations:
        for item in allocation.get("repositories", []):
            if not isinstance(item, dict) or item.get("state") != "finalized":
                continue
            source = str(Path(str(item["source"])).resolve())
            integrations[(source, str(item["integration_branch"]))] = str(
                item["integration_workspace"]
            )
            task_branches.add((source, str(item["branch"])))

    for (source_raw, branch), workspace_raw in integrations.items():
        source = Path(source_raw)
        workspace = Path(workspace_raw)
        if workspace.exists():
            result = await _git(
                source, "worktree", "remove", str(workspace), check=False
            )
            if result.returncode != 0 and workspace.exists():
                warnings.append(
                    f"Could not remove integration worktree {workspace}: "
                    f"{_git_detail(result)}"
                )
                continue
        result = await _git(source, "branch", "-D", branch, check=False)
        if result.returncode != 0 and await _branch_exists(source, branch):
            warnings.append(
                f"Could not delete integration branch {branch}: {_git_detail(result)}"
            )

    for source_raw, branch in sorted(task_branches):
        source = Path(source_raw)
        result = await _git(source, "branch", "-D", branch, check=False)
        if result.returncode != 0 and await _branch_exists(source, branch):
            warnings.append(
                f"Could not delete task branch {branch}: {_git_detail(result)}"
            )
    return warnings


def _resolve_target_repositories(
    *,
    primary_workspace: str,
    extra_workspace_paths: list[str],
    read_only_paths: list[str],
    selectors: list[str],
) -> list[Path]:
    if not primary_workspace:
        raise DelegationWorktreeError(
            "Worktree isolation requires an explicit primary project repository."
        )
    primary = Path(primary_workspace).resolve()
    available = list(
        dict.fromkeys(
            [primary, *(Path(path).resolve() for path in extra_workspace_paths)]
        )
    )
    read_only = {Path(path).resolve() for path in read_only_paths}
    if not selectors:
        selected = [primary]
    else:
        selected = []
        for selector in selectors:
            candidate = Path(selector).expanduser()
            matches = (
                [path for path in available if path == candidate.resolve()]
                if candidate.is_absolute()
                else [path for path in available if path.name == selector]
            )
            if len(matches) != 1:
                raise DelegationWorktreeError(
                    f"Repository selector {selector!r} matched {len(matches)} "
                    "project repositories; use an exact absolute path."
                )
            if matches[0] not in selected:
                selected.append(matches[0])
    for source in selected:
        if source in read_only:
            raise DelegationWorktreeError(
                f"Cannot allocate a writable worktree for read-only repository: {source}"
            )
        result = _git_sync(source, "rev-parse", "--is-inside-work-tree")
        if result.returncode != 0 or result.stdout.strip() != "true":
            raise DelegationWorktreeError(f"Not a git repository: {source}")
        top_level = _git_sync(source, "rev-parse", "--show-toplevel")
        if (
            top_level.returncode != 0
            or Path(top_level.stdout.strip()).resolve() != source
        ):
            raise DelegationWorktreeError(
                f"Project repository must be configured at its Git root: {source}"
            )
    return selected


async def _allocate_repository(
    *,
    source: Path,
    task_id: str,
    recipient: str,
    session_id: str,
) -> dict:
    lock = _repo_lock(str(source))
    async with lock:
        integration = await _ensure_integration(source, session_id)
        root = selected_worktree_root(source)
        task_short = _slug(task_id)[:12]
        repo_slug = _slug(source.name)[:24]
        recipient_slug = _slug(recipient)[:24]
        name = f"{recipient_slug}-{task_short}-{repo_slug}"
        workspace = (root / name).resolve()
        if workspace.parent != root:
            raise DelegationWorktreeError("Managed worktree path traversal rejected.")
        branch = (
            f"EvoFlux/task/{_session_slug(session_id)}/"
            f"{recipient_slug}/{task_short}/{repo_slug}"
        )
        if (
            workspace.exists()
            or (
                await _git(
                    source,
                    "show-ref",
                    "--verify",
                    "--quiet",
                    f"refs/heads/{branch}",
                    check=False,
                )
            ).returncode
            == 0
        ):
            raise DelegationWorktreeError(
                f"Delegation worktree already exists for task {task_id}: {workspace}"
            )
        await _git(
            source,
            "worktree",
            "add",
            "--no-checkout",
            "-b",
            branch,
            str(workspace),
            str(integration["branch"]),
        )
        try:
            await _git(workspace, "reset", "--hard", str(integration["branch"]))
        except Exception:
            await _git(
                source, "worktree", "remove", "--force", str(workspace), check=False
            )
            await _git(source, "branch", "-D", branch, check=False)
            raise
        base_commit = (await _git(workspace, "rev-parse", "HEAD")).stdout.strip()
        return {
            "source": str(source),
            "source_branch": integration["source_branch"],
            "source_base_commit": integration["source_base_commit"],
            "workspace": str(workspace),
            "branch": branch,
            "base_commit": base_commit,
            "integration_workspace": integration["workspace"],
            "integration_branch": integration["branch"],
            "state": "active",
        }


async def _ensure_integration(source: Path, session_id: str) -> dict:
    slug = _session_slug(session_id)
    branch = f"EvoFlux/integration/{slug}"
    workspace = (selected_worktree_root(source) / f"integration-{slug}").resolve()
    source_branch = (await _git(source, "branch", "--show-current")).stdout.strip()
    if not source_branch:
        raise DelegationWorktreeError(
            f"Source repository must be on a branch, not detached HEAD: {source}"
        )
    source_head = (await _git(source, "rev-parse", "HEAD")).stdout.strip()
    branch_exists = (
        await _git(
            source,
            "show-ref",
            "--verify",
            "--quiet",
            f"refs/heads/{branch}",
            check=False,
        )
    ).returncode == 0
    if branch_exists:
        contains_source = await _git(
            source,
            "merge-base",
            "--is-ancestor",
            source_head,
            branch,
            check=False,
        )
        if contains_source.returncode != 0:
            raise DelegationWorktreeError(
                f"Source HEAD changed after integration started for {source}; "
                "finalize or discard the existing session worktrees first."
            )
    if not workspace.exists():
        if branch_exists:
            await _git(source, "worktree", "add", str(workspace), branch)
        else:
            await _git(
                source,
                "worktree",
                "add",
                "-b",
                branch,
                str(workspace),
                source_head,
            )
    integration_base = (
        await _git(source, "merge-base", branch, source_head)
    ).stdout.strip()
    return {
        "workspace": str(workspace),
        "branch": branch,
        "source_branch": source_branch,
        "source_base_commit": integration_base,
    }


async def _remove_task_worktree(
    item: dict, *, delete_branch: bool, force: bool
) -> None:
    source = Path(str(item["source"]))
    workspace = Path(str(item["workspace"]))
    args = ["worktree", "remove"]
    if force:
        args.append("--force")
    args.append(str(workspace))
    await _git(source, *args, check=False)
    if delete_branch:
        await _git(source, "branch", "-D", str(item["branch"]), check=False)


def _repo_lock(source: str) -> asyncio.Lock:
    key = str(Path(source).resolve())
    lock = _locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _locks[key] = lock
    return lock


def _session_slug(session_id: str) -> str:
    return _slug(session_id)[:_SESSION_CHARS]


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "task"


def _copy_allocation(allocation: dict) -> dict:
    return {
        **allocation,
        "repositories": [
            dict(item)
            for item in allocation.get("repositories", [])
            if isinstance(item, dict)
        ],
    }


async def _validated_snapshot_commit(item: dict) -> str:
    snapshot_commit = item.get("snapshot_commit")
    if not isinstance(snapshot_commit, str) or not snapshot_commit:
        raise DelegationWorktreeError(
            f"Worktree branch has no final snapshot: {item.get('branch')}"
        )
    source = Path(str(item["source"]))
    branch_head = (await _git(source, "rev-parse", str(item["branch"]))).stdout.strip()
    if branch_head != snapshot_commit:
        raise DelegationWorktreeError(
            "Task branch changed after its final handoff; reject/reopen the task "
            f"before merging: {item['branch']}"
        )
    return snapshot_commit


def _resolve_finalize_selectors(
    available_sources: set[str],
    *,
    target_repos: list[str] | None,
) -> set[str]:
    if not target_repos:
        return set(available_sources)
    selected: set[str] = set()
    for raw in target_repos:
        candidate = Path(raw).expanduser()
        if candidate.is_absolute():
            matches = {
                source
                for source in available_sources
                if Path(source).resolve() == candidate.resolve()
            }
        else:
            matches = {
                source for source in available_sources if Path(source).name == raw
            }
        if len(matches) != 1:
            raise DelegationWorktreeError(
                f"Finalize repository selector {raw!r} matched {len(matches)} "
                "repositories; use an exact absolute path."
            )
        selected.update(matches)
    return selected


def _validate_repository_allocation_consistency(source: str, items: list[dict]) -> None:
    integration_branches = {str(item.get("integration_branch")) for item in items}
    source_branches = {str(item.get("source_branch")) for item in items}
    source_bases = {str(item.get("source_base_commit")) for item in items}
    if (
        len(integration_branches) != 1
        or len(source_branches) != 1
        or len(source_bases) != 1
    ):
        raise DelegationWorktreeError(
            f"Inconsistent integration metadata for {source}; source branch or "
            "base changed during the session."
        )


async def _branch_exists(source: Path, branch: str) -> bool:
    return (
        await _git(
            source,
            "show-ref",
            "--verify",
            "--quiet",
            f"refs/heads/{branch}",
            check=False,
        )
    ).returncode == 0


def _git_sync(workspace: Path, *args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", "-C", str(workspace), *args],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DelegationWorktreeError(f"git failed in {workspace}: {exc}") from exc


async def _git(
    workspace: Path,
    *args: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = await asyncio.to_thread(_git_sync, workspace, *args)
    if check and result.returncode != 0:
        raise DelegationWorktreeError(_git_detail(result))
    return result


def _git_detail(result: subprocess.CompletedProcess[str]) -> str:
    return result.stderr.strip() or result.stdout.strip() or "git command failed"
