"""Show widget tool — render interactive HTML widgets inline.

This tool renders HTML widgets inline in the conversation with streaming
support for progressive rendering.
"""

import asyncio
from typing import Annotated, Any

from pydantic import Field

from app.agent.tools import tool


@tool(
    name="show_widget",
    tiers=("work",),
    description="Render an interactive HTML widget inline in the conversation. Call visualize_read_me first to load design guidelines.",
    concurrency_safe=False,
    read_only=True,
    deferred=True,
    deferred_summary="Render an interactive HTML widget inline in the conversation.",
    search_aliases=(
        "chart",
        "charts",
        "plot",
        "graph",
        "diagram",
        "flowchart",
        "dashboard",
        "visualise",
        "visualize",
        "visualization",
        "mockup",
        "timeline",
        "infographic",
        "svg",
    ),
)
async def show_widget(
    title: Annotated[
        str,
        Field(description="Snake_case identifier for the widget"),
    ],
    loading_messages: Annotated[
        list[str],
        Field(
            description="1-4 short messages shown while widget loads",
            examples=[["Loading visualization...", "Rendering chart..."]],
        ),
    ],
    widget_code: Annotated[
        str,
        Field(
            description="HTML content to render. No <!DOCTYPE>, <html>, <head>, or <body> tags."
        ),
    ],
    i_have_seen_read_me: Annotated[
        bool,
        Field(description="Must be true. Confirms you called visualize_read_me first."),
    ],
    width: Annotated[
        int,
        Field(description="Widget width in pixels", ge=200, le=1200),
    ] = 800,
    height: Annotated[
        int,
        Field(description="Widget height in pixels", ge=150, le=900),
    ] = 600,
    _injected: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Render an interactive HTML widget inline in the conversation.

    This tool renders HTML content as an interactive widget. The HTML
    streams progressively for smooth rendering.

    Requirements:
    1. Call visualize_read_me first to load design guidelines
    2. Follow the streaming-first architecture (style → content → script)
    3. Use CSS variables for colors (supports dark mode)
    4. Only load scripts from allowed CDNs

    Args:
        title: Snake_case identifier for the widget
        loading_messages: 1-4 messages shown while widget loads
        widget_code: HTML content (no doctype/html/head/body tags)
        i_have_seen_read_me: Must be true
        width: Widget width (200-1200px, default 800)
        height: Widget height (150-900px, default 600)

    Returns:
        Widget metadata for rendering
    """
    if not i_have_seen_read_me:
        return {
            "error": "You must call visualize_read_me before using show_widget",
            "success": False,
        }

    # Get the agent and tool_call_id from injected state
    agent = ""
    tool_call_id = ""
    session_id = ""

    if _injected:
        agent = _injected.get("agent_name", "")
        tool_call_id = _injected.get("tool_call_id", "")
        session_id = _injected.get("session_id", "")

    # Emit widget delta events for streaming
    try:
        from app.services import memory_stream_store as stream_store
        from app.services.stream_envelope import StreamEnvelope
        from app.agent.schemas.events import WidgetDeltaEvent

        # Split widget_code into chunks for streaming simulation
        # In production, this would be called as tokens arrive from LLM
        chunk_size = 500
        chunks = [
            widget_code[i : i + chunk_size]
            for i in range(0, len(widget_code), chunk_size)
        ]

        for i, chunk in enumerate(chunks):
            is_final = i == len(chunks) - 1
            event = WidgetDeltaEvent(
                agent=agent,
                tool_call_id=tool_call_id,
                html=chunk,
                is_final=is_final,
                metadata={"title": title, "sequence": i},
            )
            await stream_store.push_event(session_id, StreamEnvelope.from_event(event))

            # Small delay to simulate streaming
            if not is_final:
                await asyncio.sleep(0.05)

    except Exception:
        # Log but don't fail — widget will render on final result
        pass

    return {
        "success": True,
        "title": title,
        "width": width,
        "height": height,
        "widget_code": widget_code,
        "loading_messages": loading_messages,
        "message": f"Widget '{title}' rendered successfully",
    }
