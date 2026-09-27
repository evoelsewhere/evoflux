"""CLI detection and JSON parsing against the stub tailscale binary."""

from __future__ import annotations

import json
from pathlib import Path

from app.services import remote_use_service as service


async def test_ready_state_parses_status_and_serve(tailscale_stub: Path) -> None:
    status = await service.get_status()
    assert status["tailscale"] == {
        "installed": True,
        "logged_in": True,
        "https_certs": True,
        "error": None,
    }
    assert status["serve"]["enabled"] is True
    assert status["serve"]["url"] == "https://machine.tailnet-example.ts.net"


async def test_logged_out_is_a_distinct_state(tailscale_stub: Path) -> None:
    (tailscale_stub / "status.json").write_text(
        json.dumps({"BackendState": "NeedsLogin", "Health": []}),
        encoding="utf-8",
    )
    state = await service.detect_tailscale_state()
    assert state == {
        "installed": True,
        "logged_in": False,
        "https_certs": None,
        "error": None,
    }


async def test_health_warning_marks_https_certs_disabled(
    tailscale_stub: Path,
) -> None:
    (tailscale_stub / "status.json").write_text(
        json.dumps(
            {
                "BackendState": "Running",
                "CertDomains": [],
                "Health": ["https certificates are not enabled for this tailnet"],
            }
        ),
        encoding="utf-8",
    )
    state = await service.detect_tailscale_state()
    assert state["logged_in"] is True
    assert state["https_certs"] is False
    assert state["error"] is None


async def test_missing_binary_is_the_not_installed_state(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.delenv(service.TAILSCALE_BIN_ENV, raising=False)
    monkeypatch.setenv("PATH", str(tmp_path))
    state = await service.detect_tailscale_state()
    assert state == {
        "installed": False,
        "logged_in": False,
        "https_certs": None,
        "error": "tailscale CLI not found on PATH",
    }


async def test_status_failure_surfaces_stderr(tailscale_stub: Path) -> None:
    (tailscale_stub / "status.fail").write_text(
        "failed: cannot connect to tailscaled", encoding="utf-8"
    )
    state = await service.detect_tailscale_state()
    assert state["installed"] is True
    assert state["logged_in"] is False
    assert state["error"] == "failed: cannot connect to tailscaled"


async def test_unparseable_status_json_is_reported(tailscale_stub: Path) -> None:
    (tailscale_stub / "status.json").write_text("not json {", encoding="utf-8")
    state = await service.detect_tailscale_state()
    assert "unparseable" in state["error"]


async def test_serve_status_without_handlers_is_disabled(
    tailscale_stub: Path,
) -> None:
    (tailscale_stub / "serve.json").write_text(
        json.dumps({"TCP": {}, "Web": {}}), encoding="utf-8"
    )
    status = await service.get_status()
    assert status["serve"] == {"enabled": False, "url": None}
    # Cert evidence from status --json survives an empty serve config.
    assert status["tailscale"]["https_certs"] is True


async def test_serve_status_failure_is_reported(tailscale_stub: Path) -> None:
    (tailscale_stub / "serve.fail").write_text(
        "serve status unavailable", encoding="utf-8"
    )
    status = await service.get_status()
    assert status["serve"] == {"enabled": False, "url": None}
    assert status["tailscale"]["error"] == "serve status unavailable"


async def test_enable_runs_serve_bg_toward_the_sidecar(
    tailscale_stub: Path,
) -> None:
    status = await service.enable_serve(4082)
    calls = (tailscale_stub / "calls.log").read_text(encoding="utf-8")
    expected_target = "http://" + ".".join(("127", "0", "0", "1")) + ":4082"
    assert "serve --bg " + expected_target in calls
    target = (tailscale_stub / "enable.target").read_text(encoding="utf-8").strip()
    assert target == expected_target
    assert status["serve"]["enabled"] is True
    assert status["tailscale"]["error"] is None


async def test_enable_requires_login_and_skips_the_cli(
    tailscale_stub: Path,
) -> None:
    (tailscale_stub / "status.json").write_text(
        json.dumps({"BackendState": "NeedsLogin"}), encoding="utf-8"
    )
    status = await service.enable_serve(4082)
    assert "not logged in" in status["tailscale"]["error"]
    assert not (tailscale_stub / "enable.target").exists()


async def test_enable_https_error_marks_certs_disabled(
    tailscale_stub: Path,
) -> None:
    (tailscale_stub / "enable.fail").write_text(
        "https is not enabled for this tailnet", encoding="utf-8"
    )
    status = await service.enable_serve(4082)
    assert "https is not enabled" in status["tailscale"]["error"]
    assert status["tailscale"]["https_certs"] is False


async def test_enable_rejects_unknown_port(tailscale_stub: Path) -> None:
    status = await service.enable_serve(None)
    assert "backend port unknown" in status["tailscale"]["error"]
    assert not (tailscale_stub / "enable.target").exists()


async def test_disable_runs_serve_reset(tailscale_stub: Path) -> None:
    (tailscale_stub / "serve.json").write_text(
        json.dumps({"TCP": {}, "Web": {}}), encoding="utf-8"
    )
    status = await service.disable_serve()
    calls = (tailscale_stub / "calls.log").read_text(encoding="utf-8")
    assert "serve reset" in calls
    assert status["serve"]["enabled"] is False
    assert status["tailscale"]["error"] is None


async def test_disable_failure_surfaces_stderr(tailscale_stub: Path) -> None:
    (tailscale_stub / "reset.fail").write_text("reset denied", encoding="utf-8")
    status = await service.disable_serve()
    assert status["tailscale"]["error"] == "reset denied"
