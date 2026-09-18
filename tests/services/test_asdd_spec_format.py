from __future__ import annotations

import pytest

from app.services.asdd_spec_format import (
    AsddSpecFormatError,
    Requirement,
    Scenario,
    Spec,
    SpecDelta,
    apply_delta,
    parse_delta,
    parse_spec,
    render_delta,
    render_spec,
    validate_delta,
    validate_requirements,
)

SPEC_BODY = """## Purpose

Define how a change reaches the catalogue.

## Requirements

### Requirement: Slug identity

A change SHALL be identified by its directory name.

#### Scenario: Two chats open the same change

- **WHEN** two Coding chats point at `add-user-auth`
- **THEN** both read and write the same change folder

### Requirement: Declared status

A change SHALL declare its status in `proposal.md`.

#### Scenario: Read a status

- **WHEN** a reader opens `proposal.md`
- **THEN** the front matter names the current phase
"""

DELTA_BODY = """## ADDED Requirements

### Requirement: Archive folds deltas

Archiving SHALL merge every delta into its capability spec.

#### Scenario: Merge on archive

- **WHEN** a change with deltas is archived
- **THEN** each capability spec carries the change's requirements

## MODIFIED Requirements

### Requirement: Declared status

A change SHALL declare its status and its approvals in `proposal.md`.

#### Scenario: Read a status

- **WHEN** a reader opens `proposal.md`
- **THEN** the front matter names the current phase and every approval

## REMOVED Requirements

### Requirement: Slug identity
"""


def test_parse_spec_reads_purpose_requirements_and_scenarios() -> None:
    spec = parse_spec(SPEC_BODY)

    assert spec.purpose == "Define how a change reaches the catalogue."
    assert [item.name for item in spec.requirements] == [
        "Slug identity",
        "Declared status",
    ]
    first = spec.requirements[0]
    assert first.statement == "A change SHALL be identified by its directory name."
    assert [scenario.name for scenario in first.scenarios] == [
        "Two chats open the same change"
    ]
    assert first.scenarios[0].steps == [
        "- **WHEN** two Coding chats point at `add-user-auth`",
        "- **THEN** both read and write the same change folder",
    ]


def test_spec_round_trip_is_stable() -> None:
    once = render_spec(parse_spec(SPEC_BODY))
    twice = render_spec(parse_spec(once))

    assert once == twice
    assert parse_spec(once) == parse_spec(SPEC_BODY)


def test_delta_round_trip_is_stable() -> None:
    delta = parse_delta(DELTA_BODY)

    assert [item.name for item in delta.added] == ["Archive folds deltas"]
    assert [item.name for item in delta.modified] == ["Declared status"]
    assert delta.removed == ["Slug identity"]
    assert parse_delta(render_delta(delta)) == delta


def test_apply_delta_adds_modifies_and_removes_in_place() -> None:
    merged = apply_delta(parse_spec(SPEC_BODY), parse_delta(DELTA_BODY))

    assert [item.name for item in merged.requirements] == [
        "Declared status",
        "Archive folds deltas",
    ]
    assert "every approval" in merged.requirements[0].scenarios[0].steps[1]


def test_apply_delta_rejects_modifying_an_absent_requirement() -> None:
    delta = SpecDelta(
        modified=[
            Requirement(
                name="Nobody home",
                statement="The system SHALL do something.",
                scenarios=[Scenario(name="s", steps=["- **WHEN** a", "- **THEN** b"])],
            )
        ]
    )

    with pytest.raises(AsddSpecFormatError, match="MODIFIED names 'Nobody home'"):
        apply_delta(parse_spec(SPEC_BODY), delta)


def test_apply_delta_rejects_adding_an_existing_requirement() -> None:
    delta = SpecDelta(
        added=[
            Requirement(
                name="Slug identity",
                statement="The system SHALL do something.",
                scenarios=[Scenario(name="s", steps=["- **WHEN** a", "- **THEN** b"])],
            )
        ]
    )

    with pytest.raises(AsddSpecFormatError, match="already contains"):
        apply_delta(parse_spec(SPEC_BODY), delta)


def test_apply_delta_onto_an_empty_spec_creates_the_capability() -> None:
    """A brand-new capability has no spec yet; the delta is its first content."""

    delta = parse_delta(
        """## ADDED Requirements

### Requirement: First contract

The system SHALL start somewhere.

#### Scenario: Bootstrap

- **WHEN** a capability has no spec
- **THEN** archiving creates one from the delta
"""
    )

    merged = apply_delta(Spec(purpose="", requirements=[]), delta)

    assert [item.name for item in merged.requirements] == ["First contract"]


def test_validate_requirements_reports_every_structural_fault() -> None:
    requirements = parse_spec(
        """## Requirements

### Requirement: No scenario

The system SHALL be stated but unproven.

### Requirement: Half a scenario

The system SHALL be stated.

#### Scenario: Only a when

- **WHEN** something happens
"""
    ).requirements

    problems = validate_requirements(requirements, source="spec.md")

    assert any("has no scenario" in problem for problem in problems)
    assert any("has no **THEN** step" in problem for problem in problems)


def test_a_scenario_may_use_either_markdown_bullet() -> None:
    requirements = parse_spec(
        """## Requirements

### Requirement: Either bullet

The system SHALL accept both list markers.

#### Scenario: Asterisks

* **WHEN** a scenario uses asterisks
* **THEN** its steps still count
"""
    ).requirements

    assert validate_requirements(requirements, source="spec.md") == []


def test_a_section_the_grammar_does_not_know_declares_nothing() -> None:
    """There is no RENAMED section: a rename is a REMOVED plus an ADDED."""

    delta = parse_delta(
        """## RENAMED Requirements

### Requirement: Slug identity

#### Scenario: s

- **WHEN** a
- **THEN** b
"""
    )

    assert delta.is_empty()
    assert validate_delta(delta, source="spec.md") == [
        "spec.md: declares no ADDED, MODIFIED or REMOVED requirement"
    ]


def test_validate_delta_rejects_an_empty_page() -> None:
    assert validate_delta(SpecDelta(), source="spec.md") == [
        "spec.md: declares no ADDED, MODIFIED or REMOVED requirement"
    ]


def test_validate_delta_rejects_a_requirement_in_two_sections() -> None:
    delta = parse_delta(
        """## ADDED Requirements

### Requirement: Twice

The system SHALL be listed once.

#### Scenario: s

- **WHEN** a
- **THEN** b

## REMOVED Requirements

### Requirement: Twice
"""
    )

    problems = validate_delta(delta, source="spec.md")

    assert any("more than one delta section" in problem for problem in problems)


def test_scenario_before_any_requirement_is_rejected() -> None:
    with pytest.raises(AsddSpecFormatError, match="before any requirement"):
        parse_spec(
            """## Requirements

#### Scenario: Orphan

- **WHEN** a
- **THEN** b
"""
        )
