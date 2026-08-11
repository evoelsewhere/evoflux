"""Canonicalization for AIM's compare engine — normalizes volatile noise
(timestamps, run ids, whitespace, ...) out of legacy/target output *before*
diffing. See ``documents/research/aim-framework.md`` §2.7.3 / §3.8: compare
must be deterministic, and canonicalization is what keeps a "harmless"
formatting difference from masquerading as (or hiding) a real defect.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from app.services.aim.models import CanonicalProfile


def load_profile(path: Path) -> CanonicalProfile:
    """Load a ``canonicalizers/<id>.yaml`` profile from a rulebook."""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return CanonicalProfile.from_yaml_dict(data)


# A standalone decimal token: a run of digits, a dot, then a fractional
# part, not embedded in a longer dotted/numeric run (so version strings like
# ``1.2.3`` and dotted dates like ``12.00.00`` are left alone).
_DECIMAL_RE = re.compile(r"(?<![\d.])(\d+)\.(\d+)(?![\d.])")


def _trim_trailing_zeros(match: re.Match[str]) -> str:
    whole, frac = match.group(1), match.group(2).rstrip("0")
    return whole if not frac else f"{whole}.{frac}"


def mask_text(text: str, profile: CanonicalProfile) -> str:
    """Apply only the profile's mask rules — no whitespace or decimal
    normalization. Fixed-width record compares use this: collapsing spaces or
    trimming trailing zeros would shift column positions and misalign fields.
    """
    result = text
    for rule in profile.mask:
        result = re.sub(rule.pattern, rule.replace, result)
    return result


def canonicalize_text(text: str, profile: CanonicalProfile) -> str:
    """Apply mask rules, whitespace normalization, then decimal
    normalization — in that order.

    Masks run first because they sometimes target whitespace-sensitive
    patterns (e.g. a padded timestamp field) — normalizing whitespace first
    could shift a mask's regex out of alignment. Decimal normalization runs
    last, on already-cleaned text, so ``trim_trailing_zeros`` makes ``1.50``
    and ``1.5`` compare equal in the line-diff path (the JSON path already
    normalizes via float parsing).
    """
    result = text
    for rule in profile.mask:
        result = re.sub(rule.pattern, rule.replace, result)
    if profile.whitespace == "normalize":
        result = "\n".join(
            re.sub(r"[ \t]+", " ", line).rstrip() for line in result.splitlines()
        )
    if profile.trim_trailing_zeros:
        result = _DECIMAL_RE.sub(_trim_trailing_zeros, result)
    return result
