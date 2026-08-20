"""Explicit AI assistance for repository review and Git workflows."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.agent.outbound_redaction import (
    OutboundContext,
    load_outbound_data_policy,
    load_outbound_pii_policy,
    protect_outbound_payload,
)
from app.agent.providers.base import LLMProviderBase
from app.agent.schemas.chat import ChatMessage, HumanMessage, SystemMessage
from app.services.change_set_service import (
    ChangeFileInput,
    ChangeSetError,
    ChangeSetStale,
    create_change_set,
    normalize_change_path,
    serialize_change_set,
)
from app.services.git_ops import run_git
from app.services.problems_service import ProblemInput, list_problems, publish_problems

GitAIAction = Literal[
    "self_review",
    "generate_commit_message",
    "explain_commit",
    "generate_pr_description",
    "summarize_pull_request",
    "propose_conflict_resolution",
    "review_resolved_conflicts",
]

_MAX_EVIDENCE = 180_000
_MAX_UNTRACKED_FILES = 50
_MAX_UNTRACKED_FILE_BYTES = 32_000
_MAX_UNTRACKED_TOTAL_BYTES = 96_000
_SYSTEM_PROMPT = """You are EvoFlux's explicit Git review engine. Return one
JSON object and no Markdown fence. Ground every finding in the supplied diff,
diagnostics, project rules, test evidence, or code-impact evidence. Do not
invent tests or claim verification passed. Conflict resolutions must return
complete UTF-8 file contents and preserve both intended behaviors.
PR drafts must describe only the committed source-to-target branch range in
the supplied evidence, including validation status without inventing results.

