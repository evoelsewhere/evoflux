from __future__ import annotations

import json
from pathlib import Path

from scripts.smoke_intelligent_ui import LIVE_SMOKE_FIELDS, load_cases, parse_args


FIXTURE = (
    Path(__file__).parents[1]
    / "fixtures"
    / "intelligent_ui"
    / "rich_artifact_cases.json"
)
EXPECTED_CHOICES = {"prose", "ui_block", "dashboard", "motion", "scene3d"}


def test_visual_eval_cases_cover_native_rich_prose_and_missing_capability() -> None:
    cases = load_cases(FIXTURE)
    assert {case["expected_choice"] for case in cases} == EXPECTED_CHOICES
    missing = next(case for case in cases if case["id"] == "missing_capability")
    assert "visual_artifact" in missing["forbidden_choices"]


def test_cases_encode_task_intent_instead_of_runtime_keyword_rules() -> None:
    source = FIXTURE.read_text(encoding="utf-8")
    assert all(case["prompt"].strip() for case in json.loads(source))
    assert "keyword_router" not in source


def test_live_smoke_is_opt_in_and_records_only_outcomes_and_tool_quality() -> None:
    assert parse_args([]).live is False
    assert LIVE_SMOKE_FIELDS == {
        "case_id",
        "model_id",
        "tool",
        "kind",
        "payload_bytes",
        "has_provenance",
        "status",
    }
