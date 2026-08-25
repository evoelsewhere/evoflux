"""Versioned repository-scoped Agent Skills installed by EASD setup."""

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
)


__all__ = [
    "EASD_SKILL_NAMES",
    "EASD_TEMPLATE_NAMES",
    "read_easd_rules",
    "read_easd_skill",
    "read_easd_template",
]
