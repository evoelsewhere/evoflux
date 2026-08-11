"""Strict SemVer 2.0 parsing and precedence for client compatibility gates."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import total_ordering

_SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)


@total_ordering
@dataclass(frozen=True)
class SemanticVersion:
    major: int
    minor: int
    patch: int
    prerelease: tuple[str, ...] = ()

    @classmethod
    def parse(cls, value: str) -> SemanticVersion:
        match = _SEMVER_RE.fullmatch(value.strip())
        if match is None:
            raise ValueError("version must follow strict SemVer 2.0")
        prerelease = tuple(match.group(4).split(".")) if match.group(4) else ()
        return cls(
            major=int(match.group(1)),
            minor=int(match.group(2)),
            patch=int(match.group(3)),
            prerelease=prerelease,
        )

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, SemanticVersion):
            return NotImplemented
        current_core = (self.major, self.minor, self.patch)
        other_core = (other.major, other.minor, other.patch)
        if current_core != other_core:
            return current_core < other_core
        if not self.prerelease:
            return False
        if not other.prerelease:
            return True
        for current, candidate in zip(self.prerelease, other.prerelease, strict=False):
            if current == candidate:
                continue
            current_numeric = current.isdigit()
            candidate_numeric = candidate.isdigit()
            if current_numeric and candidate_numeric:
                return int(current) < int(candidate)
            if current_numeric != candidate_numeric:
                return current_numeric
            return current < candidate
        return len(self.prerelease) < len(other.prerelease)


__all__ = ["SemanticVersion"]
