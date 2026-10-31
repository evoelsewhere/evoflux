import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def replay():
    spec = importlib.util.spec_from_file_location(
        "replay_diff", ROOT / "scripts/migration/replay_diff.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeClient:
    def __init__(self, body):
        self.body = body
        self.calls = []

    def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        return type("Response", (), {"status_code": 200, "json": lambda _: self.body})()


@pytest.mark.parametrize(
    "left,right,known,expected",
    [
        ({"x": 1}, {"x": 1}, set(), 0),
        ({"x": 1}, {"x": 2}, set(), 1),
        (
            {"x": 1},
            {"x": 2},
            {
                (
                    "POST",
                    "/api/commands/init/render",
                    '{"body": {"x": 1}, "status": 200}',
                    '{"body": {"x": 2}, "status": 200}',
                )
            },
            0,
        ),
    ],
)
def test_compare_body_diffs(replay, tmp_path, left, right, known, expected):
    requests = [
        {
            "method": "POST",
            "path": "/api/commands/init/render",
            "json": {"input": "hello"},
        }
    ]
    output = tmp_path / "diff.jsonl"
    a, b = FakeClient(left), FakeClient(right)
    result = replay.compare_requests(requests, a, b, known, output)
    assert result == expected
    rows = [
        json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()
    ]
    assert len(rows) == (left != right)
    assert a.calls == b.calls


def test_non_unit_recordings_are_skipped(replay, tmp_path):
    (tmp_path / "traffic.jsonl").write_text(
        "\n".join(
            json.dumps(row)
            for row in [
                {"seq": 2, "method": "GET", "path": "/api/quote"},
                {"seq": 1, "method": "POST", "path": "/api/commands/init/render"},
                {"seq": 0, "method": "GET", "path": "/api/settings"},
            ]
        ),
        encoding="utf-8",
    )
    assert [r["path"] for r in replay.recorded_gets(tmp_path, "edge-stateless")] == [
        "/api/quote"
    ]


def test_known_path_does_not_hide_unapproved_body_difference(replay, tmp_path):
    requests = [{"method": "GET", "path": "/api/quote"}]
    approved = {("GET", "/api/quote")}
    result = replay.compare_requests(
        requests,
        FakeClient({"x": 1}),
        FakeClient({"x": 2}),
        approved,
        tmp_path / "diff.jsonl",
    )
    assert result == 1


def test_contract_post_request_and_order_are_compared(replay, tmp_path):
    row = {
        "test": "commands/test.py::test_render",
        "method": "POST",
        "path": "/api/commands/init/render",
        "request_headers": {"content-type": "application/json"},
        "request_body": '{"name":"a"}',
        "status": 200,
        "body": {"rendered": "a"},
    }
    output = tmp_path / "diff.jsonl"
    with output.open("w", encoding="utf-8") as stream:
        assert replay.compare_transcripts(
            [row], [row], "edge-stateless", set(), stream
        ) == (1, 1, 0)
    changed = dict(row, body={"rendered": "b"})
    with output.open("w", encoding="utf-8") as stream:
        assert replay.compare_transcripts(
            [row], [changed], "edge-stateless", set(), stream
        ) == (1, 0, 1)
    assert len(output.read_text(encoding="utf-8").splitlines()) == 1
    changed_request = dict(row, request_body='{"name":"b"}')
    with output.open("w", encoding="utf-8") as stream:
        assert replay.compare_transcripts(
            [row], [changed_request], "edge-stateless", set(), stream
        ) == (1, 0, 1)


def test_post_coverage_fails_when_contract_request_sets_are_missing(replay):
    with pytest.raises(ValueError, match="POST"):
        replay.require_non_get_coverage("edge-stateless", [])
    rows = [
        {"method": "POST", "path": "/api/commands/init/render"},
        {"method": "POST", "path": "/api/snippets/example/render"},
    ]
    replay.require_non_get_coverage("edge-stateless", rows)


def test_response_media_type_is_part_of_comparison(replay, tmp_path):
    class Client:
        def __init__(self, media):
            self.media = media

        def request(self, *args, **kwargs):
            return type(
                "Response",
                (),
                {
                    "status_code": 200,
                    "headers": {"content-type": self.media},
                    "json": lambda _: {"x": 1},
                },
            )()

    requests = [{"method": "GET", "path": "/api/quote"}]
    assert (
        replay.compare_requests(
            requests,
            Client("application/json"),
            Client("text/plain"),
            set(),
            tmp_path / "diff.jsonl",
        )
        == 1
    )


def test_recording_sequences_are_ordered_within_each_file(replay, tmp_path):
    for name, paths in [
        ("a", ["/api/quote?a=1", "/api/quote?a=0"]),
        ("b", ["/api/quote?b=1", "/api/quote?b=0"]),
    ]:
        (tmp_path / f"{name}.jsonl").write_text(
            "\n".join(
                json.dumps({"seq": seq, "method": "GET", "path": path})
                for seq, path in zip([1, 0], paths)
            ),
            encoding="utf-8",
        )
    assert [
        row["path"] for row in replay.recorded_gets(tmp_path, "edge-stateless")
    ] == ["/api/quote?a=0", "/api/quote?a=1", "/api/quote?b=0", "/api/quote?b=1"]


@pytest.mark.parametrize(
    "different,approved,expected",
    [(False, False, 0), (True, False, 1), (True, True, 0)],
)
def test_cli_exit_and_jsonl_with_fake_backends(
    replay, monkeypatch, tmp_path, capsys, different, approved, expected
):
    import types
    import httpx

    path = "/api/observability/summary"
    monkeypatch.setattr(replay, "contract_lanes", lambda unit: [])
    monkeypatch.setattr(
        replay,
        "recorded_gets",
        lambda directory, unit: [{"method": "GET", "path": path}],
    )
    known = (
        {
            (
                "GET",
                path,
                json.dumps({"status": 200, "body": {"x": 1}}, sort_keys=True),
                json.dumps({"status": 200, "body": {"x": 2}}, sort_keys=True),
            )
        }
        if approved
        else set()
    )
    monkeypatch.setattr(replay, "known_differences", lambda *_: known)

    def start(target, *args, **kwargs):
        return types.SimpleNamespace(base_url=target, token="fake", stop=lambda: None)

    monkeypatch.setitem(
        __import__("sys").modules,
        "backends",
        types.SimpleNamespace(start_backend=start),
    )

    class Client(FakeClient):
        def __init__(self, base_url, **kwargs):
            super().__init__({"x": 2 if different and base_url == "rust" else 1})

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

    monkeypatch.setattr(httpx, "Client", Client)
    output = tmp_path / "out"
    assert (
        replay.main(
            ["observability", "--recordings", str(tmp_path), "--out", str(output)]
        )
        == expected
    )
    rows = (
        (output / "observability-replay.jsonl").read_text(encoding="utf-8").splitlines()
    )
    assert len(rows) == int(different)
    out = capsys.readouterr().out
    assert "compared=1" in out
    assert f"unknown={int(different and not approved)}" in out
    assert f"known={int(different and approved)}" in out


def test_noise_uses_two_python_backends(replay, monkeypatch, tmp_path):
    import types
    import httpx

    monkeypatch.setattr(replay, "contract_lanes", lambda unit: [])
    monkeypatch.setattr(
        replay,
        "recorded_gets",
        lambda *_: [{"method": "GET", "path": "/api/observability/summary"}],
    )
    started = []

    def start(target, *args, **kwargs):
        started.append(target)
        return types.SimpleNamespace(base_url=target, token="fake", stop=lambda: None)

    monkeypatch.setitem(
        __import__("sys").modules,
        "backends",
        types.SimpleNamespace(start_backend=start),
    )

    class Client(FakeClient):
        def __init__(self, **kwargs):
            super().__init__({"ok": True})

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

    monkeypatch.setattr(httpx, "Client", Client)
    assert (
        replay.main(
            [
                "observability",
                "--recordings",
                str(tmp_path),
                "--out",
                str(tmp_path / "out"),
                "--noise",
            ]
        )
        == 0
    )
    assert started == ["python", "python"]


def test_approved_difference_is_read_from_known_differences(replay, tmp_path):
    path = tmp_path / "KNOWN_DIFFERENCES.md"
    path.write_text(
        '| observability | GET | /api/observability/summary | `{"status":200,"body":{"x":1}}` | `{"status":200,"body":{"x":2}}` | owner approved |\n',
        encoding="utf-8",
    )
    known = replay.known_differences(path, "observability")
    output = tmp_path / "diff.jsonl"
    assert (
        replay.compare_requests(
            [{"method": "GET", "path": "/api/observability/summary"}],
            FakeClient({"x": 1}),
            FakeClient({"x": 2}),
            known,
            output,
        )
        == 0
    )
    assert (
        replay.compare_requests(
            [{"method": "GET", "path": "/api/observability/summary"}],
            FakeClient({"x": 1}),
            FakeClient({"x": 3}),
            known,
            output,
        )
        == 1
    )
