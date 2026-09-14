"""What a WebBridge snapshot spends its tokens on.

A snapshot is the most expensive thing this tool returns and the model reads
one before nearly every action, so what each line carries is a budget
decision, not a formatting preference. These tests pin the decisions.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.agent.tools.builtin import webbridge_tool
from app.services.webbridge_service import webbridge_manager


def _state(session_id: str = "s1") -> SimpleNamespace:
    return SimpleNamespace(metadata={"session_id": session_id})


def _element(**overrides: Any) -> dict[str, Any]:
    element = {
        "role": "link",
        "text": "History",
        "name": "History",
        "selector": "div > a:nth-of-type(2)",
        "state": {},
        "attributes": {},
        "box": {"x": 120, "y": 300, "w": 60, "h": 20},
    }
    element.update(overrides)
    return element


@pytest.mark.asyncio
async def test_a_labelled_link_does_not_repeat_its_address(monkeypatch) -> None:
    """The label is how the model names the target; the URL is 50% of the bill.

    Measured on an 80-element snapshot of a Wikipedia article: 4.3k of 8.6k
    characters were absolute hrefs, 72 of the 74 links also carrying a label.
    """
    result = await _run(
        monkeypatch,
        [
            _element(
                attributes={
                    "href": "https://en.wikipedia.org/wiki/History_of_the_web_browser"
                }
            )
        ],
        "https://en.wikipedia.org/wiki/Web_browser",
    )

    assert "'History'" in result
    assert "href" not in result


@pytest.mark.asyncio
async def test_an_unlabelled_link_keeps_a_shortened_address(monkeypatch) -> None:
    """With no label the address is the only way to tell one icon from another."""
    result = await _run(
        monkeypatch,
        [
            _element(
                text="",
                name="",
                attributes={"href": "https://en.wikipedia.org/wiki/Main_Page"},
            )
        ],
        "https://en.wikipedia.org/wiki/Web_browser",
    )

    # Same origin as the page it was found on, so the origin says nothing.
    assert "href='/wiki/Main_Page'" in result
    assert "https://en.wikipedia.org/wiki/Main_Page" not in result


@pytest.mark.asyncio
async def test_a_cross_origin_address_keeps_its_host(monkeypatch) -> None:
    result = await _run(
        monkeypatch,
        [_element(text="", name="", attributes={"href": "https://example.com/a"})],
        "https://en.wikipedia.org/wiki/Web_browser",
    )

    assert "href='https://example.com/a'" in result


@pytest.mark.asyncio
async def test_a_very_long_address_is_cut(monkeypatch) -> None:
    href = "https://example.com/" + "x" * 300
    result = await _run(
        monkeypatch,
        [_element(text="", name="", attributes={"href": href})],
        "https://en.wikipedia.org/",
    )

    assert "…" in result
    assert len(max(result.splitlines(), key=len)) < 200


@pytest.mark.asyncio
async def test_ordinary_states_are_not_worth_a_line(monkeypatch) -> None:
    """Every control on a page is enabled; saying so 80 times says nothing."""
    result = await _run(
        monkeypatch,
        [_element(role="button", text="Submit", state={"disabled": False})],
        "https://example.com/",
    )

    assert "disabled" not in result


@pytest.mark.asyncio
async def test_being_unchecked_is_worth_a_line(monkeypatch) -> None:
    """Unlike disabled=false, this is the thing the next click will change."""
    result = await _run(
        monkeypatch,
        [_element(role="checkbox", text="I agree", state={"checked": False})],
        "https://example.com/",
    )

    assert "[checked=false]" in result


@pytest.mark.asyncio
async def test_a_disabled_control_still_says_so(monkeypatch) -> None:
    result = await _run(
        monkeypatch,
        [_element(role="button", text="Submit", state={"disabled": True})],
        "https://example.com/",
    )

    assert "[disabled=true]" in result


@pytest.mark.asyncio
async def test_the_handle_the_model_acts_with_survives(monkeypatch) -> None:
    """Whatever else is trimmed, a line has to stay actionable."""
    result = await _run(
        monkeypatch,
        [_element(role="button", text="Submit", attributes={"type": "submit"})],
        "https://example.com/",
    )

    assert "div > a:nth-of-type(2)" in result  # selector for click_selector
    assert "@(120,300)" in result  # coordinates for the click fallback
    assert "type='submit'" in result


async def _run(monkeypatch, elements: list[dict[str, Any]], url: str) -> str:
    async def send_command(_sid: str, action: str, _params=None, **_kw):
        assert action == "snapshot"
        return {
            "success": True,
            "data": {
                "url": url,
                "title": "Page",
                "viewport": {"width": 1280, "height": 800, "scrollX": 0, "scrollY": 0},
                "elements": elements,
            },
        }

    monkeypatch.setattr(webbridge_manager, "send_command", send_command)
    result = await webbridge_tool.webbridge.arun(
        _injected={"_state": _state()}, actions=[{"action": "snapshot"}]
    )
    assert isinstance(result, str)
    return result


@pytest.mark.asyncio
async def test_a_failed_step_stops_the_ones_that_depended_on_it(monkeypatch) -> None:
    """A chain whose first step failed has nothing left worth running.

    It used to run every later action anyway — filling and submitting a form
    that was never opened — which buries the one failure that mattered under
    a list of consequences.
    """
    sent: list[str] = []

    async def send_command(_sid: str, action: str, _params=None, **_kw):
        sent.append(action)
        if action == "click_selector":
            return {"success": False, "data": None, "error": "No visible element"}
        return {"success": True, "data": {}}

    monkeypatch.setattr(webbridge_manager, "send_command", send_command)
    result = await webbridge_tool.webbridge.arun(
        _injected={"_state": _state()},
        actions=[
            {"action": "click_selector", "selector": "#open"},
            {"action": "fill", "selector": "#name", "value": "Hung"},
            {"action": "click_text", "text": "Submit"},
        ],
    )

    assert sent == ["click_selector"]
    assert "2 later action(s) not run" in result


@pytest.mark.asyncio
async def test_independent_actions_can_still_all_run(monkeypatch) -> None:
    sent: list[str] = []

    async def send_command(_sid: str, action: str, _params=None, **_kw):
        sent.append(action)
        if action == "extract":
            return {"success": False, "data": None, "error": "tab gone"}
        return {"success": True, "data": {"content": "ok"}}

    monkeypatch.setattr(webbridge_manager, "send_command", send_command)
    await webbridge_tool.webbridge.arun(
        _injected={"_state": _state()},
        continue_on_error=True,
        actions=[
            {"action": "extract", "tab_id": 1},
            {"action": "extract", "tab_id": 2},
        ],
    )

    assert sent == ["extract", "extract"]


@pytest.mark.asyncio
async def test_a_working_chain_is_unaffected(monkeypatch) -> None:
    sent: list[str] = []

    async def send_command(_sid: str, action: str, _params=None, **_kw):
        sent.append(action)
        return {"success": True, "data": {"url": "https://example.com/done"}}

    monkeypatch.setattr(webbridge_manager, "send_command", send_command)
    result = await webbridge_tool.webbridge.arun(
        _injected={"_state": _state()},
        actions=[
            {"action": "navigate", "url": "https://example.com"},
            {"action": "wait_for_url", "url": "https://example.com/*"},
            {"action": "click_text", "text": "Next"},
        ],
    )

    assert sent == ["navigate", "wait_for_url", "click_text"]
    assert "not run" not in result
