"""Definition parsing/validation + graph semantics (plan §4.4, §6.3)."""

from __future__ import annotations

import pytest

from app.workflow.graph import (
    SKIPPED,
    GraphState,
    topological_order,
    validate_dag,
)
from app.workflow.models import (
    DefinitionError,
    parse_definition,
    validate_environment,
)

MINIMAL = """
schema_version: 1
name: minimal
scope: work
nodes:
  - id: only
    kind: notify
    message: hi
"""

BRANCHED = """
schema_version: 1
name: branched
scope: work
nodes:
  - { id: start, kind: transform, set: { x: "1" } }
  - { id: decide, kind: gate, title: "Go?", choices: ["yes", "no"] }
  - { id: left, kind: notify, message: left }
  - { id: right, kind: notify, message: right }
  - { id: join, kind: notify, message: join }
edges:
  - { from: start, to: decide }
  - { from: decide, to: left, when: "yes" }
  - { from: decide, to: right, when: "no" }
  - { from: left, to: join }
  - { from: right, to: join }
"""


def test_minimal_parses():
    definition = parse_definition(MINIMAL)
    assert definition.name == "minimal"
    assert definition.entry_nodes() == ["only"]


def test_scope_aim_is_valid():
    definition = parse_definition(MINIMAL.replace("scope: work", "scope: aim"))
    assert definition.scope == "aim"


def test_scope_normalizes_legacy_forge_to_work():
    definition = parse_definition(MINIMAL.replace("scope: work", "scope: forge"))
    assert definition.scope == "work"


def test_duplicate_node_ids_rejected():
    bad = MINIMAL + "  - id: only\n    kind: notify\n    message: again\n"
    with pytest.raises(DefinitionError, match="duplicate node id"):
        parse_definition(bad)


def test_unknown_edge_endpoint_rejected():
    bad = MINIMAL + "edges:\n  - { from: only, to: ghost }\n"
    with pytest.raises(DefinitionError, match="unknown node 'ghost'"):
        parse_definition(bad)


def test_gate_edge_when_must_be_a_choice():
    bad = """
schema_version: 1
name: badgate
nodes:
  - { id: g, kind: gate, title: t, choices: [a] }
  - { id: n, kind: notify, message: m }
edges:
  - { from: g, to: n, when: b }
"""
    with pytest.raises(DefinitionError, match="not a choice"):
        parse_definition(bad)


def test_non_router_nodes_reject_conditional_edges():
    bad = """
schema_version: 1
name: badwhen
nodes:
  - { id: a, kind: notify, message: m }
  - { id: b, kind: notify, message: m }
edges:
  - { from: a, to: b, when: x }
"""
    with pytest.raises(DefinitionError, match="only gate/switch"):
        parse_definition(bad)


def test_agent_node_rejects_tools_field():
    bad = """
schema_version: 1
name: badtools
nodes:
  - { id: a, kind: agent, subagents: [], prompt: p, tool: shell }
"""
    with pytest.raises(DefinitionError, match="blueprint"):
        parse_definition(bad)


def test_shell_background_rejected():
    bad = """
schema_version: 1
name: badbg
nodes:
  - { id: s, kind: tool, tool: shell, args: { command: "sleep 1", background: true } }
"""
    with pytest.raises(DefinitionError, match="background"):
        parse_definition(bad)


def test_foreach_body_kind_restricted():
    bad = """
schema_version: 1
name: badbody
nodes:
  - id: loop
    kind: foreach
    items: "{{inputs.items}}"
    body: { kind: gate, title: t }
"""
    with pytest.raises(DefinitionError, match="not allowed in v1"):
        parse_definition(bad)


def test_foreach_body_rejects_router_fields_outright():
    bad = """
schema_version: 1
name: badbody2
nodes:
  - id: loop
    kind: foreach
    items: "{{inputs.items}}"
    body: { kind: gate, title: t, choices: [a] }
"""
    with pytest.raises(DefinitionError):
        parse_definition(bad)


def test_wait_seconds_capped():
    bad = """
schema_version: 1
name: badwait
nodes:
  - { id: w, kind: wait, seconds: 1200 }
"""
    with pytest.raises(DefinitionError, match="1..600"):
        parse_definition(bad)


