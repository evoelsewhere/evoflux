"""Regenerate ``body_golden.json``: pydantic's verdict on request bodies.

Run from the repository root:
    uv run python server/crates/area-settings-providers/tests/gen_body_golden.py

Each case validates one JSON value with the real request model from
``app/api/schemas/settings.py`` / ``app/api/routes/auth.py`` and records either
the parsed model (``model_dump(mode="json")``) or FastAPI's 422 detail list
(``loc`` prefixed with ``"body"``, no ``url``). The Rust validator must agree.
Only JSON objects are cases: FastAPI answers a non-object body itself
(``model_attributes_type``, ``missing`` for ``null``), see ``src/body.rs``.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from app.api.routes.auth import OAuthCallbackBody
from app.api.schemas.settings import (
    BackgroundTaskSettingsBody,
    ContextSettingsBody,
    FollowUpSettingsBody,
    ResponseStyleSettingsBody,
    SandboxSettingsBody,
    TeamSpawnSettingsBody,
    VersionControlSettingsBody,
)

VC = {
    "network_timeout_seconds": 60,
    "max_diff_bytes": 1_000_000,
    "default_pull_strategy": "rebase",
    "prune_on_fetch": True,
    "allow_force_push": False,
    "review_request_timeout_seconds": 30,
    "review_retry_attempts": 2,
    "review_retry_backoff_seconds": 1.5,
    "review_max_concurrent_repositories": 4,
    "review_max_pages_per_repository": 5,
    "allow_review_mutations": False,
    "allow_insecure_connections": False,
    "require_successful_checks_before_merge": True,
}

BOOLS = [
    True, False, 0, 1, 2, -1, 0.0, 1.0, 1.5, 2.0, -0.0, "yes", "no", "YES", "On", "off", "t",
    "f", "y", "n", "1", "0", "true", "False", " true", "maybe", "", None, [], {},
]
INTS = [
    3, -1, 0, 2.0, 2.5, "3", " 3 ", "+3", "-3", "3.0", "3.5", "1_000", "0x10",
    "three", "", True, False, None, [], {}, 1e20, "99999999999999999999",
]
FLOATS = [
    60, 60.5, "60", "60.5", " 61 ", "1e2", "inf", "nan", "abc", "", True, False,
    None, [], 9.9, 1800.1,
]
STRS = ["ask", "auto", "x", "", 1, 1.5, True, None, [], {}, "ASK", " ask"]

CASES: dict[str, tuple[type, list]] = {
    "team_spawn": (
        TeamSpawnSettingsBody,
        [{}, {"work": "auto"}, {"work": "x", "coding": 1}, {"other": "ask"}]
        + [{"work": v} for v in STRS],
    ),
    "follow_up": (
        FollowUpSettingsBody,
        [{}, {"delivery": "steer"}, {"delivery": None}, {"delivery": "queue", "x": 1}],
    ),
    "background_tasks": (
        BackgroundTaskSettingsBody,
        [{}, {"x": True}] + [{"wake_idle": v} for v in BOOLS],
    ),
    "response_style": (
        ResponseStyleSettingsBody,
        [{}, {"style": "fancy"}, {"style": 3}, {"style": "simple", "x": 1, "y": 2}],
    ),
    "sandbox": (
        SandboxSettingsBody,
        [
            {},
            {"denied_patterns": [" a ", "", "a"]},
            {"denied_patterns": "a"},
            {"denied_patterns": [1, None, "x"]},
            {"denied_patterns": None},
            {"denied_patterns": ("a",)},
            {"worktree_location": "x", "max_execution_seconds": 1, "unknown": 1},
            {"outbound_data_policy": "redact", "outbound_pii_policy": "strict"},
            {"max_output_bytes": 4095},
            {"max_output_bytes": 1_048_577},
            {"max_execution_seconds": 3600, "max_output_bytes": 4096},
        ]
        + [{"max_execution_seconds": v} for v in INTS]
        + [{"inherit_shell_environment": v} for v in BOOLS],
    ),
    "context": (
        ContextSettingsBody,
        [
            {},
            {"summary_trigger_tokens": None},
            {"summary_trigger_tokens": 19_999},
            {"summary_trigger_tokens": 2_000_001},
            {"keep_recent_turns": "3", "keep_recent_tool_batches": 2.0},
            {"keep_recent_turns": 2.5},
            {"keep_recent_turns": "three"},
            {"keep_recent_turns": 11, "keep_recent_tool_batches": 0, "x": 1},
            {"defaults": {"a": 1}, "coding_defaults": {"b": "2"}},
            {"defaults": {"a": "x"}},
            {"defaults": []},
            {"ignored": [{"field": "x", "message": "y"}]},
            {"ignored": [{"field": "x", "message": "y", "extra": 1}]},
            {"ignored": [{"field": 1}]},
            {"ignored": "x"},
            {"ignored": [1, None, {"field": "a", "message": "b"}]},
            {"defaults": {"a": 1.5, "b": True, "c": None}},
            {"max_tokens": -1, "context_ratio": 1.5},
            {"max_tokens": "5", "context_ratio": "0.5"},
            {"context_ratio": -0.1},
        ]
        + [{"keep_recent_turns": v} for v in INTS],
    ),
    "version_control": (
        VersionControlSettingsBody,
        [{}, VC, {**VC, "extra": 1}, {**VC, "prune_on_fetch": "yes", "max_diff_bytes": "1000000"}]
        + [{**VC, "network_timeout_seconds": v} for v in FLOATS]
        + [{**VC, "review_retry_backoff_seconds": v} for v in (-0.1, 10.1, 0, 10)]
        + [{**VC, "default_pull_strategy": v} for v in ("squash", "ff_only", None)],
    ),
    "oauth_callback": (
        OAuthCallbackBody,
        [{}, {"code": "c"}, {"code": "c", "x": 1}, {"code": 5}, {"code": None}],
    ),
}


def detail(exc: ValidationError) -> list[dict]:
    out = []
    for error in exc.errors(include_url=False):
        item = dict(error)
        item["loc"] = ["body", *item["loc"]]
        if "ctx" in item:
            item["ctx"] = {k: (v if isinstance(v, (int, float, str)) else str(v)) for k, v in item["ctx"].items()}
        out.append(item)
    return out


def main() -> None:
    golden: dict[str, list] = {}
    for name, (model, inputs) in CASES.items():
        rows = []
        for value in inputs:
            try:
                parsed = model.model_validate(value)
            except ValidationError as exc:
                rows.append({"input": value, "errors": detail(exc)})
            else:
                rows.append({"input": value, "ok": parsed.model_dump(mode="json")})
        golden[name] = rows
    path = Path(__file__).with_name("body_golden.json")
    text = json.dumps(golden, indent=1, ensure_ascii=False, allow_nan=False, default=str)
    path.write_text(text + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
