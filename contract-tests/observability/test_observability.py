"""``/api/observability`` contract: span-derived summary, trace list, trace detail.

Spans come from the committed synthetic JSONL under ``fixtures/spans/``; see
``otel_fixtures.py`` for how it is shifted to the backend's clock. The fixture
holds seven traces (T1..T7):

* T1  tool error under an OK root, two models, cache read and write
* T2  failed root, title generation and summarization count as LLM calls
* T3  one trace with two runs (team); usage must not be shared between them
* T4  orphan chat span (parent trimmed) and a span without ``end_time``
* T5  newest turn, no children
* T6  30 h old, inside windows of 2 days or more
* T7  40 days old, outside the default detail window
"""

from __future__ import annotations

import json
import re
import shutil
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from otel_fixtures import (
    FIXTURE_DIR,
    Seeded,
    seed,
    span,
    write_partition,
)

UNAUTHORIZED_BODY = {"detail": "Unauthorized — EvoFlux access key required."}
SUMMARY = "/api/observability/summary"
TRACES = "/api/observability/traces"


def trace_id(n: int) -> str:
    return "0x" + format(n, "032x")


def at(hours: int = 0, minutes: int = 0, seconds: int = 0) -> datetime:
    return Seeded(timedelta()).at(hours, minutes, seconds)


def ge_error(field: str, minimum: int, given: str) -> dict:
    return {
        "type": "greater_than_equal",
        "loc": ["query", field],
        "msg": f"Input should be greater than or equal to {minimum}",
        "input": given,
        "ctx": {"ge": minimum},
    }


def le_error(field: str, maximum: int, given: str) -> dict:
    return {
        "type": "less_than_equal",
        "loc": ["query", field],
        "msg": f"Input should be less than or equal to {maximum}",
        "input": given,
        "ctx": {"le": maximum},
    }


def empty_summary_body(days: int) -> dict:
    return {
        "sample_ratio": 1.0,
        "totals": {
            "turns": 0,
            "llm_calls": 0,
            "tool_calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cached_tokens": 0,
            "cache_write_tokens": 0,
            "cache_percent": 0.0,
            "estimated_cost_usd": 0.0,
            "errors": 0,
            "failed_turns": 0,
            "error_spans": 0,
            "error_rate": 0.0,
        },
        "latency_ms": {
            "turn_p50": 0.0,
            "turn_p95": 0.0,
            "llm_p50": 0.0,
            "llm_p95": 0.0,
            "tool_p50": 0.0,
            "tool_p95": 0.0,
        },
        "daily_turns": [],
        "time_series": [],
        "bucket_size": "hour" if days == 1 else "day",
        "by_model": [],
        "cache_by_step": [],
        "by_tool": [],
        "tokens_by_model": [],
    }


def without_window(body: dict) -> dict:
    return {k: v for k, v in body.items() if k not in ("window_start", "window_end")}


def window_days(body: dict) -> timedelta:
    return datetime.fromisoformat(body["window_end"]) - datetime.fromisoformat(
        body["window_start"]
    )


@pytest.fixture
def no_spans_dir(backend, tmp_path: Path) -> None:
    """Python creates the spans dir at start-up; v3 must also cope without it."""
    shutil.rmtree(tmp_path / "state" / "otel" / "spans")


@pytest.fixture
def seeded(backend, tmp_path: Path) -> Seeded:
    return seed(tmp_path)


# ── span facts (the oracle for time-bucketed fields) ────────────────────────
# (kind, end, status, duration_ms, input, output, cost, minimum days to be in window)

FACTS = [
    ("turn", at(-3, 30), "OK", 60000.0, 0, 0, 0.0, 1),
    ("turn", at(-2, 40), "ERROR", 30000.0, 0, 0, 0.0, 1),
    ("turn", at(-1, 10), "OK", 20000.0, 0, 0, 0.0, 1),
    ("turn", at(-1, 9, 55), "OK", 12000.0, 0, 0, 0.0, 1),
    ("turn", at(0, 20), "OK", 500.0, 0, 0, 0.0, 1),
    ("turn", at(-30, 10), "OK", 9000.0, 0, 0, 0.0, 2),
    ("llm", at(-3, 29, 20), "OK", 4000.0, 1000, 200, 0.01, 1),
    ("llm", at(-3, 29, 40), "OK", 2000.0, 500, 100, 0.002, 1),
    ("llm", at(-2, 39, 40), "OK", 300.0, 100, 20, 0.0001, 1),
    ("llm", at(-2, 39, 55), "OK", 800.0, 300, 60, 0.0004, 1),
    ("llm", at(-1, 9, 50), "OK", 1500.0, 700, 70, 0.005, 1),
    ("llm", at(-1, 9, 52), "OK", 1800.0, 900, 90, 0.007, 1),
    ("llm", at(0, 5), "OK", 700.0, 200, 20, 0.001, 1),
    ("llm", at(-30, 9, 58), "OK", 1200.0, 50, 5, 0.0005, 2),
    ("tool", at(-3, 29, 25), "OK", 120.0, 0, 0, 0.0, 1),
    ("tool", at(-3, 29, 50), "ERROR", 900.0, 0, 0, 0.0, 1),
    ("tool", at(-2, 39, 45), "OK", 50.0, 0, 0, 0.0, 1),
    ("tool", at(-1, 9, 53), "OK", 40.0, 0, 0, 0.0, 1),
]


