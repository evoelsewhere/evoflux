"""Tests for the Computer App Control tool."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.agent.schemas.chat import ImageDataBlock, TextBlock, ToolResult
from app.agent.tools.builtin import computer_app_tool as computer_tool
from app.core.runtime_settings import ComputerAppSettings, RuntimeSettings
from app.services.direct_computer_bridge import direct_computer_bridge

_WINDOWS = {
    "count": 3,
    "windows": [
        {"id": 11, "app": "Notepad.exe", "title": "notes.txt - Notepad"},
        {"id": 22, "app": "EXCEL.EXE", "title": "Budget.xlsx - Excel"},
        {"id": 33, "app": "mstsc.exe", "title": "Remote Desktop", "minimized": True},
    ],
}


def _state(session_id: str = "desktop-session") -> SimpleNamespace:
    return SimpleNamespace(metadata={"stream_session_id": session_id})


def _use_policy(monkeypatch, **policy: Any) -> None:
    settings = RuntimeSettings(computer_app=ComputerAppSettings(**policy))
    monkeypatch.setattr(
        "app.core.runtime_settings.load_runtime_settings", lambda: settings
    )


def _fake_bridge(monkeypatch, responses: dict[str, Any]) -> list[tuple[str, str, dict]]:
    requests: list[tuple[str, str, dict]] = []
    monkeypatch.setattr(direct_computer_bridge, "is_connected", lambda _sid: True)

    async def request(sid: str, action: str, params: dict):
        requests.append((sid, action, params))
        response = responses.get(action)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(direct_computer_bridge, "request", request)
    return requests


async def _run(*actions: dict[str, Any]) -> str | ToolResult:
    return await computer_tool.computer_app.arun(
        _injected={"_state": _state()}, actions=list(actions)
    )


@pytest.mark.asyncio
async def test_disabled_by_default(monkeypatch) -> None:
    _use_policy(monkeypatch)
    requests = _fake_bridge(monkeypatch, {})

    result = await _run({"action": "list_windows"})

    assert isinstance(result, str)
    assert "Settings → Computer App Control" in result
    assert requests == []


@pytest.mark.asyncio
async def test_requires_desktop_connection(monkeypatch) -> None:
    _use_policy(monkeypatch, enabled=True)
    monkeypatch.setattr(direct_computer_bridge, "is_connected", lambda _sid: False)

    async def wait_connected(_sid: str) -> bool:
        return False

    monkeypatch.setattr(direct_computer_bridge, "wait_connected", wait_connected)

    result = await _run({"action": "list_windows"})

    assert isinstance(result, str)
    assert "EvoFlux Desktop on Windows or macOS" in result


@pytest.mark.asyncio
async def test_list_windows_hides_blocked_apps_and_marks_untrusted(monkeypatch) -> None:
    _use_policy(monkeypatch, enabled=True, blocked_apps=["mstsc"])
    _fake_bridge(monkeypatch, {"list_windows": _WINDOWS})

    result = await _run({"action": "list_windows"})

    assert isinstance(result, str)
    assert "Untrusted app content" in result
    assert "window_id=11 | Notepad.exe" in result
    assert "window_id=22" in result
    assert "mstsc" not in result


@pytest.mark.asyncio
async def test_attach_checks_allowlist_before_attaching(monkeypatch) -> None:
    _use_policy(monkeypatch, enabled=True, allowed_apps=["notepad"])
    requests = _fake_bridge(monkeypatch, {"list_windows": _WINDOWS})

    result = await _run({"action": "attach", "window_id": 22})

    assert result == (
        "Error (attach): EXCEL.EXE is not in the Computer App Control allowlist."
    )
    assert [action for _sid, action, _params in requests] == ["list_windows"]


@pytest.mark.asyncio
async def test_attach_by_app_name_attaches_the_resolved_window(monkeypatch) -> None:
    _use_policy(monkeypatch, enabled=True, allowed_apps=["notepad.exe"])
    requests = _fake_bridge(
        monkeypatch,
        {
            "list_windows": _WINDOWS,
            "attach": {
                "attached": True,
                "window": {
                    "id": 11,
                    "app": "Notepad.exe",
                    "title": "notes.txt - Notepad",
                    "screenshot_size": [1200, 800],
                },
            },
        },
    )

    result = await _run({"action": "attach", "app": "notepad"})

    assert isinstance(result, str)
    assert result.startswith('Attached to Notepad.exe — "notes.txt - Notepad"')
    assert "screenshot 1200x800" in result
    assert requests[-1] == (
        "desktop-session",
        "attach",
        {"window_id": 11, "hide": True},
    )


@pytest.mark.asyncio
async def test_attach_respects_keep_hidden_and_explains_web_content(
    monkeypatch,
) -> None:
    _use_policy(monkeypatch, enabled=True, keep_hidden=False)
    requests = _fake_bridge(
        monkeypatch,
        {
            "list_windows": {
                "windows": [{"id": 44, "app": "ms-teams.exe", "title": "Chat | Teams"}]
            },
            "attach": {
                "attached": True,
                "window": {
                    "id": 44,
                    "app": "ms-teams.exe",
                    "title": "Chat | Teams",
                    "screenshot_size": [1568, 848],
                    "hidden": False,
                    "web_content": True,
                },
            },
            "click": {
                "pointer": {"x": 10, "y": 20},
                "delivered_to": "Send",
                "delivered_via": "ui_automation",
                "pattern": "invoke",
                "window": "Chat | Teams",
                "button": "left",
                "clicks": 1,
            },
        },
    )

    result = await _run(
        {"action": "attach", "window_id": 44},
        {"action": "click", "ref": "e7"},
    )

    assert isinstance(result, str)
    assert requests[1] == (
        "desktop-session",
        "attach",
        {"window_id": 44, "hide": False},
    )
    assert "web content" in result
    assert "off-screen" not in result
    assert (
        'Clicked at (10, 20) → Send in "Chat | Teams" (via UI Automation: invoke)'
        in result
    )


@pytest.mark.asyncio
async def test_actions_forward_params_and_summarize(monkeypatch) -> None:
    _use_policy(monkeypatch, enabled=True)
    requests = _fake_bridge(
        monkeypatch,
        {
            "click": {
                "pointer": {"x": 40, "y": 60},
                "delivered_to": "Edit",
                "window": "notes.txt - Notepad",
                "button": "left",
                "clicks": 2,
            },
            "type": {"typed_chars": 5, "delivered_to": "Edit", "window": "notes"},
            "key": {"key": "ctrl+s", "repeat": 1, "delivered_to": "Edit"},
            "snapshot": 'UI of Notepad.exe\n- Button "Save" [ref=e1] @1,2 3x4',
        },
    )

    result = await _run(
        {"action": "click", "x": 40, "y": 60, "clicks": 2},
        {"action": "type", "text": "hello"},
        {"action": "key", "key": "ctrl+s"},
        {"action": "snapshot"},
    )

    assert isinstance(result, str)
    assert 'Double-clicked at (40, 60) → Edit in "notes.txt - Notepad"' in result
    assert "Typed 5 characters → Edit" in result
    assert "Pressed ctrl+s ×1 → Edit" in result
    assert "Untrusted app content" in result
    assert [(action, params) for _sid, action, params in requests] == [
        ("click", {"x": 40.0, "y": 60.0, "button": "left", "clicks": 2}),
        ("type", {"text": "hello"}),
        ("key", {"key": "ctrl+s", "repeat": 1}),
        ("snapshot", {"max_depth": 30, "max_elements": 400}),
    ]


@pytest.mark.asyncio
async def test_screenshot_becomes_multimodal_result(monkeypatch) -> None:
    _use_policy(monkeypatch, enabled=True)
    _fake_bridge(
        monkeypatch,
        {
            "screenshot": {
                "kind": "image",
                "media_type": "image/png",
                "data": "aGVsbG8=",
                "width": 800,
                "height": 600,
                "window": {"app": "Notepad.exe", "title": "notes", "dialog": "Save As"},
            }
        },
    )

    result = await _run({"action": "screenshot"})

    assert isinstance(result, ToolResult)
    text = next(part for part in result.parts if isinstance(part, TextBlock))
    assert "800x600 screenshot" in text.text
    assert 'modal dialog "Save As"' in text.text
    assert "Untrusted app content" in text.text
    assert any(isinstance(part, ImageDataBlock) for part in result.parts)


@pytest.mark.asyncio
async def test_a_failed_action_skips_the_rest_but_still_detaches(monkeypatch) -> None:
    _use_policy(monkeypatch, enabled=True)
    requests = _fake_bridge(
        monkeypatch,
        {
            "click": RuntimeError("That point is on the window's frame"),
            "detach": {"detached": True},
        },
    )

    result = await _run(
        {"action": "click", "x": 1, "y": 1},
        {"action": "type", "text": "hello"},
        {"action": "key", "key": "enter"},
        {"action": "detach"},
    )

    assert [action for _, action, _ in requests] == ["click", "detach"]
    assert result == (
        "Error (click): That point is on the window's frame\n---\n"
        "Skipped 2 action(s) (type, key) because click failed. Check the app's "
        "state, then send them again.\n---\nDetached."
    )


@pytest.mark.asyncio
async def test_a_refused_attach_does_not_type_into_the_previous_app(
    monkeypatch,
) -> None:
    _use_policy(monkeypatch, enabled=True, blocked_apps=["excel"])
    requests = _fake_bridge(monkeypatch, {"list_windows": _WINDOWS})

    result = await _run(
        {"action": "attach", "app": "excel"},
        {"action": "type", "text": "=SUM(A1:A9)"},
        {"action": "key", "key": "ctrl+s"},
    )

    assert isinstance(result, str)
    assert "blocked" in result
    assert "Skipped 2 action(s) (type, key) because attach failed" in result
    assert [action for _, action, _ in requests] == ["list_windows"]


def test_app_policy_matching_ignores_case_and_exe_suffix() -> None:
    policy = ComputerAppSettings(
        enabled=True, allowed_apps=["Notepad"], blocked_apps=["notepad2.exe"]
    )
    assert computer_tool.app_policy_refusal("NOTEPAD.EXE", policy) is None
    assert "blocked" in (computer_tool.app_policy_refusal("Notepad2.exe", policy) or "")
    assert "allowlist" in (computer_tool.app_policy_refusal("calc.exe", policy) or "")


def test_app_policy_matches_mac_executables() -> None:
    # The picker stores "textedit.exe" for older settings; macOS reports the
    # bare executable name or its path inside the bundle.
    policy = ComputerAppSettings(
        enabled=True, allowed_apps=["textedit.exe"], blocked_apps=["MSTeams"]
    )
    assert computer_tool.app_policy_refusal("TextEdit", policy) is None
    assert (
        computer_tool.app_policy_refusal(
            "/System/Applications/TextEdit.app/Contents/MacOS/TextEdit", policy
        )
        is None
    )
    assert "blocked" in (computer_tool.app_policy_refusal("MSTeams", policy) or "")


@pytest.mark.asyncio
async def test_list_windows_explains_missing_mac_permissions(monkeypatch) -> None:
    _use_policy(monkeypatch, enabled=True)
    _fake_bridge(
        monkeypatch,
        {
            "list_windows": {
                "count": 1,
                "windows": [{"id": 7, "app": "TextEdit", "title": "notes.txt"}],
                "platform": "macos",
                "missing_permissions": ["accessibility", "screen_recording"],
            }
        },
    )

    result = await _run({"action": "list_windows"})

    assert isinstance(result, str)
    assert "Accessibility and Screen Recording access" in result
    assert "Screen & System Audio Recording" in result
    assert "window_id=7 | TextEdit" in result


@pytest.mark.asyncio
async def test_mac_attach_and_menu_shortcut_are_explained(monkeypatch) -> None:
    _use_policy(monkeypatch, enabled=True)
    _fake_bridge(
        monkeypatch,
        {
            "list_windows": {
                "windows": [{"id": 7, "app": "TextEdit", "title": "notes.txt"}]
            },
            "attach": {
                "attached": True,
                "window": {
                    "id": 7,
                    "app": "TextEdit",
                    "title": "notes.txt",
                    "screenshot_size": [800, 600],
                    "platform": "macos",
                },
            },
            "key": {
                "key": "cmd+s",
                "repeat": 1,
                "delivered_to": "Save…",
                "delivered_via": "menu",
                "window": "notes.txt",
            },
        },
    )

    result = await _run(
        {"action": "attach", "window_id": 7},
        {"action": "key", "key": "cmd+s"},
    )

    assert isinstance(result, str)
    assert "shortcuts use cmd" in result
    assert 'Pressed cmd+s ×1 → Save… in "notes.txt" (via the app\'s menu bar)' in result
