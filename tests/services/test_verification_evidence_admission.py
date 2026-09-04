"""Machine evidence must be reachable without delegating a mission.

`record_mission_handoff_evidence` was the only writer of `kind="machine"`, and
it runs only when a delegated mission hands off. A run driven by a single agent
— the shape `direct` flow exists for — therefore could never satisfy a
criterion whose policy sets `machine_required`, and Converge stayed blocked
forever. Measured on a real run: 7 review records, 0 machine records, 6 of 7
criteria stuck `in_progress`, while the verifier reported "ready for
convergence ... with fresh machine evidence".

Verify already runs the accepted verification commands and builds a
revision-bound CompletionContract. This admits that contract as the machine
record it already is — produced by the runtime, never asserted by the agent.
"""

from __future__ import annotations

import pytest

from app.models.chat import ChatSession
from app.services import trace_service
from app.services.trace_contracts import TraceSpecification
from app.services.trace_service import (
    _accepted_command_results,
    admit_verification_machine_evidence,
)

COMMAND = "python -m pytest tests/test_rate.py"


def _spec(repository: str, *, machine_required: bool = True) -> TraceSpecification:
    return TraceSpecification.model_validate(
        {
            "title": "Implement per-client rate limiting",
            "problem": "RateLimiter.allow() raises NotImplementedError.",
            "outcome": "The limiter rejects requests past the quota.",
            "risk_tier": "standard",
            "verification_commands": [COMMAND],
            "impact_targets": [
                {
                    "repository": repository,
                    "path": "tasklib/rate.py",
                    "reason": "Implementation target",
                }
            ],
            "criteria": [
                {
                    "id": "AC-ROLL",
                    "statement": "The eleventh request in the window is rejected.",
                    "required": True,
                    "evidence_policy": {
                        "allowed_kinds": ["machine", "review"],
                        "machine_required": machine_required,
                        "minimum_passes": 1,
                    },
                },
                {
                    "id": "AC-PURE",
                    "statement": "tasklib stays pure-python.",
                    "required": True,
                    "evidence_policy": {
                        "allowed_kinds": ["review"],
                        "machine_required": False,
                        "minimum_passes": 1,
                    },
                },
            ],
        }
    )


def _contract(*, exit_code: int = 0, spec_command: str = COMMAND) -> dict:
    return {
        "artifact_hash": "a" * 64,
        "changed_files": ["tasklib/rate.py"],
        "scope_paths": ["tasklib/rate.py"],
        "scope_targets": [],
        "passed": exit_code == 0,
        "rigor": "standard",
        "evidence": [
            {
                "command_id": "c1",
                "command": ["python", "-m", "pytest", "tests/test_rate.py"],
                "cwd": "C:/repo",
                "exit_code": exit_code,
                "revision": "b" * 40,
                "artifact_hash": "a" * 64,
                "output": "4 passed" if exit_code == 0 else "4 failed",
                "source": "planned",
                "spec_command": spec_command,
                "passed": exit_code == 0,
            }
        ],
    }


class TestAcceptedCommandResults:
    def test_only_accepted_commands_count(self):
        contract = _contract(spec_command="ruff check .")
        assert _accepted_command_results(contract, [COMMAND]) == []

    def test_matching_command_is_returned_with_its_exit_code(self):
        assert _accepted_command_results(_contract(exit_code=1), [COMMAND]) == [
            (COMMAND, 1)
        ]

    def test_a_contract_without_evidence_is_empty(self):
        assert _accepted_command_results({"evidence": None}, [COMMAND]) == []

    def test_malformed_entries_are_skipped(self):
        contract = {"evidence": ["nonsense", {"spec_command": 5}]}
        assert _accepted_command_results(contract, [COMMAND]) == []


@pytest.fixture
async def verifying_run(tmp_path, setup_db):
    """A run parked in `verifying` with an accepted spec, as Verify sees it."""

    from app.core.db import async_session_factory

    async with async_session_factory() as db:
        session = ChatSession(
            agent_name="evoflux", mode="coding", workspace=str(tmp_path)
        )
        db.add(session)
        await db.flush()
        specification = _spec(tmp_path.name)
        run = await trace_service.create_run(
            db,
            workspace=str(tmp_path),
            title=specification.title,
            risk_tier=specification.risk_tier,
            specification=specification,
            session_id=session.id,
        )
        draft = (await trace_service.run_detail(db, run.id))["revisions"][0]
        await trace_service.accept_revision(
            db,
            run_id=run.id,
            revision_id=draft["id"],
            expected_hash=draft["content_hash"],
        )
        run.status = "verifying"
        db.add(run)
        await db.commit()
        return run.id


