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
    kb_root = tmp_path / "kb"  # no rulebook/ override -- resolves to the builtin fake pack

    installed = rulebook_install.install_rulebook_content(kb_root, "demo-pack")
    assert installed == {
        "workflows": ["demo-flow.yaml"],
        "skills": ["demo-skill"],
        "agents": [],
        "runners": [],
    }

    # Gap-fill: user-edited files survive a re-install.
    from app.services.workflows_fs import global_workflows_dir

    target = global_workflows_dir() / "demo-flow.yaml"
    target.write_text("user edited", encoding="utf-8")
    installed2 = rulebook_install.install_rulebook_content(kb_root, "demo-pack")
    assert installed2 == {"workflows": [], "skills": [], "agents": [], "runners": []}
    assert target.read_text(encoding="utf-8") == "user edited"


def test_unknown_pack_installs_nothing(config_dirs):
    from app.services.aim.rulebook_install import install_rulebook_content

    kb_root = config_dirs / "kb"
    assert install_rulebook_content(kb_root, "not-a-pack") == {
        "workflows": [],
        "skills": [],
        "agents": [],
        "runners": [],
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
    kb_root = tmp_path / "kb"

    # Pre-install a minimal base blueprint (so the seed backfill is a no-op).
    agents_dir = _resolve_aim_agents_dir()
    agents_dir.mkdir(parents=True, exist_ok=True)
    base = agents_dir / "aim-converter.md"
    base.write_text(
        "---\nname: aim-converter\nrole: member\nmodel: prov:model\n"
        "skills:\n  - test-driven-development\n---\n\nYou are aim-converter.\n",
        encoding="utf-8",
    )

    installed = rulebook_install.install_rulebook_content(kb_root, "java-pack")
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
    installed2 = rulebook_install.install_rulebook_content(kb_root, "java-pack")
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

    installed = rulebook_install.install_rulebook_content(tmp_path / "kb", "orphan-pack")
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


# ---------------------------------------------------------------------------
# KB-first resolution — resolve_rulebook_dir / is_project_rulebook.
# ---------------------------------------------------------------------------


def test_resolve_rulebook_dir_prefers_kb_override_over_builtin(tmp_path, monkeypatch):
    from app.services.aim import rulebook_install

    builtin_pack = tmp_path / "builtin" / "some-id"
    builtin_pack.mkdir(parents=True)
    monkeypatch.setattr(rulebook_install, "_pack_dir", lambda _rid: builtin_pack)

    kb_root = tmp_path / "kb"
    project_rulebook = kb_root / "rulebook"
    project_rulebook.mkdir(parents=True)

    # Both a KB override AND a matching builtin pack exist -- KB wins.
    resolved = rulebook_install.resolve_rulebook_dir(kb_root, "some-id")
    assert resolved == project_rulebook
    assert rulebook_install.is_project_rulebook(kb_root) is True


def test_resolve_rulebook_dir_falls_back_to_builtin_without_override(tmp_path, monkeypatch):
    from app.services.aim import rulebook_install

    builtin_pack = tmp_path / "builtin" / "some-id"
    builtin_pack.mkdir(parents=True)
    monkeypatch.setattr(rulebook_install, "_pack_dir", lambda _rid: builtin_pack)

    kb_root = tmp_path / "kb"  # no rulebook/ subdirectory
    resolved = rulebook_install.resolve_rulebook_dir(kb_root, "some-id")
    assert resolved == builtin_pack
    assert rulebook_install.is_project_rulebook(kb_root) is False


def test_resolve_rulebook_dir_returns_none_when_neither_exists(tmp_path, monkeypatch):
    from app.services.aim import rulebook_install

    monkeypatch.setattr(rulebook_install, "_pack_dir", lambda _rid: tmp_path / "no-such-pack")
    assert rulebook_install.resolve_rulebook_dir(tmp_path / "kb", "ghost-id") is None


def test_install_rulebook_content_reads_from_kb_override(config_dirs, tmp_path):
    """End to end: a KB-local rulebook/ pack's workflows/skills install
    exactly like a builtin pack would, with no _pack_dir monkeypatching —
    proving the KB override path is actually wired, not just resolved."""
    from app.services.aim.rulebook_install import install_rulebook_content

    kb_root = tmp_path / "kb"
    project_pack = kb_root / "rulebook"
    (project_pack / "skills" / "custom-idiom").mkdir(parents=True)
    (project_pack / "skills" / "custom-idiom" / "SKILL.md").write_text(
        "---\nname: custom-idiom\ndescription: d\n---\nbody", encoding="utf-8"
    )

    installed = install_rulebook_content(kb_root, "whatever-id-the-project-chose")
    assert installed["skills"] == ["custom-idiom"]

    from pathlib import Path

    from app.core.config import settings as app_settings

    assert (Path(app_settings.SKILLS_DIR) / "custom-idiom" / "SKILL.md").is_file()


def test_installs_runners_into_kb_gap_fill(config_dirs, monkeypatch, tmp_path):
    from app.services.aim import rulebook_install

    pack = tmp_path / "packs" / "runner-pack"
    (pack / "runners").mkdir(parents=True)
    (pack / "runners" / "run_legacy.sh").write_text("#!/usr/bin/env bash\nexit 1\n")
    (pack / "runners" / "run_target.sh").write_text("#!/usr/bin/env bash\nexit 1\n")
    monkeypatch.setattr(rulebook_install, "_pack_dir", lambda _rid: pack)

    kb_root = tmp_path / "kb"
    installed = rulebook_install.install_rulebook_content(kb_root, "runner-pack")
    assert sorted(installed["runners"]) == ["run_legacy.sh", "run_target.sh"]
    assert (kb_root / "runners" / "run_target.sh").is_file()

    # Gap-fill: a KB-edited runner survives a re-install.
    (kb_root / "runners" / "run_target.sh").write_text("# customized\n")
    installed2 = rulebook_install.install_rulebook_content(kb_root, "runner-pack")
    assert installed2["runners"] == []
    assert (kb_root / "runners" / "run_target.sh").read_text() == "# customized\n"