def quantile_cont(values: list[float], q: float) -> float:
    ordered = sorted(values)
    position = q * (len(ordered) - 1)
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def bucket_key(seeded: Seeded, end: datetime, size: str) -> str:
    return (
        seeded.hour_bucket(end)
        if size == "hour"
        else seeded.hour_bucket(end)[:11] + "00:00:00Z"
    )


ZERO_ROW = {
    "turns": 0,
    "llm_calls": 0,
    "tool_calls": 0,
    "failed_turns": 0,
    "error_spans": 0,
    "input_tokens": 0,
    "output_tokens": 0,
    "estimated_cost_usd": 0.0,
    "turn_p95_ms": 0.0,
}


def expected_series(seeded: Seeded, days: int) -> list[dict]:
    size = "hour" if days == 1 else "day"
    groups: dict[str, list] = defaultdict(list)
    for fact in FACTS:
        if fact[7] <= days:
            groups[bucket_key(seeded, fact[1], size)].append(fact)
    rows = {}
    for key, facts in groups.items():
        turns = [f for f in facts if f[0] == "turn"]
        llms = [f for f in facts if f[0] == "llm"]
        rows[key] = {
            "bucket_start": key,
            "turns": len(turns),
            "llm_calls": len(llms),
            "tool_calls": len([f for f in facts if f[0] == "tool"]),
            "failed_turns": len([f for f in turns if f[2] == "ERROR"]),
            "error_spans": len([f for f in facts if f[2] == "ERROR"]),
            "input_tokens": sum(f[4] for f in llms),
            "output_tokens": sum(f[5] for f in llms),
            "estimated_cost_usd": round(sum(f[6] for f in llms), 8),
            "turn_p95_ms": round(quantile_cont([f[3] for f in turns], 0.95), 1)
            if turns
            else 0.0,
        }
    return rows


def assert_series(seeded: Seeded, days: int, series: list[dict]) -> None:
    size = "hour" if days == 1 else "day"
    keys = [row["bucket_start"] for row in series]
    assert keys == sorted(keys)
    assert len(keys) == len(set(keys))
    assert len(series) == (25 if days == 1 else days + 1)
    step = timedelta(hours=1) if size == "hour" else timedelta(days=1)
    fmt = "%Y-%m-%dT%H:00:00Z" if size == "hour" else "%Y-%m-%dT00:00:00Z"
    parsed = [datetime.strptime(k, fmt) for k in keys]
    assert all(b - a == step for a, b in zip(parsed, parsed[1:]))
    expected = expected_series(seeded, days)
    assert set(expected) <= set(keys)
    for row in series:
        assert row == expected.get(
            row["bucket_start"], {**ZERO_ROW, "bucket_start": row["bucket_start"]}
        )


# ── authentication ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "path",
    [SUMMARY, TRACES, f"{TRACES}/{trace_id(1)}"],
)
def test_requires_auth(backend, path) -> None:
    response = httpx.get(f"{backend.base_url}{path}", timeout=30.0)
    assert response.status_code == 401
    assert response.json() == UNAUTHORIZED_BODY


@pytest.mark.parametrize("path", [SUMMARY, TRACES, f"{TRACES}/{trace_id(1)}"])
def test_wrong_token_is_rejected(backend, path) -> None:
    response = httpx.get(
        f"{backend.base_url}{path}",
        headers={"Authorization": "Bearer not-the-token"},
        timeout=30.0,
    )
    assert response.status_code == 401
    assert response.json() == UNAUTHORIZED_BODY


def test_auth_is_checked_before_query_validation(backend) -> None:
    response = httpx.get(f"{backend.base_url}{SUMMARY}?days=0", timeout=30.0)
    assert response.status_code == 401
    assert response.json() == UNAUTHORIZED_BODY


def test_token_query_param(backend) -> None:
    response = httpx.get(
        f"{backend.base_url}{SUMMARY}",
        params={"_token": backend.token},
        timeout=30.0,
    )
    assert response.status_code == 200


@pytest.mark.parametrize("path", [SUMMARY, TRACES, f"{TRACES}/{trace_id(1)}"])
def test_only_get_is_allowed(client, path) -> None:
    for method in ("POST", "PUT", "DELETE"):
        response = client.request(method, path)
        assert response.status_code == 405
        assert response.json() == {"detail": "Method Not Allowed"}


# ── validation ──────────────────────────────────────────────────────────────


def test_summary_days_zero(client) -> None:
    response = client.get(SUMMARY, params={"days": 0})
    assert response.status_code == 422
    assert response.json() == {"detail": [ge_error("days", 1, "0")]}


def test_summary_days_91(client) -> None:
    response = client.get(SUMMARY, params={"days": 91})
    assert response.status_code == 422
    assert response.json() == {"detail": [le_error("days", 90, "91")]}


def test_summary_days_not_an_integer(client) -> None:
    for given in ("abc", "1.5", ""):
        response = client.get(SUMMARY, params={"days": given})
        assert response.status_code == 422
        detail = response.json()["detail"]
        assert len(detail) == 1
        assert detail[0]["loc"] == ["query", "days"]
        assert detail[0]["input"] == given
    response = client.get(SUMMARY, params={"days": "abc"})
    assert response.json() == {
        "detail": [
            {
                "type": "int_parsing",
                "loc": ["query", "days"],
                "msg": "Input should be a valid integer, unable to parse string as an integer",
                "input": "abc",
            }
        ]
    }


