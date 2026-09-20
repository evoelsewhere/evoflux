from app.remote.imessage.live import IMessageLiveBudget
from app.remote.imessage.redaction import redact


def test_live_budget_allows_four_edits_then_requires_fresh_card() -> None:
    budget = IMessageLiveBudget()
    for index in range(4):
        assert budget.allow_edit(
            connection_id="c1", key=f"k{index}", text=str(index), now=0
        )
        budget.record_edit(connection_id="c1", key=f"k{index}", text=str(index), now=0)
    assert not budget.allow_edit(connection_id="c1", key="k4", text="4", now=1)
    assert budget.completion_allowed()


def test_live_budget_uses_fresh_card_after_edit_quota() -> None:
    budget = IMessageLiveBudget()
    for index in range(4):
        assert (
            budget.delivery_mode(
                connection_id="c1", key=f"k{index}", text=str(index), now=0
            )
            == "edit"
        )
    assert budget.delivery_mode(connection_id="c1", key="k4", text="4", now=1) == "new"
    assert budget.completion_allowed()


def test_live_budget_expires_edits() -> None:
    budget = IMessageLiveBudget()
    assert budget.allow_edit(connection_id="c1", key="k", text="x", now=0)
    budget.record_edit(connection_id="c1", key="k", text="x", now=0)
    assert budget.allow_edit(connection_id="c1", key="k2", text="y", now=901)


def test_redaction_boundary_returns_safe_text() -> None:
    assert redact("normal remote response") == "normal remote response"