def test_cycle_detected():
    definition = parse_definition("""
schema_version: 1
name: cyclic
nodes:
  - { id: a, kind: notify, message: m }
  - { id: b, kind: notify, message: m }
edges:
  - { from: a, to: b }
  - { from: b, to: a }
""")
    assert topological_order(definition) is None
    assert any("cycle" in e for e in validate_dag(definition))


def test_unreachable_node_reported():
    definition = parse_definition("""
schema_version: 1
name: island
nodes:
  - { id: a, kind: notify, message: m }
  - { id: b, kind: notify, message: m }
  - { id: c, kind: notify, message: m }
edges:
  - { from: b, to: c }
  - { from: c, to: b }
""")
    errors = validate_dag(definition)
    assert any("cycle" in e for e in errors)


def test_environment_validation_checks_tools_and_blueprints():
    definition = parse_definition("""
schema_version: 1
name: envcheck
nodes:
  - { id: t, kind: tool, tool: made_up_tool, args: {} }
  - { id: a, kind: agent, subagents: [ghost], prompt: p }
edges:
  - { from: t, to: a }
""")
    errors = validate_environment(
        definition, known_tools={"shell", "python"}, known_blueprints={"debate"}
    )
    assert any("made_up_tool" in e for e in errors)
    assert any("ghost" in e for e in errors)
    # mcp_* names pass without registry membership.
    definition2 = parse_definition("""
schema_version: 1
name: envok
nodes:
  - { id: t, kind: tool, tool: mcp_jira_get_issue, args: {} }
""")
    assert (
        validate_environment(definition2, known_tools=set(), known_blueprints=set())
        == []
    )


# ── graph walk semantics (§6.3) ──────────────────────────────────────────────


def test_sequential_walk_interleaves_branches_in_topo_order():
    definition = parse_definition(BRANCHED)
    state = GraphState.create(definition)

    assert state.next_ready() == "start"
    state.mark_running("start")
    state.mark_succeeded("start")

    assert state.next_ready() == "decide"
    state.mark_running("decide")
    state.mark_succeeded("decide", answer="yes")

    # 'no' branch is dead → right is skipped; left then join.
    assert state.next_ready() == "left"
    state.mark_running("left")
    state.mark_succeeded("left")
    assert state.node_status["right"] == SKIPPED

    assert state.next_ready() == "join"
    state.mark_running("join")
    state.mark_succeeded("join")
    assert state.next_ready() is None
    assert state.is_finished()


def test_gate_answer_matching_no_edge_ends_gracefully():
    definition = parse_definition("""
schema_version: 1
name: deadend
nodes:
  - { id: g, kind: gate, title: t, choices: [go, stop] }
  - { id: n, kind: notify, message: m }
edges:
  - { from: g, to: n, when: go }
""")
    state = GraphState.create(definition)
    state.mark_running("g")
    state.mark_succeeded("g", answer="stop")
    assert state.next_ready() is None
    assert state.node_status["n"] == SKIPPED
    assert state.is_finished()


def test_switch_default_edge_fires_only_without_match():
    definition = parse_definition("""
schema_version: 1
name: switchy
nodes:
  - { id: s, kind: switch, value: "{{inputs.x}}" }
  - { id: hot, kind: notify, message: m }
  - { id: fallback, kind: notify, message: m }
edges:
  - { from: s, to: hot, when: critical }
  - { from: s, to: fallback, when: "*" }
""")
    state = GraphState.create(definition)
    state.mark_running("s")
    state.mark_succeeded("s", answer="critical")
    assert state.next_ready() == "hot"
    assert ("s", "fallback") in state.dead_edges

    state2 = GraphState.create(definition)
    state2.mark_running("s")
    state2.mark_succeeded("s", answer="mild")
    assert state2.next_ready() == "fallback"


def test_failure_skips_everything_else():
    definition = parse_definition(BRANCHED)
    state = GraphState.create(definition)
    state.mark_running("start")
    state.mark_failed("start")
    assert state.next_ready() is None
    assert state.node_status["decide"] == SKIPPED
    assert state.is_finished()


def test_join_waits_for_all_incoming_to_resolve():
    definition = parse_definition(BRANCHED)
    state = GraphState.create(definition)
    state.mark_running("start")
    state.mark_succeeded("start")
    state.mark_running("decide")
    state.mark_succeeded("decide", answer="yes")
    state.mark_running("left")
    # join must NOT be ready while left is still running.
    assert state.next_ready() is None
    state.mark_succeeded("left")
    assert state.next_ready() == "join"
