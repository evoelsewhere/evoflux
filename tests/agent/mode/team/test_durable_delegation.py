from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
from unittest.mock import AsyncMock
from uuid import UUID, uuid7

import pytest
from sqlmodel import col, select

from app.agent.agent_loop import Agent
from app.agent.loader import load_team_from_dir
from app.agent.mode.team.delegate import make_team_delegate_tool
from app.agent.mode.team.handoff import make_team_handoff_tool
from app.agent.mode.team.member import TeamLead, TeamMember
from app.agent.mode.team.reject import make_team_reject_tool
from app.agent.mode.team.team import AgentTeam
from app.core import db as db_module
from app.models.chat import SessionMessage
from app.models.team import DelegationTask
from tests.agent.mode.team.conftest import MockTeamProvider


def _mock_provider(model: str | None, model_kwargs: dict | None = None):
    return MockTeamProvider()


def _write_agent(path: Path, *, name: str, role: str) -> None:
    path.write_text(
        f"---\nname: {name}\nrole: {role}\nmodel: mock:model\n---\nYou are {name}.\n",
        encoding="utf-8",
    )


async def _make_dynamic_team(agents_dir: Path, session_id: str) -> AgentTeam:
    if not (agents_dir / "lead.md").exists():
        _write_agent(agents_dir / "lead.md", name="lead", role="lead")
        _write_agent(agents_dir / "coder.md", name="coder", role="member")
    team = load_team_from_dir(
        agents_dir,
        provider_factory=_mock_provider,
        db_factory=db_module.async_session_factory,
    )
    assert team is not None
    await team.start()
    team.lead.session_id = session_id
    await team.lead._ensure_db_session()
    return team


async def _make_team(*member_names: str, session_id: str | None = None) -> AgentTeam:
    lead = TeamLead(
        Agent(name="lead", llm_provider=MockTeamProvider()),
        session_id=session_id or str(uuid7()),
        db_factory=db_module.async_session_factory,
    )
    members = {
        name: TeamMember(
            Agent(name=name, llm_provider=MockTeamProvider()),
            session_id=str(uuid7()),
            db_factory=db_module.async_session_factory,
        )
        for name in member_names
    }
    team = AgentTeam(
        lead=lead,
        members=members,
        db_factory=db_module.async_session_factory,
    )
    await team.start()
    await lead._ensure_db_session()
    for member in members.values():
        await member._ensure_db_session()
    # These tests drive inbox persistence explicitly; no LLM activation is
    # needed to verify the durable coordination contract.
    team.mailbox._on_message = None
    return team


async def _tasks(team: AgentTeam) -> list[DelegationTask]:
    async with db_module.async_session_factory() as db:
        return list(
            (
                await db.exec(
                    select(DelegationTask)
                    .where(DelegationTask.lead_session_id == UUID(team.lead.session_id))
                    .order_by(col(DelegationTask.created_at).asc())
                )
            ).all()
        )


@pytest.mark.asyncio
async def test_delegate_dispatch_failure_returns_durable_task_ids():
    team = await _make_team("coder#1", "coder#2")
    delegate = make_team_delegate_tool(team.mailbox, "lead", team)
    team.dispatch_delegation_tasks = AsyncMock(  # type: ignore[method-assign]
        side_effect=RuntimeError("second allocation failed")
    )

    result = await delegate(
        to=["coder#1", "coder#2"],
        goal="Implement independent changes",
        expected_output="Both changes are ready for review",
    )

    tasks = await _tasks(team)
    assert "Durable Task IDs:" in result
    assert "second allocation failed" in result
    assert len(tasks) == 2
    assert all(str(task.id) in result for task in tasks)


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "project"
    repo.mkdir()
    _git(repo, "init")
    (repo / "feature.txt").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "feature.txt")
    _git(
        repo,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-m",
        "initial",
    )
    return repo.resolve()


