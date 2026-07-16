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


def canonicalize_text(text: str, profile: CanonicalProfile) -> str:
    """Apply mask rules, then whitespace normalization, in that order.

    Masks run first because they sometimes target whitespace-sensitive
    patterns (e.g. a padded timestamp field) — normalizing whitespace first
    could shift a mask's regex out of alignment.
    """
    result = text
    for rule in profile.mask:
        result = re.sub(rule.pattern, rule.replace, result)
    if profile.whitespace == "normalize":
        result = "\n".join(
            re.sub(r"[ \t]+", " ", line).rstrip() for line in result.splitlines()
        )
    return result