def test_summary_days_boundaries_are_accepted(client) -> None:
    for days in (1, 90):
        assert client.get(SUMMARY, params={"days": days}).status_code == 200


def test_traces_validation_bodies(client) -> None:
    cases = [
        ({"days": 0}, [ge_error("days", 1, "0")]),
        ({"days": 91}, [le_error("days", 90, "91")]),
        ({"limit": 0}, [ge_error("limit", 1, "0")]),
        ({"limit": 201}, [le_error("limit", 200, "201")]),
        ({"offset": -1}, [ge_error("offset", 0, "-1")]),
        # several errors at once come back in parameter order: days, limit, offset
        (
            {"offset": -1, "limit": 0, "days": 91},
            [
                le_error("days", 90, "91"),
                ge_error("limit", 1, "0"),
                ge_error("offset", 0, "-1"),
            ],
        ),
    ]
    for params, detail in cases:
        response = client.get(TRACES, params=params)
        assert response.status_code == 422, params
        assert response.json() == {"detail": detail}, params


def test_traces_boundaries_are_accepted(client) -> None:
    for params in ({"limit": 1}, {"limit": 200}, {"offset": 0}, {"days": 90}):
        assert client.get(TRACES, params=params).status_code == 200, params


def test_trace_detail_days_validation(client) -> None:
    for days, error in (
        (0, ge_error("days", 1, "0")),
        (91, le_error("days", 90, "91")),
    ):
        response = client.get(f"{TRACES}/{trace_id(1)}", params={"days": days})
        assert response.status_code == 422
        assert response.json() == {"detail": [error]}


def test_trace_detail_validation_comes_before_lookup(client) -> None:
    response = client.get(f"{TRACES}/anything", params={"days": 0})
    assert response.status_code == 422


def test_trace_id_with_a_slash_is_not_a_route(client) -> None:
    response = client.get(f"{TRACES}/a/b")
    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


# ── empty state ─────────────────────────────────────────────────────────────


def test_summary_without_a_spans_dir(client, no_spans_dir) -> None:
    for days in (1, 7):
        response = client.get(SUMMARY, params={"days": days})
        assert response.status_code == 200
        body = response.json()
        assert without_window(body) == empty_summary_body(days)
        assert window_days(body) == timedelta(days=days)


def test_summary_default_window_is_seven_days(client) -> None:
    body = client.get(SUMMARY).json()
    assert window_days(body) == timedelta(days=7)
    assert body["bucket_size"] == "day"


def test_traces_without_a_spans_dir(client, no_spans_dir) -> None:
    response = client.get(TRACES)
    assert response.status_code == 200
    assert response.json() == {
        "traces": [],
        "limit": 50,
        "offset": 0,
        "total": 0,
        "has_next": False,
    }


def test_trace_detail_without_a_spans_dir_is_404(client, no_spans_dir) -> None:
    response = client.get(f"{TRACES}/{trace_id(1)}")
    assert response.status_code == 404
    assert response.json() == {
        "detail": {"reason": "trace_not_found", "trace_id": trace_id(1)}
    }


def test_empty_spans_dir(client, tmp_path) -> None:
    spans = tmp_path / "state" / "otel" / "spans"
    assert spans.is_dir()
    assert list(spans.iterdir()) == []
    assert client.get(TRACES).json()["total"] == 0
    assert without_window(client.get(SUMMARY).json()) == empty_summary_body(7)


def test_only_partitions_older_than_the_window_are_empty(client, tmp_path) -> None:
    seed(tmp_path, only=["2026-09-20-12"])
    assert without_window(client.get(SUMMARY, params={"days": 7}).json()) == (
        empty_summary_body(7)
    )
    assert client.get(TRACES, params={"days": 7}).json()["total"] == 0


def test_non_jsonl_files_are_ignored(client, tmp_path) -> None:
    directory = tmp_path / "state" / "otel" / "spans"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "notes.txt").write_text("not spans", encoding="utf-8")
    assert client.get(TRACES).json()["total"] == 0


# ── summary ─────────────────────────────────────────────────────────────────

BY_MODEL_GPT = {
    "provider": "openai",
    "model": "gpt-test",
    "provider_model": "openai:gpt-test",
    "cache_read_usd": 0.0,
    "cache_write_usd": 0.0,
    "input_usd": 0.004,
    "output_usd": 0.006,
    "reasoning_tokens": 50,
    "cache_write_tokens": 100,
    "cached_tokens": 500,
    "errors": 0,
    "error_rate": 0.0,
}
BY_MODEL_CLAUDE = {
    "provider": "anthropic",
    "model": "claude-test",
    "provider_model": "anthropic:claude-test",
    "calls": 4,
    "input_tokens": 1800,
    "output_tokens": 270,
    "cached_tokens": 380,
    "cache_write_tokens": 0,
    "reasoning_tokens": 0,
    "cache_percent": 21.1,
    "estimated_cost_usd": 0.0095,
    "input_usd": 0.0,
    "output_usd": 0.0,
    "cache_read_usd": 0.0,
    "cache_write_usd": 0.0,
    "usd_per_mtok": 4.589372,
    "errors": 0,
    "error_rate": 0.0,
    "avg_ms": 1225.0,
    "p50_ms": 1300.0,
    "p95_ms": 1970.0,
}
CACHE_BY_STEP = [
    ("chat", "anthropic", "claude-test", 2, 1400, 300, 0, 1100, 1100, 21.4, 0.009),
    ("summarization", "anthropic", "claude-test", 1, 300, 0, 0, 300, 300, 0.0, 0.0004),
    (
        "title_generation",
        "anthropic",
        "claude-test",
        1,
        100,
        80,
        0,
        20,
        20,
        80.0,
        0.0001,
    ),
]