@pytest.mark.asyncio
async def test_isolated_handoff_waits_for_lead_merge_then_finalizes(
    tmp_path: Path,
):
    repo = _git_repo(tmp_path)
    team = await _make_team("coder#1")
    team.mode = "coding"
    team.workspace = str(repo)
    delegate = make_team_delegate_tool(team.mailbox, "lead", team)

    result = await delegate(
        to=["coder#1"],
        goal="Implement isolated feature",
        expected_output="Code and verification",
        target_paths=["feature.txt"],
        isolation="worktree",
    )

    assert "Task delegated" in result
    task = (await _tasks(team))[0]
    allocation = task.spec["worktree_allocation"]
    task_workspace = Path(allocation["repositories"][0]["workspace"])
    assert task_workspace != repo
    (task_workspace / "feature.txt").write_text("isolated\n", encoding="utf-8")

    handoff = make_team_handoff_tool(
        team.mailbox,
        "coder#1",
        role="member",
        team=team,
    )
    delivered = await handoff(
        to=["lead"],
        task_id=str(task.id),
        summary="The isolated feature implementation is ready for lead review.",
        findings=["feature.txt updated in the assigned worktree"],
        verified=True,
        verification_method="read feature.txt",
    )

    assert "Handoff delivered" in delivered
    task = (await _tasks(team))[0]
    assert task.status == "review"
    assert team.pending_delegation_task_ids("lead", "coder#1") == [str(task.id)]
    assert (repo / "feature.txt").read_text(encoding="utf-8") == "base\n"

    duplicate = await handoff(
        to=["lead"],
        task_id=str(task.id),
        summary="The isolated feature implementation is ready for lead review.",
        findings=["feature.txt updated in the assigned worktree"],
        verified=True,
        verification_method="read feature.txt",
    )
    assert "Handoff delivered" in duplicate
    assert (await _tasks(team))[0].status == "review"

    merged = await team.merge_delegation_worktree(str(task.id))

    assert str(repo) in merged
    task = (await _tasks(team))[0]
    assert task.status == "completed"
    assert team.pending_delegation_task_ids("lead", "coder#1") == []
    assert (repo / "feature.txt").read_text(encoding="utf-8") == "base\n"

    duplicate_after_merge = await handoff(
        to=["lead"],
        task_id=str(task.id),
        summary="The isolated feature implementation is ready for lead review.",
        findings=["feature.txt updated in the assigned worktree"],
        verified=True,
        verification_method="read feature.txt",
    )
    assert "Handoff delivered" in duplicate_after_merge

    await team.finalize_delegation_worktrees()

    assert (repo / "feature.txt").read_text(encoding="utf-8") == "isolated\n"
    assert _git(repo, "status", "--porcelain") == ""
    await team.stop()


