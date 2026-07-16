"""Workflow templating (app/workflow/template.py) — plan §4.3."""

from __future__ import annotations

import pytest

from app.workflow.template import (
    TemplateError,
    referenced_env_names,
    render,
    render_object,
)

SCOPE = {
    "inputs": {"ticket": "T-1", "count": 3},
    "nodes": {
        "fetch": {"output": {"summary": "Login fails", "tags": ["p1", "auth"]}},
        "plan": {"output": {"repos": [{"path": "/a"}, {"path": "/b"}]}},
    },
    "env": {"REGION": "eu-1"},
}


def test_renders_dotted_paths_inline():
    assert render(
        "Ticket {{inputs.ticket}}: {{nodes.fetch.output.summary}}", SCOPE
    ) == ("Ticket T-1: Login fails")


def test_exact_placeholder_preserves_type():
    value = render("{{nodes.plan.output.repos}}", SCOPE)
    assert isinstance(value, list)
    assert value[0]["path"] == "/a"


def test_list_index_path():
    assert render("{{nodes.fetch.output.tags.1}}", SCOPE) == "auth"


def test_json_filter():
    assert render("{{nodes.fetch.output.tags | json}}", SCOPE) == '["p1", "auth"]'


def test_truncate_filter():
    assert render("{{nodes.fetch.output.summary | truncate:5}}", SCOPE) == "Login…"


def test_missing_path_fails_loudly():
    with pytest.raises(TemplateError, match="does not resolve"):
        render("{{nodes.fetch.output.nope}}", SCOPE)


def test_unknown_filter_rejected():
    with pytest.raises(TemplateError, match="unknown template filter"):
        render("{{inputs.ticket | upper}}", SCOPE)


def test_bad_truncate_arg_rejected():
    with pytest.raises(TemplateError, match="integer"):
        render("{{inputs.ticket | truncate:x}}", SCOPE)


def test_render_object_recurses():
    rendered = render_object(
        {"key": "{{inputs.ticket}}", "nested": ["{{inputs.count}}"]}, SCOPE
    )
    assert rendered == {"key": "T-1", "nested": [3]}


def test_foreach_scope_binds_item_and_index():
    scope = dict(SCOPE, item={"path": "/a"}, index=0)
    assert render("git -C {{item.path}} status ({{index}})", scope) == (
        "git -C /a status (0)"
    )


def test_referenced_env_names():
    refs = referenced_env_names(
        {"args": {"region": "{{env.REGION}}", "x": "{{inputs.ticket}}"}}
    )
    assert refs == {"REGION"}