def cache_step(row: tuple) -> dict:
    step, provider, model, calls, inp, cached, written, miss, ordinary, pct, cost = row
    return {
        "step": step,
        "provider": provider,
        "model": model,
        "provider_model": f"{provider}:{model}",
        "calls": calls,
        "input_tokens": inp,
        "cached_tokens": cached,
        "cache_write_tokens": written,
        "miss_tokens": miss,
        "ordinary_input_tokens": ordinary,
        "cache_percent": pct,
        "estimated_cost_usd": cost,
    }


BY_TOOL = [
    {
        "tool": "bash",
        "calls": 1,
        "errors": 1,
        "error_rate": 100.0,
        "avg_ms": 900.0,
        "p50_ms": 900.0,
        "p95_ms": 900.0,
    },
    {
        "tool": "grep",
        "calls": 1,
        "errors": 0,
        "error_rate": 0.0,
        "avg_ms": 40.0,
        "p50_ms": 40.0,
        "p95_ms": 40.0,
    },
    {
        "tool": "read",
        "calls": 2,
        "errors": 0,
        "error_rate": 0.0,
        "avg_ms": 85.0,
        "p50_ms": 85.0,
        "p95_ms": 116.5,
    },
]


def daily_turns(seeded: Seeded, days: int) -> list[dict]:
    per_day: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for kind, end, status, *_rest, min_days in FACTS:
        if kind == "turn" and min_days <= days:
            per_day[seeded.day(end)][0] += 1
            per_day[seeded.day(end)][1] += status == "ERROR"
    return [
        {"day": day, "turns": turns, "errors": errors}
        for day, (turns, errors) in sorted(per_day.items())
    ]


def tokens_by_model_row(
    seeded: Seeded, size: str, end: datetime, model: str, **kw
) -> dict:
    provider = "openai" if model == "gpt-test" else "anthropic"
    return {
        "bucket_start": bucket_key(seeded, end, size),
        "provider": provider,
        "model": model,
        "provider_model": f"{provider}:{model}",
        **kw,
    }


def test_summary_one_day(client, seeded: Seeded) -> None:
    response = client.get(SUMMARY, params={"days": 1})
    assert response.status_code == 200
    body = response.json()
    assert window_days(body) == timedelta(days=1)
    series = body.pop("time_series")
    assert_series(seeded, 1, series)
    by_tool = body.pop("by_tool")

    gpt = {
        **BY_MODEL_GPT,
        "calls": 3,
        "input_tokens": 1900,
        "output_tokens": 290,
        "cache_percent": 26.3,
        "estimated_cost_usd": 0.016,
        "usd_per_mtok": 7.305936,
        "avg_ms": 2066.7,
        "p50_ms": 1500.0,
        "p95_ms": 3750.0,
    }
    gpt_step = cache_step(
        ("chat", "openai", "gpt-test", 3, 1900, 500, 100, 1400, 1300, 26.3, 0.016)
    )
    assert without_window(body) == {
        "sample_ratio": 1.0,
        "totals": {
            "turns": 5,
            "llm_calls": 7,
            "tool_calls": 4,
            "input_tokens": 3700,
            "output_tokens": 560,
            "cached_tokens": 880,
            "cache_write_tokens": 100,
            "cache_percent": 23.8,
            "estimated_cost_usd": 0.0255,
            "errors": 1,
            "failed_turns": 1,
            "error_spans": 2,
            "error_rate": 20.0,
        },
        "latency_ms": {
            "turn_p50": 20000.0,
            "turn_p95": 54000.0,
            "llm_p50": 1500.0,
            "llm_p95": 3400.0,
            "tool_p50": 85.0,
            "tool_p95": 783.0,
        },
        "daily_turns": daily_turns(seeded, 1),
        "bucket_size": "hour",
        "by_model": [gpt, BY_MODEL_CLAUDE],
        "cache_by_step": [
            gpt_step,
            cache_step(CACHE_BY_STEP[0]),
            cache_step(CACHE_BY_STEP[1]),
            cache_step(CACHE_BY_STEP[2]),
        ],
        "tokens_by_model": [
            tokens_by_model_row(
                seeded,
                "hour",
                at(-3, 29, 40),
                "claude-test",
                input_tokens=500,
                output_tokens=100,
                cached_tokens=0,
                cache_write_tokens=0,
                fresh_input_tokens=500,
                cache_percent=0.0,
                calls=1,
            ),
            tokens_by_model_row(
                seeded,
                "hour",
                at(-3, 29, 20),
                "gpt-test",
                input_tokens=1000,
                output_tokens=200,
                cached_tokens=400,
                cache_write_tokens=100,
                fresh_input_tokens=500,
                cache_percent=40.0,
                calls=1,
            ),
            tokens_by_model_row(
                seeded,
                "hour",
                at(-2, 40),
                "claude-test",
                input_tokens=400,
                output_tokens=80,
                cached_tokens=80,
                cache_write_tokens=0,
                fresh_input_tokens=320,
                cache_percent=20.0,
                calls=2,
            ),
            tokens_by_model_row(
                seeded,
                "hour",
                at(-1, 9, 52),
                "claude-test",
                input_tokens=900,
                output_tokens=90,
                cached_tokens=300,
                cache_write_tokens=0,
                fresh_input_tokens=600,
                cache_percent=33.3,
                calls=1,
            ),
            tokens_by_model_row(
                seeded,
                "hour",
                at(-1, 9, 50),
                "gpt-test",
                input_tokens=700,
                output_tokens=70,
                cached_tokens=100,
                cache_write_tokens=0,
                fresh_input_tokens=600,
                cache_percent=14.3,
                calls=1,
            ),
            tokens_by_model_row(
                seeded,
                "hour",
                at(0, 5),
                "gpt-test",
                input_tokens=200,
                output_tokens=20,
                cached_tokens=0,
                cache_write_tokens=0,
                fresh_input_tokens=200,
                cache_percent=0.0,
                calls=1,
            ),
        ],
    }
    # equal call counts make the order of bash and grep unspecified
    assert by_tool[0]["tool"] == "read"
    assert sorted(by_tool, key=lambda r: r["tool"]) == BY_TOOL


