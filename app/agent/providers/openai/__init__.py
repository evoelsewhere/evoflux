"""OpenAI Chat Completions provider package."""

from .compatible_provider import ChatCompletionsOnlyProvider
from .openai import OpenAIProvider

OpenAICompatibleProvider = OpenAIProvider

__all__ = [
    "ChatCompletionsOnlyProvider",
    "OpenAICompatibleProvider",
    "OpenAIProvider",
]
