from __future__ import annotations

from app.agent import usage as usage_module
from app.agent.providers.model_metadata import ModelCost
from app.agent.schemas.chat import Usage


def test_usage_to_dict_estimates_disjoint_input_cache_and_output_cost(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        usage_module,
        "get_model_cost",
        lambda model_id: ModelCost(
            input=2.0, output=10.0, cache_read=0.5, cache_write=2.5
        ),
    )

    result = usage_module.usage_to_dict(
        Usage(
            prompt_tokens=1_000,
            completion_tokens=200,
            total_tokens=1_200,
            cached_tokens=250,
            cache_write_tokens=100,
        ),
        "openai:gpt-test",
    )

    assert result["input"] == 1_000
    assert result["output"] == 200
    assert result["cache"] == 250
    assert result["cache_write"] == 100
    assert result["cost"] == {
        "estimated_usd": 0.003675,
        "cache_read_usd": 0.000125,
        "cache_write_usd": 0.00025,
        "input_usd": 0.0013,
        "output_usd": 0.002,
    }


def test_usage_to_dict_charges_all_input_when_cache_price_unknown(monkeypatch) -> None:
    monkeypatch.setattr(
        usage_module,
        "get_model_cost",
        lambda model_id: ModelCost(
            input=2.0, output=None, cache_read=None, cache_write=None
        ),
    )

    result = usage_module.usage_to_dict(
        Usage(
            prompt_tokens=1_000,
            completion_tokens=0,
            total_tokens=1_000,
            cached_tokens=250,
            cache_write_tokens=100,
        ),
        "openai:gpt-test",
    )

    assert result["cost"] == {
        "estimated_usd": 0.002,
        "input_usd": 0.002,
    }


def test_usage_to_dict_omits_cost_when_registry_has_no_prices(monkeypatch) -> None:
    monkeypatch.setattr(
        usage_module,
        "get_model_cost",
        lambda model_id: ModelCost(),
    )

    result = usage_module.usage_to_dict(
        Usage(prompt_tokens=1_000, completion_tokens=200, total_tokens=1_200),
        "unknown:model",
    )

    assert result == {"input": 1_000, "output": 200}


def test_usage_to_dict_does_not_invent_token_spend_for_subscription_provider(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        usage_module,
        "get_model_cost",
        lambda model_id: ModelCost(input=10.0, output=50.0, cache_read=1.0),
    )

    result = usage_module.usage_to_dict(
        Usage(
            prompt_tokens=1_000,
            completion_tokens=200,
            total_tokens=1_200,
            cached_tokens=250,
        ),
        "copilot:claude-sonnet-4.6",
    )

    assert result == {"input": 1_000, "output": 200, "cache": 250}