def test_summary_seven_days_adds_the_older_turn(client, seeded: Seeded) -> None:
    response = client.get(SUMMARY, params={"days": 7})
    assert response.status_code == 200
    body = response.json()
    assert window_days(body) == timedelta(days=7)
    assert_series(seeded, 7, body.pop("time_series"))
    assert body["bucket_size"] == "day"
    assert body["totals"] == {
        "turns": 6,
        "llm_calls": 8,
        "tool_calls": 4,
        "input_tokens": 3750,
        "output_tokens": 565,
        "cached_tokens": 880,
        "cache_write_tokens": 100,
        "cache_percent": 23.5,
        "estimated_cost_usd": 0.026,
        "errors": 1,
        "failed_turns": 1,
        "error_spans": 2,
        "error_rate": 16.7,
    }
    assert body["latency_ms"] == {
        "turn_p50": 16000.0,
        "turn_p95": 52500.0,
        "llm_p50": 1350.0,
        "llm_p95": 3300.0,
        "tool_p50": 85.0,
        "tool_p95": 783.0,
    }
    assert body["daily_turns"] == daily_turns(seeded, 7)
    gpt = {
        **BY_MODEL_GPT,
        "calls": 4,
        "input_tokens": 1950,
        "output_tokens": 295,
        "cache_percent": 25.6,
        "estimated_cost_usd": 0.0165,
        "usd_per_mtok": 7.349666,
        "avg_ms": 1850.0,
        "p50_ms": 1350.0,
        "p95_ms": 3625.0,
    }
    assert body["by_model"] == [gpt, BY_MODEL_CLAUDE]
    assert body["cache_by_step"][0] == cache_step(
        ("chat", "openai", "gpt-test", 4, 1950, 500, 100, 1450, 1350, 25.6, 0.0165)
    )
    assert len(body["cache_by_step"]) == 4
    assert sorted(body["by_tool"], key=lambda r: r["tool"]) == BY_TOOL
    # the day bucket splits by model, so the 30 h old call sits in its own row
    older = [r for r in body["tokens_by_model"] if r["input_tokens"] == 50]
    assert older == [
        tokens_by_model_row(
            seeded,
            "day",
            at(-30, 9, 58),
            "gpt-test",
            input_tokens=50,
            output_tokens=5,
            cached_tokens=0,
            cache_write_tokens=0,
            fresh_input_tokens=50,
            cache_percent=0.0,
            calls=1,
        )
    ]
    assert sum(r["input_tokens"] for r in body["tokens_by_model"]) == 3750


def test_summary_window_widens_with_days(client, seeded: Seeded) -> None:
    turns = {
        days: client.get(SUMMARY, params={"days": days}).json()["totals"]["turns"]
        for days in (1, 2, 7, 30, 90)
    }
    # T6 enters at 2 days; T7 (40 days old) only at 90 days
    assert turns == {1: 5, 2: 6, 7: 6, 30: 6, 90: 7}


def test_summary_counts_title_generation_and_summarization_as_llm_calls(
    client, seeded: Seeded
) -> None:
    steps = {
        r["step"]
        for r in client.get(SUMMARY, params={"days": 1}).json()["cache_by_step"]
    }
    assert steps == {"chat", "summarization", "title_generation"}


def test_summary_survives_llm_spans_without_a_turn_span(client, tmp_path) -> None:
    end = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(minutes=5)
    write_partition(
        tmp_path,
        end,
        [
            span(
                name="title_generation",
                end=end,
                duration_ms=100.0,
                attributes={
                    "gen_ai.operation.name": "title_generation",
                    "gen_ai.provider.name": "openai",
                    "gen_ai.request.model": "gpt-test",
                    "gen_ai.usage.input_tokens": 10,
                    "gen_ai.usage.output_tokens": 2,
                },
            )
        ],
    )
    response = client.get(SUMMARY, params={"days": 1})
    assert response.status_code == 200
    totals = response.json()["totals"]
    assert totals["turns"] == 0
    assert totals["failed_turns"] == 0
    assert totals["llm_calls"] == 1
    assert totals["input_tokens"] == 10
    assert totals["error_rate"] == 0.0
    assert response.json()["daily_turns"] == []


