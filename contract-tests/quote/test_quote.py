"""``GET /api/quote`` contract (unit ``quote``).

The backend runs without ``NINJA_API_KEY`` and with no network, so the answer is
either the built-in fallback or the quote cached for today's UTC date in
``<cache>/quoteoftheday.json``. Tests seed that file directly.
"""

from __future__ import annotations

import datetime
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest

QUOTE = "/api/quote"
UNAUTHORIZED_BODY = {"detail": "Unauthorized — EvoFlux access key required."}
FALLBACK = {
    "quote": "First, solve the problem. Then, write the code.",
    "author": "John Johnson",
}
SEEDED = {"quote": "Seeded “quote” — ünïcode ✓", "author": "Test Author"}


def _utc_today() -> datetime.date:
    return datetime.datetime.now(datetime.timezone.utc).date()


@pytest.fixture
def cache_file(tmp_path: Path, backend) -> Path:
    return tmp_path / "cache" / "quoteoftheday.json"


def _seed(path: Path, date: datetime.date, **fields: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"date": date.isoformat(), **(fields or SEEDED)}
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _get_with_stable_day(client: httpx.Client) -> httpx.Response:
    """GET once; retry if UTC midnight passed during the request."""
    for _ in range(2):
        before = _utc_today()
        response = client.get(QUOTE)
        if _utc_today() == before:
            return response
    return response


def test_no_cache_returns_fallback(client: httpx.Client, cache_file: Path) -> None:
    response = client.get(QUOTE)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == FALLBACK
    assert not cache_file.exists(), "the fallback is never cached"


def test_cache_for_today_is_served(client: httpx.Client, cache_file: Path) -> None:
    _seed(cache_file, _utc_today())
    response = _get_with_stable_day(client)
    assert response.status_code == 200
    assert response.json() == SEEDED
    assert set(response.json()) == {"quote", "author"}


def test_cached_quote_is_stable_and_not_rewritten(
    client: httpx.Client, cache_file: Path
) -> None:
    _seed(cache_file, _utc_today())
    before = cache_file.read_text(encoding="utf-8")
    first = client.get(QUOTE).json()
    second = client.get(QUOTE).json()
    assert first == second == SEEDED
    assert cache_file.read_text(encoding="utf-8") == before


@pytest.mark.parametrize("offset_days", [-1, 1, -365])
def test_cache_for_another_day_is_ignored(
    client: httpx.Client, cache_file: Path, offset_days: int
) -> None:
    """Any date different from today's UTC date is a miss, including a future one."""
    _seed(cache_file, _utc_today() + datetime.timedelta(days=offset_days))
    assert client.get(QUOTE).json() == FALLBACK


def test_cache_extra_fields_are_ignored(client: httpx.Client, cache_file: Path) -> None:
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    data = {"date": _utc_today().isoformat(), **SEEDED, "extra": 1}
    cache_file.write_text(json.dumps(data), encoding="utf-8")
    response = _get_with_stable_day(client)
    assert response.json() == SEEDED


@pytest.mark.parametrize(
    "content",
    [
        "",
        "   \n",
        "not json",
        "[]",
        '"text"',
        "null",
        '{"date": "2000-01-01"}',
        '{"quote": "x", "author": "y"}',
        '{"date": 123, "quote": "x", "author": "y"}',
    ],
    ids=[
        "empty",
        "blank",
        "invalid-json",
        "list",
        "string",
        "null",
        "stale-no-fields",
        "no-date",
        "numeric-date",
    ],
)
def test_unreadable_cache_falls_back(
    client: httpx.Client, cache_file: Path, content: str
) -> None:
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(content, encoding="utf-8")
    response = client.get(QUOTE)
    assert response.status_code == 200
    assert response.json() == FALLBACK


def test_today_cache_missing_fields_falls_back(
    client: httpx.Client, cache_file: Path
) -> None:
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(
        json.dumps({"date": _utc_today().isoformat(), "quote": "only a quote"}),
        encoding="utf-8",
    )
    assert client.get(QUOTE).json() == FALLBACK


def test_cache_deleted_between_requests(client: httpx.Client, cache_file: Path) -> None:
    _seed(cache_file, _utc_today())
    assert _get_with_stable_day(client).json() == SEEDED
    cache_file.unlink()
    assert client.get(QUOTE).json() == FALLBACK


def test_requires_auth(backend) -> None:
    response = httpx.get(f"{backend.base_url}{QUOTE}", timeout=30.0)
    assert response.status_code == 401
    assert response.json() == UNAUTHORIZED_BODY


def test_wrong_token_rejected(backend) -> None:
    for kwargs in (
        {"headers": {"Authorization": "Bearer not-the-token"}},
        {"params": {"_token": "not-the-token"}},
    ):
        response = httpx.get(f"{backend.base_url}{QUOTE}", timeout=30.0, **kwargs)
        assert response.status_code == 401, kwargs
        assert response.json() == UNAUTHORIZED_BODY, kwargs


def test_token_query_param(backend) -> None:
    response = httpx.get(
        f"{backend.base_url}{QUOTE}", params={"_token": backend.token}, timeout=30.0
    )
    assert response.status_code == 200
    assert response.json() == FALLBACK


def test_has_no_parameters(client: httpx.Client) -> None:
    """No validation can fail: unknown query parameters are ignored."""
    response = client.get(QUOTE, params={"date": "1999-01-01", "limit": "x"})
    assert response.status_code == 200
    assert response.json() == FALLBACK


def test_rejects_other_methods(client: httpx.Client) -> None:
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        response = client.request(method, QUOTE)
        assert response.status_code == 405, method
        assert response.json() == {"detail": "Method Not Allowed"}, method
        assert "GET" in response.headers["allow"], method


def test_trailing_slash_redirects(client: httpx.Client) -> None:
    response = client.get(f"{QUOTE}/", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"].endswith(QUOTE)


def test_concurrent_requests(client: httpx.Client, cache_file: Path) -> None:
    _seed(cache_file, _utc_today())
    with ThreadPoolExecutor(max_workers=16) as pool:
        responses = list(pool.map(lambda _: client.get(QUOTE), range(48)))
    assert {r.status_code for r in responses} == {200}
    assert {r.text for r in responses} <= {
        json.dumps(SEEDED, ensure_ascii=False, separators=(",", ":")),
        json.dumps(FALLBACK, separators=(",", ":")),
    }
