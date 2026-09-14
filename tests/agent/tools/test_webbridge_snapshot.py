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


# ── Handles ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_handle_is_what_a_snapshot_offers(monkeypatch) -> None:
    result = await _run(
        monkeypatch,
        [_element(ref="e12", role="button", text="Submit")],
        "https://example.com/",
    )

    assert "e12 [button]" in result
    # With a handle there is no reason to also print a path to quote back.
    assert "div > a:nth-of-type(2)" not in result


@pytest.mark.asyncio
async def test_an_element_no_selector_can_reach_says_so_by_omission(monkeypatch) -> None:
    """Inside a shadow root there is no CSS path, and pretending otherwise
    costs an action to discover."""
    result = await _run(
        monkeypatch,
        [_element(ref="e4", role="button", text="In a shadow root", selector="")],
        "https://example.com/",
    )

    assert "e4 [button]" in result
    assert "—" not in result


@pytest.mark.asyncio
async def test_an_offscreen_element_warns_about_its_coordinates(monkeypatch) -> None:
    result = await _run(
        monkeypatch,
        [_element(ref="e9", text="Below the fold", offscreen=True)],
        "https://example.com/",
    )

    assert "(offscreen)" in result


@pytest.mark.asyncio
async def test_a_cross_origin_frame_is_named_rather_than_hidden(monkeypatch) -> None:
    result = await _run(
        monkeypatch,
        [_element(ref="e8", role="iframe", text="", cross_origin=True)],
        "https://example.com/",
    )

    assert "cross-origin frame" in result


@pytest.mark.asyncio
async def test_acting_by_ref_sends_the_ref(monkeypatch) -> None:
    sent: list[tuple[str, dict]] = []

    async def send_command(_sid: str, action: str, params=None, **_kw):
        sent.append((action, params or {}))
        return {"success": True, "data": {"ref": "e12", "target": "Submit"}}

    monkeypatch.setattr(webbridge_manager, "send_command", send_command)
    await webbridge_tool.webbridge.arun(
        _injected={"_state": _state()},
        actions=[{"action": "click_selector", "ref": "e12"}],
    )

    assert sent[0][1]["ref"] == "e12"
    assert "selector" not in sent[0][1]


@pytest.mark.asyncio
async def test_a_target_needs_one_of_the_two_ways_to_name_it(monkeypatch) -> None:
    with pytest.raises(Exception) as caught:
        await webbridge_tool.webbridge.arun(
            _injected={"_state": _state()},
            actions=[{"action": "click_selector"}],
        )
    assert "ref" in str(caught.value)


# ── What the action did ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_click_reports_what_it_changed(monkeypatch) -> None:
    """So the caller does not spend a snapshot asking whether it worked."""

    async def send_command(_sid: str, _action: str, _params=None, **_kw):
        return {"success": True, "data": {"target": "Next", "navigated_to": "https://x/2"}}

    monkeypatch.setattr(webbridge_manager, "send_command", send_command)
    result = await webbridge_tool.webbridge.arun(
        _injected={"_state": _state()},
        actions=[{"action": "click_selector", "ref": "e1"}],
    )

    assert "Page went to https://x/2" in result


@pytest.mark.asyncio
async def test_a_click_that_changed_nothing_says_so(monkeypatch) -> None:
    async def send_command(_sid: str, _action: str, _params=None, **_kw):
        return {"success": True, "data": {"target": "Next", "dom_changes": 0}}

    monkeypatch.setattr(webbridge_manager, "send_command", send_command)
    result = await webbridge_tool.webbridge.arun(
        _injected={"_state": _state()},
        actions=[{"action": "click_selector", "ref": "e1"}],
    )

    assert "Nothing on the page changed" in result


# ── Only what changed ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_diff_snapshot_lists_only_the_difference(monkeypatch) -> None:
    async def send_command(_sid: str, action: str, params=None, **_kw):
        assert action == "snapshot"
        assert (params or {}).get("diff") is True
        return {
            "success": True,
            "data": {
                "url": "https://example.com/",
                "title": "Quiz",
                "diff": True,
                "added": [_element(ref="e10", role="button", text="Submit")],
                "changed": [
                    _element(ref="e3", role="checkbox", text="B", state={"checked": True})
                ],
                "removed": ["e1"],
                "unchanged": 57,
            },
        }

    monkeypatch.setattr(webbridge_manager, "send_command", send_command)
    result = await webbridge_tool.webbridge.arun(
        _injected={"_state": _state()},
        actions=[{"action": "snapshot", "diff": True}],
    )

    assert "57 unchanged" in result
    assert "e10 [button]" in result
    assert "[checked=true]" in result
    assert "Gone: e1" in result
    # The whole point: the 57 that did not change cost nothing.
    assert len(result) < 600


