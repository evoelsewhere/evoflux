"""Portable repository-scoped EASD Skills and knowledge-base resources."""

from __future__ import annotations

from importlib.resources import files


EASD_SKILL_NAMES = (
    "easd-specify",
    "easd-plan",
    "easd-implement",
    "easd-review",
    "easd-verify",
)


def read_easd_skill(name: str) -> str:
    """Return one bundled portable ``SKILL.md`` template."""

    if name not in EASD_SKILL_NAMES:
        raise KeyError(f"Unknown EASD skill: {name}")
    return files(__name__).joinpath(name, "SKILL.md").read_text(encoding="utf-8")


def read_easd_rules() -> str:
    """Return the shared normative rules installed beside the manifest."""

    return files(__name__).joinpath("RULES.md").read_text(encoding="utf-8")


def read_easd_template(name: str) -> str:
    """Return one standard repository-store YAML template."""

    if name not in EASD_TEMPLATE_NAMES:
        raise KeyError(f"Unknown EASD template: {name}")
    return files(__name__).joinpath("templates", name).read_text(encoding="utf-8")


def read_easd_skeleton(name: str) -> str:
    """Return one portable knowledge-base skeleton file."""

    if name not in EASD_SKELETON_FILES:
        raise KeyError(f"Unknown EASD skeleton file: {name}")
    return files(__name__).joinpath("skeleton", name).read_text(encoding="utf-8")


EASD_TEMPLATE_NAMES = (
    "intent.yaml",
    "specification.yaml",
    "plan.yaml",
    "mission.yaml",
    "review.yaml",
    "verification.yaml",
    "evidence.yaml",
    "deviation.yaml",
    "event.yaml",
    "run.yaml",
    "spec-index.yaml",
    "feature.md",
    "architecture.md",
    "decision.md",
    "reference.md",
    "guide.md",
    "record.md",
)

EASD_SKELETON_FILES = (
    "README.md",
    "index.yaml",
    "specs/README.md",
    "features/README.md",
    "architecture/README.md",
    "architecture/decisions/README.md",
    "reference/README.md",
    "guides/README.md",
    "development/README.md",
    "records/README.md",
    "records/analysis/README.md",
    "records/research/README.md",
    "records/plans/README.md",
    "records/releases/README.md",
    "images/README.md",
    "runs/README.md",
    "templates/README.md",
)


__all__ = [
    "EASD_SKILL_NAMES",
    "EASD_SKELETON_FILES",
    "EASD_TEMPLATE_NAMES",
    "read_easd_rules",
    "read_easd_skeleton",
    "read_easd_skill",
    "read_easd_template",
]
