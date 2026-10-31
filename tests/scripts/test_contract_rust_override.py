import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "contract-tests"))
spec = importlib.util.spec_from_file_location(
    "contract_conftest", ROOT / "contract-tests" / "conftest.py"
)
contract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(contract)


def test_quote_rust_backend_overrides_its_unit(monkeypatch, tmp_path):
    calls = []
    backend = SimpleNamespace(
        stop=lambda: None, base_url="http://127.0.0.1:1234", token="test-token"
    )
    monkeypatch.setattr(
        contract,
        "start_backend",
        lambda *args, **kwargs: calls.append(kwargs) or backend,
    )
    request = SimpleNamespace(
        node=SimpleNamespace(path=ROOT / "contract-tests" / "quote" / "test_quote.py")
    )
    fixture = contract.backend.__wrapped__(
        request, "rust", ["edge-stateless"], tmp_path, None
    )
    next(fixture)
    assert calls[0]["extra_env"]["EVOFLUX_ROUTE_OVERRIDE"] == "edge-stateless=rust"
    fixture.close()


def test_replay_capture_records_direct_post(monkeypatch, tmp_path):
    import httpx

    transcript = tmp_path / "transcript.jsonl"
    monkeypatch.setenv("EVOFLUX_REPLAY_TRANSCRIPT", str(transcript))
    monkeypatch.setenv("EVOFLUX_REPLAY_UNIT", "edge-stateless")
    node = SimpleNamespace(
        nodeid="quote/test.py::test_post",
        _replay_backend_url="http://test",
        _replay_backend_token="test-token",
    )
    contract.replay_capture.__wrapped__(SimpleNamespace(node=node), monkeypatch)
    transport = httpx.MockTransport(
        lambda req: httpx.Response(200, json={"result": "rendered"})
    )
    with httpx.Client(transport=transport) as client:
        client.post(
            "http://test/api/commands/init/render",
            json={"name": "test"},
            headers={"Authorization": "Bearer test-token"},
        )
    row = __import__("json").loads(transcript.read_text(encoding="utf-8"))
    assert row["method"] == "POST"
    assert row["request_body"] == '{"name":"test"}'
    assert row["request_headers"]["authorization"] == "Bearer <backend-token>"
    assert row["body"] == {"result": "rendered"}


def _gateway_extra_env(monkeypatch, tmp_path, override):
    calls = []
    backend = SimpleNamespace(
        stop=lambda: None, base_url="http://127.0.0.1:1234", token="test-token"
    )
    monkeypatch.setattr(
        contract,
        "start_backend",
        lambda *args, **kwargs: calls.append(kwargs) or backend,
    )
    if override is None:
        monkeypatch.delenv("EVOFLUX_ROUTE_OVERRIDE", raising=False)
    else:
        monkeypatch.setenv("EVOFLUX_ROUTE_OVERRIDE", override)
    request = SimpleNamespace(
        node=SimpleNamespace(path=ROOT / "contract-tests" / "quote" / "test_quote.py")
    )
    fixture = contract.backend.__wrapped__(
        request, "gateway", ["edge-stateless"], tmp_path, None
    )
    next(fixture)
    fixture.close()
    return calls[0]["extra_env"]


def test_gateway_target_passes_the_rust_forward_override(monkeypatch, tmp_path):
    extra = _gateway_extra_env(monkeypatch, tmp_path, "edge-stateless=rust")
    assert extra == {"EVOFLUX_ROUTE_OVERRIDE": "edge-stateless=rust"}


def test_gateway_target_has_no_override_by_default(monkeypatch, tmp_path):
    assert not _gateway_extra_env(monkeypatch, tmp_path, None)
