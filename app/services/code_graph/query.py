"""Query normalization shared by graph and live-source retrieval.

This module deliberately knows nothing about user intents, task verbs, file
extensions, or supported languages. It only turns arbitrary text into stable
identifier-like terms and measures their overlap with indexed fields.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Iterable


def _identifier_parts(value: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    for index, char in enumerate(value):
        previous = value[index - 1] if index else ""
        following = value[index + 1] if index + 1 < len(value) else ""
        boundary = bool(
            current
            and char.isupper()
            and (
                previous.islower()
                or previous.isdigit()
                or (previous.isupper() and following.islower())
            )
        )
        if boundary:
            parts.append("".join(current))
            current = []
        current.append(char)
    if current:
        parts.append("".join(current))
    return parts


def query_terms(query: str, *, limit: int = 32) -> tuple[str, ...]:
    """Return structural query evidence before ordinary prose.

    Compound identifiers, camel-case names, and acronyms are the strongest
    code-shaped evidence.  They are collected across the whole query before
    ordinary words, so a named symbol near the end of a long question cannot
    be displaced by the prose that introduces it.  Order remains stable within
    each evidence class and no language- or intent-specific vocabulary is
    involved.
    """
    runs: list[str] = []
    current: list[str] = []
    connectors = frozenset("_.$/-")
    for char in query:
        if char.isalnum() or (current and char in connectors):
            current.append(char)
        elif current:
            runs.append("".join(current))
            current = []
    if current:
        runs.append("".join(current))

    structural: list[str] = []
    derived: list[str] = []
    prose: list[str] = []
    for run in runs:
        normalized_run = run.strip("".join(connectors))
        components: list[str] = []
        component: list[str] = []
        for char in normalized_run:
            if char in connectors:
                if component:
                    components.append("".join(component))
                    component = []
            else:
                component.append(char)
        if component:
            components.append("".join(component))
        identifier_parts = [
            part for value in components for part in _identifier_parts(value)
        ]
        is_structural = bool(
            any(char in connectors for char in normalized_run)
            or len(identifier_parts) > len(components)
            or (len(normalized_run) > 1 and normalized_run.isupper())
        )
        destination = structural if is_structural else prose
        for value in (normalized_run,):
            normalized = value.casefold()
            if len(normalized) >= 2:
                destination.append(normalized)
        if is_structural:
            for value in (*components, *identifier_parts):
                normalized = value.casefold()
                if len(normalized) >= 2:
                    derived.append(normalized)

    ordered: list[str] = []
    seen: set[str] = set()

    def add(term: str) -> None:
        if term not in seen:
            seen.add(term)
            ordered.append(term)

    for term in structural:
        add(term)

    # Full prose terms carry the user's own granularity, while derived pieces
    # add identifier recall. Interleave both classes so neither a standalone
    # action nor the component of a late compound symbol can consume the
    # other's entire bounded expansion.
    for index in range(max(len(prose), len(derived))):
        if index < len(prose):
            add(prose[index])
        if index < len(derived):
            add(derived[index])
    return tuple(ordered[: max(1, limit)])


@dataclass(frozen=True, slots=True)
class QueryMatch:
    hits: int
    total: int
    weighted_coverage: float
    exact: bool

    @property
    def score(self) -> float:
        return (100.0 if self.exact else 0.0) + self.weighted_coverage * 100.0


def match_query(
    query: str,
    terms: Iterable[str],
    values: Iterable[str | None],
) -> QueryMatch:
    """Measure query overlap across fields using term length as information weight."""
    normalized_values = tuple(value.casefold() for value in values if value)
    normalized_query = query.strip().casefold()
    normalized_terms = tuple(dict.fromkeys(term.casefold() for term in terms if term))
    matched = tuple(
        term
        for term in normalized_terms
        if any(term in value for value in normalized_values)
    )
    total_weight = sum(len(term) for term in normalized_terms)
    matched_weight = sum(len(term) for term in matched)
    exact = bool(normalized_query) and any(
        normalized_query in value for value in normalized_values
    )
    return QueryMatch(
        hits=len(matched),
        total=len(normalized_terms),
        weighted_coverage=(matched_weight / total_weight if total_weight else 0.0),
        exact=exact,
    )
