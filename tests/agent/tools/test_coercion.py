"""Tests for list-argument coercion and the self-correcting tool contracts.

Covers the three argument mistakes models were seen making:

- ``team_delegate(to="explorer")`` — a lone string where an array is required.
- ``todo_manage(todos=[...])`` — the right idea under the wrong argument name.
- the validation error itself: it must show the call that works, or the model
  repeats the failing call verbatim.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from app.agent.errors import ToolArgumentError
from app.agent.mode.team.delegate import make_team_delegate_tool
from app.agent.mode.team.handoff import make_team_handoff_tool
from app.agent.mode.team.mailbox import TeamMailbox
from app.agent.mode.team.reject import make_team_reject_tool
from app.agent.mode.team.tools import make_team_message_tool
from app.agent.tools.coercion import coerce_str_list
from app.agent.tools.builtin.todo import todo_manage, todo_manage_member


class TestCoerceStrList:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("explorer", ["explorer"]),
            ("  executor#1  ", ["executor#1"]),
            ('["a", "b"]', ["a", "b"]),
            ('  ["a"]', ["a"]),
            ("", []),
            ("   ", []),
            # Not valid JSON: it is still one element, not a parse error.
            ("[unterminated", ["[unterminated"]),
            # A JSON value that is not an array is just text.
            ("[1, 2", ["[1, 2"]),
        ],
    )
    def test_strings_become_lists(self, value, expected):
        assert coerce_str_list(value) == expected

    @pytest.mark.parametrize("value", [["a"], [], ("a",), None, 3, {"a": 1}])
    def test_non_strings_pass_through_untouched(self, value):
        assert coerce_str_list(value) is value


def _mailbox() -> TeamMailbox:
    mailbox = TeamMailbox()
    for name in ("lead", "explorer"):
        mailbox.register(name)
    return mailbox


def _tools():
    mailbox = _mailbox()
    return {
        "team_delegate": make_team_delegate_tool(mailbox, agent_name="lead"),
        "team_message": make_team_message_tool(mailbox, agent_name="lead"),
        "team_handoff": make_team_handoff_tool(mailbox, agent_name="lead"),
        "team_reject": make_team_reject_tool(mailbox, agent_name="lead"),
    }


class TestRecipientListsAcceptAString:
    @pytest.mark.parametrize("name", ["team_delegate", "team_message"])
    def test_lone_string_recipient_is_read_as_a_list(self, name):
        tool = _tools()[name]
        args = {"to": "explorer", "goal": "g", "expected_output": "e", "content": "c"}
        fields = tool._model.model_fields
        model = tool._model(**{k: v for k, v in args.items() if k in fields})
        assert model.to == ["explorer"]

    def test_double_encoded_array_is_decoded(self):
        tool = _tools()["team_delegate"]
        model = tool._model(
            to='["explorer#1", "writer"]', goal="g", expected_output="e"
        )
        assert model.to == ["explorer#1", "writer"]

    @pytest.mark.parametrize(
        "name", ["team_delegate", "team_message", "team_handoff", "team_reject"]
    )
    def test_advertised_schema_still_says_array(self, name):
        """Widening what is accepted must not change what the model is told."""
        to = _tools()[name].definition["function"]["parameters"]["properties"]["to"]
        assert to["type"] == "array"
        assert to["items"] == {"type": "string"}

    def test_other_delegate_lists_accept_a_string_too(self):
        tool = _tools()["team_delegate"]
        model = tool._model(
            to=["explorer"],
            goal="g",
            expected_output="e",
            constraints="do not touch tests/",
            target_paths="app/x.py",
        )
        assert model.constraints == ["do not touch tests/"]
        assert model.target_paths == ["app/x.py"]


class TestTodoManageContract:
    @pytest.mark.asyncio
    async def test_wrong_argument_name_error_shows_the_working_call(self):
        with pytest.raises(ToolArgumentError) as caught:
            await todo_manage.arun(
                todos=[{"content": "x", "status": "pending", "priority": "high"}]
            )

        message = str(caught.value)
        assert "actions" in message
        assert "Example of a valid call: todo_manage(actions=[" in message
        assert '"action": "create"' in message

    @pytest.mark.asyncio
    async def test_member_error_shows_the_member_call(self):
        with pytest.raises(ToolArgumentError) as caught:
            await todo_manage_member.arun(todos=[])

        assert '"action": "claim"' in str(caught.value)

    @pytest.mark.parametrize("tool", [todo_manage, todo_manage_member])
    def test_description_names_the_single_argument(self, tool):
        description = tool.description
        assert "Call shape" in description
        assert "`actions`" in description

    def test_lead_description_says_there_is_no_todos_argument(self):
        assert "no `todos` argument" in todo_manage.description

    @pytest.mark.parametrize("tool", [todo_manage, todo_manage_member])
    def test_actions_field_carries_an_example(self, tool):
        actions = tool.definition["function"]["parameters"]["properties"]["actions"]
        assert '"action"' in actions["description"]
        assert "actions" in tool.definition["function"]["parameters"]["required"]

    def test_the_documented_example_is_itself_valid(self):
        """An example that fails validation would teach the wrong shape."""
        example = todo_manage.usage_example
        assert example is not None
        payload = example.removeprefix("todo_manage(actions=").removesuffix(")")
        actions = json.loads(payload)
        assert todo_manage._model(actions=actions).actions


class TestToolsWithoutAnExampleKeepPlainErrors:
    @pytest.mark.asyncio
    async def test_no_example_line_is_added(self):
        tool = _tools()["team_message"]
        assert tool.usage_example is None
        with pytest.raises(ToolArgumentError) as caught:
            await tool.arun(content="hi")
        assert "Example of a valid call" not in str(caught.value)


def test_team_delegate_example_is_a_valid_call():
    tool = make_team_delegate_tool(MagicMock(), agent_name="lead")
    assert tool.usage_example is not None
    assert tool.usage_example.startswith("team_delegate(to=[")
