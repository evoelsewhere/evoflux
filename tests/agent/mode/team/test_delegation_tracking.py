"""Tests for code-level enforcement of "wait for delegated work before answering".

Covers:
- AgentTeam.register_delegation / resolve_delegation / pending_delegation_recipients
- team_delegate / team_reject register pending delegations on the team
- team_handoff resolves pending delegations only on status="final"
- TeamMemberBase._maybe_inject_delegation_wait_nudge: the system-level backstop
  that catches a lead answering before a delegated handoff arrives and forces
  a <sleep>-and-wait correction on the next wake.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

from app.agent.mode.team.delegate import make_team_delegate_tool
from app.agent.mode.team.handoff import make_team_handoff_tool
from app.agent.mode.team.mailbox import TeamMailbox
from app.agent.mode.team.member import (
    MAX_LEAD_WAIT_NUDGES,
    TeamLead,
    TeamMember,
    _lead_wait_nudge_content,
)
from app.agent.mode.team.reject import make_team_reject_tool
from app.agent.mode.team.team import AgentTeam
from tests.agent.mode.team.conftest import MockTeamProvider


def _make_mailbox(*agents: str) -> TeamMailbox:
    mb = TeamMailbox()
    for name in agents:
        mb.register(name)
    return mb


def _make_agent(name: str):
    from app.agent.agent_loop import Agent

    return Agent(name=name, llm_provider=MockTeamProvider(), system_prompt=name)


def _make_db_factory(rows: list | None = None):
    """DB factory stub.

    ``team_delegate``/``team_handoff``/``team_reject`` calls in these tests
    go through the real mailbox, whose ``on_message`` callback really does
    spawn a background ``_run_activation()`` task for the recipient (see
    ``AgentTeam._on_message`` / ``_maybe_activate``) — so the mock needs to
    survive a real (mocked) ``save_message`` call, not just the ``.exec()``
    lookup this test file actually asserts on.
    """
    mock_db = MagicMock()
    mock_db.exec = AsyncMock(
        return_value=MagicMock(all=MagicMock(return_value=rows or []))
    )
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()

    @asynccontextmanager
    async def factory():
        yield mock_db

    return factory


async def _make_team(rows: list | None = None, extra_members: tuple[str, ...] = ()):
    """Build a minimal, fully-registered AgentTeam for delegation-tracking tests.

    Recipient resolution for team_delegate/team_handoff/team_reject goes
    through ``team.resolve_recipient`` when a real ``team`` is passed (see
    ``tools._resolve``) — so a delegation target must be an actual key in
    ``team.members``, not just a raw mailbox registration. ``team.start()``
    is required too: it binds each member's ``_team``/``_mailbox`` and
    registers its mailbox inbox (``TeamMemberBase.register``).
    """
    lead_agent = _make_agent("lead")
    db_factory = _make_db_factory(rows)
    lead = TeamLead(
        lead_agent,
        session_id="01900000-0000-7000-8000-000000000001",
        db_factory=db_factory,
    )
    members = {
        "worker": TeamMember(
            _make_agent("worker"),
            session_id="01900000-0000-7000-8000-000000000002",
            db_factory=db_factory,
        )
    }
    for i, name in enumerate(extra_members, start=3):
        members[name] = TeamMember(
            _make_agent(name),
            session_id=f"01900000-0000-7000-8000-{i:012d}",
            db_factory=db_factory,
        )
    team = AgentTeam(lead=lead, members=members)
    await team.start()
    return team


def _row(role: str, content: str | None, tool_calls: list | None = None):
    return MagicMock(role=role, content=content, tool_calls=tool_calls)


# =============================================================================
# AgentTeam.register_delegation / resolve_delegation / pending_delegation_recipients
# =============================================================================


class TestPendingDelegationBookkeeping:
    async def test_register_adds_recipients(self):
        team = await _make_team()
        team.register_delegation("lead", ["executor#1", "explorer#1"])
        assert team.pending_delegation_recipients("lead") == {
            "executor#1",
            "explorer#1",
        }

    async def test_register_with_empty_recipients_is_noop(self):
        team = await _make_team()
        team.register_delegation("lead", [])
        assert team.pending_delegation_recipients("lead") == set()

    async def test_resolve_removes_recipient(self):
        team = await _make_team()
        team.register_delegation("lead", ["executor#1", "explorer#1"])
        team.resolve_delegation("lead", "executor#1")
        assert team.pending_delegation_recipients("lead") == {"explorer#1"}

    async def test_resolve_unknown_recipient_is_noop(self):
        team = await _make_team()
        team.register_delegation("lead", ["executor#1"])
        team.resolve_delegation("lead", "someone_else")
        assert team.pending_delegation_recipients("lead") == {"executor#1"}

    async def test_resolve_unknown_delegator_is_noop(self):
        team = await _make_team()
        team.resolve_delegation("nobody", "executor#1")  # must not raise
        assert team.pending_delegation_recipients("nobody") == set()

    async def test_pending_recipients_returns_copy(self):
        """Mutating the returned set must not affect internal state."""
        team = await _make_team()
        team.register_delegation("lead", ["executor#1"])
        result = team.pending_delegation_recipients("lead")
        result.add("injected")
        assert team.pending_delegation_recipients("lead") == {"executor#1"}

    async def test_resolving_last_recipient_clears_delegator_entry(self):
        team = await _make_team()
        team.register_delegation("lead", ["executor#1"])
        team.resolve_delegation("lead", "executor#1")
        assert "lead" not in team._pending_delegations


# =============================================================================
# team_delegate / team_reject register pending delegations
# =============================================================================


class TestDelegateRegistersPending:
    async def test_delegate_registers_recipients_on_team(self):
        team = await _make_team(extra_members=("executor#1",))
        tool = make_team_delegate_tool(team.mailbox, agent_name="lead", team=team)

        await tool(
            to=["executor#1"],
            goal="Implement retry logic",
            expected_output="Modified file, tests pass",
        )
        assert team.pending_delegation_recipients("lead") == {"executor#1"}

    async def test_delegate_without_team_does_not_raise(self):
        """team=None (the default) must not error — existing tests rely on this."""
        mb = _make_mailbox("executor#1", "lead")
        tool = make_team_delegate_tool(mb, agent_name="lead")

        result = await tool(to=["executor#1"], goal="Do X", expected_output="X done")
        assert "Task delegated" in result


class TestRejectRegistersPending:
    async def test_reject_re_registers_recipient_as_pending(self):
        team = await _make_team(extra_members=("executor#1",))
        # Simulate: executor#1's handoff already resolved the original delegation.
        team.register_delegation("lead", ["executor#1"])
        team.resolve_delegation("lead", "executor#1")
        assert team.pending_delegation_recipients("lead") == set()

        tool = make_team_reject_tool(team.mailbox, agent_name="lead", team=team)
        await tool(to=["executor#1"], reason="Missing test coverage for the retry path")

        assert team.pending_delegation_recipients("lead") == {"executor#1"}


# =============================================================================
# team_handoff resolves pending delegations only when status="final"
# =============================================================================


class TestHandoffResolvesPending:
    async def test_final_handoff_resolves_delegator(self):
        team = await _make_team(extra_members=("executor#1",))
        team.register_delegation("lead", ["executor#1"])

        tool = make_team_handoff_tool(
            team.mailbox, agent_name="executor#1", team=team, role="member"
        )
        await tool(
            to=["lead"],
            summary="Implemented retry logic with exponential backoff and tests.",
            findings=["Added backoff helper", "3 new tests pass"],
            status="final",
            verified=True,
            verification_method="ran the new tests",
        )
        assert team.pending_delegation_recipients("lead") == set()

    async def test_partial_handoff_does_not_resolve_delegator(self):
        team = await _make_team(extra_members=("executor#1",))
        team.register_delegation("lead", ["executor#1"])

        tool = make_team_handoff_tool(
            team.mailbox, agent_name="executor#1", team=team, role="member"
        )
        await tool(
            to=["lead"],
            summary="First batch of results, more coming shortly after.",
            findings=["Partial finding"],
            status="partial",
        )
        assert team.pending_delegation_recipients("lead") == {"executor#1"}

    async def test_handoff_to_unrelated_recipient_does_not_resolve(self):
        """Handoff to a peer who never delegated to the sender must be a no-op."""
        team = await _make_team(extra_members=("executor#1", "explorer#1"))
        team.register_delegation("lead", ["executor#1"])

        tool = make_team_handoff_tool(
            team.mailbox, agent_name="executor#1", team=team, role="member"
        )
        await tool(
            to=["explorer#1"],
            summary="Sharing my intermediate results with a peer for context.",
            findings=["Some finding"],
            status="final",
            verified=True,
            verification_method="checked the output",
        )
        assert team.pending_delegation_recipients("lead") == {"executor#1"}


# =============================================================================
# _maybe_inject_delegation_wait_nudge — the lead-side backstop
# =============================================================================


class TestLeadWaitNudge:
    async def test_noop_when_no_pending_delegations(self):
        team = await _make_team(rows=[_row("assistant", "Here's my answer.", None)])
        await team.lead._maybe_inject_delegation_wait_nudge()
        assert team.mailbox.inbox_empty("lead")

    async def test_noop_for_member_role(self):
        team = await _make_team(rows=[_row("assistant", "Some answer.", None)])
        team.register_delegation("worker", ["lead"])  # contrived, but role gate must win
        await team.members["worker"]._maybe_inject_delegation_wait_nudge()
        assert team.mailbox.inbox_empty("worker")

    async def test_noop_when_last_message_is_sleep(self):
        team = await _make_team(rows=[_row("assistant", "<sleep>", None)])
        team.register_delegation("lead", ["executor#1"])
        await team.lead._maybe_inject_delegation_wait_nudge()
        assert team.mailbox.inbox_empty("lead")

    async def test_noop_when_last_message_has_tool_calls(self):
        """Loop hasn't actually ended on a real answer yet — nothing to correct."""
        team = await _make_team(
            rows=[_row("assistant", None, [{"function": {"name": "team_delegate"}}])]
        )
        team.register_delegation("lead", ["executor#1"])
        await team.lead._maybe_inject_delegation_wait_nudge()
        assert team.mailbox.inbox_empty("lead")

    async def test_fires_when_lead_answered_with_pending_delegation(self):
        team = await _make_team(
            rows=[_row("assistant", "Here's the final answer to your question.", None)]
        )
        team.register_delegation("lead", ["executor#1"])

        await team.lead._maybe_inject_delegation_wait_nudge()

        msg = team.mailbox.receive_nowait("lead")
        assert msg.from_agent == "system"
        assert "executor#1" in msg.content
        task_ids = team.pending_delegation_task_ids("lead")
        assert msg.content == _lead_wait_nudge_content(["executor#1"], task_ids)

    async def test_nudge_identity_changes_when_one_of_two_same_recipient_tasks_finishes(
        self,
    ):
        team = await _make_team(
            rows=[_row("assistant", "Here's the final answer.", None)]
        )
        first, second = team.register_delegation(
            "lead", ["executor#1", "executor#1"]
        )

        await team.lead._maybe_inject_delegation_wait_nudge()
        first_nudge = team.mailbox.receive_nowait("lead")
        assert first in first_nudge.content
        assert second in first_nudge.content

        team.resolve_delegation("lead", "executor#1", task_id=first)
        await team.lead._maybe_inject_delegation_wait_nudge()
        second_nudge = team.mailbox.receive_nowait("lead")
        assert first not in second_nudge.content
        assert second in second_nudge.content

    async def test_nudge_is_rate_limited(self):
        team = await _make_team(
            rows=[_row("assistant", "Here's the final answer.", None)]
        )
        team.register_delegation("lead", ["executor#1"])

        for _ in range(MAX_LEAD_WAIT_NUDGES):
            await team.lead._maybe_inject_delegation_wait_nudge()
            team.mailbox.receive_nowait("lead")  # drain so inbox_empty reflects new sends

        await team.lead._maybe_inject_delegation_wait_nudge()
        assert team.mailbox.inbox_empty("lead")
