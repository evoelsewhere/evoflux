from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agent.sandbox import SandboxConfig, set_sandbox
from app.agent.schemas.chat import AssistantMessage
from app.services.easd_generation_service import (
    EasdGenerationIntent,
    GenerationRepository,
    collect_generation_context,
    generate_scope_and_proof,
)
from app.services.easd_setup_service import (
    EasdRepositoryTarget,
    initialize_repositories,
)


def _repository(tmp_path: Path) -> GenerationRepository:
    (tmp_path / "AGENTS.md").write_text(
        "Preserve API compatibility.\n", encoding="utf-8"
    )
    (tmp_path / "README.md").write_text(
        "Run pytest -q before handoff.\n", encoding="utf-8"
    )
    (tmp_path / "documents").mkdir()
    (tmp_path / "documents" / "feature.md").write_text(
        "The route response is a compatibility contract.\n", encoding="utf-8"
    )
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "routes.py").write_text(
        "def list_runs(): return []\n", encoding="utf-8"
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_routes.py").write_text(
        "def test_runs(): pass\n", encoding="utf-8"
    )
    (tmp_path / ".evoflux" / "trace").mkdir(parents=True)
    (tmp_path / ".evoflux" / "trace" / "spec.yaml").write_text(
        "outcome: stable API\n", encoding="utf-8"
    )
    (tmp_path / ".evoflux" / "private-state").mkdir()
    (tmp_path / ".evoflux" / "private-state" / "secret.txt").write_text(
        "must not be included", encoding="utf-8"
    )
    return GenerationRepository(path=tmp_path, name="Backend")


def _ready_payload(*, confidence: float = 0.91) -> dict:
    return {
        "status": "ready",
        "confidence": confidence,
        "rationale": "Grounded in route ownership and focused tests.",
        "questions": [],
        "outcome": "Clients can query runs through a stable API response.",
        "scope": {
            "goals": ["Add the endpoint"],
            "non_goals": ["Change unrelated routes"],
            "source_refs": ["Backend:app/routes.py"],
            "impact_targets": [
                {
                    "repository": "Backend",
                    "path": "app/routes.py",
                    "module": "API",
                    "reason": "Owns the endpoint",
                }
            ],
            "constraints": [
                {
                    "kind": "compatibility",
                    "statement": "Preserve the existing response shape",
                    "source_refs": ["Backend:README.md"],
                }
            ],
            "used_sources": ["Backend:app/routes.py", "unknown:file.py"],
        },
        "proof": {
            "risk_tier": "cross_layer",
            "criteria": [
                {
                    "id": "AC-1",
                    "statement": "The endpoint returns a stable response.",
                    "required": True,
                    "evidence_policy": {
                        "allowed_kinds": ["machine", "review"],
                        "machine_required": True,
                        "minimum_passes": 1,
                    },
                }
            ],
            "verification_commands": ["pytest -q tests/test_routes.py"],
            "independent_review_required": False,
            "used_sources": ["Backend:tests/test_routes.py"],
        },
    }


@pytest.mark.asyncio
async def test_generation_is_grounded_bounded_and_draft_only(tmp_path: Path):
    repository = _repository(tmp_path)
    provider = SimpleNamespace(
        provider_name="test",
        chat=AsyncMock(
            return_value=AssistantMessage(
                content=json.dumps(_ready_payload()),
                extra={"usage": {"input": 120, "output": 40, "cache": 20}},
            )
        ),
    )
    token = set_sandbox(
        SandboxConfig(
            workspace=str(tmp_path),
            outbound_data_policy="off",
            outbound_pii_policy="off",
        )
    )
    try:
        result = await generate_scope_and_proof(
            provider=provider,
            repositories=[repository],
            intent=EasdGenerationIntent(
                title="Add runs endpoint",
                problem="Runs are not queryable.",
            ),
            target="both",
            current_draft={},
            clarifications=[],
        )
    finally:
        from app.agent.sandbox import _sandbox_ctx

        _sandbox_ctx.reset(token)

    assert result.status == "ready"
    assert result.outcome == "Clients can query runs through a stable API response."
    assert result.scope is not None
    assert result.scope.used_sources == ["Backend:app/routes.py"]
    assert result.proof is not None
    assert result.proof.independent_review_required is True
    assert result.proof.delivery_flow.mode == "planned"
    assert "risk:cross_layer" in result.proof.delivery_flow.required_by
    assert "constraint:compatibility" in result.proof.delivery_flow.required_by
    assert result.provider == "test"
    assert result.usage == {"input": 120, "output": 40, "cache": 20}
    assert any(item.kind == "instructions" for item in result.provenance)
    assert any(
        item.path == "documents/feature.md" and item.kind == "documentation"
        for item in result.provenance
    )
    sent = provider.chat.await_args.args[0]
    assert sent[0].role == "system"
    assert "DRAFT only" in sent[0].content
    assert '"delivery_flow"' in sent[0].content
    assert not list(tmp_path.glob("documents/easd/runs/*"))


def test_context_ignores_symlink_escape(tmp_path: Path):
    repository = _repository(tmp_path)
    outside = tmp_path.parent / "outside-secret.txt"
    outside.write_text("must not be included", encoding="utf-8")
    (tmp_path / "linked.txt").symlink_to(outside)

    context = collect_generation_context(
        [repository],
        EasdGenerationIntent(
            title="Inspect routes",
            problem="Need scope.",
            outcome="Grounded proposal.",
        ),
    )

    assert all(item.path != "linked.txt" for item in context)
    assert any(item.path == ".evoflux/trace/spec.yaml" for item in context)
    assert all("private-state" not in item.path for item in context)
    assert "must not be included" not in "\n".join(item.content for item in context)