def test_summary_bounds_the_cache_rate_and_fresh_tokens(client, tmp_path) -> None:
    end = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(minutes=5)
    write_partition(
        tmp_path,
        end,
        [
            span(
                name="chat gpt-test",
                end=end,
                duration_ms=100.0,
                attributes={
                    "gen_ai.provider.name": "openai",
                    "gen_ai.request.model": "gpt-test",
                    "gen_ai.usage.input_tokens": 100,
                    "gen_ai.usage.output_tokens": 10,
                    "gen_ai.usage.cache_read.input_tokens": 500,
                },
            ),
            span(
                name="chat gpt-test",
                end=end,
                duration_ms=100.0,
                attributes={
                    "gen_ai.provider.name": "openai",
                    "gen_ai.request.model": "silent",
                },
                span_id="0x" + "d" * 16,
            ),
        ],
    )
    body = client.get(SUMMARY, params={"days": 1}).json()
    assert body["totals"]["cache_percent"] == 100.0
    by_model = {m["model"]: m for m in body["by_model"]}
    assert by_model["gpt-test"]["cache_percent"] == 100.0
    row = body["tokens_by_model"]
    # the span that reported no tokens has no row
    assert [r["model"] for r in row] == ["gpt-test"]
    assert row[0]["fresh_input_tokens"] == 0
    assert row[0]["cache_percent"] == 100.0
    # a span without usage still counts as a call and groups under its model
    assert sum(m["calls"] for m in body["by_model"]) == 2


def test_summary_missing_attributes_group_as_unknown(client, tmp_path) -> None:
    end = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(minutes=5)
    write_partition(
        tmp_path,
        end,
        [
            span(name="chat x", end=end, duration_ms=10.0, span_id="0x" + "1" * 16),
            span(
                name="execute_tool x",
                end=end,
                duration_ms=10.0,
                span_id="0x" + "2" * 16,
            ),
        ],
    )
    body = client.get(SUMMARY, params={"days": 1}).json()
    assert [
        (m["provider"], m["model"], m["provider_model"]) for m in body["by_model"]
    ] == [("unknown", "unknown", "unknown:unknown")]
    assert [t["tool"] for t in body["by_tool"]] == ["unknown"]
    assert body["cache_by_step"] == []


# ── trace list ──────────────────────────────────────────────────────────────


def trace_row(seeded: Seeded, **kw) -> dict:
    start, end = kw.pop("start"), kw.pop("end")
    provider = kw.pop("provider", "openai")
    model = kw.pop("model", "gpt-test")
    return {
        "provider": provider,
        "model": model,
        "provider_model": f"{provider}:{model}",
        "start_ms": seeded.ms(start),
        "end_ms": seeded.ms(end),
        **kw,
    }


def expected_rows(seeded: Seeded) -> list[dict]:
    return [
        trace_row(
            seeded,
            trace_id=trace_id(5),
            span_id="0x0000000000000501",
            run_id="run-t5",
            session_id="sess-5",
            agent_name="Coder",
            start=at(0, 20) - timedelta(milliseconds=500),
            end=at(0, 20),
            duration_ms=500.0,
            input_tokens=0,
            output_tokens=0,
            cached_tokens=0,
            estimated_cost_usd=0.0,
            tool_calls=0,
            llm_calls=0,
            error=False,
        ),
        trace_row(
            seeded,
            trace_id=trace_id(3),
            span_id="0x0000000000000301",
            run_id="run-t3a",
            session_id="sess-3",
            agent_name="Lead",
            start=at(-1, 9, 40),
            end=at(-1, 10),
            duration_ms=20000.0,
            input_tokens=700,
            output_tokens=70,
            cached_tokens=100,
            estimated_cost_usd=0.005,
            tool_calls=0,
            llm_calls=1,
            error=False,
        ),
        trace_row(
            seeded,
            trace_id=trace_id(3),
            span_id="0x0000000000000302",
            run_id="run-t3b",
            session_id="sess-3",
            agent_name="Helper",
            provider="anthropic",
            model="claude-test",
            start=at(-1, 9, 43),
            end=at(-1, 9, 55),
            duration_ms=12000.0,
            input_tokens=900,
            output_tokens=90,
            cached_tokens=300,
            estimated_cost_usd=0.007,
            tool_calls=1,
            llm_calls=1,
            error=False,
        ),
        trace_row(
            seeded,
            trace_id=trace_id(2),
            span_id="0x0000000000000201",
            run_id="run-t2",
            session_id="sess-2",
            agent_name="Writer",
            provider="anthropic",
            model="claude-test",
            start=at(-2, 39, 30),
            end=at(-2, 40),
            duration_ms=30000.0,
            input_tokens=400,
            output_tokens=80,
            cached_tokens=80,
            estimated_cost_usd=0.0005,
            tool_calls=1,
            llm_calls=2,
            error=True,
        ),
        trace_row(
            seeded,
            trace_id=trace_id(1),
            span_id="0x0000000000000101",
            run_id="run-t1",
            session_id="sess-1",
            agent_name="Coder",
            start=at(-3, 29),
            end=at(-3, 30),
            duration_ms=60000.0,
            input_tokens=1500,
            output_tokens=300,
            cached_tokens=400,
            estimated_cost_usd=0.012,
            tool_calls=2,
            llm_calls=2,
            error=True,
        ),
        trace_row(
            seeded,
            trace_id=trace_id(6),
            span_id="0x0000000000000601",
            run_id="run-t6",
            session_id="sess-6",
            agent_name="Coder",
            start=at(-30, 9, 51),
            end=at(-30, 10),
            duration_ms=9000.0,
            input_tokens=50,
            output_tokens=5,
            cached_tokens=0,
            estimated_cost_usd=0.0005,
            tool_calls=0,
            llm_calls=1,
            error=False,
        ),
    ]


