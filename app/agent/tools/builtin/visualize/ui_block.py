"""UI block tool — render declarative shadcn-native UI blocks inline.

``ui_block`` is the structured sibling of ``show_widget``: instead of a raw
HTML iframe it emits one validated, declarative UI block list (stat cards,
charts, steps, table, key/value, callout, buttons, form, progress,
flashcards, checklist, calculator, layout, custom) as a single complete
``ui_block`` SSE event — never delta-streamed.

The block payload persists through the tool's own arguments; history reload
reconstructs the block from ``SessionMessage.tool_calls`` (no migration).
"""

from __future__ import annotations

import json
from typing import Annotated, Any

from loguru import logger
from pydantic import Field, ValidationError

from app.agent.schemas.events import UiBlockEvent
from app.agent.tools import tool
from app.agent.tools.registry import InjectedArg

_VALID_TYPES = (
    "stat_cards",
    "chart",
    "steps",
    "table",
    "key_value",
    "callout",
    "buttons",
    "form",
    "progress",
    "flashcards",
    "checklist",
    "calculator",
    "layout",
    "custom",
)


@tool(
    name="ui_block",
    tiers=("work", "coding"),
    description=(
        "Render a declarative UI block in the conversation. Use it "
        "proactively — without waiting to be asked — when the content would "
        "naturally be a comparison, a schedule or timeline, a metric set, a "
        "decision matrix, math with changing variables, step progress, or "
        "study/review material; prefer it over a plain markdown table "
        "whenever the user will interact with the data or revisit it. "
        "Accepts {blocks: [...]} where each block has type one of: "
        "stat_cards, chart, steps, table, key_value, callout, buttons, "
        "form, progress, flashcards, checklist, calculator, layout, "
        "custom. Use instead of "
        "show_widget for structured data UI (metrics, charts, step progress, "
        "tables, forms, interactive flashcards/checklists/calculators, "
        "side-by-side sections, embedded HTML widgets) — no "
        "raw HTML, server-validated, small SSE frames, and the block survives "
        "history reload. layout: {orientation?: 'columns'|'stack', "
        "sections: [{title?, children: [...]}]} groups other blocks in a "
        "grid, nested at most 3 levels deep. custom: {html, height?} renders "
        "agent-authored HTML in a sandboxed widget iframe — prefer layout "
        "for shadcn-native UI. Optionally pass title: a short snake_case "
        "title for "
        "the block group. Blocks should explain themselves: form and steps "
        "take an optional 240-char 'description', form fields an optional "
        "160-char 'helper', and buttons an optional 160-char 'hint' — use "
        "them to say what the UI does and what happens when it is submitted. "
        "Pass block_id (a stable id like 'metrics') to give the group a "
        "repeatable identity, and later calls with the same block_id update "
        "it in place instead of appending. Pass replace_id to update an "
        "existing group in place; if nothing matches, a new group is appended."
    ),
    concurrency_safe=False,
)
async def ui_block(
    blocks: Annotated[
        list[Any] | str,
        Field(
            description=(
                "Array of UI block objects, each with a 'type' of stat_cards, "
                "chart, steps, table, key_value, callout, buttons, form, "
                "progress, flashcards, checklist, calculator, layout, or "
                "custom (a "
                "JSON-array string is also accepted). layout: "
                "{orientation?: 'columns'|'stack', sections: [{title?, "
                "children: [block, ...]}]}, nesting <= 3 levels; custom: "
                "{html, height?} (raw HTML, <= 100000 chars, height 64-2000). "
                "Optional guidance "
                "fields: form/steps 'description', form field 'helper', "
                "buttons 'hint' (all optional, capped length). flashcards: "
                "{title?, cards:[{front,back}]} flips on tap. checklist: "
                "{title?, description?, items:[{label,detail?,checked?}]} "
                "shows a live done-counter. calculator: {description?, "
                "inputs:[{name,label,value,unit?,min?,max?,step?}], "
                "outputs:[{label,formula,unit?,decimals?}]} recomputes live; "
                "formulas allow only numbers, input names, + - * / ( ) "
                "(e.g. 'total / people')"
            ),
        ),
    ],
    title: Annotated[
        str,
        Field(
            description="Short snake_case title for the block group",
            max_length=80,
        ),
    ] = "",
    block_id: Annotated[
        str,
        Field(
            description=(
                "Optional stable identity for this block group (e.g. "
                "'metrics'). Omit for one-off groups; later calls with the "
                "same block_id update the group in place instead of "
                "appending a new one."
            ),
            max_length=128,
            pattern=r"^$|^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$",
        ),
    ] = "",
    replace_id: Annotated[
        str,
        Field(
            description=(
                "Update the existing group whose block_id (or earlier "
                "replace_id) matches this value in place, keeping its "
                "position; if no match, a new group is appended. Use to "
                "refresh data without adding another block."
            ),
            max_length=128,
            pattern=r"^$|^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$",
        ),
    ] = "",
    _injected: dict[str, Any] | None = None,
    # Tool.arun only merges InjectedArg-annotated params (registry.py), so the
    # executor keys are declared explicitly; _injected (spec §5.2 / show_widget
    # contract) still serves direct calls and wins when present.
    agent_name: Annotated[str, InjectedArg()] = "",
    tool_call_id: Annotated[str, InjectedArg()] = "",
    session_id: Annotated[str, InjectedArg()] = "",
) -> dict[str, Any]:
    """Validate the block list, emit exactly one ``ui_block`` event (§5.2)."""
    # 2. Normalize a string payload (models sometimes JSON-stringify arrays).
    if isinstance(blocks, str):
        try:
            parsed: Any = json.loads(blocks)  # noqa: ANN401 - external payload
        except ValueError:
            return {
                "success": False,
                "error": "blocks must be a JSON array of objects",
            }
        if not isinstance(parsed, list):
            return {
                "success": False,
                "error": "blocks must be a JSON array of objects",
            }
        blocks = parsed

    # Injected context — direct calls pass _injected (show_widget contract);
    # Tool.arun merges the InjectedArg params above.
    if _injected:
        agent = str(_injected.get("agent_name") or "")
        tool_call_id = str(_injected.get("tool_call_id") or "")
        session_id = str(_injected.get("session_id") or "")
    else:
        agent = agent_name or ""
        tool_call_id = tool_call_id or ""
        session_id = session_id or ""

    # 3. Validate through the event itself; friendly error, never raise.
    try:
        event = UiBlockEvent.model_validate(
            {
                "agent": agent,
                "tool_call_id": tool_call_id,
                "blocks": blocks,
                **({"metadata": {"title": title}} if title else {}),
                # Empty strings normalize to None (§5.1): "" must never
                # become a literal group identity.
                **({"block_id": block_id or None} if block_id else {}),
                **({"replace_id": replace_id or None} if replace_id else {}),
            }
        )
    except ValidationError as exc:
        return {
            "success": False,
            "error": str(exc),
            "valid_types": list(_VALID_TYPES),
        }

    # 4-5. Push exactly one complete frame through the session stream.
    pushed = False
    if session_id:
        try:
            from app.services import memory_stream_store as stream_store
            from app.services.stream_envelope import StreamEnvelope

            await stream_store.push_event(session_id, StreamEnvelope.from_event(event))
            pushed = True
        except Exception:  # noqa: BLE001 - logged-failure per spec §5.2 step 5
            logger.opt(exception=True).warning(
                "ui_block_push_failed session_id={}", session_id
            )
    else:
        logger.warning("ui_block_push_skipped reason=missing_session_id")

    # 6. Do not echo blocks — history persistence uses the tool arguments.
    types = [node.type for node in event.blocks]
    return {
        "success": True,
        "block_count": len(event.blocks),
        "types": types,
        "message": f"Rendered {len(event.blocks)} UI block(s)",
        "pushed": pushed,
    }
