"""Integration proof that the real ``seed/agents/aim/`` roster (AIM-0)
loads correctly under ``mode="aim"`` (AIM-2 dispatch) and gets access to
the ``aim_units``/``aim_compare`` tools (AIM-1), tying all three
milestones together end to end — not just each piece in isolation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agent.builtin_prompts import tier_tools
from app.agent.loader import _default_tool_registry, load_team_from_dir

_SEED_AIM_DIR = Path(__file__).resolve().parents[2] / "seed" / "agents" / "aim"


@pytest.fixture
def real_aim_agents_dir(tmp_path: Path) -> Path:
    """A copy of the real seed/agents/aim/*.md files with the
    __PROVIDER_MODEL__ placeholder substituted — mirrors what
    install_seed's _copy_with_substitution does at real install time."""
    target = tmp_path / "aim"
    target.mkdir()
    for md_file in _SEED_AIM_DIR.glob("*.md"):
        text = md_file.read_text(encoding="utf-8").replace(
            "__PROVIDER_MODEL__", "mock:model"
        )
        (target / md_file.name).write_text(text, encoding="utf-8")
    return target


def test_real_aim_roster_loads_with_correct_lead_and_members(real_aim_agents_dir):
    team = load_team_from_dir(real_aim_agents_dir, mode="aim", workspace="/tmp/target")

    assert team is not None
    assert team.mode == "aim"
    assert team.lead.name == "aim-lead"
    assert set(team.blueprints.keys()) == {
        "aim-appraiser",
        "aim-archaeologist",
        "aim-target-architect",
        "aim-converter",
        "aim-test-engineer",
        "aim-triage-analyst",
    }


def test_aim_mode_grants_aim_tools_to_the_real_lead(real_aim_agents_dir):
    team = load_team_from_dir(real_aim_agents_dir, mode="aim", workspace="/tmp/target")
    assert team is not None

    assert "aim_units" in team.lead.agent._tools
    assert "aim_compare" in team.lead.agent._tools


def test_aim_tier_tools_matches_what_the_real_lead_received(real_aim_agents_dir):
    """Cross-check: what tier_tools(mode='aim') computes from the registry
    is exactly what a real loaded team's lead ends up with."""
    team = load_team_from_dir(real_aim_agents_dir, mode="aim", workspace="/tmp/target")
    assert team is not None

    registry = _default_tool_registry()
    expected = set(tier_tools(registry, mode="aim", role="lead"))
    assert "aim_units" in expected
    assert "aim_compare" in expected
    assert expected.issubset(set(team.lead.agent._tools.keys()))


def test_phase_producing_members_declare_workflow_owned_transitions():
    for name in ("aim-archaeologist", "aim-target-architect", "aim-converter"):
        content = (_SEED_AIM_DIR / f"{name}.md").read_text(encoding="utf-8")
        assert "Phase transitions are workflow-owned" in content, name
