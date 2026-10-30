"""Tests of the harness itself: if these fail, no area result can be trusted."""

from __future__ import annotations

import copy
import http.server
import importlib.util
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from normalize import NormalizeRules, normalize
from sse import collect_events

_SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts" / "migration" / "openapi_diff.py"
)
_spec = importlib.util.spec_from_file_location("openapi_diff", _SCRIPT)
assert _spec is not None and _spec.loader is not None
openapi_diff = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(openapi_diff)


# --- backend isolation ----------------------------------------------------


@pytest.fixture
def leaky_env(monkeypatch: pytest.MonkeyPatch, tmp_path_factory) -> Path:
    """Parent environment that would redirect the database, set before `backend`."""
    outside = tmp_path_factory.mktemp("outside")
    monkeypatch.setenv(
        "DATABASE_URL", f"sqlite+aiosqlite:///{(outside / 'leak.db').as_posix()}"
    )
    return outside


def test_backend_ignores_parent_database_url(leaky_env: Path, backend) -> None:
    response = httpx.get(
        f"{backend.base_url}/api/health/ready",
        headers={"Authorization": f"Bearer {backend.token}"},
        timeout=30.0,
    )
    assert response.status_code == 200
    assert not list(leaky_env.iterdir()), "backend wrote outside its data dir"


# --- sse.collect_events ----------------------------------------------------


class _CommentsOnly(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        try:
            while True:
                self.wfile.write(b": ping\n\n")
                self.wfile.flush()
                time.sleep(0.1)
        except OSError:
            pass

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture
def comment_server() -> Iterator[str]:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _CommentsOnly)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()


def test_collect_events_times_out_on_comment_only_stream(comment_server: str) -> None:
    started = time.monotonic()
    with httpx.Client(base_url=comment_server) as client:
        with pytest.raises(TimeoutError):
            collect_events(client, "/", until=lambda e: True, timeout_s=1.0)
    assert time.monotonic() - started < 5.0


# --- normalize --------------------------------------------------------------

_A = "11111111-1111-4111-8111-111111111111"
_B = "22222222-2222-4222-8222-222222222222"


def test_uuid_numbering_ignores_key_order() -> None:
    first = normalize({"a": _A, "b": _B})
    second = normalize({"b": _B, "a": _A})
    assert first == second == {"a": "<uuid:1>", "b": "<uuid:2>"}


def test_lists_sorted_only_at_named_paths() -> None:
    rules = NormalizeRules(sort_paths=frozenset({"$.sorted"}))
    body = {"sorted": ["b", "a"], "kept": ["b", "a"]}
    assert normalize(body, rules) == {"sorted": ["a", "b"], "kept": ["b", "a"]}


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("2026-10-30T05:00:00", "2031-01-02T23:59:59"),
        ("2026-10-30T05:00:00Z", "2031-01-02T23:59:59Z"),
        ("2026-10-30T05:00:00+07:00", "2031-01-02T23:59:59-05:00"),
        ("2026-10-30T05:00:00.123456Z", "2031-01-02T23:59:59.9Z"),
        ("2026-10-30 05:00:00", "2031-01-02 23:59:59"),
        ("2026-10-30", "2031-01-02"),
    ],
)
def test_same_timestamp_class_normalizes_equal(a: str, b: str) -> None:
    assert normalize({"t": a}) == normalize({"t": b})
    assert "<ts:" in normalize({"t": a})["t"]


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("2026-10-30T05:00:00", "2026-10-30T05:00:00Z"),
        ("2026-10-30T05:00:00Z", "2026-10-30T05:00:00+00:00"),
        ("2026-10-30T05:00:00", "2026-10-30T05:00:00.000"),
        ("2026-10-30T05:00:00", "2026-10-30 05:00:00"),
        ("2026-10-30", "2026-10-30T05:00:00"),
    ],
)
def test_different_timestamp_class_stays_different(a: str, b: str) -> None:
    assert normalize({"t": a}) != normalize({"t": b})


