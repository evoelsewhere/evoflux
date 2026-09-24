from __future__ import annotations

from pathlib import Path

import pytest

from app.core.ai_policy import resolve_ai_policy
from app.core.config import settings
from app.core.runtime_settings import (
    ConductorSettings,
    RuntimeSettings,
    save_runtime_settings,
)


def _save(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, conductor: ConductorSettings) -> None:
    monkeypatch.setattr(settings, "EVOFLUX_CONFIG_DIR", str(tmp_path / "config"))
    save_runtime_settings(RuntimeSettings(conductor=conductor))


def test_no_rows_means_unrestricted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _save(tmp_path, monkeypatch, ConductorSettings())

    policy = resolve_ai_policy()

    assert policy.allowed_providers == []
    assert policy.allowed_tools == []
    assert policy.provider_allowed("anthropic")
    assert policy.tool_allowed("read")


def test_project_row_restricts_providers_and_tools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save(
        tmp_path,
        monkeypatch,
        ConductorSettings(
            ai_policy_rows=[
                {
                    "scope": "project",
                    "subject_id": "",
                    "allowed_providers": ["anthropic", "googlegenai"],
                    "allowed_tools": ["read", "write"],
                }
            ]
        ),
    )

    policy = resolve_ai_policy()

    assert policy.provider_allowed("anthropic")
    assert not policy.provider_allowed("openai")
    assert policy.tool_allowed("read")
    assert not policy.tool_allowed("browser")


def test_role_row_narrows_but_never_widens_the_project_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save(
        tmp_path,
        monkeypatch,
        ConductorSettings(
            member_primary_role="user",
            ai_policy_rows=[
                {
                    "scope": "project",
                    "subject_id": "",
                    "allowed_providers": ["anthropic", "googlegenai"],
                    "allowed_tools": [],
                },
                {
                    "scope": "role",
                    "subject_id": "user",
                    "allowed_providers": ["anthropic", "openai"],
                    "allowed_tools": ["read"],
                },
            ],
        ),
    )

    policy = resolve_ai_policy()

    # Intersection of project + role: only anthropic survives, even though
    # the role row itself also lists openai (not in the project's list).
    assert policy.allowed_providers == ["anthropic"]
    assert policy.provider_allowed("anthropic")
    assert not policy.provider_allowed("openai")
    assert not policy.provider_allowed("googlegenai")
    # The role row's tools apply even though the project row set no
    # restriction of its own — an empty project list means "no restriction
    # from this tier", not "nothing to intersect against".
    assert policy.allowed_tools == ["read"]


def test_role_row_for_a_different_role_does_not_apply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save(
        tmp_path,
        monkeypatch,
        ConductorSettings(
            member_primary_role="admin",
            ai_policy_rows=[
                {
                    "scope": "role",
                    "subject_id": "user",
                    "allowed_providers": ["anthropic"],
                    "allowed_tools": [],
                },
            ],
        ),
    )

    policy = resolve_ai_policy()

    assert policy.allowed_providers == []
    assert policy.provider_allowed("openai")


def test_default_provider_and_model_prefer_the_role_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save(
        tmp_path,
        monkeypatch,
        ConductorSettings(
            member_primary_role="contribute",
            ai_policy_rows=[
                {
                    "scope": "project",
                    "subject_id": "",
                    "default_provider": "anthropic",
                    "default_model": "anthropic:claude-sonnet-5",
                },
                {
                    "scope": "role",
                    "subject_id": "contribute",
                    "default_provider": "googlegenai",
                    "default_model": None,
                },
            ],
        ),
    )

    policy = resolve_ai_policy()

    assert policy.default_provider == "googlegenai"
    # Role row set no default_model of its own, so the project row's wins.
    assert policy.default_model == "anthropic:claude-sonnet-5"
