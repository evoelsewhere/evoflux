from __future__ import annotations

from app.agent import checkpointer
from app.agent.schemas.chat import AssistantMessage, HumanMessage, ToolMessage


def _tool(i: int) -> ToolMessage:
    return ToolMessage(content="ok", tool_call_id=f"call-{i}", name="shell")


def test_batches_do_not_split_tool_results_from_their_call(monkeypatch) -> None:
    monkeypatch.setattr(checkpointer, "_SYNC_BATCH_SIZE", 3)
    messages = [
        HumanMessage(content="a"),
        HumanMessage(content="b"),
        AssistantMessage(content="", tool_calls=[]),
        _tool(1),
        _tool(2),
        HumanMessage(content="c"),
    ]
    batches = checkpointer._message_batches(messages)
    assert [len(batch) for batch in batches] == [5, 1]
    assert [m for batch in batches for m in batch] == messages


def test_empty_input_yields_no_batches() -> None:
    assert checkpointer._message_batches([]) == []
