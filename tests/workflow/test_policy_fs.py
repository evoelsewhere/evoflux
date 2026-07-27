"""Policy (hash/manifest/lint) + filesystem discovery, incl. the builtin
corpus: every shipped YAML (generic + AIM library) must parse clean."""

from __future__ import annotations

from pathlib import Path

from app.services.workflows_fs import (
    delete_workflow,
    discover_workflows,
    get_workflow,
    save_workflow,
)
from app.workflow.models import parse_definition
from app.workflow.policy import compute_manifest, content_hash, destructive_lint

MANIFESTY = """
schema_version: 1
name: manifesty
scope: coding
nodes:
  - { id: fetch, kind: tool, tool: mcp_jira_get_issue, args: { key: "{{env.JIRA_KEY}}" } }
  - { id: work, kind: agent, subagents: [debate, executor], prompt: "do it" }
  - { id: run, kind: tool, tool: shell, args: { command: "echo hi" } }
edges:
  - { from: fetch, to: work }
  - { from: work, to: run }
"""


def test_content_hash_is_stable_sha256():
    assert content_hash(b"abc") == content_hash(b"abc")
    assert content_hash(b"abc") != content_hash(b"abd")


def test_manifest_collects_agents_tools_servers_env():
    definition = parse_definition(MANIFESTY)
    manifest = compute_manifest(
        definition, blueprint_tools={"debate": {"web"}, "executor": {"shell"}}
    )
    assert manifest["agents"] == ["debate", "executor"]
    assert manifest["tools"] == ["mcp_jira_get_issue", "shell"]
    assert manifest["mcp_servers"] == ["jira"]
    assert manifest["env_refs"] == ["JIRA_KEY"]
    assert manifest["agent_tools"]["executor"] == ["shell"]


def test_destructive_lint_flags_ungated_and_respects_gates():
    definition = parse_definition(MANIFESTY)
    warnings = destructive_lint(
        definition, blueprint_tools={"executor": {"shell"}}, lead_tools=set()
    )
    # Both the agent node (executor has shell) and the shell tool node are
    # ungated.
    assert any("'work'" in w for w in warnings)
    assert any("'run'" in w for w in warnings)

    gated = parse_definition("""
schema_version: 1
name: gated
nodes:
  - { id: ok, kind: gate, title: t, choices: [go] }
  - { id: run, kind: tool, tool: shell, args: { command: "echo" } }
edges:
  - { from: ok, to: run, when: go }
""")
    assert destructive_lint(gated) == []


def test_builtin_corpus_parses_clean():
    """Every shipped builtin workflow (generic + the AIM library) must be a
    valid v1 definition whose name matches its file stem."""
    app_dir = Path(__file__).resolve().parents[2] / "app"
    corpus = list((app_dir / "agent" / "builtin_workflows").glob("*.yaml"))
    corpus += list((app_dir / "agent" / "builtin_aim" / "workflows").glob("*.yaml"))
    assert len(corpus) >= 8  # 2 generic + 6 aim
    for path in corpus:
        definition = parse_definition(path.read_text(encoding="utf-8"))
        assert definition.name == path.stem, path


def test_aim_action_workflows_have_readiness_preflight():
    app_dir = Path(__file__).resolve().parents[2] / "app"
    workflow_dir = app_dir / "agent" / "builtin_aim" / "workflows"
    for path in sorted(workflow_dir.glob("*.yaml")):
        if path.stem == "aim-assess":
            continue
        definition = parse_definition(path.read_text(encoding="utf-8"))
        assert any(
            node.kind == "tool" and node.tool == "aim_readiness"
            for node in definition.nodes
        ), path
        if path.stem != "aim-suggest-workflow":
            claim_actions = {
                node.args.get("action")
                for node in definition.nodes
                if node.kind == "tool" and node.tool == "aim_claim"
            }
            assert {"acquire", "release"} <= claim_actions, path


def test_aim_workflows_have_single_entry_node():
    app_dir = Path(__file__).resolve().parents[2] / "app"
    workflow_dir = app_dir / "agent" / "builtin_aim" / "workflows"
    for path in sorted(workflow_dir.glob("*.yaml")):
        definition = parse_definition(path.read_text(encoding="utf-8"))
        assert definition.entry_nodes() == [definition.nodes[0].id], path


def test_aim_conversion_workflows_commit_target_changes():
    app_dir = Path(__file__).resolve().parents[2] / "app"
    workflow_dir = app_dir / "agent" / "builtin_aim" / "workflows"
    for name in ("aim-convert-unit", "aim-convert-wave"):
        raw = (workflow_dir / f"{name}.yaml").read_text(encoding="utf-8")
        normalized = " ".join(raw.split())
        assert "target-repo changes before returning" in normalized, name


