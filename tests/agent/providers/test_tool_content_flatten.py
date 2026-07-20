"""Tests for tool content flattening for MiMo/GLM/Xiaomi providers."""

from __future__ import annotations

from app.agent.providers.openai.schemas import OpenAIMessage
from app.agent.providers.openai.tool_content import (
    flatten_tool_content_for_provider,
    should_flatten_tool_content,
)


class TestShouldFlattenToolContent:
    """Test model ID matching for flatten providers."""

    def test_mimo_models_match(self):
        assert should_flatten_tool_content("mimo-v2.5") is True
        assert should_flatten_tool_content("xiaomi:mimo-v2.5-pro") is True

    def test_glm_models_match(self):
        assert should_flatten_tool_content("glm-5.2") is True
        assert should_flatten_tool_content("zai:glm-5-turbo") is True

    def test_xiaomi_models_match(self):
        assert should_flatten_tool_content("xiaomi:mimo-v2.5") is True

    def test_non_matching_models(self):
        assert should_flatten_tool_content("gpt-4o") is False
        assert should_flatten_tool_content("claude-3-sonnet") is False
        assert should_flatten_tool_content("gemini-2.0-flash") is False


class TestFlattenToolContentForProvider:
    """Test the flatten transform on message lists."""

    def test_single_text_part_flattened(self):
        """Single text part should be flattened to plain string."""
        messages = [
            OpenAIMessage(
                role="tool",
                content=[{"type": "text", "text": "File contents here"}],
                tool_call_id="call_1",
                name="read_file",
            )
        ]
        result = flatten_tool_content_for_provider(messages, "mimo-v2.5")

        assert len(result) == 1
        assert result[0].role == "tool"
        assert result[0].content == "File contents here"
        assert isinstance(result[0].content, str)
        assert result[0].tool_call_id == "call_1"
        assert result[0].name == "read_file"

    def test_multi_part_tool_content_preserved(self):
        """Multi-part tool content should be left as array."""
        messages = [
            OpenAIMessage(
                role="tool",
                content=[
                    {"type": "text", "text": "Here is the image:"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "https://example.com/img.jpg"},
                    },
                ],
                tool_call_id="call_1",
                name="read_file",
            )
        ]
        result = flatten_tool_content_for_provider(messages, "mimo-v2.5")

        assert len(result) == 1
        assert isinstance(result[0].content, list)
        assert len(result[0].content) == 2

    def test_single_image_part_not_flattened(self):
        """Single image part should not be flattened (preserves error signal)."""
        messages = [
            OpenAIMessage(
                role="tool",
                content=[
                    {
                        "type": "image_url",
                        "image_url": {"url": "https://example.com/img.jpg"},
                    }
                ],
                tool_call_id="call_1",
                name="read_file",
            )
        ]
        result = flatten_tool_content_for_provider(messages, "mimo-v2.5")

        assert len(result) == 1
        assert isinstance(result[0].content, list)

    def test_string_content_unchanged(self):
        """String content should not be modified."""
        messages = [
            OpenAIMessage(
                role="tool",
                content="Plain text result",
                tool_call_id="call_1",
                name="read_file",
            )
        ]
        result = flatten_tool_content_for_provider(messages, "mimo-v2.5")

        assert len(result) == 1
        assert result[0].content == "Plain text result"

    def test_non_matching_model_no_transform(self):
        """Non-matching model should not trigger flatten."""
        messages = [
            OpenAIMessage(
                role="tool",
                content=[{"type": "text", "text": "File contents here"}],
                tool_call_id="call_1",
                name="read_file",
            )
        ]
        result = flatten_tool_content_for_provider(messages, "gpt-4o")

        assert len(result) == 1
        assert isinstance(result[0].content, list)

    def test_mixed_messages_only_tool_flattened(self):
        """Only tool messages should be flattened, not user/assistant."""
        messages = [
            OpenAIMessage(role="user", content=[{"type": "text", "text": "Hello"}]),
            OpenAIMessage(
                role="tool",
                content=[{"type": "text", "text": "Tool result"}],
                tool_call_id="call_1",
                name="tool",
            ),
        ]
        result = flatten_tool_content_for_provider(messages, "mimo-v2.5")

        assert len(result) == 2
        assert isinstance(result[0].content, list)  # user unchanged
        assert result[1].content == "Tool result"  # tool flattened

    def test_empty_messages_list(self):
        """Empty list should return empty list."""
        result = flatten_tool_content_for_provider([], "mimo-v2.5")
        assert result == []