def test_traces_newest_first_with_per_run_usage(client, seeded: Seeded) -> None:
    response = client.get(TRACES, params={"days": 7})
    assert response.status_code == 200
    assert response.json() == {
        "traces": expected_rows(seeded),
        "limit": 50,
        "offset": 0,
        "total": 6,
        "has_next": False,
    }


def test_traces_default_window_is_seven_days(client, seeded: Seeded) -> None:
    assert client.get(TRACES).json()["total"] == 6


def test_traces_window(client, seeded: Seeded) -> None:
    one = client.get(TRACES, params={"days": 1}).json()
    assert one["total"] == 5
    assert [t["run_id"] for t in one["traces"]] == [
        "run-t5",
        "run-t3a",
        "run-t3b",
        "run-t2",
        "run-t1",
    ]
    wide = client.get(TRACES, params={"days": 90}).json()
    assert wide["total"] == 7
    assert wide["traces"][-1]["run_id"] == "run-t7"


def test_traces_leave_out_orphan_spans(client, seeded: Seeded) -> None:
    # T4 has an LLM span but no agent_run, so it is not a turn
    ids = {
        t["trace_id"] for t in client.get(TRACES, params={"days": 90}).json()["traces"]
    }
    assert trace_id(4) not in ids


def test_traces_pagination_boundaries(client, seeded: Seeded) -> None:
    rows = expected_rows(seeded)
    cases = [
        # limit, offset, first row, count, has_next
        (2, 0, 0, 2, True),
        (2, 2, 2, 2, True),
        (2, 3, 3, 2, True),
        (2, 4, 4, 2, False),
        (3, 3, 3, 3, False),
        (5, 1, 1, 5, False),
        (1, 5, 5, 1, False),
        (1, 4, 4, 1, True),
        (6, 0, 0, 6, False),
        (200, 0, 0, 6, False),
    ]
    for limit, offset, first, count, has_next in cases:
        body = client.get(
            TRACES, params={"days": 7, "limit": limit, "offset": offset}
        ).json()
        assert body["traces"] == rows[first : first + count], (limit, offset)
        assert body["limit"] == limit
        assert body["offset"] == offset
        assert body["total"] == 6
        assert body["has_next"] is has_next, (limit, offset)


def test_traces_offset_past_the_end_keeps_the_total(client, seeded: Seeded) -> None:
    for offset in (6, 7, 1000):
        body = client.get(TRACES, params={"days": 7, "offset": offset}).json()
        assert body == {
            "traces": [],
            "limit": 50,
            "offset": offset,
            "total": 6,
            "has_next": False,
        }


# ── trace detail ────────────────────────────────────────────────────────────


def span_row(seeded: Seeded, **kw) -> dict:
    start, end = kw.pop("start"), kw.pop("end")
    return {
        "kind": "INTERNAL",
        "status": "OK",
        "start_ms": seeded.ms(start),
        "end_ms": seeded.ms(end),
        **kw,
    }


def test_trace_detail_orders_spans_by_start_and_keeps_attributes(
    client, seeded: Seeded
) -> None:
    response = client.get(f"{TRACES}/{trace_id(1)}")
    assert response.status_code == 200
    tid = trace_id(1)
    root = "0x0000000000000101"
    assert response.json() == {
        "trace_id": tid,
        "spans": [
            span_row(
                seeded,
                span_id=root,
                parent_span_id=None,
                trace_id=tid,
                name="agent_run Coder",
                start=at(-3, 29),
                end=at(-3, 30),
                duration_ms=60000.0,
                attributes={
                    "gen_ai.provider.name": "openai",
                    "gen_ai.request.model": "gpt-test",
                    "run_id": "run-t1",
                    "gen_ai.conversation.id": "sess-1",
                    "gen_ai.agent.name": "Coder",
                },
            ),
            span_row(
                seeded,
                span_id="0x0000000000000102",
                parent_span_id=root,
                trace_id=tid,
                name="chat gpt-test",
                kind="CLIENT",
                start=at(-3, 29, 16),
                end=at(-3, 29, 20),
                duration_ms=4000.0,
                attributes={
                    "gen_ai.provider.name": "openai",
                    "gen_ai.request.model": "gpt-test",
                    "gen_ai.usage.input_tokens": 1000,
                    "gen_ai.usage.output_tokens": 200,
                    "gen_ai.usage.estimated_cost_usd": 0.01,
                    "gen_ai.usage.cache_read.input_tokens": 400,
                    "gen_ai.usage.cache_write.input_tokens": 100,
                    "run_id": "run-t1",
                    "gen_ai.usage.reasoning_tokens": 50,
                    "gen_ai.usage.cost.input_usd": 0.004,
                    "gen_ai.usage.cost.output_usd": 0.006,
                },
            ),
            span_row(
                seeded,
                span_id="0x0000000000000104",
                parent_span_id=root,
                trace_id=tid,
                name="execute_tool read",
                start=at(-3, 29, 24) + timedelta(milliseconds=880),
                end=at(-3, 29, 25),
                duration_ms=120.0,
                attributes={"run_id": "run-t1", "gen_ai.tool.name": "read"},
            ),
            span_row(
                seeded,
                span_id="0x0000000000000103",
                parent_span_id=root,
                trace_id=tid,
                name="chat claude-test",
                kind="CLIENT",
                start=at(-3, 29, 38),
                end=at(-3, 29, 40),
                duration_ms=2000.0,
                attributes={
                    "gen_ai.provider.name": "anthropic",
                    "gen_ai.request.model": "claude-test",
                    "gen_ai.usage.input_tokens": 500,
                    "gen_ai.usage.output_tokens": 100,
                    "gen_ai.usage.estimated_cost_usd": 0.002,
                    "gen_ai.usage.cache_read.input_tokens": 0,
                    "gen_ai.usage.cache_write.input_tokens": 0,
                    "run_id": "run-t1",
                },
            ),
            span_row(
                seeded,
                span_id="0x0000000000000105",
                parent_span_id=root,
                trace_id=tid,
                name="execute_tool bash",
                status="ERROR",
                start=at(-3, 29, 49) + timedelta(milliseconds=100),
                end=at(-3, 29, 50),
                duration_ms=900.0,
                attributes={"run_id": "run-t1", "gen_ai.tool.name": "bash"},
            ),
        ],
    }


