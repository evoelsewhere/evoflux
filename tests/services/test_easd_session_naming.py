"""A run's linked chat should be named after the run.

Sessions are titled from their first message, which for an EASD phase is the
machine-generated instruction. The sidebar therefore showed
"$easd-specify Draft the specification for EASD run 06a99a5e-c22e-71a5-…",
which identifies nothing at a glance and truncates before the run title.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.models.chat import ChatSession
from app.models.trace import TraceRun
from app.services.trace_service import _name_session_after_run


def _run(title="Implement per-client rate limiting") -> TraceRun:
    return TraceRun(
        id=uuid4(),
        workspace="C:/Users/dev/easd-lab",
        title=title,
        status="intent",
        risk_tier="standard",
    )


def _session(title=None) -> ChatSession:
    return ChatSession(
        agent_name="evoflux",
        mode="coding",
        workspace="C:/Users/dev/easd-lab",
        title=title,
    )


@pytest.mark.parametrize(
    "placeholder", [None, "", "   ", "Untitled", "untitled", "New chat"]
)
def test_placeholder_titles_are_replaced(placeholder):
    session = _session(placeholder)
    _name_session_after_run(session, _run())
    assert session.title == "EASD · Implement per-client rate limiting"


def test_a_title_the_user_chose_is_left_alone():
    session = _session("Rate limiter spike")
    _name_session_after_run(session, _run())
    assert session.title == "Rate limiter spike"


def test_an_already_named_easd_session_is_not_renamed_again():
    session = _session("EASD · Something else")
    _name_session_after_run(session, _run())
    assert session.title == "EASD · Something else"


def test_the_run_id_never_appears_in_the_title():
    run = _run()
    session = _session()
    _name_session_after_run(session, run)
    assert str(run.id) not in (session.title or "")
    assert "$easd" not in (session.title or "")


def test_a_very_long_run_title_stays_within_the_column_limit():
    session = _session()
    _name_session_after_run(session, _run(title="x" * 400))
    assert session.title is not None
    assert len(session.title) <= 255