def test_timestamp_inside_text_keeps_surrounding_text() -> None:
    assert normalize("at 2026-10-30T05:00:00Z ok") == "at <ts:utc-z> ok"
    assert normalize("v3.1.1") == "v3.1.1"


# --- openapi_diff -------------------------------------------------------------


def _spec_with_title_property() -> dict:
    return {
        "paths": {
            "/api/x": {
                "post": {
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/Req"}
                            }
                        }
                    }
                }
            }
        },
        "components": {
            "schemas": {
                "Req": {
                    "title": "Req",
                    "type": "object",
                    "properties": {"title": {"type": "string", "title": "Title"}},
                }
            }
        },
    }


def test_openapi_diff_sees_a_property_named_title_change() -> None:
    pinned = _spec_with_title_property()
    candidate = copy.deepcopy(pinned)
    candidate["components"]["schemas"]["Req"]["properties"]["title"]["type"] = "integer"
    a = openapi_diff.extract(pinned, ["/api/x"])
    b = openapi_diff.extract(candidate, ["/api/x"])
    assert openapi_diff.diff(a, b)


def test_openapi_diff_ignores_generated_schema_titles_and_names() -> None:
    pinned = _spec_with_title_property()
    candidate = copy.deepcopy(pinned)
    schemas = candidate["components"]["schemas"]
    schemas["Renamed"] = schemas.pop("Req")
    schemas["Renamed"]["title"] = "Other"
    candidate["paths"]["/api/x"]["post"]["requestBody"]["content"]["application/json"][
        "schema"
    ]["$ref"] = "#/components/schemas/Renamed"
    a = openapi_diff.extract(pinned, ["/api/x"])
    b = openapi_diff.extract(candidate, ["/api/x"])
    assert not openapi_diff.diff(a, b)


def test_openapi_single_level_pattern_is_not_recursive() -> None:
    assert openapi_diff.owns("/api/a/b", ["/api/a/*"])
    assert not openapi_diff.owns("/api/a/b/c", ["/api/a/*"])
    assert openapi_diff.owns("/api/a/b/c", ["/api/a/**"])


@pytest.mark.parametrize("keyword", ["default", "example", "enum"])
def test_openapi_preserves_titles_in_literal_values(keyword: str) -> None:
    pinned = _spec_with_title_property()
    schema = pinned["components"]["schemas"]["Req"]
    value = {"title": "first", "nested": {"title": "inner"}}
    schema[keyword] = [value] if keyword == "enum" else value
    candidate = copy.deepcopy(pinned)
    target = candidate["components"]["schemas"]["Req"][keyword]
    if keyword == "enum":
        target = target[0]
    target["title"] = "changed"
    assert openapi_diff.diff(
        openapi_diff.extract(pinned, ["/api/x"]),
        openapi_diff.extract(candidate, ["/api/x"]),
    )


def test_windows_backend_does_not_signal_parent_with_pid_watch() -> None:
    import os
    import backends

    if os.name == "nt":
        assert "--parent-pid" not in backends._command("python")
    else:
        assert "--parent-pid" in backends._command("python")


def test_backend_stop_terminates_handshake_process(backend) -> None:
    import os

    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x00100000, False, backend.pid)
        assert handle, "could not open backend process for waiting"
        try:
            backend.stop()
            assert kernel.WaitForSingleObject(handle, 10000) == 0
        finally:
            kernel.CloseHandle(handle)
    else:
        backend.stop()
        with pytest.raises(ProcessLookupError):
            os.kill(backend.pid, 0)


def test_normalize_ignores_non_ascii_digits() -> None:
    # \d would match Arabic-Indic digits without re.ASCII; Rust's port is ASCII only.
    text = "٢٠٢٦-١٠-٣١"
    assert normalize({"d": text}) == {"d": text}
