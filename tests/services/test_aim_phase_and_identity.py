"""Unit tests for AIM phase-vocabulary helpers and repo-identity credential
stripping (audit hardening)."""

from __future__ import annotations

from app.services.aim.models import (
    VALID_PHASES,
    is_valid_project_phase,
    is_valid_unit_phase,
    next_unit_phase,
)
from app.services.aim.project import _strip_url_credentials


def test_unit_phase_validation():
    assert all(is_valid_unit_phase(p) for p in VALID_PHASES)
    assert not is_valid_unit_phase("convert")  # a plausible typo
    assert not is_valid_unit_phase("assessed")


def test_project_phase_validation():
    assert is_valid_project_phase("assess")
    assert is_valid_project_phase("cutover")
    assert not is_valid_project_phase("assessed")


def test_next_unit_phase_walks_and_terminates():
    assert next_unit_phase("inventory") == "understood"
    assert next_unit_phase("equivalent") == "cutover"
    assert next_unit_phase("cutover") is None
    assert next_unit_phase("bogus") is None


def test_strip_url_credentials():
    assert (
        _strip_url_credentials("https://user:ghp_secret@github.com/o/r.git")
        == "https://github.com/o/r.git"
    )
    # scp-style remote carries only a username, not a secret — left intact.
    assert _strip_url_credentials("git@github.com:o/r.git") == "git@github.com:o/r.git"
    # credential-free https is unchanged.
    assert (
        _strip_url_credentials("https://github.com/o/r.git")
        == "https://github.com/o/r.git"
    )
