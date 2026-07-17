"""AIM-4 rulebook content installation (app/services/aim/rulebook_install.py)."""

from __future__ import annotations

import pytest


@pytest.fixture
def config_dirs(tmp_path, monkeypatch):
    from app.core.config import settings as app_settings

    monkeypatch.setattr(app_settings, "EVOFLUX_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setattr(app_settings, "SKILLS_DIR", str(tmp_path / "config" / "skills"))
    return tmp_path


def test_installs_pack_workflows_and_skills_gap_fill(config_dirs, monkeypatch, tmp_path):
    from app.services.aim import rulebook_install

    # Fake pack with one workflow + one skill.
    pack = tmp_path / "packs" / "demo-pack"
    (pack / "workflows").mkdir(parents=True)
    (pack / "workflows" / "demo-flow.yaml").write_text(
        "schema_version: 1\nname: demo-flow\nnodes:\n  - {id: n, kind: notify, message: hi}\n",
        encoding="utf-8",
    )
    (pack / "skills" / "demo-skill").mkdir(parents=True)
    (pack / "skills" / "demo-skill" / "SKILL.md").write_text(
        "---\nname: demo-skill\ndescription: d\n---\nbody", encoding="utf-8"
    )
    monkeypatch.setattr(rulebook_install, "_pack_dir", lambda _rid: pack)

    installed = rulebook_install.install_rulebook_content("demo-pack")
    assert installed == {
        "workflows": ["demo-flow.yaml"],
        "skills": ["demo-skill"],
        "agents": [],
    }

    # Gap-fill: user-edited files survive a re-install.
    from app.services.workflows_fs import global_workflows_dir

    target = global_workflows_dir() / "demo-flow.yaml"
    target.write_text("user edited", encoding="utf-8")
    installed2 = rulebook_install.install_rulebook_content("demo-pack")
    assert installed2 == {"workflows": [], "skills": [], "agents": []}
    assert target.read_text(encoding="utf-8") == "user edited"


def test_unknown_pack_installs_nothing(config_dirs):
    from app.services.aim.rulebook_install import install_rulebook_content

    assert install_rulebook_content("not-a-pack") == {
        "workflows": [],
        "skills": [],
        "agents": [],
    }


def test_agent_overlay_merges_skills_and_prompt(config_dirs, monkeypatch, tmp_path):
    """Pack agents/<name>.md overlays merge onto the installed blueprint:
    skills appended (deduped), body appended once (marker-guarded)."""
    from app.services.aim import rulebook_install
    from app.services.team_manager import _resolve_aim_agents_dir

    pack = tmp_path / "packs" / "java-pack"
    (pack / "agents").mkdir(parents=True)
    (pack / "agents" / "aim-converter.md").write_text(
        "---\nskills:\n  - java-modernization-idioms\n  - test-driven-development\n---\n\n"
        "## Java specifics\n\nPrefer safe modernization.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(rulebook_install, "_pack_dir", lambda _rid: pack)

    # Pre-install a minimal base blueprint (so the seed backfill is a no-op).
    agents_dir = _resolve_aim_agents_dir()
    agents_dir.mkdir(parents=True, exist_ok=True)
    base = agents_dir / "aim-converter.md"
    base.write_text(
        "---\nname: aim-converter\nrole: member\nmodel: prov:model\n"
        "skills:\n  - test-driven-development\n---\n\nYou are aim-converter.\n",
        encoding="utf-8",
    )

    installed = rulebook_install.install_rulebook_content("java-pack")
    assert installed["agents"] == ["aim-converter.md"]

    from app.agent.tools.builtin.skill import _parse_frontmatter

    meta, body = _parse_frontmatter(base.read_text(encoding="utf-8"))
    # Appended + deduped, base order preserved.
    assert meta["skills"] == ["test-driven-development", "java-modernization-idioms"]
    assert meta["name"] == "aim-converter"
    assert meta["model"] == "prov:model"
    assert "You are aim-converter." in body
    assert "## Java specifics" in body
    assert "rulebook-overlay: java-pack/aim-converter.md" in body

    # Idempotent: a second create/join doesn't append twice.
    installed2 = rulebook_install.install_rulebook_content("java-pack")
    assert installed2["agents"] == []
    assert base.read_text(encoding="utf-8").count("## Java specifics") == 1


def test_agent_overlay_without_base_is_skipped(config_dirs, monkeypatch, tmp_path):
    from app.services.aim import rulebook_install
    from app.services.team_manager import _resolve_aim_agents_dir

    pack = tmp_path / "packs" / "orphan-pack"
    (pack / "agents").mkdir(parents=True)
    (pack / "agents" / "aim-nonexistent.md").write_text(
        "---\nskills: [x]\n---\nbody", encoding="utf-8"
    )
    monkeypatch.setattr(rulebook_install, "_pack_dir", lambda _rid: pack)
    # Base roster exists but has no blueprint with that name.
    agents_dir = _resolve_aim_agents_dir()
    agents_dir.mkdir(parents=True, exist_ok=True)
    (agents_dir / "aim-lead.md").write_text(
        "---\nname: aim-lead\nrole: lead\n---\nlead", encoding="utf-8"
    )

    installed = rulebook_install.install_rulebook_content("orphan-pack")
    assert installed["agents"] == []


def test_builtin_packs_have_no_conflicting_workflow_names(config_dirs):
    # Builtin aim pipelines are their own discovery root — packs must not
    # ship same-named workflows that would shadow them confusingly.
    from app.services.aim.rulebook_install import _pack_dir

    for rulebook_id in ("java8-java21", "vb6-dotnet", "cobol-java21"):
        pack_workflows = _pack_dir(rulebook_id) / "workflows"
        if pack_workflows.is_dir():
            names = {p.stem for p in pack_workflows.glob("*.yaml")}
            assert not names & {
                "aim-assess",
                "aim-understand",
                "aim-convert-unit",
                "aim-convert-wave",
                "aim-test-compare",
                "aim-cutover-check",
            }
