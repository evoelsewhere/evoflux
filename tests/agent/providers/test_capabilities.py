"""Tests for the capability resolver.

The resolver does exactly two things:

1. Provider-live sparse metadata when available.
2. Exact static registry metadata for fields the provider does not report.
3. Safe defaults for unknown fields.

There are no provider-prefix or model-name capability heuristics.
"""

from __future__ import annotations

import pytest

from app.agent.providers.capabilities import (
    ModelCapabilities,
    ModelInputCapabilities,
    ModelOutputCapabilities,
    _merge_caps,
    clear_runtime_model_capabilities,
    get_capabilities,
    has_model_capabilities,
    has_runtime_model_capabilities,
    replace_runtime_provider_capabilities,
)


# ── Dataclasses ─────────────────────────────────────────────────────────────


class TestModelInputCapabilities:
    def test_defaults(self) -> None:
        caps = ModelInputCapabilities()
        assert caps.vision is False
        # document_text defaults true because markitdown handles
        # conversion on the client side, never reaches the model.
        assert caps.document_text is True
        assert caps.audio is False
        assert caps.video is False

    def test_to_dict(self) -> None:
        caps = ModelInputCapabilities(vision=True, document_text=False)
        assert caps.to_dict() == {
            "vision": True,
            "document_text": False,
            "audio": False,
            "video": False,
        }

    def test_frozen(self) -> None:
        caps = ModelInputCapabilities()
        with pytest.raises(AttributeError):
            caps.vision = True  # type: ignore[misc]


class TestModelOutputCapabilities:
    def test_defaults(self) -> None:
        caps = ModelOutputCapabilities()
        # Text-out defaults true because every chat model emits text.
        assert caps.text is True
        assert caps.image is False
        assert caps.audio is False


class TestModelCapabilities:
    def test_defaults(self) -> None:
        caps = ModelCapabilities()
        assert caps.input.vision is False
        assert caps.input.document_text is True
        assert caps.output.text is True

    def test_to_dict(self) -> None:
        caps = ModelCapabilities(input=ModelInputCapabilities(vision=True))
        d = caps.to_dict()
        assert d["input"]["vision"] is True
        assert d["output"]["text"] is True


# ── _merge_caps — sparse merge semantics ────────────────────────────────────


class TestMergeCaps:
    """``_merge_caps`` is what makes ``input: { vision: true }`` enough."""

    def test_empty_spec_inherits_defaults(self) -> None:
        caps = _merge_caps({})
        assert caps == ModelCapabilities()

    def test_vision_only(self) -> None:
        caps = _merge_caps({"input": {"vision": True}})
        assert caps.input.vision is True
        # Untouched fields inherit defaults.
        assert caps.input.document_text is True
        assert caps.output.text is True

    def test_output_image(self) -> None:
        caps = _merge_caps({"output": {"image": True}})
        assert caps.output.image is True
        assert caps.output.text is True  # unchanged

    def test_invalid_spec_raises(self) -> None:
        with pytest.raises(TypeError):
            _merge_caps({"input": "not a dict"})


# ── get_capabilities — exact-match resolution against the bundled YAML ──────


class TestGetCapabilities:
    """The model registry is the source of truth."""

    def test_none_returns_default(self) -> None:
        caps = get_capabilities(None)
        assert caps == ModelCapabilities()

    def test_empty_string_returns_default(self) -> None:
        caps = get_capabilities("")
        assert caps == ModelCapabilities()

    def test_unknown_model_returns_default(self) -> None:
        caps = get_capabilities("openai:made-up-model-zzz")
        assert caps.input.vision is False
        assert caps.input.document_text is True
        assert caps.output.text is True
        assert has_model_capabilities("openai:made-up-model-zzz") is False

    def test_unknown_provider_returns_default(self) -> None:
        caps = get_capabilities("nonexistent_provider:foo")
        assert caps.input.vision is False

    @pytest.mark.parametrize(
        "model_id",
        [
            "openai:gpt-5.5",
            "openai:gpt-5.4-mini",
            "googlegenai:gemini-3.1-pro-preview",
            "vertexai:gemini-2.5-pro",
            "xai:grok-4.3",
            "bedrock:anthropic.claude-opus-4-7",
            "bedrock:global.anthropic.claude-sonnet-4-6",
            "bedrock:amazon.nova-pro-v1:0",
            "zai:glm-4.6v",
        ],
    )
    def test_listed_vision_models(self, model_id: str) -> None:
        # Smoke-test that everything we curated as vision-true in the
        # YAML actually resolves that way. If you change the YAML, the
        # parametrize list is the obvious place to keep things honest.
        assert get_capabilities(model_id).input.vision is True, model_id

    @pytest.mark.parametrize(
        "model_id",
        [
            # Non-vision providers — vision stays false.
            "deepseek:deepseek-v4-pro",
            "ollama:llama3.2",
            # Z.AI non-vision GLMs (the vision-capable ones end in `v`).
            "zai:glm-5",
            "zai:glm-4.7",
        ],
    )
    def test_unlisted_models_default_no_vision(self, model_id: str) -> None:
        caps = get_capabilities(model_id)
        assert caps.input.vision is False, model_id
        # But document_text and text-output should still be on (defaults).
        assert caps.input.document_text is True
        assert caps.output.text is True

    def test_live_provider_capabilities_overlay_static_registry(self) -> None:
        try:
            replace_runtime_provider_capabilities(
                "openai",
                {"made-up-model-zzz": {"input": {"vision": True}}},
            )
            assert has_runtime_model_capabilities("openai:made-up-model-zzz") is True
            assert has_model_capabilities("openai:made-up-model-zzz") is True
            assert get_capabilities("openai:made-up-model-zzz").input.vision is True
        finally:
            clear_runtime_model_capabilities()
        assert has_runtime_model_capabilities("openai:made-up-model-zzz") is False

    def test_case_insensitive_lookup(self) -> None:
        lower = get_capabilities("openai:gpt-5.5")
        upper = get_capabilities("OPENAI:GPT-5.5")
        assert lower == upper
        assert lower.input.vision is True