class TestAdmission:
    @pytest.mark.asyncio
    async def test_a_passing_contract_becomes_machine_evidence(self, verifying_run):
        from app.core.db import async_session_factory

        async with async_session_factory() as db:
            evidence = await admit_verification_machine_evidence(
                db,
                run_id=verifying_run,
                completion_contract=_contract(),
                producer="runtime:evoflux",
            )
            await db.commit()

        assert evidence is not None
        assert evidence.kind == "machine"
        assert evidence.result == "passed"
        # Only criteria whose policy admits machine evidence.
        assert evidence.criterion_ids == ["AC-ROLL"]
        assert COMMAND in evidence.summary
        assert "exit 0" in evidence.summary

    @pytest.mark.asyncio
    async def test_a_failing_contract_is_recorded_not_dropped(self, verifying_run):
        from app.core.db import async_session_factory

        async with async_session_factory() as db:
            evidence = await admit_verification_machine_evidence(
                db,
                run_id=verifying_run,
                completion_contract=_contract(exit_code=1),
                producer="runtime:evoflux",
            )
            await db.commit()

        assert evidence is not None
        assert evidence.result == "failed"

    @pytest.mark.asyncio
    async def test_readmitting_the_same_artifact_does_not_duplicate(
        self, verifying_run
    ):
        from app.core.db import async_session_factory

        for _ in range(2):
            async with async_session_factory() as db:
                await admit_verification_machine_evidence(
                    db,
                    run_id=verifying_run,
                    completion_contract=_contract(),
                    producer="runtime:evoflux",
                )
                await db.commit()

        async with async_session_factory() as db:
            detail = await trace_service.run_detail(db, verifying_run)
        machine = [item for item in detail["evidence"] if item["kind"] == "machine"]
        assert len(machine) == 1

    @pytest.mark.asyncio
    async def test_a_contract_that_ran_something_else_is_refused(self, verifying_run):
        from app.core.db import async_session_factory

        async with async_session_factory() as db:
            evidence = await admit_verification_machine_evidence(
                db,
                run_id=verifying_run,
                completion_contract=_contract(spec_command="ruff check ."),
                producer="runtime:evoflux",
            )
        assert evidence is None

    @pytest.mark.asyncio
    async def test_evidence_is_only_admitted_while_verifying(self, verifying_run):
        from app.core.db import async_session_factory

        async with async_session_factory() as db:
            run = await trace_service.get_run(db, verifying_run)
            run.status = "active"
            db.add(run)
            await db.commit()

        async with async_session_factory() as db:
            evidence = await admit_verification_machine_evidence(
                db,
                run_id=verifying_run,
                completion_contract=_contract(),
                producer="runtime:evoflux",
            )
        assert evidence is None

    @pytest.mark.asyncio
    async def test_the_producer_is_the_runtime_not_the_model(self, verifying_run):
        from app.core.db import async_session_factory

        async with async_session_factory() as db:
            evidence = await admit_verification_machine_evidence(
                db,
                run_id=verifying_run,
                completion_contract=_contract(),
                producer="runtime:evoflux",
            )
            await db.commit()

        assert evidence is not None
        assert evidence.producer.startswith("runtime:")


class TestConvergenceDetectorSeesIt:
    """Admission is pointless if the Converge gate cannot read the record.

    `_passed_planned_commands` reads the contract from
    `payload["verification"]["completion_contract"]`. Storing it one level
    shallower left every accepted command looking unverified, so all seven
    criteria showed `passed` while Converge still reported
    "Accepted verification commands still need passing machine evidence".
    """

    @pytest.mark.asyncio
    async def test_the_accepted_command_counts_as_verified(self, verifying_run):
        from app.core.db import async_session_factory
        from app.services.trace_service import _passed_planned_commands

        async with async_session_factory() as db:
            await admit_verification_machine_evidence(
                db,
                run_id=verifying_run,
                completion_contract=_contract(),
                producer="runtime:evoflux",
            )
            await db.commit()

        async with async_session_factory() as db:
            detail = await trace_service.run_detail(db, verifying_run)

        assert _passed_planned_commands(detail["evidence"]) == {COMMAND}

    @pytest.mark.asyncio
    async def test_converge_reports_no_missing_verification(self, verifying_run):
        from app.core.db import async_session_factory
        from app.services.trace_service import _convergence_reasons

        async with async_session_factory() as db:
            await admit_verification_machine_evidence(
                db,
                run_id=verifying_run,
                completion_contract=_contract(),
                producer="runtime:evoflux",
            )
            await db.commit()

        async with async_session_factory() as db:
            detail = await trace_service.run_detail(db, verifying_run)
            context = await trace_service.active_context(db, verifying_run)

        reasons = _convergence_reasons(
            detail=detail,
            specification=context.specification,
            independent_required=False,
        )
        codes = {reason["code"] for reason in reasons}
        assert "planned_verification_missing" not in codes

    @pytest.mark.asyncio
    async def test_a_failing_contract_does_not_count_as_verified(self, verifying_run):
        from app.core.db import async_session_factory
        from app.services.trace_service import _passed_planned_commands

        async with async_session_factory() as db:
            await admit_verification_machine_evidence(
                db,
                run_id=verifying_run,
                completion_contract=_contract(exit_code=1),
                producer="runtime:evoflux",
            )
            await db.commit()

        async with async_session_factory() as db:
            detail = await trace_service.run_detail(db, verifying_run)

        assert _passed_planned_commands(detail["evidence"]) == set()