# ── One crossing instead of five ───────────────────────────────────────────


def _extension(monkeypatch, commands: list[str]) -> None:
    monkeypatch.setattr(
        webbridge_manager,
        "resolve_target",
        lambda _sid, _ext=None: SimpleNamespace(capabilities={"commands": commands}),
    )


@pytest.mark.asyncio
async def test_a_run_of_simple_actions_travels_as_one_command(monkeypatch) -> None:
    """Five fields used to be five round trips across the relay."""
    sent: list[tuple[str, dict]] = []
    _extension(monkeypatch, ["batch", "fill", "click_selector"])

    async def send_command(_sid: str, action: str, params=None, **_kw):
        sent.append((action, params or {}))
        return {
            "success": True,
            "data": {
                "results": [
                    {"action": command["action"], "success": True, "data": {}}
                    for command in (params or {}).get("commands", [])
                ],
                "skipped": 0,
            },
        }

    monkeypatch.setattr(webbridge_manager, "send_command", send_command)
    result = await webbridge_tool.webbridge.arun(
        _injected={"_state": _state()},
        actions=[
            {"action": "fill", "ref": "e1", "value": "Hung"},
            {"action": "fill", "ref": "e2", "value": "hung@example.com"},
            {"action": "set_checked", "ref": "e3", "checked": True},
            {"action": "click_selector", "ref": "e4"},
        ],
    )

    assert [action for action, _ in sent] == ["batch"]
    assert len(sent[0][1]["commands"]) == 4
    assert sent[0][1]["commands"][0]["params"]["ref"] == "e1"
    assert result.count("ok.") == 4


@pytest.mark.asyncio
async def test_a_batch_stops_where_the_chain_broke(monkeypatch) -> None:
    _extension(monkeypatch, ["batch", "fill", "click_selector"])

    async def send_command(_sid: str, _action: str, params=None, **_kw):
        return {
            "success": True,
            "data": {
                "results": [
                    {"action": "click_selector", "success": False, "error": "covered by div.modal"},
                ],
                "stopped_at": 0,
                "skipped": 2,
            },
        }

    monkeypatch.setattr(webbridge_manager, "send_command", send_command)
    result = await webbridge_tool.webbridge.arun(
        _injected={"_state": _state()},
        actions=[
            {"action": "click_selector", "ref": "e1"},
            {"action": "fill", "ref": "e2", "value": "x"},
            {"action": "click_selector", "ref": "e3"},
        ],
    )

    assert "covered by div.modal" in result
    assert "not run" in result


@pytest.mark.asyncio
async def test_actions_that_are_not_simple_stay_on_their_own(monkeypatch) -> None:
    """A screenshot returns an image and a wait is where the time goes; both
    would be the wrong thing to fold into one message."""
    sent: list[str] = []
    _extension(monkeypatch, ["batch", "fill", "wait_for_load", "click_selector"])

    async def send_command(_sid: str, action: str, params=None, **_kw):
        sent.append(action)
        if action == "batch":
            return {
                "success": True,
                "data": {
                    "results": [
                        {"action": c["action"], "success": True, "data": {}}
                        for c in (params or {}).get("commands", [])
                    ],
                    "skipped": 0,
                },
            }
        return {"success": True, "data": {}}

    monkeypatch.setattr(webbridge_manager, "send_command", send_command)
    await webbridge_tool.webbridge.arun(
        _injected={"_state": _state()},
        actions=[
            {"action": "click_selector", "ref": "e1"},
            {"action": "fill", "ref": "e2", "value": "x"},
            {"action": "wait_for_load"},
            {"action": "click_selector", "ref": "e3"},
        ],
    )

    assert sent == ["batch", "wait_for_load", "click_selector"]


@pytest.mark.asyncio
async def test_an_older_extension_still_gets_one_command_at_a_time(monkeypatch) -> None:
    sent: list[str] = []
    _extension(monkeypatch, ["fill", "click_selector"])  # no batch

    async def send_command(_sid: str, action: str, _params=None, **_kw):
        sent.append(action)
        return {"success": True, "data": {}}

    monkeypatch.setattr(webbridge_manager, "send_command", send_command)
    await webbridge_tool.webbridge.arun(
        _injected={"_state": _state()},
        actions=[
            {"action": "click_selector", "ref": "e1"},
            {"action": "fill", "ref": "e2", "value": "x"},
        ],
    )

    assert sent == ["click_selector", "fill"]
