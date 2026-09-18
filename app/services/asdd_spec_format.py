"""The requirement/scenario grammar shared by ASDD specs and change deltas.

A capability's `spec.md` is the current truth for one behavior; a change's
`specs/<capability>/spec.md` says only what that change does to it. Both are
Markdown with the same shape, so the archive step is a structural merge rather
than a rewrite, and a reviewer reads a delta and a spec with the same eyes.

The grammar is deliberately small — three heading levels and two bullet
keywords — because it has to survive being written by an agent, edited by a
person and diffed in a pull request. Anything richer would need a parser people
cannot hold in their head, and the format's whole value is that they can.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace

_REQUIREMENT = re.compile(r"^###\s+Requirement:\s*(?P<name>.+?)\s*$")
_SCENARIO = re.compile(r"^####\s+Scenario:\s*(?P<name>.+?)\s*$")
_SECTION = re.compile(r"^##\s+(?P<name>.+?)\s*$")
#: A rename is a REMOVED plus an ADDED, so there is no RENAMED section. A
#: section this pattern does not recognize is ignored, and `validate_delta`
#: reports the delta as declaring nothing — which is what a reader needs to see.
_DELTA_SECTION = re.compile(
    r"^##\s+(?P<operation>ADDED|MODIFIED|REMOVED)\s+Requirements\s*$"
)
_STEP = re.compile(r"^[-*]\s+\*\*(?P<keyword>WHEN|THEN|AND|GIVEN)\*\*\s*(?P<text>.*)$")

PURPOSE_HEADING = "Purpose"
REQUIREMENTS_HEADING = "Requirements"


class AsddSpecFormatError(ValueError):
    """A spec or delta page does not follow the requirement grammar."""


@dataclass(frozen=True, slots=True)
class Scenario:
    name: str
    steps: list[str]

    def render(self) -> list[str]:
        return [f"#### Scenario: {self.name}", "", *self.steps, ""]


@dataclass(frozen=True, slots=True)
class Requirement:
    name: str
    statement: str
    scenarios: list[Scenario] = field(default_factory=list)

    def render(self) -> list[str]:
        lines = [f"### Requirement: {self.name}", ""]
        if self.statement:
            lines += [self.statement, ""]
        for scenario in self.scenarios:
            lines += scenario.render()
        return lines


@dataclass(frozen=True, slots=True)
class Spec:
    """One capability's current truth."""

    purpose: str
    requirements: list[Requirement] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class SpecDelta:
    """What one change does to one capability."""

    added: list[Requirement] = field(default_factory=list)
    modified: list[Requirement] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.added or self.modified or self.removed)

    def touched_names(self) -> list[str]:
        return [
            *(item.name for item in self.added),
            *(item.name for item in self.modified),
            *self.removed,
        ]


def _clean(lines: list[str]) -> str:
    return "\n".join(lines).strip("\n")


def _parse_requirements(lines: list[str], *, source: str) -> list[Requirement]:
    """Read a run of `### Requirement:` blocks and their scenarios."""

    requirements: list[Requirement] = []
    name: str | None = None
    statement: list[str] = []
    scenarios: list[Scenario] = []
    scenario_name: str | None = None
    scenario_steps: list[str] = []

    def close_scenario() -> None:
        nonlocal scenario_name, scenario_steps
        if scenario_name is None:
            return
        scenarios.append(
            Scenario(name=scenario_name, steps=[step for step in scenario_steps])
        )
        scenario_name = None
        scenario_steps = []

    def close_requirement() -> None:
        nonlocal name, statement, scenarios
        close_scenario()
        if name is None:
            return
        requirements.append(
            Requirement(
                name=name,
                statement=_clean(statement),
                scenarios=list(scenarios),
            )
        )
        name = None
        statement = []
        scenarios = []

    for line in lines:
        requirement_match = _REQUIREMENT.match(line)
        if requirement_match:
            close_requirement()
            name = requirement_match.group("name")
            continue
        scenario_match = _SCENARIO.match(line)
        if scenario_match:
            if name is None:
                raise AsddSpecFormatError(
                    f"{source}: scenario '{scenario_match.group('name')}' appears "
                    "before any requirement"
                )
            close_scenario()
            scenario_name = scenario_match.group("name")
            continue
        if scenario_name is not None:
            if line.strip():
                scenario_steps.append(line.rstrip())
            continue
        if name is not None:
            statement.append(line)

    close_requirement()
    return requirements


def _split_sections(text: str) -> list[tuple[str, list[str]]]:
    """Return `(heading, lines)` for each `##` section, in document order."""

    sections: list[tuple[str, list[str]]] = []
    heading = ""
    buffer: list[str] = []
    for line in text.replace("\r\n", "\n").split("\n"):
        # `^##\s` cannot match `### Requirement:` or `#### Scenario:`, because the
        # third `#` is not whitespace — deeper headings stay inside their section.
        match = _SECTION.match(line)
        if match:
            sections.append((heading, buffer))
            heading = match.group("name")
            buffer = []
            continue
        buffer.append(line)
    sections.append((heading, buffer))
    return sections


def parse_spec(body: str, *, source: str = "spec.md") -> Spec:
    """Parse a capability's canonical page."""

    purpose: list[str] = []
    requirements: list[Requirement] = []
    for heading, lines in _split_sections(body):
        if heading.lower() == PURPOSE_HEADING.lower():
            purpose = lines
        elif heading.lower() == REQUIREMENTS_HEADING.lower():
            requirements = _parse_requirements(lines, source=source)
    return Spec(purpose=_clean(purpose), requirements=requirements)