def test_aim_test_compare_executes_actuals_deterministically():
    app_dir = Path(__file__).resolve().parents[2] / "app"
    path = app_dir / "agent" / "builtin_aim" / "workflows" / "aim-test-compare.yaml"
    definition = parse_definition(path.read_text(encoding="utf-8"))
    run_node = next(node for node in definition.nodes if node.id == "run")
    assert run_node.kind == "tool"
    assert run_node.tool == "aim_execute"


def test_aim_assess_rework_requires_second_approval():
    app_dir = Path(__file__).resolve().parents[2] / "app"
    path = app_dir / "agent" / "builtin_aim" / "workflows" / "aim-assess.yaml"
    definition = parse_definition(path.read_text(encoding="utf-8"))

    approve_rework = next(
        node for node in definition.nodes if node.id == "approve_rework"
    )
    assert approve_rework.kind == "gate"
    assert approve_rework.choices == ["approve", "stop"]
    edges = {(edge.from_, edge.to, edge.when) for edge in definition.edges}
    assert ("rework", "approve_rework", None) in edges
    assert ("approve_rework", "advance_phase", "approve") in edges
    assert ("approve_rework", "rework_stopped", "stop") in edges


def test_aim_assess_offers_suggestion_generation_after_approval():
    app_dir = Path(__file__).resolve().parents[2] / "app"
    path = app_dir / "agent" / "builtin_aim" / "workflows" / "aim-assess.yaml"
    definition = parse_definition(path.read_text(encoding="utf-8"))

    suggest = next(node for node in definition.nodes if node.id == "suggest_next")
    generate = next(
        node for node in definition.nodes if node.id == "generate_suggestions"
    )
    edges = {(edge.from_, edge.to, edge.when) for edge in definition.edges}

    assert suggest.kind == "gate"
    assert suggest.choices == ["generate", "skip"]
    assert generate.kind == "tool" and generate.tool == "aim_suggestions"
    assert ("advance_phase", "suggest_next", None) in edges
    assert ("suggest_next", "generate_suggestions", "generate") in edges
    assert ("suggest_next", "done", "skip") in edges


def test_aim_action_workflow_outputs_distinguish_readiness_from_outcome():
    app_dir = Path(__file__).resolve().parents[2] / "app"
    workflow_dir = app_dir / "agent" / "builtin_aim" / "workflows"
    for path in sorted(workflow_dir.glob("*.yaml")):
        if path.stem == "aim-assess":
            continue
        definition = parse_definition(path.read_text(encoding="utf-8"))
        assert "readiness_status" in definition.outputs, path
        assert "blockers" in definition.outputs, path
        assert "status" not in definition.outputs, path

    compare = parse_definition(
        (workflow_dir / "aim-test-compare.yaml").read_text(encoding="utf-8")
    )
    assert {"verdict", "report_path", "decision"} <= compare.outputs.keys()


def test_discovery_precedence_and_crud(tmp_path, monkeypatch):
    from app.core.config import settings as app_settings

    monkeypatch.setattr(app_settings, "EVOFLUX_CONFIG_DIR", str(tmp_path / "config"))
    workspace = tmp_path / "repo"
    (workspace / ".evoflux" / "workflows").mkdir(parents=True)

    # Workspace shadows global for the same name.
    save_workflow("dupe", MANIFESTY.replace("manifesty", "dupe"))  # global root
    (workspace / ".evoflux" / "workflows" / "dupe.yaml").write_text(
        MANIFESTY.replace("manifesty", "dupe").replace("echo hi", "echo ws"),
        encoding="utf-8",
    )
    found = get_workflow("dupe", workspace=str(workspace))
    assert found is not None and found.root == "workspace"
    assert "echo ws" in found.raw_yaml

    # Discovery lists builtin examples plus ours, first-source-wins.
    names = {wf.name: wf.root for wf in discover_workflows(str(workspace))}
    assert names["dupe"] == "workspace"
    assert names["second-opinion"] == "builtin"
    assert names["aim-test-compare"] == "builtin"

    # Invalid file still listed, with errors.
    (workspace / ".evoflux" / "workflows" / "broken.yaml").write_text(
        "schema_version: 1\nname: broken\nnodes: []\n", encoding="utf-8"
    )
    broken = get_workflow("broken", workspace=str(workspace))
    assert broken is not None and broken.definition is None and broken.errors

    # Name/stem mismatch is an error.
    (workspace / ".evoflux" / "workflows" / "renamed.yaml").write_text(
        MANIFESTY, encoding="utf-8"
    )
    mismatch = get_workflow("renamed", workspace=str(workspace))
    assert mismatch is not None and any("must match" in e for e in mismatch.errors)

    # Delete removes from both editable roots; builtin untouched.
    assert delete_workflow("dupe", workspace=str(workspace)) is True
    assert get_workflow("dupe", workspace=str(workspace)) is None
    assert delete_workflow("second-opinion") is False
    assert get_workflow("second-opinion") is not None
