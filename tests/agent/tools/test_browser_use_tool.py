"""Tests for EvoFlux's direct in-app browser tool."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agent.schemas.chat import ImageDataBlock, TextBlock, ToolResult
from app.agent.tools.builtin import browser_use_tool as browser_tool
from app.services.direct_browser_bridge import direct_browser_bridge


def _state(session_id: str = "desktop-session") -> SimpleNamespace:
    return SimpleNamespace(metadata={"session_id": session_id})


@pytest.mark.asyncio
async def test_browser_use_requires_evoflux_desktop(monkeypatch) -> None:
    monkeypatch.setattr(direct_browser_bridge, "is_connected", lambda _sid: False)
    monkeypatch.setattr(direct_browser_bridge, "is_available", lambda _sid: False)

    result = await browser_tool.browser_use.arun(
        _injected={"_state": _state()}, actions=[{"action": "snapshot"}]
    )

    assert isinstance(result, str)
    assert "EvoFlux Desktop" in result


@pytest.mark.asyncio
async def test_browser_use_mounts_panel_and_runs_actions(monkeypatch) -> None:
    connected = False
    requests: list[tuple[str, str, dict]] = []
    monkeypatch.setattr(direct_browser_bridge, "is_available", lambda _sid: True)
    monkeypatch.setattr(direct_browser_bridge, "is_connected", lambda _sid: connected)

    async def request_mount(_sid: str) -> bool:
        return True

    async def wait_connected(_sid: str) -> bool:
        nonlocal connected
        connected = True
        return True

    async def request(sid: str, action: str, params: dict):
        requests.append((sid, action, params))
        return f"direct:{action}"

    monkeypatch.setattr(direct_browser_bridge, "request_mount", request_mount)
    monkeypatch.setattr(direct_browser_bridge, "wait_connected", wait_connected)
    monkeypatch.setattr(direct_browser_bridge, "request", request)

    result = await browser_tool.browser_use.arun(
        _injected={"_state": _state()},
        actions=[
            {"action": "navigate", "url": "https://example.com"},
            {"action": "snapshot"},
            {"action": "press", "index": 2, "key": "Enter"},
        ],
    )

    assert isinstance(result, str)
    assert "direct:navigate" in result
    assert "Untrusted browser content" in result
    assert requests == [
        ("desktop-session", "navigate", {"url": "https://example.com"}),
        ("desktop-session", "snapshot", {"max_chars": 15_000}),
        ("desktop-session", "press", {"index": 2, "key": "Enter"}),
    ]


@pytest.mark.asyncio
async def test_screenshot_becomes_multimodal_tool_result(monkeypatch) -> None:
    monkeypatch.setattr(direct_browser_bridge, "is_connected", lambda _sid: True)

    async def request(_sid: str, action: str, params: dict):
        assert action == "screenshot"
        assert params == {"index": 4, "full_page": False}
        return {
            "kind": "image",
            "media_type": "image/png",
            "data": "aGVsbG8=",
            "text": "[In-app browser screenshot]",
            "coordinate_mapping": {
                "css_origin_x": 0,
                "css_origin_y": 0,
                "css_per_pixel_x": 2.0,
                "css_per_pixel_y": 2.0,
            },
        }

    monkeypatch.setattr(direct_browser_bridge, "request", request)

    result = await browser_tool.browser_use.arun(
        _injected={"_state": _state()},
        actions=[{"action": "screenshot", "index": 4}],
    )

    assert isinstance(result, ToolResult)
    assert any(isinstance(part, TextBlock) for part in result.parts)
    assert any(isinstance(part, ImageDataBlock) for part in result.parts)
    text = next(part for part in result.parts if isinstance(part, TextBlock))
    assert "image_x×2.0000" in text.text


@pytest.mark.asyncio
async def test_direct_errors_are_action_scoped(monkeypatch) -> None:
    monkeypatch.setattr(direct_browser_bridge, "is_connected", lambda _sid: True)

    async def request(_sid: str, action: str, _params: dict):
        raise RuntimeError(f"failed {action}")

    monkeypatch.setattr(direct_browser_bridge, "request", request)

    result = await browser_tool.browser_use.arun(
        _injected={"_state": _state()}, actions=[{"action": "console"}]
    )

    assert result == "Error (console): failed console"


@pytest.mark.asyncio
async def test_browser_policy_blocks_unsafe_urls_and_disabled_evaluate(
    monkeypatch,
) -> None:
    from app.core.runtime_settings import BuiltInBrowserSettings

    monkeypatch.setattr(direct_browser_bridge, "is_connected", lambda _sid: True)
    monkeypatch.setattr(
        "app.core.runtime_settings.load_runtime_settings",
        lambda: SimpleNamespace(
            browser=BuiltInBrowserSettings(
                blocked_domains=["private.example"],
                allow_evaluate=False,
            )
        ),
    )
    requests: list[tuple[str, dict]] = []

    async def request(_sid: str, action: str, params: dict):
        requests.append((action, params))
        if action == "status":
            return {"url": "https://example.com"}
        return f"direct:{action}"

    monkeypatch.setattr(direct_browser_bridge, "request", request)

    result = await browser_tool.browser_use.arun(
        _injected={"_state": _state()},
        actions=[
            {"action": "navigate", "url": "file:///etc/passwd"},
            {"action": "navigate", "url": "https://private.example/account"},
            {"action": "evaluate", "script": "document.cookie"},
        ],
    )

    assert "only allows http:// and https://" in result
    assert "is blocked" in result
    assert "evaluate is disabled" in result
    assert requests == [("status", {})]


@pytest.mark.asyncio
async def test_browser_policy_blocks_clipboard_reads_by_default(monkeypatch) -> None:
    monkeypatch.setattr(direct_browser_bridge, "is_connected", lambda _sid: True)

    result = await browser_tool.browser_use.arun(
        _injected={"_state": _state()},
        actions=[{"action": "clipboard_read"}],
    )

    assert (
        result
        == "Error (clipboard_read): Clipboard reads are disabled in Settings → Browser."
    )


@pytest.mark.asyncio
async def test_browser_policy_requires_user_for_permission_accept(monkeypatch) -> None:
    monkeypatch.setattr(direct_browser_bridge, "is_connected", lambda _sid: True)

    result = await browser_tool.browser_use.arun(
        _injected={"_state": _state()},
        actions=[{"action": "resolve_permission", "id": 1, "allow": True}],
    )

    assert "ask the user to decide" in result


@pytest.mark.asyncio
async def test_set_files_reads_only_session_workspace_files(
    monkeypatch, tmp_path
) -> None:
    from app.core.runtime_settings import BuiltInBrowserSettings

    upload = tmp_path / "report.txt"
    upload.write_text("hello", encoding="utf-8")
    state = SimpleNamespace(
        metadata={"session_id": "desktop-session", "workspace": str(tmp_path)}
    )
    seen: dict = {}
    monkeypatch.setattr(direct_browser_bridge, "is_connected", lambda _sid: True)
    monkeypatch.setattr(
        "app.core.runtime_settings.load_runtime_settings",
        lambda: SimpleNamespace(
            browser=BuiltInBrowserSettings(allow_file_uploads=True)
        ),
    )

    async def request(_sid: str, action: str, params: dict):
        seen.update({"action": action, "params": params})
        return {"files": [{"name": "report.txt", "size": 5}]}

    monkeypatch.setattr(direct_browser_bridge, "request", request)
    result = await browser_tool.browser_use.arun(
        _injected={"_state": state},
        actions=[
            {
                "action": "set_files",
                "selector": "input[type=file]",
                "paths": ["report.txt"],
            }
        ],
    )

    assert "report.txt" in result
    assert seen["action"] == "set_files"
    assert seen["params"]["files"][0]["data"] == "aGVsbG8="
    assert "paths" not in seen["params"]


def test_encode_browser_uploads_rejects_workspace_escape(tmp_path) -> None:
    outside = tmp_path.parent / "outside-browser-upload.txt"
    outside.write_text("private", encoding="utf-8")
    with pytest.raises(ValueError, match="escapes"):
        browser_tool._encode_browser_uploads(
            tmp_path, ["../outside-browser-upload.txt"]
        )


@pytest.mark.asyncio
async def test_download_saves_into_session_workspace(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(direct_browser_bridge, "is_connected", lambda _sid: True)
    state = SimpleNamespace(
        metadata={"session_id": "desktop-session", "workspace": str(tmp_path)}
    )

    async def request(_sid: str, action: str, params: dict):
        assert action == "download"
        assert params["url"] == "https://example.com/report.txt"
        return {
            "url": params["url"],
            "filename": "report.txt",
            "media_type": "text/plain",
            "bytes": 5,
            "data": "aGVsbG8=",
        }

    monkeypatch.setattr(direct_browser_bridge, "request", request)
    result = await browser_tool.browser_use.arun(
        _injected={"_state": state},
        actions=[
            {
                "action": "download",
                "url": "https://example.com/report.txt",
            }
        ],
    )

    assert "downloads/report.txt" in result
    assert (tmp_path / "downloads" / "report.txt").read_text() == "hello"


def test_save_browser_download_avoids_overwrite(tmp_path) -> None:
    payload = {
        "url": "https://example.com/report.txt",
        "filename": "report.txt",
        "data": "MQ==",
    }
    first = browser_tool._save_browser_download(
        tmp_path, payload, None, browser_tool._MAX_DOWNLOAD_BYTES
    )
    second = browser_tool._save_browser_download(
        tmp_path, payload, None, browser_tool._MAX_DOWNLOAD_BYTES
    )
    assert first == "downloads/report.txt"
    assert second == "downloads/report (1).txt"


@pytest.mark.asyncio
async def test_save_pdf_stores_native_pdf_in_workspace(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(direct_browser_bridge, "is_connected", lambda _sid: True)
    state = SimpleNamespace(
        metadata={"session_id": "desktop-session", "workspace": str(tmp_path)}
    )

    async def request(_sid: str, action: str, params: dict):
        assert action == "save_pdf"
        assert params["filename"] == "capture.pdf"
        return {
            "filename": "capture.pdf",
            "media_type": "application/pdf",
            "bytes": 8,
            "data": "JVBERi0xLjQ=",
        }

    monkeypatch.setattr(direct_browser_bridge, "request", request)
    result = await browser_tool.browser_use.arun(
        _injected={"_state": state},
        actions=[{"action": "save_pdf", "filename": "capture.pdf"}],
    )

    assert "downloads/capture.pdf" in result
    assert (tmp_path / "downloads" / "capture.pdf").read_bytes() == b"%PDF-1.4"


@pytest.mark.asyncio
async def test_expanded_control_and_debug_actions_are_forwarded(monkeypatch) -> None:
    monkeypatch.setattr(direct_browser_bridge, "is_connected", lambda _sid: True)
    requests: list[tuple[str, dict]] = []

    async def request(_sid: str, action: str, params: dict):
        requests.append((action, params))
        return {"action": action, "ok": True}

    monkeypatch.setattr(direct_browser_bridge, "request", request)

    result = await browser_tool.browser_use.arun(
        _injected={"_state": _state()},
        actions=[
            {"action": "query", "selector": "[data-testid]"},
            {"action": "inspect", "index": 3, "styles": ["display", "opacity"]},
            {"action": "type", "index": 4, "text": "hello"},
            {"action": "dispatch_event", "index": 4, "event": "blur"},
            {
                "action": "wait",
                "selector": "#result",
                "state": "visible",
                "text": "Saved",
            },
            {"action": "performance", "include_resources": False},
            {
                "action": "http",
                "method": "POST",
                "url": "/api/debug",
                "body": "{}",
            },
            {
                "action": "evaluate",
                "script": "Promise.resolve(42)",
                "await_promise": True,
            },
            {"action": "resize", "preset": "mobile", "color_scheme": "dark"},
            {"action": "reset_viewport"},
        ],
    )

    assert isinstance(result, str)
    assert [action for action, _params in requests] == [
        "query",
        "inspect",
        "type",
        "dispatch_event",
        "wait",
        "performance",
        "http",
        "evaluate",
        "resize",
        "reset_viewport",
    ]
    assert requests[0][1] == {
        "selector": "[data-testid]",
        "limit": 50,
        "include_hidden": False,
    }
    assert requests[4][1] == {
        "selector": "#result",
        "state": "visible",
        "text": "Saved",
        "seconds": 2.0,
    }
    assert requests[6][1]["timeout_ms"] == 15_000
    assert requests[7][1] == {
        "script": "Promise.resolve(42)",
        "await_promise": True,
        "timeout_ms": 15_000,
    }
    assert requests[8][1] == {
        "preset": "mobile",
        "color_scheme": "dark",
        "device_scale_factor": 1.0,
        "orientation": "portrait",
    }
    assert requests[9][1] == {}