def parse_delta(body: str, *, source: str = "spec.md") -> SpecDelta:
    """Parse a change's delta page for one capability."""

    added: list[Requirement] = []
    modified: list[Requirement] = []
    removed: list[str] = []
    for line_group in _split_sections(body):
        heading, lines = line_group
        match = _DELTA_SECTION.match(f"## {heading}")
        if match is None:
            continue
        operation = match.group("operation")
        parsed = _parse_requirements(lines, source=source)
        if operation == "ADDED":
            added += parsed
        elif operation == "MODIFIED":
            modified += parsed
        elif operation == "REMOVED":
            removed += [item.name for item in parsed]
    return SpecDelta(added=added, modified=modified, removed=removed)


def render_spec(spec: Spec) -> str:
    """Render a capability's canonical page."""

    lines = [f"## {PURPOSE_HEADING}", "", spec.purpose or "_Not yet described._", ""]
    lines += [f"## {REQUIREMENTS_HEADING}", ""]
    for requirement in spec.requirements:
        lines += requirement.render()
    return "\n".join(lines).rstrip("\n") + "\n"


def render_delta(delta: SpecDelta) -> str:
    """Render a change's delta page for one capability."""

    lines: list[str] = []
    for heading, requirements in (
        ("ADDED Requirements", delta.added),
        ("MODIFIED Requirements", delta.modified),
    ):
        if not requirements:
            continue
        lines += [f"## {heading}", ""]
        for requirement in requirements:
            lines += requirement.render()
    if delta.removed:
        lines += ["## REMOVED Requirements", ""]
        for name in delta.removed:
            lines += [f"### Requirement: {name}", ""]
    return "\n".join(lines).rstrip("\n") + "\n"


def apply_delta(spec: Spec, delta: SpecDelta, *, source: str = "spec.md") -> Spec:
    """Fold one delta into a capability's current truth.

    `MODIFIED` replaces a requirement in place so the page keeps its reading
    order; a modification naming a requirement that does not exist is an error
    rather than an append, because silently turning it into an addition is how a
    renamed requirement ends up duplicated in the catalogue.
    """

    requirements = list(spec.requirements)
    by_name = {item.name: index for index, item in enumerate(requirements)}

    for requirement in delta.modified:
        index = by_name.get(requirement.name)
        if index is None:
            raise AsddSpecFormatError(
                f"{source}: MODIFIED names '{requirement.name}', which the current "
                "spec does not contain — add it under ADDED Requirements instead"
            )
        requirements[index] = requirement

    for name in delta.removed:
        if name not in by_name:
            raise AsddSpecFormatError(
                f"{source}: REMOVED names '{name}', which the current spec does "
                "not contain"
            )
    dropped = set(delta.removed)
    requirements = [item for item in requirements if item.name not in dropped]

    existing = {item.name for item in requirements}
    for requirement in delta.added:
        if requirement.name in existing:
            raise AsddSpecFormatError(
                f"{source}: ADDED names '{requirement.name}', which the current "
                "spec already contains — use MODIFIED Requirements instead"
            )
        requirements.append(requirement)

    return replace(spec, requirements=requirements)


def validate_requirements(requirements: list[Requirement], *, source: str) -> list[str]:
    """Return every structural problem in a set of requirements.

    Returns rather than raises: the UI shows a change's problems as blockers on
    its action rail, and a page with three faults should report three, not the
    first one encountered.
    """

    problems: list[str] = []
    seen: set[str] = set()
    for requirement in requirements:
        label = f"{source}: requirement '{requirement.name}'"
        if requirement.name in seen:
            problems.append(f"{label} is declared twice")
        seen.add(requirement.name)
        if not requirement.statement:
            problems.append(f"{label} has no statement")
        if not requirement.scenarios:
            problems.append(f"{label} has no scenario")
        scenario_names: set[str] = set()
        for scenario in requirement.scenarios:
            scenario_label = f"{label}, scenario '{scenario.name}'"
            if scenario.name in scenario_names:
                problems.append(f"{scenario_label} is declared twice")
            scenario_names.add(scenario.name)
            keywords = {
                match.group("keyword")
                for match in (_STEP.match(step) for step in scenario.steps)
                if match is not None
            }
            if "WHEN" not in keywords:
                problems.append(f"{scenario_label} has no **WHEN** step")
            if "THEN" not in keywords:
                problems.append(f"{scenario_label} has no **THEN** step")
    return problems


def validate_delta(delta: SpecDelta, *, source: str) -> list[str]:
    """Return every structural problem in one delta page."""

    if delta.is_empty():
        return [f"{source}: declares no ADDED, MODIFIED or REMOVED requirement"]
    problems = validate_requirements(delta.added + delta.modified, source=source)
    names = delta.touched_names()
    duplicates = {name for name in names if names.count(name) > 1}
    problems += [
        f"{source}: requirement '{name}' appears in more than one delta section"
        for name in sorted(duplicates)
    ]
    return problems


__all__ = [
    "AsddSpecFormatError",
    "Requirement",
    "Scenario",
    "Spec",
    "SpecDelta",
    "apply_delta",
    "parse_delta",
    "parse_spec",
    "render_delta",
    "render_spec",
    "validate_delta",
    "validate_requirements",
]
