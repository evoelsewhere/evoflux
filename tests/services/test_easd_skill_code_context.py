"""EASD phase skills must ship the bounded-discovery contract.

Without it an EASD agent has no rule against bulk scanning, so it falls back to
raw reads and speculative globbing: a measured specify phase on a three-file
repository spent a third of its tool calls on duplicate reads and empty globs.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app.easd_skills import (
    EASD_SKILL_NAMES,
    EASD_SKILL_REFERENCE_FILES,
    read_easd_skill,
    read_easd_skill_reference,
)
from app.services.easd_setup_service import (
    EasdRepositoryTarget,
    initialize_repositories,
    inspect_repository,
)

CANONICAL_CONTRACT = Path(
    "app/agent/builtin_skills/coding-investigation/references/code-context-contract.md"
)


def _normalized(text: str) -> str:
    return " ".join(text.split())


@pytest.mark.parametrize("name", EASD_SKILL_NAMES)
def test_skill_names_the_tool_and_states_refresh_semantics(name):
    text = _normalized(read_easd_skill(name))
    assert "`code_context`" in text
    assert "skip" in text.casefold()
    assert "Keep `refresh=true` for the first indexed query" in text
    assert "`refresh=false` only for an immediate follow-up" in text
    assert "references/code-context-contract.md" in text


@pytest.mark.parametrize("name", EASD_SKILL_NAMES)
def test_skill_has_a_code_graph_section(name):
    assert "## Code graph navigation" in read_easd_skill(name)


def test_bundled_contract_matches_the_canonical_coding_contract():
    canonical = CANONICAL_CONTRACT.read_text(encoding="utf-8")
    for name in EASD_SKILL_NAMES:
        bundled = read_easd_skill_reference(name, "code-context-contract.md")
        assert bundled == canonical, f"{name} carries a diverged contract"


def test_every_skill_bundles_an_identical_contract():
    digests = {
        hashlib.sha256(
            read_easd_skill_reference(name, reference).encode("utf-8")
        ).hexdigest()
        for name in EASD_SKILL_NAMES
        for reference in EASD_SKILL_REFERENCE_FILES
    }
    assert len(digests) == 1


def test_phase_guidance_is_tailored_not_copy_pasted():
    """Each phase needs its own actions; a cloned section teaches nothing."""

    sections: dict[str, str] = {}
    for name in EASD_SKILL_NAMES:
        body = read_easd_skill(name).split("## Code graph navigation", 1)[1]
        # Drop the deliberately shared contract pointer before comparing.
        sections[name] = body.split("Read `references/code-context-contract.md`", 1)[0]
    assert len(set(sections.values())) == len(EASD_SKILL_NAMES), (
        "phase-specific guidance is duplicated across skills"
    )


class TestInstallation:
    def test_setup_installs_the_contract_into_each_skill(self, tmp_path):
        root = tmp_path / "project"
        root.mkdir()
        target = EasdRepositoryTarget(path=str(root), name="project")
        initialize_repositories([target])

        for name in EASD_SKILL_NAMES:
            for reference in EASD_SKILL_REFERENCE_FILES:
                installed = (
                    root / ".evoflux" / "skills" / name / "references" / reference
                )
                assert installed.is_file(), f"missing {name}/references/{reference}"
                assert installed.read_text(encoding="utf-8") == (
                    read_easd_skill_reference(name, reference)
                )
        assert inspect_repository(target)["state"] == "ready"

    def test_a_missing_contract_marks_the_repository_for_upgrade(self, tmp_path):
        root = tmp_path / "project"
        root.mkdir()
        target = EasdRepositoryTarget(path=str(root), name="project")
        initialize_repositories([target])

        (
            root
            / ".evoflux"
            / "skills"
            / "easd-specify"
            / "references"
            / "code-context-contract.md"
        ).unlink()

        status = inspect_repository(target)
        assert status["state"] == "upgrade_required"
        assert "easd-specify" in (status["issue"] or "")

        initialize_repositories([target])
        assert inspect_repository(target)["state"] == "ready"


class TestSupersededGenerations:
    """Every superseded bundle hash must be listed, not only the first.

    `_is_legacy_bundled_skill` gates the in-place refresh. An installed Skill
    matching none of the recorded generations is treated as a project edit and
    preserved, which strands the repository: the references install while the
    phase guidance never arrives.
    """

    def test_predicate_refreshes_a_recorded_generation(self, tmp_path, monkeypatch):
        from app.services import easd_setup_service
        from app.services.easd_setup_service import _is_legacy_bundled_skill

        path = tmp_path / "SKILL.md"
        path.write_text("generation under test\n", encoding="utf-8")
        digest = hashlib.sha256(
            path.read_text(encoding="utf-8").encode("utf-8")
        ).hexdigest()

        assert _is_legacy_bundled_skill(path, "easd-specify") is False

        monkeypatch.setattr(
            easd_setup_service,
            "EASD_SUPERSEDED_SKILL_SHA256",
            {"easd-specify": digest},
        )
        assert _is_legacy_bundled_skill(path, "easd-specify") is True

    def test_a_stranded_generation_is_offered_an_upgrade(self, tmp_path, monkeypatch):
        from app.services import easd_setup_service

        root = tmp_path / "project"
        root.mkdir()
        target = EasdRepositoryTarget(path=str(root), name="project")
        initialize_repositories([target])
        assert inspect_repository(target)["state"] == "ready"

        installed = {
            name: root / ".evoflux" / "skills" / name / "SKILL.md"
            for name in EASD_SKILL_NAMES
        }
        monkeypatch.setattr(
            easd_setup_service,
            "EASD_SUPERSEDED_SKILL_SHA256",
            {
                name: hashlib.sha256(
                    path.read_text(encoding="utf-8").encode("utf-8")
                ).hexdigest()
                for name, path in installed.items()
            },
        )

        status = inspect_repository(target)
        assert status["state"] == "upgrade_required"
        assert "Missing EASD skills" in (status["issue"] or "")
        for name in EASD_SKILL_NAMES:
            assert name in (status["issue"] or "")

    def test_the_current_bundle_is_not_recorded_as_superseded(self):
        from app.easd_skills import (
            EASD_LEGACY_SKILL_SHA256,
            EASD_SUPERSEDED_SKILL_SHA256,
        )

        assert set(EASD_LEGACY_SKILL_SHA256) == set(EASD_SKILL_NAMES)
        assert set(EASD_SUPERSEDED_SKILL_SHA256) == set(EASD_SKILL_NAMES)
        for name in EASD_SKILL_NAMES:
            current = hashlib.sha256(read_easd_skill(name).encode("utf-8")).hexdigest()
            assert current != EASD_LEGACY_SKILL_SHA256[name]
            assert current != EASD_SUPERSEDED_SKILL_SHA256[name], (
                f"{name}: the shipped bundle equals a superseded hash, so setup "
                "would treat the current generation as stale forever"
            )
