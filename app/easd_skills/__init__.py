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

# Exact hashes of the last bundled phase Skills that incorrectly resolved Runs
# below ``data_directory``. Setup may refresh these byte-identical generated
# copies; any project edit changes the hash and is preserved.
EASD_LEGACY_SKILL_SHA256 = {
    "easd-specify": "08fe0fbf89bae7ce1c9e66aa9a04a908237b0d256d733dda55ae346ea0fac9a3",
    "easd-plan": "f22f3e90da84672e2a689f5191c169f3b4b1114a43ec9e332643445126556832",
    "easd-implement": "d71f65cec5a228e8ff13401786333858f82eee1eb29167555e305d7e7ac52513",
    "easd-review": "622ab3016556d717141fe08fa6b4ff00195ed5e033f8d73329d37d5f1a8e7916",
    "easd-verify": "52ba9c666cef96b380e92e2a8b2dd32854e340147be41fda59123a816bef3ab6",
}


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

    if name not in (*EASD_SKELETON_FILES, *EASD_LEGACY_OPTIONAL_SKELETON_FILES):
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
)

EASD_LEGACY_OPTIONAL_SKELETON_FILES = (
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
    "EASD_LEGACY_SKILL_SHA256",
    "EASD_SKILL_NAMES",
    "EASD_LEGACY_OPTIONAL_SKELETON_FILES",
    "EASD_SKELETON_FILES",
    "EASD_TEMPLATE_NAMES",
    "read_easd_rules",
    "read_easd_skeleton",
    "read_easd_skill",
    "read_easd_template",
]
