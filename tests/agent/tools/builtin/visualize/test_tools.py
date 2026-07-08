"""Tests for visualize tools."""

import pytest

from app.agent.tools.builtin.visualize.read_me import visualize_read_me
from app.agent.tools.builtin.visualize.show_widget import show_widget


class TestVisualizeReadMe:
    """Test visualize_read_me tool."""

    @pytest.mark.asyncio
    async def test_single_module(self):
        result = await visualize_read_me(modules=["interactive"])
        assert isinstance(result, str)
        assert "Interactive Components" in result

    @pytest.mark.asyncio
    async def test_multiple_modules(self):
        result = await visualize_read_me(modules=["interactive", "chart"])
        assert isinstance(result, str)
        assert "Interactive Components" in result
        assert "Chart.js Integration" in result

    @pytest.mark.asyncio
    async def test_invalid_module(self):
        result = await visualize_read_me(modules=["invalid"])
        assert isinstance(result, str)
        assert "Invalid modules" in result
        assert "interactive" in result

    @pytest.mark.asyncio
    async def test_empty_modules(self):
        result = await visualize_read_me(modules=[])
        assert isinstance(result, str)
        # Empty modules returns invalid modules message
        assert "Invalid modules" in result

    @pytest.mark.asyncio
    async def test_gallery_module(self):
        result = await visualize_read_me(modules=["gallery"])
        assert isinstance(result, str)
        assert "Widget Gallery" in result
        assert "Metric Dashboard" in result


class TestShowWidget:
    """Test show_widget tool."""

    @pytest.mark.asyncio
    async def test_basic_widget(self):
        result = await show_widget(
            title="test_widget",
            loading_messages=["Loading..."],
            widget_code="<div>Test</div>",
            i_have_seen_read_me=True,
            _injected={
                "agent_name": "test_agent",
                "tool_call_id": "test_id",
                "session_id": "test_session",
            },
        )
        assert isinstance(result, dict)
        assert result["success"] is True
        assert result["title"] == "test_widget"

    @pytest.mark.asyncio
    async def test_requires_read_me(self):
        result = await show_widget(
            title="test_widget",
            loading_messages=["Loading..."],
            widget_code="<div>Test</div>",
            i_have_seen_read_me=False,
        )
        assert isinstance(result, dict)
        assert result["success"] is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_custom_dimensions(self):
        result = await show_widget(
            title="custom_widget",
            loading_messages=["Loading..."],
            widget_code="<div>Test</div>",
            i_have_seen_read_me=True,
            width=1000,
            height=500,
            _injected={
                "agent_name": "test_agent",
                "tool_call_id": "test_id",
                "session_id": "test_session",
            },
        )
        assert result["width"] == 1000
        assert result["height"] == 500

    @pytest.mark.asyncio
    async def test_html_content_preserved(self):
        html = "<div class='test'><p>Hello World</p></div>"
        result = await show_widget(
            title="html_widget",
            loading_messages=["Loading..."],
            widget_code=html,
            i_have_seen_read_me=True,
            _injected={
                "agent_name": "test_agent",
                "tool_call_id": "test_id",
                "session_id": "test_session",
            },
        )
        assert result["widget_code"] == html
