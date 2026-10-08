import app.services.local_stt_runtime.installer as installer


def test_status_reports_detected_platform_when_release_assets_are_not_published(monkeypatch):
    monkeypatch.setattr(installer, "current_assets", lambda: None)
    monkeypatch.setattr(installer, "installed_runtime", lambda: None)
    monkeypatch.setattr(installer, "_read_record", lambda: None)
    monkeypatch.setattr(installer, "_job", None)
    monkeypatch.setattr(installer, "_health_failed", False)
    monkeypatch.setattr(installer, "platform_key", lambda: "win32-x64", raising=False)

    status = installer.runtime_status()

    assert status.state == "unavailable"
    assert status.available is False
    assert status.platform == "win32-x64"