Schema:
{
  "kind": "review" | "text" | "pr" | "changes",
  "summary": "short result",
  "message": "commit message or explanation",
  "title": "PR title",
  "body": "PR description",
  "findings": [{"title":"...", "message":"...", "severity":"error|warning|info|hint", "path":"relative", "line":1, "code":"rule", "source":"ai_review|security"}],
  "files": [{"path":"relative", "proposed_content":"complete resolved file"}]
}
"""


class _Finding(BaseModel):
    model_config = ConfigDict(extra="ignore")
    title: str | None = None
    message: str = Field(min_length=1, max_length=8000)
    severity: Literal["error", "warning", "info", "hint"] = "warning"
    path: str | None = None
    line: int | None = Field(default=None, ge=1)
    code: str | None = None
    source: Literal["ai_review", "security"] = "ai_review"


class _File(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    proposed_content: str = Field(max_length=2_000_000)


class _Output(BaseModel):
    model_config = ConfigDict(extra="ignore")
    kind: Literal["review", "text", "pr", "changes"]
    summary: str
    message: str | None = None
    title: str | None = None
    body: str | None = None
    findings: list[_Finding] = Field(default_factory=list, max_length=200)
    files: list[_File] = Field(default_factory=list, max_length=100)


async def run_git_ai_action(
    *,
    workspace: Path,
    provider: LLMProviderBase,
    action: GitAIAction,
    session_id: str,
    reference: str | None = None,
    remote_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = workspace.resolve()
    evidence = await _evidence(root, action, reference, remote_context)
    human: list[ChatMessage] = [
        HumanMessage(
            content=json.dumps(
                {"action": action, "reference": reference, "evidence": evidence},
                ensure_ascii=False,
            )
        )
    ]
    prompt, messages, _report = protect_outbound_payload(
        system_prompt=_SYSTEM_PROMPT,
        messages=human,
        policy=load_outbound_data_policy(),
        pii_policy=load_outbound_pii_policy(),
        context=OutboundContext(
            channel="model", destination=getattr(provider, "provider_name", None)
        ),
    )
    provider_messages: list[ChatMessage] = [SystemMessage(content=prompt), *messages]
    try:
        async with asyncio.timeout(90):
            response = await provider.chat(
                provider_messages, max_tokens=16_000, temperature=0.1
            )
    except TimeoutError as exc:
        raise ValueError("AI Git action timed out.") from exc
    output = _parse_output(response.content or "")
    _validate_action_output(action, output)
    result: dict[str, Any] = {
        "kind": output.kind,
        "summary": output.summary,
        "message": output.message,
        "title": output.title,
        "body": output.body,
        "findings": [],
        "change_set": None,
        "evidence_sha256": hashlib.sha256(
            json.dumps(evidence, sort_keys=True).encode()
        ).hexdigest(),
    }
    if output.findings:
        grouped: dict[str, list[ProblemInput]] = {"ai_review": [], "security": []}
        for item in output.findings:
            grouped[item.source].append(
                ProblemInput(
                    title=item.title,
                    message=item.message,
                    severity=item.severity,
                    path=item.path,
                    line=item.line,
                    code=item.code,
                    provenance={
                        "producer": "git-ai",
                        "action": action,
                        "evidence_sha256": result["evidence_sha256"],
                    },
                )
            )
        ids: list[str] = []
        sources: tuple[Literal["ai_review", "security"], ...] = (
            "ai_review",
            "security",
        )
        for source in sources:
            inputs = grouped[source]
            rows = publish_problems(
                root,
                source=source,
                scope=f"git-ai:{action}:{result['evidence_sha256'][:16]}",
                problems=inputs,
                session_id=session_id,
            )
            ids.extend(row.id for row in rows)
        result["findings"] = ids
    if output.files:
        record = create_change_set(
            root,
            origin="git",
            title=output.summary,
            description=output.message,
            files=_guarded_conflict_inputs(root, evidence, output.files),
        )
        result["change_set"] = serialize_change_set(record)
    return result


async def _evidence(
    workspace: Path,
    action: GitAIAction,
    reference: str | None,
    remote_context: dict[str, Any] | None,
) -> dict[str, Any]:
    if action == "explain_commit":
        ref = await _verified_commit(workspace, reference or "HEAD")
        shown = await run_git(
            str(workspace),
            "show",
            "--stat",
            "--patch",
            "--no-ext-diff",
            ref,
            timeout=10,
            max_output_bytes=_MAX_EVIDENCE,
        )
        return {"commit": shown.stdout[:_MAX_EVIDENCE]}
    if action == "summarize_pull_request":
        return {"pull_request": _bounded_json(remote_context or {})}
    if action == "propose_conflict_resolution":
        return {"conflicts": await _conflict_evidence(workspace)}
    if action == "generate_pr_description":
        return await _pr_evidence(workspace, remote_context)

    staged = await run_git(
        str(workspace),
        "diff",
        "--cached",
        "--unified=3",
        "--no-ext-diff",
        timeout=10,
        max_output_bytes=_MAX_EVIDENCE,
    )
    unstaged = await run_git(
        str(workspace),
        "diff",
        "--unified=3",
        "--no-ext-diff",
        timeout=10,
        max_output_bytes=_MAX_EVIDENCE,
    )
    status = await run_git(str(workspace), "status", "--short", timeout=5)
    diagnostics = _diagnostic_evidence(workspace)
    changed_paths = _status_paths(status.stdout)
    if action == "generate_commit_message":
        return {
            "status": status.stdout,
            "staged_diff": staged.stdout[:_MAX_EVIDENCE],
            "diagnostics": diagnostics,
            "test_evidence": [
                item for item in diagnostics if item["source"] in {"test", "build"}
            ],
            "guidelines": _guidelines(workspace),
        }
    return {
        "status": status.stdout,
        "staged_diff": staged.stdout[:_MAX_EVIDENCE],
        "unstaged_diff": unstaged.stdout[:_MAX_EVIDENCE],
        "untracked_files": await _untracked_evidence(workspace),
        "diagnostics": diagnostics,
        "test_evidence": [
            item for item in diagnostics if item["source"] in {"test", "build"}
        ],
        "code_impact": await _code_impact(workspace, changed_paths),
        "guidelines": _guidelines(workspace),
        "remote_context": _bounded_json(remote_context or {}),
    }


async def _pr_evidence(
    workspace: Path,
    remote_context: dict[str, Any] | None,
) -> dict[str, Any]:
    context = remote_context or {}
    source_branch = context.get("source_branch")
    target_branch = context.get("target_branch")
    if not isinstance(source_branch, str) or not source_branch.strip():
        raise ValueError("A source branch is required to draft a PR description.")
    if not isinstance(target_branch, str) or not target_branch.strip():
        raise ValueError("A target branch is required to draft a PR description.")
    source_branch = source_branch.strip()
    target_branch = target_branch.strip()
    if source_branch == target_branch:
        raise ValueError("Source and target branches must be different.")

    source_sha = await _verified_commit(workspace, source_branch)
    target_sha = await _verified_commit(workspace, target_branch)
    commit_range = f"{target_sha}..{source_sha}"
    diff_range = f"{target_sha}...{source_sha}"

    commits = await run_git(
        str(workspace),
        "log",
        "--format=%H%x09%s",
        commit_range,
        timeout=10,
        max_output_bytes=64_000,
    )
    if not commits.ok:
        raise ValueError(
            f"Could not read commits from {target_branch} to {source_branch}: "
            f"{commits.stderr or 'git log failed'}"
        )
    commit_rows = [row for row in commits.stdout.splitlines() if row.strip()]
    if not commit_rows:
        raise ValueError(
            f"No commits from {source_branch} are ahead of {target_branch}."
        )

    diff = await run_git(
        str(workspace),
        "diff",
        "--stat",
        "--patch",
        "--no-ext-diff",
        diff_range,
        timeout=15,
        max_output_bytes=_MAX_EVIDENCE,
    )
    if not diff.ok:
        raise ValueError(
            f"Could not compare {source_branch} with {target_branch}: "
            f"{diff.stderr or 'git diff failed'}"
        )
    changed = await run_git(
        str(workspace),
        "diff",
        "--name-only",
        "--no-ext-diff",
        diff_range,
        timeout=10,
        max_output_bytes=64_000,
    )
    if not changed.ok:
        raise ValueError(
            f"Could not list files changed between {target_branch} and "
            f"{source_branch}: {changed.stderr or 'git diff failed'}"
        )

    diagnostics = _diagnostic_evidence(workspace)
    changed_paths = [row for row in changed.stdout.splitlines() if row.strip()]
    return {
        "source_branch": source_branch,
        "source_sha": source_sha,
        "target_branch": target_branch,
        "target_sha": target_sha,
        "commits": commit_rows,
        "committed_diff": diff.stdout[:_MAX_EVIDENCE],
        "diagnostics": diagnostics,
        "test_evidence": [
            item for item in diagnostics if item["source"] in {"test", "build"}
        ],
        "code_impact": await _code_impact(workspace, changed_paths),
        "guidelines": _guidelines(workspace),
    }


async def _untracked_evidence(workspace: Path) -> list[dict[str, Any]]:
    listed = await run_git(
        str(workspace),
        "ls-files",
        "--others",
        "--exclude-standard",
        "-z",
        timeout=10,
        max_output_bytes=_MAX_EVIDENCE,
    )
    if not listed.ok:
        raise ValueError(
            f"Could not enumerate untracked files: "
            f"{listed.stderr or 'git ls-files failed'}"
        )

    rows: list[dict[str, Any]] = []
    total_bytes = 0
    raw_paths = [value for value in listed.stdout.split("\0") if value]
    for raw_path in raw_paths[:_MAX_UNTRACKED_FILES]:
        candidate = workspace / raw_path
        if candidate.is_symlink():
            rows.append({"path": raw_path, "skipped": "symlink"})
            continue
        try:
            normalized = normalize_change_path(workspace, raw_path)
        except ChangeSetError:
            rows.append({"path": raw_path, "skipped": "unsafe_path"})
            continue
        path = workspace / normalized
        try:
            if not path.is_file():
                rows.append({"path": normalized, "skipped": "not_a_file"})
                continue
            size = path.stat().st_size
            remaining = _MAX_UNTRACKED_TOTAL_BYTES - total_bytes
            if remaining <= 0:
                rows.append({"truncated": True, "reason": "total_size_limit"})
                break
            read_limit = min(_MAX_UNTRACKED_FILE_BYTES, remaining)
            with path.open("rb") as handle:
                raw = handle.read(read_limit + 1)
        except OSError:
            rows.append({"path": normalized, "skipped": "unreadable"})
            continue

        truncated = len(raw) > read_limit or size > read_limit
        raw = raw[:read_limit]
        total_bytes += len(raw)
        if b"\0" in raw:
            rows.append(
                {
                    "path": normalized,
                    "size": size,
                    "binary": True,
                    "truncated": truncated,
                }
            )
            continue
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError:
            rows.append(
                {
                    "path": normalized,
                    "size": size,
                    "binary": True,
                    "truncated": truncated,
                }
            )
            continue
        rows.append(
            {
                "path": normalized,
                "size": size,
                "content": content,
                "truncated": truncated,
            }
        )
    if len(raw_paths) > _MAX_UNTRACKED_FILES:
        rows.append(
            {
                "truncated": True,
                "reason": "file_count_limit",
                "omitted": len(raw_paths) - _MAX_UNTRACKED_FILES,
            }
        )
    return rows


def _diagnostic_evidence(workspace: Path) -> list[dict[str, Any]]:
    return [
        {
            "source": problem.source,
            "severity": problem.severity,
            "path": problem.path,
            "line": problem.line,
            "code": problem.code,
            "message": problem.message,
        }
        for problem in list_problems(workspace)[:200]
    ]


async def _verified_commit(workspace: Path, reference: str) -> str:
    verified = await run_git(
        str(workspace),
        "rev-parse",
        "--verify",
        "--end-of-options",
        f"{reference}^{{commit}}",
        timeout=5,
    )
    sha = verified.stdout.strip()
    if not verified.ok or not re.fullmatch(r"[0-9a-fA-F]{40,64}", sha):
        raise ValueError(f"Invalid Git commit reference: {reference}")
    return sha


async def _conflict_evidence(workspace: Path) -> list[dict[str, Any]]:
    status = await run_git(
        str(workspace), "diff", "--name-only", "--diff-filter=U", timeout=5
    )
    rows: list[dict[str, Any]] = []
    for path in status.stdout.splitlines()[:50]:
        stages: dict[str, Any] = {}
        for stage, label in ((1, "base"), (2, "ours"), (3, "theirs")):
            value = await run_git(
                str(workspace),
                "show",
                f":{stage}:{path}",
                timeout=5,
                max_output_bytes=64_000,
            )
            stages[label] = value.stdout[:64_000]
        working = workspace / path
        if working.is_file():
            raw_working = working.read_bytes()
            stages["working"] = raw_working.decode("utf-8", errors="replace")[:64_000]
            stages["working_sha256"] = hashlib.sha256(raw_working).hexdigest()
            stages["working_truncated"] = len(raw_working) > 64_000
        else:
            stages["working"] = ""
            stages["working_sha256"] = ""
            stages["working_truncated"] = False
        rows.append({"path": path, **stages})
    return rows


def _validate_action_output(action: GitAIAction, output: _Output) -> None:
    expected: dict[GitAIAction, set[str]] = {
        "self_review": {"review"},
        "generate_commit_message": {"text"},
        "explain_commit": {"text"},
        "generate_pr_description": {"pr"},
        "summarize_pull_request": {"review", "text", "pr"},
        "propose_conflict_resolution": {"changes"},
        "review_resolved_conflicts": {"review"},
    }
    if output.kind not in expected[action]:
        raise ValueError(
            f"AI Git action {action} returned unexpected kind: {output.kind}"
        )
    if action == "propose_conflict_resolution" and not output.files:
        raise ValueError("AI conflict resolution returned no file proposals.")
    if action == "generate_pr_description" and (
        not output.title
        or not output.title.strip()
        or not output.body
        or not output.body.strip()
    ):
        raise ValueError("AI PR draft returned an empty title or description.")
    if action != "propose_conflict_resolution" and output.files:
        raise ValueError("Only conflict resolution may return file proposals.")


def _guarded_conflict_inputs(
    workspace: Path,
    evidence: dict[str, Any],
    files: list[_File],
) -> list[ChangeFileInput]:
    conflicts = evidence.get("conflicts")
    if not isinstance(conflicts, list):
        raise ValueError("Conflict evidence is unavailable.")
    reviewed: dict[str, tuple[str | None, bool]] = {}
    for item in conflicts:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            continue
        normalized = normalize_change_path(workspace, item["path"])
        raw_hash = item.get("working_sha256")
        reviewed[normalized] = (
            raw_hash if isinstance(raw_hash, str) and raw_hash else None,
            bool(item.get("working_truncated")),
        )

    inputs: list[ChangeFileInput] = []
    for item in files:
        normalized = normalize_change_path(workspace, item.path)
        if normalized not in reviewed:
            raise ValueError(
                f"AI proposed a file outside the reviewed conflict set: {normalized}"
            )
        base_hash, truncated = reviewed[normalized]
        if truncated:
            raise ValueError(
                f"Conflict file was truncated in reviewed evidence: {normalized}"
            )
        if base_hash is None and (workspace / normalized).exists():
            raise ChangeSetStale([normalized])
        inputs.append(
            ChangeFileInput(
                path=normalized,
                proposed_content=item.proposed_content,
                base_hash=base_hash,
            )
        )
    return inputs


async def _code_impact(workspace: Path, paths: list[str]) -> list[dict[str, Any]]:
    from app.services.code_index.models import RepositoryScope
    from app.services.code_index.service import query_code_context

    results: list[dict[str, Any]] = []
    scope = (RepositoryScope(root=workspace, label=workspace.name),)
    for path in paths[:8]:
        try:
            search = await query_code_context(
                scopes=scope,
                action="search",
                query=Path(path).stem,
                paths=[path],
                limit=3,
                refresh=True,
            )
        except (OSError, RuntimeError, ValueError):
            continue
        symbols = [hit.symbol for hit in search.hits if hit.symbol]
        for symbol in symbols[:2]:
            try:
                impact = await query_code_context(
                    scopes=scope,
                    action="impact",
                    query=symbol,
                    depth=1,
                    limit=8,
                    refresh=False,
                )
            except (OSError, RuntimeError, ValueError):
                continue
            results.extend(
                {
                    "symbol": symbol,
                    "kind": relation.kind,
                    "source": relation.source.qualified_name,
                    "target": relation.target.qualified_name,
                    "path": relation.callsite_file,
                    "line": relation.callsite_line,
                }
                for relation in impact.relations
            )
    return results[:40]


def _guidelines(workspace: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for relative in ("AGENTS.md", ".evoflux/review-guidelines.md", "SECURITY.md"):
        path = workspace / relative
        if path.is_file():
            try:
                rows.append(
                    {
                        "path": relative,
                        "content": path.read_text(encoding="utf-8")[:32_000],
                    }
                )
            except (OSError, UnicodeDecodeError):
                pass
    return rows


def _status_paths(raw: str) -> list[str]:
    paths: list[str] = []
    for row in raw.splitlines():
        value = row[3:].strip() if len(row) > 3 else ""
        if " -> " in value:
            value = value.split(" -> ", 1)[1]
        if value:
            paths.append(value)
    return paths


def _bounded_json(value: dict[str, Any]) -> dict[str, Any]:
    raw = json.dumps(value, ensure_ascii=False)
    if len(raw) <= _MAX_EVIDENCE:
        return value
    return {"truncated_json": raw[:_MAX_EVIDENCE]}


def _parse_output(raw: str) -> _Output:
    value = raw.strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*", "", value)
        value = re.sub(r"\s*```$", "", value)
    try:
        data = json.loads(value)
        return _Output.model_validate(data)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ValueError(f"AI Git response failed schema validation: {exc}") from exc
