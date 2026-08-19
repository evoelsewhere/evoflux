"""Explicit AI semantic-editor actions returning structured outcomes."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any, Literal

from loguru import logger
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
    create_change_set,
    normalize_change_path,
    serialize_change_set,
)
from app.services.editor_context_service import EditorContextEnvelope
from app.services.problems_service import ProblemInput, publish_problems

EditorAction = Literal[
    "explain_code",
    "fix_diagnostic",
    "refactor_selection",
    "generate_tests",
    "generate_documentation",
    "find_problems",
    "simplify_code",
    "convert_pattern",
    "propagate_api_change",
    "explain_failure",
]

_CHANGE_ACTIONS = frozenset(
    {
        "fix_diagnostic",
        "refactor_selection",
        "generate_tests",
        "generate_documentation",
        "simplify_code",
        "convert_pattern",
        "propagate_api_change",
    }
)
_SYSTEM_PROMPT = """You are EvoFlux's explicit semantic editor engine.
Return exactly one JSON object and no Markdown fences. Use only repository-local
paths. Never claim tests passed. Never include secrets not present in the
provided context. For changes, return complete UTF-8 proposed file contents,
not patches. Preserve unrelated code. For findings, report only concrete,
file-addressable defects supported by the supplied evidence.

Schema:
{
  "kind": "explanation" | "changes" | "findings",
  "summary": "short outcome",
  "explanation": "optional explanation",
  "files": [{"path": "relative/path", "proposed_content": "complete file"}],
  "findings": [{
    "title": "short title", "message": "evidence-backed problem",
    "severity": "error" | "warning" | "info" | "hint",
    "path": "relative/path", "line": 1, "column": 1,
    "code": "optional stable rule"
  }],
  "verification_commands": ["optional existing test/lint command"]
}
"""


class _AIFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=4096)
    proposed_content: str = Field(max_length=2_000_000)


class _AIFinding(BaseModel):
    model_config = ConfigDict(extra="ignore")
    title: str | None = None
    message: str = Field(min_length=1, max_length=8000)
    severity: Literal["error", "warning", "info", "hint"] = "warning"
    path: str | None = None
    line: int | None = Field(default=None, ge=1)
    column: int | None = Field(default=None, ge=1)
    code: str | None = None


class _AIOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    kind: Literal["explanation", "changes", "findings"]
    summary: str = Field(min_length=1, max_length=4000)
    explanation: str | None = Field(default=None, max_length=20_000)
    files: list[_AIFile] = Field(default_factory=list, max_length=100)
    findings: list[_AIFinding] = Field(default_factory=list, max_length=200)
    verification_commands: list[str] = Field(default_factory=list, max_length=10)


async def run_editor_action(
    *,
    provider: LLMProviderBase,
    action: EditorAction,
    instruction: str | None,
    context: EditorContextEnvelope,
    session_id: str | None,
) -> dict[str, Any]:
    """Run one user-triggered model call and materialize structured state."""
    payload = {
        "action": action,
        "instruction": instruction,
        "context": context.to_dict(),
    }
    human: list[ChatMessage] = [
        HumanMessage(content=json.dumps(payload, ensure_ascii=False))
    ]
    protected_prompt, protected_messages, report = protect_outbound_payload(
        system_prompt=_SYSTEM_PROMPT,
        messages=human,
        policy=load_outbound_data_policy(),
        pii_policy=load_outbound_pii_policy(),
        context=OutboundContext(
            channel="model", destination=getattr(provider, "provider_name", None)
        ),
    )
    messages: list[ChatMessage] = [
        SystemMessage(content=protected_prompt),
        *protected_messages,
    ]
    logger.info(
        "editor_action_start action={} file={} context_items={} redactions={}",
        action,
        context.active_file,
        len(context.provenance),
        report.matches,
    )
    try:
        async with asyncio.timeout(90):
            response = await provider.chat(
                messages,
                max_tokens=16_000,
                temperature=0.1,
            )
    except TimeoutError as exc:
        raise ValueError("AI editor action timed out.") from exc
    output = _parse_output(response.content or "")

    expected_kind = (
        "changes"
        if action in _CHANGE_ACTIONS
        else "findings"
        if action == "find_problems"
        else "explanation"
    )
    if output.kind != expected_kind:
        raise ValueError(
            f"AI editor action {action} returned {output.kind}; "
            f"expected {expected_kind}."
        )

    result: dict[str, Any] = {
        "kind": output.kind,
        "summary": output.summary,
        "explanation": output.explanation,
        "verification_commands": output.verification_commands,
        "context": {
            "active_file": context.active_file,
            "content_sha256": context.content_sha256,
            "provenance": [
                {
                    "kind": item.kind,
                    "source": item.source,
                    "path": item.path,
                    "sha256": item.sha256,
                    "truncated": item.truncated,
                }
                for item in context.provenance
            ],
        },
    }
    if output.kind == "changes":
        if not output.files:
            raise ValueError("AI returned an empty ChangeSet.")
        record = create_change_set(
            Path(context.workspace),
            origin="ai",
            title=output.summary,
            description=output.explanation,
            files=_guarded_change_inputs(context, output.files),
            verification_commands=output.verification_commands,
        )
        result["change_set"] = serialize_change_set(record)
    elif output.kind == "findings":
        rows = publish_problems(
            context.workspace,
            source="ai_review",
            scope=f"editor:{action}:{context.content_sha256[:16]}",
            problems=[
                ProblemInput(
                    title=item.title,
                    message=item.message,
                    severity=item.severity,
                    path=item.path,
                    line=item.line,
                    column=item.column,
                    code=item.code,
                    provenance={
                        "producer": "ai-editor",
                        "active_file": context.active_file,
                        "context_sha256": context.content_sha256,
                    },
                )
                for item in output.findings
            ],
            session_id=session_id,
        )
        result["findings"] = [row.id for row in rows]
    logger.info(
        "editor_action_done action={} kind={} files={} findings={}",
        action,
        output.kind,
        len(output.files),
        len(output.findings),
    )
    return result


def _guarded_change_inputs(
    context: EditorContextEnvelope,
    files: list[_AIFile],
) -> list[ChangeFileInput]:
    """Bind existing-file proposals to the exact reviewed context snapshot."""
    root = Path(context.workspace).resolve()
    reviewed_hashes = {
        item.path: item.sha256
        for item in context.provenance
        if item.path
        and item.sha256
        and not item.truncated
        and item.source in {"editor-buffer", "explicit-mention"}
        and not item.path.endswith("/")
    }
    guarded: list[ChangeFileInput] = []
    for item in files:
        normalized = normalize_change_path(root, item.path)
        target = root / normalized
        base_hash: str | None = None
        if target.exists():
            base_hash = reviewed_hashes.get(normalized)
            if base_hash is None:
                raise ValueError(
                    "AI proposed replacing an existing file that was not fully "
                    f"included in the reviewed context: {normalized}"
                )
        guarded.append(
            ChangeFileInput(
                path=normalized,
                proposed_content=item.proposed_content,
                base_hash=base_hash,
            )
        )
    return guarded


def _parse_output(raw: str) -> _AIOutput:
    value = raw.strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*", "", value)
        value = re.sub(r"\s*```$", "", value)
    try:
        data = json.loads(value)
    except json.JSONDecodeError as exc:
        start = value.find("{")
        end = value.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("AI editor response was not valid JSON.") from exc
        try:
            data = json.loads(value[start : end + 1])
        except json.JSONDecodeError as nested_exc:
            raise ValueError("AI editor response was not valid JSON.") from nested_exc
    try:
        return _AIOutput.model_validate(data)
    except ValidationError as exc:
        raise ValueError(f"AI editor response failed schema validation: {exc}") from exc
