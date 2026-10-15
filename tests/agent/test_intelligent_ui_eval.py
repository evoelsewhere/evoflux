from __future__ import annotations

import json
from pathlib import Path

import pytest

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


def test_motion_eval_separates_temporal_value_from_prompt_length() -> None:
    cases = {case["id"]: case for case in load_cases(FIXTURE)}

    implicit_motion = cases["implicit_temporal_explainer"]
    assert implicit_motion["expected_choice"] == "motion"
    assert all(
        word not in implicit_motion["prompt"].lower()
        for word in ("video", "animation", "motion")
    )

    long_summary = cases["long_context_static_summary"]
    assert long_summary["expected_choice"] == "prose"
    assert len(long_summary["prompt"].encode("utf-8")) >= 2500
    assert "visual_artifact" in long_summary["forbidden_choices"]

    long_motion = cases["long_context_motion_explainer"]
    assert long_motion["expected_choice"] == "motion"
    assert len(long_motion["prompt"].encode("utf-8")) >= 1500


def test_water_treatment_visual_explanation_is_a_motion_eval_case() -> None:
    cases = {case["id"]: case for case in load_cases(FIXTURE)}
    water_treatment = cases["implicit_water_treatment"]

    assert water_treatment["expected_choice"] == "motion"
    assert all(
        word not in water_treatment["prompt"].lower()
        for word in ("video", "animation", "motion")
    )
    assert (
        "why the next step needs the previous one"
        in water_treatment["required_evidence"]
    )


def test_explicit_video_deliverable_and_evoflux_view_are_an_eval_case() -> None:
    cases = {case["id"]: case for case in load_cases(FIXTURE)}
    espresso = cases["explicit_video_in_workbench"]

    assert espresso["expected_choice"] == "motion"
    assert "open the playable result in EvoFlux" in espresso["prompt"]
    assert "Workbench preview" in espresso["required_evidence"]
    assert "PDF substitution" in espresso["forbidden_choices"]


def test_cases_encode_task_intent_instead_of_runtime_keyword_rules() -> None:
    source = FIXTURE.read_text(encoding="utf-8")
    assert all(case["prompt"].strip() for case in json.loads(source))
    assert "keyword_router" not in source


def test_live_smoke_is_opt_in_and_records_only_outcomes_and_tool_quality() -> None:
    assert parse_args([]).live is False
    assert LIVE_SMOKE_FIELDS == {
        "case_id",
        "model_id",
        "expected_choice",
        "observed_choice",
        "selection_match",
        "tool",
        "kind",
        "prompt_bytes",
        "payload_bytes",
        "has_provenance",
        "status",
        "error_category",
    }


@pytest.mark.parametrize(
    ("expected_choice", "observed_choice", "matches"),
    [
        ("motion", "motion", True),
        ("motion", "dashboard", False),
        ("motion", None, False),
    ],
)
def test_live_smoke_reports_expected_and_observed_visual_choice(
    monkeypatch, expected_choice, observed_choice, matches
) -> None:
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
            if self.stream:
                if observed_choice is not None:
                    yield b"event: visual_artifact\n"
                    yield (
                        f'data: {{"type":"visual_artifact","kind":"{observed_choice}",'
                        '"source_html":"<html></html>"}\n'
                    ).encode()
                yield b"event: done\n"
                yield b'data: {"type":"done"}\n'

    monkeypatch.setattr(
        "scripts.smoke_intelligent_ui._request",
        lambda url, **_kwargs: Response(stream=url.endswith("/stream")),
    )

    outcome = _run_case(
        "http://127.0.0.1:8000/api/team",
        "xiaomi:mimo-v2.6-flash",
        {
            "id": "water-treatment",
            "prompt": "Explain how each stage changes the water.",
            "expected_choice": expected_choice,
        },
    )

    assert outcome["expected_choice"] == expected_choice
    assert outcome["observed_choice"] == observed_choice
    assert outcome["selection_match"] is matches


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


def test_live_smoke_records_prompt_size_without_recording_prompt_content(
    monkeypatch,
) -> None:
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

    monkeypatch.setattr(
        "scripts.smoke_intelligent_ui._request",
        lambda url, **_kwargs: Response(stream=url.endswith("/stream")),
    )
    prompt = "Tóm tắt các nguyên tắc cache trong 5 ý ngắn."

    outcome = _run_case(
        "http://127.0.0.1:8000/api/team",
        "xiaomi:mimo-v2.6-flash",
        {"id": "long-context", "prompt": prompt},
    )

    assert outcome["prompt_bytes"] == len(prompt.encode("utf-8"))
    assert prompt not in str(outcome)


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
