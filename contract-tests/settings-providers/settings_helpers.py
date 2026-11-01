"""Shared builders for the ``/api/settings`` and ``/api/auth`` contract.

Secrets here are dummies made up per test (``sk-contract-<label>-<hex>``); no
real key ever enters this suite. A failing check names the secret's label,
never its value.
"""

from __future__ import annotations

import secrets as _secrets
from pathlib import Path

import httpx
import pytest

UNAUTHORIZED_BODY = {"detail": "Unauthorized — EvoFlux access key required."}

#: Every route of the unit as (method, path, JSON body). Bodies are valid, so a
#: 401 proves authentication runs before anything else.
ROUTES: list[tuple[str, str, object]] = [
    ("GET", "/api/auth/check", None),
    ("GET", "/api/auth/codex/login", None),
    ("POST", "/api/auth/codex/callback", {"code": "x"}),
    ("GET", "/api/settings/sandbox", None),
    ("PUT", "/api/settings/sandbox", {"denied_patterns": []}),
    ("GET", "/api/settings/context", None),
    ("PUT", "/api/settings/context", {}),
    ("GET", "/api/settings/version-control", None),
    (
        "PUT",
        "/api/settings/version-control",
        {
            "network_timeout_seconds": 120,
            "max_diff_bytes": 2000000,
            "default_pull_strategy": "ff_only",
            "prune_on_fetch": True,
            "allow_force_push": False,
            "review_request_timeout_seconds": 20,
            "review_retry_attempts": 2,
            "review_retry_backoff_seconds": 0.5,
            "review_max_concurrent_repositories": 4,
            "review_max_pages_per_repository": 5,
            "allow_review_mutations": False,
            "allow_insecure_connections": False,
            "require_successful_checks_before_merge": False,
        },
    ),
    ("GET", "/api/settings/team-spawn", None),
    ("PUT", "/api/settings/team-spawn", {"work": "ask", "coding": "ask"}),
    ("GET", "/api/settings/follow-up", None),
    ("PUT", "/api/settings/follow-up", {"delivery": "queue"}),
    ("GET", "/api/settings/background-tasks", None),
    ("PUT", "/api/settings/background-tasks", {"wake_idle": True}),
    ("GET", "/api/settings/response-style", None),
    ("PUT", "/api/settings/response-style", {"style": "visual"}),
    ("GET", "/api/settings/providers", None),
    ("PUT", "/api/settings/providers/anthropic", {"api_key": "k"}),
    ("DELETE", "/api/settings/providers/anthropic", None),
    ("POST", "/api/settings/providers/anthropic/models", {"api_key": "k"}),
    ("POST", "/api/settings/providers/anthropic/test", {"model": "m"}),
    ("PUT", "/api/settings/providers/anthropic/visible-models", {"models": []}),
    ("GET", "/api/settings/providers/codex/usage", None),
    ("GET", "/api/settings/providers/openai/logo", None),
    ("POST", "/api/settings/seed", {}),
]

#: Read-only endpoints that must never carry a secret, whatever was saved.
GET_PATHS = [
    "/api/auth/check",
    "/api/settings/sandbox",
    "/api/settings/context",
    "/api/settings/version-control",
    "/api/settings/webbridge",
    "/api/settings/webbridge/agent-browsing",
    "/api/settings/computer-app",
    "/api/settings/team-spawn",
    "/api/settings/follow-up",
    "/api/settings/background-tasks",
    "/api/settings/response-style",
    "/api/settings/providers",
    "/api/settings/providers/codex/usage",
    "/api/settings/providers/copilot/usage",
    "/api/settings/providers/anthropic/usage",
    "/api/settings/providers/nope/usage",
]


class Secrets:
    """Dummy secrets for one test and the check that none of them leaked."""

    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    def new(self, label: str) -> str:
        value = f"sk-contract-{label}-{_secrets.token_hex(6)}"
        self._values[label] = value
        return value

    def leaked_in(self, blob: bytes | str) -> list[str]:
        raw = blob.encode("utf-8") if isinstance(blob, str) else blob
        return [
            label for label, value in self._values.items() if value.encode() in raw
        ]

    def assert_clean(self, where: str, blob: bytes | str) -> None:
        leaked = self.leaked_in(blob)
        if leaked:
            pytest.fail(f"secret(s) {leaked} leaked in {where}", pytrace=False)

    def assert_response_clean(self, where: str, response: httpx.Response) -> None:
        self.assert_clean(f"{where} body", response.content)
        self.assert_clean(f"{where} headers", str(dict(response.headers)))
        self.assert_clean(f"{where} url", str(response.url))


def env_lines(config_dir: Path) -> list[str]:
    """The ``.env`` file as lines; ``[]`` when it does not exist."""
    path = config_dir / ".env"
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8").splitlines()


def env_values(config_dir: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in env_lines(config_dir):
        if "=" in line and not line.startswith("#"):
            name, _, value = line.partition("=")
            values[name.strip()] = value
    return values


def mask(lines: list[str], secrets: Secrets) -> list[str]:
    """``.env`` lines with each dummy secret replaced by ``<label>``."""
    out = []
    for line in lines:
        for label, value in secrets._values.items():
            line = line.replace(value, f"<{label}>")
        out.append(line)
    return out
