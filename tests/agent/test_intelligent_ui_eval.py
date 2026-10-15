from __future__ import annotations

import json
from pathlib import Path

from scripts.smoke_intelligent_ui import (
    LIVE_SMOKE_FIELDS,
    _request,
    _run_case,
    load_cases,
    parse_args,
    select_cases,
)


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
        "error_category",
    }


def test_live_smoke_request_stays_open_until_the_caller_finishes_reading(
    monkeypatch,
) -> None:
    class Response:
        closed = False

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.closed = True

    response = Response()
    monkeypatch.setattr(
        "scripts.smoke_intelligent_ui.urlopen",
        lambda _request, timeout: response,
    )

    with _request("http://127.0.0.1:8000/api/team/chat") as opened:
        assert opened is response
        assert opened.closed is False

    assert response.closed is True


def test_live_smoke_can_run_one_case_without_sending_the_whole_fixture_set() -> None:
    cases = load_cases(FIXTURE)

    selected = select_cases(cases, ["motion_explainer"])

    assert [case["id"] for case in selected] == ["motion_explainer"]


def test_live_smoke_rejects_unknown_case_ids() -> None:
    import pytest

    with pytest.raises(ValueError, match="unknown evaluation case"):
        select_cases(load_cases(FIXTURE), ["not-a-case"])


def test_live_smoke_stops_reading_the_stream_after_done(monkeypatch) -> None:
    class Response:
        def __init__(self, stream: bool = False):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return b'{"session_id":"00000000-0000-4000-8000-000000000001"}'

        def __iter__(self):
            yield b"event: done\n"
            yield b'data: {"type":"done"}\n'
            raise AssertionError("smoke runner kept reading after the terminal event")

    def request(url: str, **_kwargs):
        return Response(stream=url.endswith("/stream"))

    monkeypatch.setattr("scripts.smoke_intelligent_ui._request", request)

    outcome = _run_case(
        "http://127.0.0.1:8000/api/team",
        "xiaomi:mimo-v2.6-flash",
        {"id": "motion", "prompt": "Show a short process over time."},
    )

    assert outcome["status"] == "complete"


def test_live_smoke_reports_only_safe_error_category(monkeypatch) -> None:
    class Response:
        def __init__(self, stream: bool = False):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return b'{"session_id":"00000000-0000-4000-8000-000000000001"}'

        def __iter__(self):
            yield b"event: error\n"
            yield (
                b'data: {"type":"error","message":"private provider detail",'
                b'"metadata":{"exception":"ProviderAuthenticationError"}}\n'
            )
            raise AssertionError("smoke runner kept reading after the terminal event")

    monkeypatch.setattr(
        "scripts.smoke_intelligent_ui._request",
        lambda url, **_kwargs: Response(stream=url.endswith("/stream")),
    )

    outcome = _run_case(
        "http://127.0.0.1:8000/api/team",
        "xiaomi:mimo-v2.6-flash",
        {"id": "motion", "prompt": "Show a short process over time."},
    )

    assert outcome["status"] == "error"
    assert outcome["error_category"] == "ProviderAuthenticationError"
    assert "private provider detail" not in str(outcome)


def test_live_smoke_marks_a_stream_that_exceeds_its_deadline(monkeypatch) -> None:
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return b'{"session_id":"00000000-0000-4000-8000-000000000001"}'

        def __iter__(self):
            yield b": keepalive\n"

    monkeypatch.setattr(
        "scripts.smoke_intelligent_ui._request",
        lambda url, **_kwargs: Response(),
    )
    times = iter([0.0, 1.1])
    monkeypatch.setattr("scripts.smoke_intelligent_ui.monotonic", lambda: next(times))

    outcome = _run_case(
        "http://127.0.0.1:8000/api/team",
        "xiaomi:mimo-v2.6-flash",
        {"id": "motion", "prompt": "Show a short process over time."},
        timeout_seconds=1,
    )

    assert outcome["status"] == "timeout"
