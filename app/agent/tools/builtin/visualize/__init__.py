"""Visualize tools — interactive HTML widgets for EvoFlux.

This module provides tools for rendering interactive HTML widgets inline
in conversations, similar to Claude's visualize feature.

Tools:
    - visualize_read_me: Load design guidelines by module
    - show_widget: Render HTML widget with streaming support
    - ui_block: Render declarative shadcn-native UI blocks
"""

from app.agent.tools.builtin.visualize.read_me import visualize_read_me
from app.agent.tools.builtin.visualize.show_widget import show_widget
from app.agent.tools.builtin.visualize.ui_block import ui_block
from app.agent.tools.builtin.visualize.visual_artifact import visual_artifact

__all__ = ["visualize_read_me", "show_widget", "ui_block", "visual_artifact"]