def test_trace_detail_returns_every_run_of_a_shared_trace(
    client, seeded: Seeded
) -> None:
    body = client.get(f"{TRACES}/{trace_id(3)}").json()
    assert body["trace_id"] == trace_id(3)
    assert [s["name"] for s in body["spans"]] == [
        "agent_run Lead",
        "agent_run Helper",
        "chat gpt-test",
        "custom_llm_step",
        "execute_tool grep",
    ]
    assert body["spans"][0]["parent_span_id"] is None
    assert body["spans"][1]["parent_span_id"] == "0x0000000000000301"


def test_trace_detail_accepts_unprefixed_and_uppercase_ids(
    client, seeded: Seeded
) -> None:
    canonical = client.get(f"{TRACES}/{trace_id(2)}").json()
    assert canonical["trace_id"] == trace_id(2)
    for given in (format(2, "032x"), trace_id(2).upper(), "0X" + format(2, "032x")):
        response = client.get(f"{TRACES}/{given}")
        assert response.status_code == 200, given
        assert response.json() == canonical


def test_trace_detail_has_no_spans_from_other_traces(client, seeded: Seeded) -> None:
    body = client.get(f"{TRACES}/{trace_id(2)}").json()
    assert {s["trace_id"] for s in body["spans"]} == {trace_id(2)}
    assert [s["name"] for s in body["spans"]] == [
        "agent_run Writer",
        "title_generation",
        "execute_tool read",
        "summarization_llm_call",
    ]


def test_trace_detail_drops_spans_without_an_end_time(client, seeded: Seeded) -> None:
    # the T4 tool span has no end_time and is dropped from the window
    body = client.get(f"{TRACES}/{trace_id(4)}").json()
    assert [s["name"] for s in body["spans"]] == ["chat gpt-test"]


def test_trace_detail_unknown_id_is_404_with_the_given_id(
    client, seeded: Seeded
) -> None:
    for given in (trace_id(99), "nope", "ABC"):
        response = client.get(f"{TRACES}/{given}")
        assert response.status_code == 404
        assert response.json() == {
            "detail": {"reason": "trace_not_found", "trace_id": given}
        }


def test_trace_detail_window_defaults_to_thirty_days(client, seeded: Seeded) -> None:
    old = f"{TRACES}/{trace_id(7)}"
    response = client.get(old)
    assert response.status_code == 404
    assert response.json() == {
        "detail": {"reason": "trace_not_found", "trace_id": trace_id(7)}
    }
    assert client.get(old, params={"days": 39}).status_code == 404
    for days in (41, 60, 90):
        found = client.get(old, params={"days": days})
        assert found.status_code == 200
        assert found.json()["spans"][0]["name"] == "agent_run Coder"


def test_trace_detail_days_one_excludes_older_traces(client, seeded: Seeded) -> None:
    assert client.get(f"{TRACES}/{trace_id(6)}", params={"days": 1}).status_code == 404
    assert client.get(f"{TRACES}/{trace_id(6)}", params={"days": 2}).status_code == 200


# ── concurrency and fixtures ────────────────────────────────────────────────


def test_concurrent_reads_agree(client, seeded: Seeded) -> None:
    def fetch(path: str) -> tuple[int, object]:
        response = client.get(path, params={"days": 7})
        body = response.json()
        if path == SUMMARY:
            body = body["totals"]
        return response.status_code, body

    paths = [SUMMARY, TRACES, f"{TRACES}/{trace_id(1)}"] * 6
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(fetch, paths))
    assert all(code == 200 for code, _ in results)
    for index in range(3):
        assert len({json.dumps(r[1], sort_keys=True) for r in results[index::3]}) == 1


def test_fixture_files_are_scrubbed_jsonl() -> None:
    forbidden = re.compile(
        r"@|sk-|Bearer|https?://|[A-Za-z]:\\\\|/Users/|/home/|\.evoflux|password|secret",
        re.IGNORECASE,
    )
    files = sorted(FIXTURE_DIR.glob("*.jsonl"))
    assert [f.stem for f in files] == [
        "2026-09-20-12",
        "2026-10-29-06",
        "2026-10-30-09",
        "2026-10-30-10",
        "2026-10-30-11",
        "2026-10-30-12",
    ]
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert not forbidden.search(text), path.name
        for line in text.splitlines():
            record = json.loads(line)
            assert record["resource"] == {"service.name": "EvoFlux"}
            assert record["trace_id"].startswith("0x" + "0" * 16)