@pytest.mark.asyncio
async def test_overdue_isolated_task_must_be_discarded_before_finalize(
    tmp_path: Path,
):
    repo = _git_repo(tmp_path)
    team = await _make_team("coder#1")
    team.mode = "coding"
    team.workspace = str(repo)
    delegate = make_team_delegate_tool(team.mailbox, "lead", team)
    handoff = make_team_handoff_tool(
        team.mailbox,
        "coder#1",
        role="member",
        team=team,
    )

    await delegate(
        to=["coder#1"],
        goal="Implement before the deadline",
        expected_output="Code and verification",
        target_paths=["feature.txt"],
        isolation="worktree",
        deadline_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    task = (await _tasks(team))[0]
    allocation = task.spec["worktree_allocation"]
    workspace = Path(allocation["repositories"][0]["workspace"])
    (workspace / "feature.txt").write_text("late\n", encoding="utf-8")
    async with db_module.async_session_factory() as db:
        row = await db.get(DelegationTask, task.id)
        assert row is not None
        row.deadline_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.add(row)
        await db.commit()

    result = await handoff(
        to=["lead"],
        task_id=str(task.id),
        summary="This isolated implementation arrived after its deadline.",
        findings=["feature.txt changed too late"],
        verified=True,
        verification_method="read feature.txt",
    )

    assert "missed its deadline" in result
    failed = (await _tasks(team))[0]
    assert failed.status == "failed"
    assert workspace.is_dir()
    with pytest.raises(ValueError, match="remain unresolved"):
        await team.finalize_delegation_worktrees()

    await team.discard_delegation_worktree(str(task.id))
    discarded = (await _tasks(team))[0]
    assert discarded.status == "failed"
    assert discarded.spec["worktree_allocation"]["state"] == "discarded"
    assert not workspace.exists()
    assert "No new integrations" in await team.finalize_delegation_worktrees()
    await team.stop()


@pytest.mark.asyncio
async def test_isolated_dispatch_failure_preserves_allocation_for_replay(
    tmp_path: Path,
):
    repo = _git_repo(tmp_path)
    team = await _make_team("coder#1")
    team.mode = "coding"
    team.workspace = str(repo)
    team.mailbox.send = AsyncMock(side_effect=RuntimeError("mailbox unavailable"))
    delegate = make_team_delegate_tool(team.mailbox, "lead", team)

    result = await delegate(
        to=["coder#1"],
        goal="Implement after mailbox recovery",
        expected_output="Code and verification",
        target_paths=["feature.txt"],
        isolation="worktree",
    )

    assert "mailbox unavailable" in result
    task = (await _tasks(team))[0]
    allocation = task.spec["worktree_allocation"]
    workspace = Path(allocation["repositories"][0]["workspace"])
    assert task.status == "pending"
    assert task.result is None
    assert workspace.is_dir()

    team.mailbox.send = AsyncMock()
    await team.dispatch_undelivered_delegations()

    team.mailbox.send.assert_awaited_once()
    replay = team.mailbox.send.await_args.kwargs["message"]
    assert replay.extra["task_id"] == str(task.id)
    assert replay.extra["_task_spec"]["worktree_allocation"] == allocation
    await team.stop()


@pytest.mark.asyncio
async def test_isolated_rejection_reuses_worktree_for_next_attempt(
    tmp_path: Path,
):
    repo = _git_repo(tmp_path)
    team = await _make_team("coder#1")
    team.mode = "coding"
    team.workspace = str(repo)
    delegate = make_team_delegate_tool(team.mailbox, "lead", team)
    handoff = make_team_handoff_tool(
        team.mailbox,
        "coder#1",
        role="member",
        team=team,
    )
    reject = make_team_reject_tool(team.mailbox, "lead", team)

    await delegate(
        to=["coder#1"],
        goal="Implement and refine isolated feature",
        expected_output="Code and verification",
        target_paths=["feature.txt"],
        isolation="worktree",
    )
    task = (await _tasks(team))[0]
    allocation = task.spec["worktree_allocation"]
    workspace = Path(allocation["repositories"][0]["workspace"])
    (workspace / "feature.txt").write_text("attempt one\n", encoding="utf-8")
    await handoff(
        to=["lead"],
        task_id=str(task.id),
        summary="The first isolated implementation is ready for review.",
        findings=["feature.txt changed"],
        verified=True,
        verification_method="read feature.txt",
    )

    result = await reject(
        to=["coder#1"],
        task_id=str(task.id),
        reason="The implementation needs the requested refinement.",
        issues=["Expected the final value"],
    )

    assert "Rejection sent" in result
    reopened = (await _tasks(team))[0]
    assert reopened.status == "pending"
    assert reopened.attempt == 2
    assert reopened.spec["worktree_allocation"]["state"] == "active"
    assert (
        Path(reopened.spec["worktree_allocation"]["repositories"][0]["workspace"])
        == workspace
    )
    assert workspace.is_dir()

    (workspace / "feature.txt").write_text("attempt two\n", encoding="utf-8")
    await handoff(
        to=["lead"],
        task_id=str(task.id),
        summary="The refined isolated implementation is ready for review.",
        findings=["feature.txt refined"],
        verified=True,
        verification_method="read feature.txt",
    )
    reviewed = (await _tasks(team))[0]
    assert reviewed.status == "review"
    assert reviewed.attempt == 2

    await team.merge_delegation_worktree(str(task.id))
    await team.finalize_delegation_worktrees()
    assert (repo / "feature.txt").read_text(encoding="utf-8") == "attempt two\n"
    await team.stop()


@pytest.mark.asyncio
async def test_same_recipient_tasks_complete_independently_and_round_trip_metadata():
    team = await _make_team("coder#1")
    delegate = make_team_delegate_tool(team.mailbox, "lead", team)

    await delegate(to=["coder#1"], goal="First", expected_output="First done")
    await delegate(to=["coder#1"], goal="Second", expected_output="Second done")
    rows = await _tasks(team)
    assert len(rows) == 2
    assert rows[0].id != rows[1].id

    handoff = make_team_handoff_tool(
        team.mailbox,
        "coder#1",
        role="member",
        team=team,
    )
    ambiguous = await handoff(
        to=["lead"],
        summary="This handoff intentionally omits the ambiguous task identity.",
        findings=["Cannot identify which assignment this completes"],
        verified=True,
        verification_method="checked task list",
    )
    assert "multiple pending delegation tasks" in ambiguous

    first_message = team.mailbox.receive_nowait("coder#1")
    second_message = team.mailbox.receive_nowait("coder#1")
    await team.members["coder#1"]._persist_inbox([first_message, second_message])

    async with db_module.async_session_factory() as db:
        inbox_rows = (
            await db.exec(
                select(SessionMessage)
                .where(
                    SessionMessage.session_id
                    == UUID(team.members["coder#1"].session_id)
                )
                .order_by(col(SessionMessage.created_at).asc())
            )
        ).all()
        assert inbox_rows[0].extra["message_id"] == first_message.id
        assert inbox_rows[0].extra["task_id"] == str(rows[0].id)
        assert inbox_rows[0].extra["_task_spec"]["goal"] == "First"

    result = await handoff(
        to=["lead"],
        task_id=str(rows[0].id),
        summary="The first durable task is complete and verified.",
        findings=["First task complete"],
        verified=True,
        verification_method="checked output",
    )
    assert "Handoff delivered" in result
    handoff_message = team.mailbox.receive_nowait("lead")
    await team.lead._persist_inbox([handoff_message])

    duplicate_result = await handoff(
        to=["lead"],
        task_id=str(rows[0].id),
        summary="The first durable task is complete and verified.",
        findings=["First task complete"],
        verified=True,
        verification_method="checked output",
    )
    assert "Handoff delivered" in duplicate_result
    duplicate_message = team.mailbox.receive_nowait("lead")
    assert duplicate_message.id == handoff_message.id
    await team.lead._persist_inbox([duplicate_message])

    async with db_module.async_session_factory() as db:
        first = await db.get(DelegationTask, rows[0].id)
        second = await db.get(DelegationTask, rows[1].id)
        assert first is not None and first.status == "completed"
        assert first.final_handoff_message_id is not None
        assert second is not None and second.status == "pending"
        handoff_row = await db.get(SessionMessage, first.final_handoff_message_id)
        assert handoff_row is not None
        assert handoff_row.extra["task_id"] == str(first.id)
        assert handoff_row.extra["_handoff_artifact"]["summary"].startswith(
            "The first durable task"
        )
        duplicate_rows = (
            await db.exec(
                select(SessionMessage).where(
                    SessionMessage.session_id == UUID(team.lead.session_id),
                    col(SessionMessage.extra)["message_id"].as_string()
                    == handoff_message.id,
                )
            )
        ).all()
        assert len(duplicate_rows) == 1

    assert team.pending_delegation_task_ids("lead", "coder#1") == [str(rows[1].id)]


@pytest.mark.asyncio
async def test_dependency_is_dispatched_only_after_parent_handoff():
    team = await _make_team("explorer#1", "coder#1")
    delegate = make_team_delegate_tool(team.mailbox, "lead", team)
    await delegate(
        to=["explorer#1"],
        goal="Research",
        expected_output="Research result",
    )
    dependency = (await _tasks(team))[0]
    await delegate(
        to=["coder#1"],
        goal="Implement",
        expected_output="Implementation",
        depends_on=[str(dependency.id)],
    )
    rows = await _tasks(team)
    blocked = rows[1]
    assert blocked.status == "blocked"
    assert team.mailbox.inbox_empty("coder#1")

    handoff = make_team_handoff_tool(
        team.mailbox,
        "explorer#1",
        role="member",
        team=team,
    )
    result = await handoff(
        to=["lead"],
        task_id=str(dependency.id),
        summary="Research dependency is complete with actionable evidence.",
        findings=["Evidence gathered"],
        verified=True,
        verification_method="checked sources",
    )
    assert "Handoff delivered" in result
    released_message = team.mailbox.receive_nowait("coder#1")
    assert released_message.extra["task_id"] == str(blocked.id)
    dependency_results = released_message.extra["_task_spec"]["dependency_results"]
    assert dependency_results[0]["task_id"] == str(dependency.id)
    assert dependency_results[0]["result"]["summary"].startswith("Research dependency")


@pytest.mark.asyncio
async def test_rejection_reopens_exact_task_and_increments_attempt():
    team = await _make_team("coder#1")
    delegate = make_team_delegate_tool(team.mailbox, "lead", team)
    await delegate(to=["coder#1"], goal="Implement", expected_output="Code and tests")
    task = (await _tasks(team))[0]
    initial_delegation = team.mailbox.receive_nowait("coder#1")
    await team.members["coder#1"]._persist_inbox([initial_delegation])

    handoff = make_team_handoff_tool(
        team.mailbox,
        "coder#1",
        role="member",
        team=team,
    )
    await handoff(
        to=["lead"],
        task_id=str(task.id),
        summary="Implementation is ready for review with test evidence.",
        findings=["Implementation complete"],
        verified=True,
        verification_method="ran tests",
    )
    team.mailbox.receive_nowait("lead")

    reject = make_team_reject_tool(team.mailbox, "lead", team)
    result = await reject(
        to=["coder#1"],
        task_id=str(task.id),
        reason="The edge-case test is missing.",
        issues=["No timeout test"],
    )
    assert "Rejection sent" in result
    rejection = team.mailbox.receive_nowait("coder#1")
    assert rejection.extra["task_id"] == str(task.id)

    restarted = await _make_team("coder#1", session_id=team.lead.session_id)
    await restarted.refresh_delegations()
    replayed_rejection = restarted.mailbox.receive_nowait("coder#1")
    assert replayed_rejection.id == rejection.id
    assert "The edge-case test is missing" in replayed_rejection.content
    assert "**Attempt:** 2" in replayed_rejection.content
    assert replayed_rejection.extra["_rejection_feedback"]["task_id"] == str(task.id)
    await restarted.members["coder#1"]._persist_inbox([replayed_rejection])

    async with db_module.async_session_factory() as db:
        reopened = await db.get(DelegationTask, task.id)
        assert reopened is not None
        assert reopened.status == "pending"
        assert reopened.attempt == 2
        assert reopened.last_rejection["reason"] == "The edge-case test is missing."
        rejection_rows = (
            await db.exec(
                select(SessionMessage).where(
                    SessionMessage.session_id
                    == UUID(restarted.members["coder#1"].session_id),
                    col(SessionMessage.extra)["message_id"].as_string()
                    == replayed_rejection.id,
                )
            )
        ).all()
        assert len(rejection_rows) == 1
        assert rejection_rows[0].extra["task_id"] == str(task.id)
        assert (
            rejection_rows[0].extra["_rejection_feedback"]["reason"]
            == "The edge-case test is missing."
        )


@pytest.mark.asyncio
async def test_restart_replays_only_unacknowledged_task():
    session_id = str(uuid7())
    first_team = await _make_team("coder#1", session_id=session_id)
    delegate = make_team_delegate_tool(first_team.mailbox, "lead", first_team)
    await delegate(to=["coder#1"], goal="Replay me", expected_output="Done once")
    task = (await _tasks(first_team))[0]
    assert task.dispatched_at is None

    # Simulate a crash before the member persisted its inbox message.
    second_team = await _make_team("coder#1", session_id=session_id)
    await second_team.refresh_delegations()
    replay = second_team.mailbox.receive_nowait("coder#1")
    assert replay.extra["task_id"] == str(task.id)
    await second_team.members["coder#1"]._persist_inbox([replay])

    async with db_module.async_session_factory() as db:
        acknowledged = await db.get(DelegationTask, task.id)
        assert acknowledged is not None
        assert acknowledged.dispatched_at is not None


@pytest.mark.asyncio
async def test_restart_replays_and_repairs_unacknowledged_final_handoff():
    session_id = str(uuid7())
    first_team = await _make_team("coder#1", session_id=session_id)
    delegate = make_team_delegate_tool(first_team.mailbox, "lead", first_team)
    await delegate(to=["coder#1"], goal="Finish", expected_output="Verified result")
    task = (await _tasks(first_team))[0]
    initial = first_team.mailbox.receive_nowait("coder#1")
    await first_team.members["coder#1"]._persist_inbox([initial])

    handoff = make_team_handoff_tool(
        first_team.mailbox,
        "coder#1",
        role="member",
        team=first_team,
    )
    await handoff(
        to=["lead"],
        task_id=str(task.id),
        summary="The final result is complete and independently verified.",
        findings=["Result complete"],
        verified=True,
        verification_method="checked output",
    )
    original = first_team.mailbox.receive_nowait("lead")

    # Crash before the lead persists its inbox: completed result must replay.
    second_team = await _make_team("coder#1", session_id=session_id)
    await second_team.refresh_delegations()
    replay = second_team.mailbox.receive_nowait("lead")
    assert replay.id == original.id
    assert replay.extra["_handoff_artifact"]["task_id"] == str(task.id)
    await second_team.lead._persist_inbox([replay])

    async with db_module.async_session_factory() as db:
        linked = await db.get(DelegationTask, task.id)
        assert linked is not None and linked.final_handoff_message_id is not None
        linked.final_handoff_message_id = None
        db.add(linked)
        await db.commit()

    # Crash after inbox commit but before task-link commit: replay dedupes the
    # same message row and repairs the missing link.
    third_team = await _make_team("coder#1", session_id=session_id)
    await third_team.refresh_delegations()
    repair = third_team.mailbox.receive_nowait("lead")
    assert repair.id == original.id
    await third_team.lead._persist_inbox([repair])

    async with db_module.async_session_factory() as db:
        repaired = await db.get(DelegationTask, task.id)
        assert repaired is not None and repaired.final_handoff_message_id is not None
        rows = (
            await db.exec(
                select(SessionMessage).where(
                    SessionMessage.session_id == UUID(session_id),
                    col(SessionMessage.extra)["message_id"].as_string() == original.id,
                )
            )
        ).all()
        assert len(rows) == 1


@pytest.mark.asyncio
async def test_restart_restores_dynamic_recipient_from_open_task(
    tmp_path: Path,
):
    session_id = str(uuid7())
    first_team = await _make_dynamic_team(tmp_path, session_id)
    member = await first_team.spawn("coder")
    original_member_session = member.session_id
    first_team.mailbox._on_message = None
    delegate = make_team_delegate_tool(first_team.mailbox, "lead", first_team)
    await delegate(
        to=["coder#1"],
        goal="Resume after restart",
        expected_output="A final verified handoff",
    )
    task = (await _tasks(first_team))[0]

    restarted = await _make_dynamic_team(tmp_path, session_id)
    assert restarted.members == {}
    restarted.mailbox._on_message = None
    await restarted.refresh_delegations()

    assert "coder#1" in restarted.members
    assert restarted.members["coder#1"].session_id == original_member_session
    replay = restarted.mailbox.receive_nowait("coder#1")
    assert replay.extra["task_id"] == str(task.id)
    assert "Resume after restart" in replay.content


@pytest.mark.asyncio
async def test_spawn_reconciliation_can_restore_another_recipient_without_deadlock(
    tmp_path: Path,
):
    session_id = str(uuid7())
    team = await _make_dynamic_team(tmp_path, session_id)
    await team.create_delegation_tasks(
        delegator="lead",
        recipients=["coder#1"],
        spec={"goal": "Restore coder", "expected_output": "Done"},
        dependencies=[],
        deadline_at=None,
    )

    async with asyncio.timeout(2):
        spawned = await team.spawn("executor")

    assert spawned.name == "executor#1"
    assert "coder#1" in team.members
