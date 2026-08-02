from app.agent.execution_policy import resolve_execution_policy


def test_complex_task_uses_high_reasoning_and_strict_verification():
    policy = resolve_execution_policy(
        complexity="complex",
        priority="critical",
        target_paths=["a.py", "b.py"],
        supported_thinking_levels=("low", "medium", "high"),
    )

    assert policy.thinking_level == "high"
    assert policy.verification_rigor == "strict"


def test_auto_complexity_scales_with_path_breadth():
    policy = resolve_execution_policy(
        complexity="auto",
        priority="normal",
        target_paths=["a", "b", "c", "d"],
    )

    assert policy.complexity == "complex"
    assert policy.thinking_level == ""


def test_explicit_level_is_clamped_to_nearest_supported_level():
    policy = resolve_execution_policy(
        complexity="simple",
        priority="normal",
        explicit_thinking_level="high",
        supported_thinking_levels=("low", "medium"),
    )

    assert policy.thinking_level == "medium"


def test_explicit_ultra_is_preserved_when_the_model_supports_it():
    policy = resolve_execution_policy(
        complexity="simple",
        priority="normal",
        explicit_thinking_level="ultra",
        supported_thinking_levels=(
            "none",
            "low",
            "medium",
            "high",
            "xhigh",
            "max",
            "ultra",
        ),
    )

    assert policy.thinking_level == "ultra"


def test_provider_default_effort_wins_over_automatic_task_heuristic():
    policy = resolve_execution_policy(
        complexity="multi_step",
        priority="normal",
        provider_default_thinking_level="high",
        supported_thinking_levels=("low", "high", "max"),
    )

    assert policy.thinking_level == "high"


def test_explicit_effort_wins_over_provider_default():
    policy = resolve_execution_policy(
        complexity="complex",
        priority="critical",
        explicit_thinking_level="low",
        provider_default_thinking_level="high",
        supported_thinking_levels=("low", "high", "max"),
    )

    assert policy.thinking_level == "low"
