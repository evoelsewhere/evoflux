from datetime import datetime

from app.agent.tools.registry import tool


@tool(
    name="date",
    concurrency_safe=True,
    read_only=True,
    deferred=True,
    deferred_summary="Get the current local date, time, and timezone.",
)
def get_date() -> str:
    """Get the current local date, time, and timezone (e.g. '2026-04-06 14:30:00 ICT')."""
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
