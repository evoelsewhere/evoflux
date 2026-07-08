"""Visualize read_me tool — load design guidelines by module.

This tool loads design guidelines for creating interactive HTML widgets.
Claude must call this tool before using show_widget to ensure consistent
design patterns.
"""

from typing import Annotated

from pydantic import Field

from app.agent.tools import tool
from app.agent.tools.builtin.visualize.guidelines import (
    AVAILABLE_MODULES,
    WIDGET_GALLERY,
    get_guidelines,
)


@tool(
    name="visualize_read_me",
    description=lambda: (
        "Load design guidelines for creating interactive HTML widgets. "
        "Call this once before your first show_widget call to understand "
        "the design system. Available modules: "
        + ", ".join(AVAILABLE_MODULES)
    ),
    concurrency_safe=True,
    read_only=True,
)
async def visualize_read_me(
    modules: Annotated[
        list[str],
        Field(
            description="List of design modules to load. Options: interactive, chart, mockup, art, diagram",
            examples=[["interactive", "chart"]],
        ),
    ],
) -> str:
    """Load design guidelines for creating interactive HTML widgets.

    This tool returns design guidelines for the requested modules.
    Call this before show_widget to understand the design system.

    Available modules:
    - interactive: UI components (cards, buttons, forms, sliders)
    - chart: Chart.js integration and data visualization
    - mockup: UI mockup patterns and layouts
    - art: SVG illustration guide
    - diagram: Flowcharts, architecture, and sequence diagrams

    Returns:
        Design guidelines text for the requested modules
    """
    # Filter to valid modules only
    valid_modules = [m for m in modules if m in AVAILABLE_MODULES]
    
    if not valid_modules:
        return (
            f"Invalid modules. Available options: {', '.join(AVAILABLE_MODULES)}\n\n"
            f"Requested: {', '.join(modules)}"
        )
    
    return get_guidelines(valid_modules)
