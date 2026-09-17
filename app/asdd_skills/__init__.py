"""Portable repository-scoped ASDD Skills and catalogue skeleton resources.

Everything an ASDD agent needs to work in a repository ships here and is copied
into that repository at setup: the six phase Skills, the normative rules, the
starting shape of the catalogue, and the artifact templates. Nothing is
generated at runtime, so a checkout carries its own method and a reviewer can
see the contract the agent was given in the same diff as the work it produced.
"""

from __future__ import annotations

from importlib.resources import files

#: One Skill per phase of the Agent-Driven Development cycle: scope, frame,
#: constrain, execute, verify, consolidate. The names double as the `draft_*`
#: and `start_*` actions the UI rail offers, so a phase never exists in the
#: product without a Skill that tells an agent how to carry it out.
ASDD_SKILL_NAMES = (
    "asdd-propose",
    "asdd-specify",
    "asdd-plan",
    "asdd-implement",
    "asdd-verify",
    "asdd-archive",
)

ASDD_SKILL_REFERENCE_FILES = ("code-context-contract.md",)

ASDD_SKILL_TEMPLATE = "TEMPLATE.md"
"""The output contract installed beside every phase ``SKILL.md``.

A Skill says how to think about a phase; its template says exactly what the
phase has to leave behind, and what gets it rejected. Keeping the two
together is what makes the shape checkable by the agent writing it rather
than only by the gate that later refuses it.
"""
"""Reference bundles installed beside every ASDD phase ``SKILL.md``.

Without the code-context contract an agent has no bounded-discovery rule, so it
falls back to raw reads and speculative globbing.
"""

#: The one artifact the product itself seeds. Every other artifact's shape is
#: the `TEMPLATE.md` installed beside the Skill that writes it, where the agent
#: doing the writing will actually read it. Shipping unread copies here is what
#: let `design.md`, `tasks.md` and `spec.md` sit in the package for a whole
#: release describing a format nothing checked and nobody was shown.
ASDD_TEMPLATE_NAMES = ("proposal.md",)

ASDD_SKELETON_FILES = (
    "project.md",
    "specs/README.md",
    "changes/README.md",
)


def read_asdd_skill(name: str) -> str:
    """Return one bundled portable ``SKILL.md``."""

    if name not in ASDD_SKILL_NAMES:
        raise KeyError(f"Unknown ASDD skill: {name}")
    return files(__name__).joinpath(name, "SKILL.md").read_text(encoding="utf-8")


def read_asdd_skill_template(name: str) -> str:
    """Return one bundled phase ``TEMPLATE.md``."""

    if name not in ASDD_SKILL_NAMES:
        raise KeyError(f"Unknown ASDD skill: {name}")
    return files(__name__).joinpath(name, ASDD_SKILL_TEMPLATE).read_text(
        encoding="utf-8"
    )


def read_asdd_skill_reference(name: str, reference: str) -> str:
    """Return one bundled reference file for an ASDD phase Skill."""

    if name not in ASDD_SKILL_NAMES:
        raise KeyError(f"Unknown ASDD skill: {name}")
    if reference not in ASDD_SKILL_REFERENCE_FILES:
        raise KeyError(f"Unknown ASDD skill reference: {reference}")
    return (
        files(__name__)
        .joinpath(name, "references", reference)
        .read_text(encoding="utf-8")
    )


def read_asdd_rules() -> str:
    """Return the normative rules installed beside the manifest."""

    return files(__name__).joinpath("RULES.md").read_text(encoding="utf-8")


def read_asdd_template(name: str) -> str:
    """Return one artifact template."""

    if name not in ASDD_TEMPLATE_NAMES:
        raise KeyError(f"Unknown ASDD template: {name}")
    return files(__name__).joinpath("templates", name).read_text(encoding="utf-8")


def read_asdd_skeleton(name: str) -> str:
    """Return one catalogue skeleton file."""

    if name not in ASDD_SKELETON_FILES:
        raise KeyError(f"Unknown ASDD skeleton file: {name}")
    return files(__name__).joinpath("skeleton", name).read_text(encoding="utf-8")


__all__ = [
    "ASDD_SKELETON_FILES",
    "ASDD_SKILL_NAMES",
    "ASDD_SKILL_REFERENCE_FILES",
    "ASDD_SKILL_TEMPLATE",
    "ASDD_TEMPLATE_NAMES",
    "read_asdd_rules",
    "read_asdd_skeleton",
    "read_asdd_skill",
    "read_asdd_skill_reference",
    "read_asdd_skill_template",
    "read_asdd_template",
]
