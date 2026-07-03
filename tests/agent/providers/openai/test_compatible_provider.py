from __future__ import annotations

from unittest.mock import MagicMock, patch

from pydantic.types import SecretStr

from app.agent.providers.openai import ChatCompletionsOnlyProvider, OpenAIProvider


def _make_provider(
    model_kwargs: dict[str, object] | None = None,
) -> ChatCompletionsOnlyProvider:
    with patch("app.agent.providers.openai.openai.CompletionsHandler"):
        with patch("app.agent.providers.openai.openai.ResponsesHandler"):
            return ChatCompletionsOnlyProvider(
                api_key="sk-compatible",
                model="provider/model",
                base_url="https://compatible.example/v1",
                model_kwargs=model_kwargs,
            )


def test_chat_completions_only_provider_subclasses_openai_provider() -> None:
    assert issubclass(ChatCompletionsOnlyProvider, OpenAIProvider)


def test_chat_completions_only_ignores_thinking_level() -> None:
    provider = _make_provider(model_kwargs={"thinking_level": "high"})

    assert provider._use_responses is False


def test_chat_completions_only_ignores_explicit_responses_api() -> None:
    provider = _make_provider(model_kwargs={"responses_api": True})

    assert provider._use_responses is False


def test_factory_builds_generic_compatible_provider_for_openrouter() -> None:
    from app.agent.providers.factory import build_provider

    with patch(
        "app.agent.providers.factory.ChatCompletionsOnlyProvider",
        return_value=MagicMock(),
    ) as mock_compatible:
        with patch("app.core.config.settings") as mock_settings:
            mock_settings.OPENROUTER_API_KEY = SecretStr("or-key")
            build_provider(
                "openrouter:qwen/qwen3.6-plus:free",
                model_kwargs={"thinking_level": "high"},
            )

    mock_compatible.assert_called_once()
    call_kwargs = mock_compatible.call_args.kwargs
    assert call_kwargs["model"] == "qwen/qwen3.6-plus:free"
    assert call_kwargs["base_url"] == "https://openrouter.ai/api/v1"
    assert call_kwargs["model_kwargs"] == {"thinking_level": "high"}


def test_factory_builds_generic_compatible_provider_for_nvidia() -> None:
    from app.agent.providers.factory import build_provider

    with patch(
        "app.agent.providers.factory.ChatCompletionsOnlyProvider",
        return_value=MagicMock(),
    ) as mock_compatible:
        with patch("app.core.config.settings") as mock_settings:
            mock_settings.NVIDIA_API_KEY = SecretStr("nvapi-key")
            build_provider("nvidia:stepfun-ai/step-3.5-flash")

    assert mock_compatible.call_args.kwargs["base_url"] == (
        "https://integrate.api.nvidia.com/v1"
    )


def test_factory_builds_generic_compatible_provider_for_cliproxy() -> None:
    from app.agent.providers.factory import build_provider

    with patch(
        "app.agent.providers.factory.ChatCompletionsOnlyProvider",
        return_value=MagicMock(),
    ) as mock_compatible:
        with patch("app.core.config.settings") as mock_settings:
            mock_settings.CLIPROXY_API_KEY = SecretStr("sk_cliproxy")
            mock_settings.CLIPROXY_BASE_URL = "http://localhost:8317/v1"
            build_provider("cliproxy:gemini-2.5-pro")

    assert mock_compatible.call_args.kwargs["base_url"] == "http://localhost:8317/v1"