def test_context_skips_easd_scaffold_but_keeps_repository_sources(tmp_path: Path):
    (tmp_path / "service.py").write_text(
        "def active_contract(): return 'ready'\n", encoding="utf-8"
    )
    initialize_repositories([EasdRepositoryTarget(path=str(tmp_path), name="backend")])

    context = collect_generation_context(
        [GenerationRepository(path=tmp_path, name="backend")],
        EasdGenerationIntent(
            title="Inspect active contract",
            problem="Need grounded source ownership.",
            outcome="Keep real source context ahead of boilerplate.",
        ),
    )

    assert any(item.path == "service.py" for item in context)
    assert all(
        not item.path.startswith("documents/easd/templates/") for item in context
    )
    assert all(item.path != "documents/easd/README.md" for item in context)
    assert all(item.path != "documents/easd/features/README.md" for item in context)


def test_multi_repo_context_keeps_all_maps_and_bounds_file_excerpts(tmp_path: Path):
    repositories: list[GenerationRepository] = []
    for index in range(10):
        root = tmp_path / f"repo-{index}"
        root.mkdir()
        _repository(root)
        repositories.append(GenerationRepository(path=root, name=f"repo-{index}"))

    context = collect_generation_context(
        repositories,
        EasdGenerationIntent(
            title="Coordinate project routes",
            problem="Ownership spans repositories.",
            outcome="A bounded multi-repo proposal.",
        ),
    )

    assert sum(item.kind == "repository_map" for item in context) == 10
    assert sum(item.kind != "repository_map" for item in context) <= 32


@pytest.mark.asyncio
async def test_generation_returns_clarifying_questions_without_scope(tmp_path: Path):
    repository = _repository(tmp_path)
    payload = {
        "status": "needs_clarification",
        "confidence": 0.42,
        "rationale": "The requested compatibility behavior is ambiguous.",
        "questions": [
            {
                "id": "Q-1",
                "question": "Must old clients keep the current response?",
                "reason": "The answer changes public behavior.",
                "required": True,
            }
        ],
        "scope": None,
        "proof": None,
    }
    provider = SimpleNamespace(
        provider_name="test",
        chat=AsyncMock(return_value=AssistantMessage(content=json.dumps(payload))),
    )
    token = set_sandbox(
        SandboxConfig(
            workspace=str(tmp_path),
            outbound_data_policy="off",
            outbound_pii_policy="off",
        )
    )
    try:
        result = await generate_scope_and_proof(
            provider=provider,
            repositories=[repository],
            intent=EasdGenerationIntent(
                title="Change the response",
                problem="Clients need more fields.",
                outcome="A useful response.",
            ),
            target="both",
            current_draft={},
            clarifications=[],
        )
    finally:
        from app.agent.sandbox import _sandbox_ctx

        _sandbox_ctx.reset(token)

    assert result.status == "needs_clarification"
    assert result.outcome is None
    assert result.questions[0].id == "Q-1"
    assert result.scope is None
    assert result.proof is None


@pytest.mark.asyncio
async def test_generation_rejects_ungrounded_sources_and_unsafe_commands(
    tmp_path: Path,
):
    repository = _repository(tmp_path)
    intent = EasdGenerationIntent(
        title="Add runs endpoint",
        problem="Runs are not queryable.",
        outcome="Clients receive stable run data.",
    )
    cases: list[tuple[dict, str]] = []
    unknown_source = _ready_payload()
    unknown_source["scope"]["source_refs"] = ["Backend:missing.py"]
    cases.append((unknown_source, "outside the grounded context"))
    unsafe_command = _ready_payload()
    unsafe_command["proof"]["verification_commands"] = ["pytest -q && rm -rf build"]
    cases.append((unsafe_command, "shell composition"))
    token = set_sandbox(
        SandboxConfig(
            workspace=str(tmp_path),
            outbound_data_policy="off",
            outbound_pii_policy="off",
        )
    )
    try:
        for payload, match in cases:
            provider = SimpleNamespace(
                provider_name="test",
                chat=AsyncMock(
                    return_value=AssistantMessage(content=json.dumps(payload))
                ),
            )
            with pytest.raises(ValueError, match=match):
                await generate_scope_and_proof(
                    provider=provider,
                    repositories=[repository],
                    intent=intent,
                    target="both",
                    current_draft={},
                    clarifications=[],
                )
    finally:
        from app.agent.sandbox import _sandbox_ctx

        _sandbox_ctx.reset(token)


@pytest.mark.asyncio
async def test_generation_cancellation_propagates_to_provider(tmp_path: Path):
    repository = _repository(tmp_path)
    entered = asyncio.Event()
    cancelled = asyncio.Event()

    async def slow_chat(*_args, **_kwargs):
        entered.set()
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    provider = SimpleNamespace(
        provider_name="test", chat=AsyncMock(side_effect=slow_chat)
    )
    token = set_sandbox(
        SandboxConfig(
            workspace=str(tmp_path),
            outbound_data_policy="off",
            outbound_pii_policy="off",
        )
    )
    try:
        task = asyncio.create_task(
            generate_scope_and_proof(
                provider=provider,
                repositories=[repository],
                intent=EasdGenerationIntent(
                    title="Cancel generation",
                    problem="The request is no longer needed.",
                    outcome="Provider work stops promptly.",
                ),
                target="both",
                current_draft={},
                clarifications=[],
            )
        )
        await asyncio.wait_for(entered.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cancelled.is_set()
    finally:
        from app.agent.sandbox import _sandbox_ctx

        _sandbox_ctx.reset(token)
