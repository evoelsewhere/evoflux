"""Reasoning-effort translation — one named level, many wire dialects.

EvoFlux exposes a single user-facing knob (``thinking_level``) with the
vocabulary ``none | minimal | low | medium | high | xhigh | max``. Every
provider spells that differently on the wire, and the differences are not
per-provider so much as per *dialect*: Chat Completions hosts take
``reasoning_effort``, Anthropic takes a token budget (or, on the newest
Claude models, an adaptive descriptor), Gemini 2.5 takes a thinking budget
while Gemini 3 takes a level name, Bedrock takes ``reasoningConfig``.

MiMo-Code solves this with ``ProviderTransform.variants()``: a per-model map
from effort name to the exact provider-options payload, switched on the
ai-sdk package behind the model. This module is the same idea with the
switch made explicit — :class:`Dialect` names the wire contract,
:data:`TRANSPORT_DIALECTS` gives the default per transport, and
:data:`PROVIDER_DIALECTS` overrides it for the handful of providers whose
endpoint diverges from its transport's norm.

Two facts stay outside this module:

- *Which* levels a model accepts is catalog knowledge, owned by
  :func:`app.agent.providers.model_metadata.get_effective_model_thinking`.
  This module reads that and clamps the request into range.
- *How much* output a model can emit is catalog knowledge too, and it caps
  every token-budget dialect: a budget at or above the output limit is
  rejected by Anthropic and wastes the whole completion allowance.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.agent.providers.registry import (
    ACTIVE_THINKING_LEVELS,
    THINKING_ORDER,
    Transport,
    clamp_thinking_level,
    get_provider_config,
    normalize_thinking_level,
)


class Dialect(StrEnum):
    """How one endpoint spells a reasoning request."""

    REASONING_EFFORT = "reasoning_effort"
    """``{"reasoning_effort": "high"}`` — the Chat Completions norm."""

    RESPONSES_REASONING = "responses_reasoning"
    """``{"reasoning": {"effort": ..., "summary": "auto"}}`` — OpenAI Responses."""

    OPENROUTER_REASONING = "openrouter_reasoning"
    """``{"reasoning": {"effort": ...}}`` — OpenRouter's normalized object."""

    ANTHROPIC_THINKING = "anthropic_thinking"
    """``{"thinking": {"type": "enabled", "budget_tokens": N}}``, or adaptive.

    The adaptive form pairs ``thinking: {type: "adaptive"}`` with the effort
    name in ``output_config``, which is where the Messages API reads it —
    ai-sdk-based clients pass a bare ``effort`` provider option and the SDK
    moves it there, so a raw-HTTP client has to place it itself.
    """

    GOOGLE_THINKING_CONFIG = "google_thinking_config"
    """``{"thinkingConfig": {...}}`` — budget on Gemini 2.5, level on Gemini 3."""

    BEDROCK_REASONING_CONFIG = "bedrock_reasoning_config"
    """``{"reasoningConfig": {...}}`` — Bedrock Converse."""

    THINKING_TOGGLE_EFFORT = "thinking_toggle_effort"
    """``{"thinking": {"type": "enabled"}, "reasoning_effort": ...}`` — DeepSeek.

    DeepSeek needs both: ``reasoning_effort`` alone does not switch thinking
    on, and the toggle alone does not select an effort.
    """

    BUDGET_TOKENS = "budget_tokens"
    """``{"thinking": {"type": "enabled", "budget_tokens": N}}`` on an
    OpenAI-shaped endpoint — Xiaomi MiMo's documented request shape."""

    GLM_THINKING = "glm_thinking"
    """``{"thinking": {"type": "enabled", "clear_thinking": false}}`` — GLM.

    GLM models reason by default; the only knob is the off switch, and
    ``clear_thinking: false`` keeps the trace in the response so EvoFlux can
    render it.
    """

    ENABLE_THINKING = "enable_thinking"
    """``{"enable_thinking": true}`` — DashScope's OpenAI-compatible surface.

    Without this field DashScope never returns ``reasoning_content``, no
    matter what the model supports. Models that also advertise named efforts
    get ``reasoning_effort`` alongside it; the toggle is what turns reasoning
    on, the effort is what sizes it.
    """

    CHAT_TEMPLATE_ARGS = "chat_template_args"
    """``{"chat_template_args": {"enable_thinking": true}}`` — vLLM-style hosts."""

    NONE = "none"
    """The endpoint exposes no reasoning control."""


#: What each dialect accepts when the catalog says nothing about a model.
#:
#: A self-hosted checkpoint, a brand-new release, or a proxy that renames
#: models is simply absent from models.dev. Dropping the user's reasoning
#: setting in that case would silently ignore it, so the dialect's own
#: vocabulary stands in — the same fallback MiMo-Code makes by keying
#: ``variants()`` on the adapter rather than on per-model metadata.
#:
#: Effort dialects get the three levels every endpoint that implements
#: ``reasoning_effort`` accepts; sending ``xhigh`` to an unknown endpoint is
#: far likelier to 400 than sending ``high``. Budget dialects get the whole
#: vocabulary, because a token budget is continuous — any level maps to a
#: number the endpoint either honours or clamps itself.
DIALECT_FALLBACK_LEVELS: dict[Dialect, tuple[str, ...]] = {}

#: Default dialect per transport.
TRANSPORT_DIALECTS: dict[Transport, Dialect] = {
    Transport.OPENAI_COMPLETIONS: Dialect.REASONING_EFFORT,
    Transport.OPENAI_RESPONSES: Dialect.RESPONSES_REASONING,
    Transport.AZURE: Dialect.RESPONSES_REASONING,
    Transport.ANTHROPIC: Dialect.ANTHROPIC_THINKING,
    Transport.GOOGLE_GENAI: Dialect.GOOGLE_THINKING_CONFIG,
    Transport.GOOGLE_VERTEX: Dialect.GOOGLE_THINKING_CONFIG,
    Transport.BEDROCK: Dialect.BEDROCK_REASONING_CONFIG,
}

#: Providers whose endpoint diverges from its transport's default dialect.
#: Each of these is a documented deviation, not a guess — the same set
#: MiMo-Code special-cases by ``providerID`` inside ``variants()``/``options()``.
PROVIDER_DIALECTS: dict[str, Dialect] = {
    "openrouter": Dialect.OPENROUTER_REASONING,
    "deepseek": Dialect.THINKING_TOGGLE_EFFORT,
    "xiaomi": Dialect.BUDGET_TOKENS,
    "zai": Dialect.GLM_THINKING,
    "zhipuai": Dialect.GLM_THINKING,
    "qwencloud": Dialect.ENABLE_THINKING,
    "baseten": Dialect.CHAT_TEMPLATE_ARGS,
    # Perplexity's Sonar models reason internally with no exposed control.
    "perplexity": Dialect.NONE,
}

#: The three levels every endpoint implementing ``reasoning_effort`` takes.
#: MiMo-Code calls the same set ``WIDELY_SUPPORTED_EFFORTS``.
_WIDELY_SUPPORTED = ("low", "medium", "high")

DIALECT_FALLBACK_LEVELS.update(
    {
        Dialect.REASONING_EFFORT: _WIDELY_SUPPORTED,
        Dialect.RESPONSES_REASONING: _WIDELY_SUPPORTED,
        Dialect.OPENROUTER_REASONING: _WIDELY_SUPPORTED,
        Dialect.GOOGLE_THINKING_CONFIG: _WIDELY_SUPPORTED,
        # Budget dialects take a *number*, so the whole vocabulary is safe:
        # every level maps to a token count the endpoint honours or clamps.
        Dialect.ANTHROPIC_THINKING: THINKING_ORDER,
        Dialect.BUDGET_TOKENS: THINKING_ORDER,
        # Bedrock is a budget for Anthropic families and an *enum* for the
        # rest, and an unknown model lands on the enum — so the fallback has
        # to stay inside what that enum accepts.
        Dialect.BEDROCK_REASONING_CONFIG: _WIDELY_SUPPORTED,
        # These put the level name in an enum too, alongside their toggle.
        Dialect.THINKING_TOGGLE_EFFORT: _WIDELY_SUPPORTED,
        Dialect.ENABLE_THINKING: _WIDELY_SUPPORTED,
        Dialect.CHAT_TEMPLATE_ARGS: _WIDELY_SUPPORTED,
        # GLM ignores the level entirely; accepting all of them is only
        # what lets the toggle fire at all.
        Dialect.GLM_THINKING: THINKING_ORDER,
        Dialect.NONE: (),
    }
)


#: Dialects whose payload actually changes with the level.
#:
#: A toggle-only model borrows its dialect's vocabulary (see
#: :func:`selectable_levels`), and that is only honest where the level makes
#: a difference on the wire. MiMo takes a token budget, so ``low`` and
#: ``high`` really do buy different amounts of thinking. GLM's payload is
#: the same bytes at every level — offering six of them would be six ways to
#: press the same switch.
LEVEL_SENSITIVE_DIALECTS: frozenset[Dialect] = frozenset(
    {
        Dialect.REASONING_EFFORT,
        Dialect.RESPONSES_REASONING,
        Dialect.OPENROUTER_REASONING,
        Dialect.ANTHROPIC_THINKING,
        Dialect.BUDGET_TOKENS,
        Dialect.GOOGLE_THINKING_CONFIG,
        Dialect.BEDROCK_REASONING_CONFIG,
        Dialect.THINKING_TOGGLE_EFFORT,
    }
)


# ---------------------------------------------------------------------------
# Token budgets
# ---------------------------------------------------------------------------
#
# Two different kinds of fact meet in a thinking budget, and keeping them
# apart is what lets the catalog own everything it can:
#
# - What the endpoint *accepts* is published per model, as ``min``/``max`` on
#   the ``budget_tokens`` reasoning option. Those are hard bounds: a request
#   under the floor is rejected outright, one over the cap is refused or
#   silently truncated.
# - How much thinking is *worth buying* at a named level is a product
#   judgement no catalog publishes. That is the ceiling table below.
#
# The budget is the judgement clamped into the published bounds, so a model
# that tightens its cap upstream tightens EvoFlux's budget the next time the
# catalog refreshes — no code change, no stale per-family table.

#: Per-level ceiling on thinking tokens, before the model's own bounds and
#: output cap are applied. The ``high`` and ``max`` figures are MiMo-Code's
#: (``16_000`` / ``31_999``); the rest interpolate below them so the whole
#: EvoFlux vocabulary maps to a budget instead of only two levels doing so.
_BUDGET_CEILINGS: dict[str, int] = {
    "minimal": 2_048,
    "low": 4_096,
    "medium": 8_192,
    "high": 16_000,
    "xhigh": 24_576,
    "max": 31_999,
}

#: Share of the output allowance each level may spend on thinking.
#:
#: The ceilings above are absolute; these keep the split sane on models with
#: a small allowance, where a flat 16k budget would leave nothing for the
#: answer. ``max`` stops at 0.8 so a budget can never reach the limit —
#: Anthropic rejects ``budget_tokens >= max_tokens`` outright.
_BUDGET_RATIOS: dict[str, float] = {
    "minimal": 0.15,
    "low": 0.25,
    "medium": 0.4,
    "high": 0.6,
    "xhigh": 0.75,
    "max": 0.8,
}

#: Floor for any enabled budget when the model publishes none. Below roughly
#: this, the model spends the allowance on a preamble and truncates
#: mid-thought.
_MIN_BUDGET = 1_024

#: Whether to ask for a summarized trace rather than raw thinking blocks.
#:
#: Every model on this dialect returns a usable trace under
#: ``display: "summarized"``, and the raw form carries signed blocks that
#: must be replayed byte-for-byte on the next turn. EvoFlux renders the
#: trace and does not replay it, so summarized is the right ask.
_SUMMARIZED_DISPLAY = {"display": "summarized"}


def thinking_budget(
    level: str,
    max_output: int | None,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    """Token budget for *level*, inside the bounds the model publishes.

    Three constraints meet here. A budget is a *share* of the completion
    allowance, so it has to scale with it — a flat 16k budget on a 4k-output
    model leaves nothing for the answer, and Anthropic rejects a budget that
    reaches ``max_tokens`` outright. Thinking also has diminishing returns,
    so each level carries an absolute ceiling. And the model itself may
    publish a hard floor and cap, which override both.

    Args:
        level: One of :data:`~app.agent.providers.registry.THINKING_ORDER`.
        max_output: The model's completion-token limit, if known.
        minimum: Smallest budget the endpoint accepts, from the catalog.
        maximum: Largest budget the endpoint honours, from the catalog.
    """
    ceiling = _BUDGET_CEILINGS.get(level, _BUDGET_CEILINGS["medium"])
    ratio = _BUDGET_RATIOS.get(level, _BUDGET_RATIOS["medium"])

    # The endpoint's own ceiling — a budget past this is refused or
    # truncated, so nothing may exceed it.
    hard_caps = [value for value in (maximum,) if value]
    if max_output and max_output > 0:
        hard_caps.append(max_output - 1)
    hard_max = min(hard_caps) if hard_caps else None

    # What EvoFlux would like to spend at this level: the product ceiling,
    # kept to a sane share of the completion allowance.
    preferred = ceiling
    if max_output and max_output > 0:
        preferred = min(preferred, int(max_output * ratio))
    if hard_max is not None:
        preferred = min(preferred, hard_max)

    # A published floor is a hard requirement — a request under it is
    # rejected rather than clamped — so it outranks the product ceiling. A
    # floor of zero means "zero turns thinking off", not "an enabled budget
    # may be zero", hence the usable minimum underneath it.
    floor = max(minimum or 0, _MIN_BUDGET)
    if hard_max is not None:
        floor = min(floor, hard_max)
    return max(floor, preferred)


# ---------------------------------------------------------------------------
# Level resolution
# ---------------------------------------------------------------------------


def model_transport(provider_id: str, model: str | None) -> Transport:
    """The wire protocol *model* is reached over, which can differ per model.

    A handful of catalog rows speak a different protocol than the rest of
    their provider: Claude on Vertex is Anthropic Messages, not Gemini;
    Bedrock's Mantle surface is OpenAI-shaped. models.dev states that as
    ``npm`` on the model itself, and ignoring it sent Claude-on-Vertex the
    Gemini reasoning payload — the wrong field, not merely a wrong value.
    """
    if model:
        from app.agent.providers.model_metadata import (
            get_model_metadata,
            qualified_model_id,
        )
        from app.agent.providers.registry import transport_for_npm

        npm = get_model_metadata(qualified_model_id(provider_id, model)).wire.get("npm")
        if npm:
            return transport_for_npm(npm)
    config = get_provider_config((provider_id or "").strip().lower())
    return config.transport if config else Transport.OPENAI_COMPLETIONS


def dialect_for(
    provider_id: str,
    model: str | None = None,
    *,
    transport: Transport | None = None,
) -> Dialect:
    """The wire dialect to use for *provider_id*, and *model* when given.

    Passing the model matters wherever one provider serves two protocols —
    see :func:`model_transport`. Omitting it falls back to the provider's
    default, which is right for the overwhelming majority of models and
    wrong for the few the catalog flags.
    """
    normalized = (provider_id or "").strip().lower()
    if transport is None:
        transport = model_transport(normalized, model)
    # A provider-level override describes that endpoint's own divergence, so
    # it only applies while the model is on that endpoint's protocol.
    override = PROVIDER_DIALECTS.get(normalized)
    if override is not None and transport == (
        get_provider_config(normalized).transport
        if get_provider_config(normalized)
        else transport
    ):
        return override
    return TRANSPORT_DIALECTS.get(transport, Dialect.REASONING_EFFORT)


def _catalog_thinking(provider_id: str, model: str) -> Any:
    from app.agent.providers.model_metadata import (
        get_effective_model_thinking,
        qualified_model_id,
    )

    qualified = qualified_model_id(provider_id, model)
    return get_effective_model_thinking(qualified)


def _catalog_is_silent(thinking: Any) -> bool:
    """Whether the catalog has no opinion about this model's reasoning.

    "No opinion" is different from "no control": an explicit
    ``control="none"`` is the catalog asserting the model exposes nothing,
    and that assertion is respected. A missing row says only that the model
    is unknown to models.dev — a self-hosted checkpoint, a renamed proxy
    model, a release newer than the snapshot.
    """
    return not thinking.levels and thinking.control is None


def supported_levels(
    provider_id: str, model: str, *, dialect: Dialect | None = None
) -> tuple[str, ...]:
    """Active effort names *model* accepts, strongest last.

    Reads the catalog through
    :func:`~app.agent.providers.model_metadata.get_effective_model_thinking`
    and drops ``"none"``, which is an off switch rather than an effort. When
    the catalog has no row for the model, falls back to what the dialect
    itself accepts (see :data:`DIALECT_FALLBACK_LEVELS`).

    An empty result means the model exposes no effort selector — either the
    catalog says so, or the dialect has none to offer.
    """
    thinking = _catalog_thinking(provider_id, model)
    if _catalog_is_silent(thinking):
        resolved = dialect or dialect_for(provider_id, model)
        return DIALECT_FALLBACK_LEVELS.get(resolved, ())
    # Normalize the catalog's own spellings before filtering. A provider's
    # live catalog may report ``ultra`` where EvoFlux calls the same effort
    # ``max``; comparing raw strings dropped it, so the strongest level a
    # model advertised became one it did not support.
    advertised = {normalize_thinking_level(name) for name in thinking.levels}
    return tuple(name for name in THINKING_ORDER if name in advertised)


def selectable_levels(
    provider_id: str, model: str, *, dialect: Dialect | None = None
) -> tuple[str, ...]:
    """Levels a caller may ask for, which is wider than what the model names.

    A model whose only published control is a toggle still has to answer
    "the user asked to think harder". The catalog is right that it names no
    efforts — MiMo and GLM take an on/off switch, nothing more — but
    refusing the request outright would leave the switch permanently off
    for anyone who selects a level rather than the bare default.

    So a toggle-only model borrows the dialect's own vocabulary here. That
    is only about *accepting* the request: :func:`supported_levels` still
    reports the empty set, which is what stops an effort field from being
    put on the wire for a model that has none.
    """
    supported = supported_levels(provider_id, model, dialect=dialect)
    if supported:
        return supported
    thinking = _catalog_thinking(provider_id, model)
    if thinking.control not in {"toggle", "budget"}:
        return ()
    resolved = dialect or dialect_for(provider_id, model)
    return DIALECT_FALLBACK_LEVELS.get(resolved, ())


def offered_levels(
    provider_id: str, model: str, *, dialect: Dialect | None = None
) -> tuple[str, ...]:
    """Levels worth *showing* a user, which is narrower than what is accepted.

    :func:`selectable_levels` answers "will this request be honoured?", and
    for a toggle-only model the answer is yes at every level: the payload
    that switches reasoning on has to be sent regardless, and on GLM it also
    carries ``clear_thinking: false``, which is what keeps the trace in the
    response.

    This answers the different question a picker asks — "does the choice
    change anything?" — and there the toggle dialects have to say no. GLM
    sends the same bytes at every level, so six entries would be six ways to
    press one switch. A model whose level really does reach the wire (MiMo's
    token budget) keeps its ladder.
    """
    resolved = dialect or dialect_for(provider_id, model)
    levels = selectable_levels(provider_id, model, dialect=resolved)
    if supported_levels(provider_id, model, dialect=resolved):
        # The catalog named these explicitly; it is not guessing.
        return levels
    return levels if resolved in LEVEL_SENSITIVE_DIALECTS else ()


def can_disable(
    provider_id: str, model: str, *, dialect: Dialect | None = None
) -> bool:
    """Whether *model* documents an explicit "do not reason" switch."""
    thinking = _catalog_thinking(provider_id, model)
    if _catalog_is_silent(thinking):
        resolved = dialect or dialect_for(provider_id, model)
        return bool(_disable_fields(resolved, model))
    if "none" in thinking.levels:
        return True
    # A model that reasons by default and has any effort control also has an
    # off switch in every dialect this module emits.
    return bool(thinking.levels) and thinking.control in {"effort", "toggle", "budget"}


def resolve_level(
    provider_id: str,
    model: str,
    requested: object,
    *,
    dialect: Dialect | None = None,
) -> str:
    """Normalize and clamp *requested* to what *model* actually accepts.

    Returns ``"none"`` for a disable request the model supports, one of
    :data:`~app.agent.providers.registry.THINKING_ORDER` for an effort, or
    ``""`` when the request cannot be honoured and the provider default
    should stand.

    A level stronger than the model advertises is clamped down rather than
    sent — spending less effort than asked is a degradation, sending an
    unsupported effort is a 400.
    """
    level = normalize_thinking_level(requested)
    if not level:
        return ""
    if level == "none":
        return "none" if can_disable(provider_id, model, dialect=dialect) else ""
    selectable = selectable_levels(provider_id, model, dialect=dialect)
    if not selectable:
        return ""
    return clamp_thinking_level(level, selectable)


# ---------------------------------------------------------------------------
# Wire payloads
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _ModelContract:
    """What the catalog says about one model's reasoning, ready to spend.

    Assembled once per request so the wire builders never reach back into
    the catalog — and, more to the point, never fall back to matching model
    ID substrings. Every discriminator they need is a field here.
    """

    #: ``effort`` | ``budget`` | ``toggle`` | ``none`` | ``None`` (unknown).
    control: str | None = None
    #: Named efforts the model accepts, weakest first, ``"none"`` excluded.
    levels: tuple[str, ...] = ()
    budget_min: int | None = None
    budget_max: int | None = None
    max_output: int | None = None
    #: Catalog model family (``claude-opus``, ``nova-lite``, ``gemini-pro``).
    family: str = ""

    @property
    def has_effort_control(self) -> bool:
        return bool(self.levels)

    @property
    def is_effort_control(self) -> bool:
        """Whether the catalog *states* this model takes a named effort.

        This is what tells Gemini 3 (``thinkingLevel``) from Gemini 2.5
        (``thinkingBudget``), and a Claude generation that takes an adaptive
        effort from one that takes an explicit budget — facts that used to
        be read off the model ID with a substring match.

        It is deliberately an assertion, not an inference: a model the
        catalog has never heard of reads as ``False`` and lands on the older
        budget contract, which is the one an unrecognised endpoint is far
        likelier to accept.
        """
        return self.control == "effort"

    def budget(self, level: str) -> int:
        return thinking_budget(
            level,
            self.max_output,
            minimum=self.budget_min,
            maximum=self.budget_max,
        )


def _model_contract(
    provider_id: str,
    model: str,
    *,
    dialect: Dialect,
    max_output: int | None,
) -> _ModelContract:
    from app.agent.providers.model_metadata import (
        get_model_metadata,
        qualified_model_id,
    )

    qualified = qualified_model_id(provider_id, model)
    metadata = get_model_metadata(qualified)
    thinking = _catalog_thinking(provider_id, model)
    return _ModelContract(
        control=thinking.control,
        levels=supported_levels(provider_id, model, dialect=dialect),
        budget_min=thinking.budget_min,
        budget_max=thinking.budget_max,
        max_output=(
            max_output
            if max_output is not None
            else metadata.limits.max_completion_tokens
        ),
        family=(metadata.features.family or "").lower(),
    )


def thinking_request_fields(
    provider_id: str,
    model: str,
    requested: object,
    *,
    transport: Transport | None = None,
    max_output: int | None = None,
) -> dict[str, Any]:
    """Wire fields expressing *requested* effort, ready to merge into a body.

    Returns an empty dict when the request cannot be expressed — either the
    caller asked for nothing, or the model advertises no control. Callers
    merge the result: ``body.update(thinking_request_fields(...))``.

    Args:
        provider_id: EvoFlux provider ID, used for dialect overrides and to
            look up model metadata.
        model: Provider-side model ID.
        requested: The caller's ``thinking_level`` value, in any spelling.
        transport: Override the provider's registered transport. Needed when
            one provider serves two transports (OpenAI Chat Completions vs
            Responses).
        max_output: The model's output-token limit. Read from the catalog
            when omitted; only budget dialects use it.
    """
    dialect = dialect_for(provider_id, model, transport=transport)
    if dialect is Dialect.NONE:
        return {}

    level = resolve_level(provider_id, model, requested, dialect=dialect)
    if not level:
        return {}

    contract = _model_contract(
        provider_id, model, dialect=dialect, max_output=max_output
    )
    if level == "none":
        return _disable_fields(dialect, contract)
    return _enable_fields(dialect, level, contract)


def _disable_fields(dialect: Dialect, contract: _ModelContract) -> dict[str, Any]:
    """Wire fields for an explicit "do not reason" request."""
    match dialect:
        case Dialect.REASONING_EFFORT:
            return {"reasoning_effort": "none"}
        case Dialect.RESPONSES_REASONING:
            return {"reasoning": {"effort": "none"}}
        case Dialect.OPENROUTER_REASONING:
            return {"reasoning": {"enabled": False}}
        case (
            Dialect.ANTHROPIC_THINKING
            | Dialect.BUDGET_TOKENS
            | Dialect.THINKING_TOGGLE_EFFORT
            | Dialect.GLM_THINKING
        ):
            return {"thinking": {"type": "disabled"}}
        case Dialect.GOOGLE_THINKING_CONFIG:
            # A model steered by budget takes the zero budget as its off
            # switch; one steered by a named level (Gemini 3 onward) dropped
            # that field and takes the weakest level instead. Sending the
            # wrong one is a request error either way.
            if contract.is_effort_control:
                return {"thinkingConfig": {"thinkingLevel": "minimal"}}
            return {"thinkingConfig": {"thinkingBudget": 0}}
        case Dialect.BEDROCK_REASONING_CONFIG:
            return {"reasoningConfig": {"type": "disabled"}}
        case Dialect.ENABLE_THINKING:
            return {"enable_thinking": False}
        case Dialect.CHAT_TEMPLATE_ARGS:
            return {"chat_template_args": {"enable_thinking": False}}
        case _:
            return {}


def _enable_fields(
    dialect: Dialect,
    level: str,
    contract: _ModelContract,
) -> dict[str, Any]:
    """Wire fields for an active effort at *level*."""
    match dialect:
        case Dialect.REASONING_EFFORT:
            return {"reasoning_effort": level}

        case Dialect.RESPONSES_REASONING:
            # ``summary: auto`` is what makes the reasoning trace visible at
            # all on the Responses API; without it the model reasons silently.
            return {"reasoning": {"effort": level, "summary": "auto"}}

        case Dialect.OPENROUTER_REASONING:
            return {"reasoning": {"effort": level}}

        case Dialect.ANTHROPIC_THINKING:
            # A Claude generation that publishes named efforts takes the
            # adaptive descriptor and reads the effort from ``output_config``;
            # one that publishes a token budget takes the budget. The catalog
            # states which, so neither is inferred from the model name.
            if contract.is_effort_control:
                return {
                    "thinking": {"type": "adaptive", **_SUMMARIZED_DISPLAY},
                    "output_config": {"effort": level},
                }
            return {
                "thinking": {
                    "type": "enabled",
                    "budget_tokens": contract.budget(level),
                    **_SUMMARIZED_DISPLAY,
                }
            }

        case Dialect.BUDGET_TOKENS:
            return {
                "thinking": {
                    "type": "enabled",
                    "budget_tokens": contract.budget(level),
                }
            }

        case Dialect.GOOGLE_THINKING_CONFIG:
            if contract.is_effort_control:
                return {
                    "thinkingConfig": {
                        "includeThoughts": True,
                        "thinkingLevel": level,
                    }
                }
            return {
                "thinkingConfig": {
                    "includeThoughts": True,
                    "thinkingBudget": contract.budget(level),
                }
            }

        case Dialect.BEDROCK_REASONING_CONFIG:
            # Bedrock carries two vendors' contracts on one field. Anthropic
            # models take a budget, or an adaptive effort on the generations
            # that publish named efforts; Nova and the rest take a plain
            # named effort.
            if contract.family.startswith("claude"):
                if contract.is_effort_control:
                    return {
                        "reasoningConfig": {
                            "type": "adaptive",
                            "maxReasoningEffort": level,
                            **_SUMMARIZED_DISPLAY,
                        }
                    }
                return {
                    "reasoningConfig": {
                        "type": "enabled",
                        "budgetTokens": contract.budget(level),
                    }
                }
            if contract.control == "budget":
                return {
                    "reasoningConfig": {
                        "type": "enabled",
                        "budgetTokens": contract.budget(level),
                    }
                }
            return {
                "reasoningConfig": {
                    "type": "enabled",
                    "maxReasoningEffort": level,
                }
            }

        case Dialect.THINKING_TOGGLE_EFFORT:
            return {
                "thinking": {"type": "enabled"},
                "reasoning_effort": level,
            }

        case Dialect.GLM_THINKING:
            return {"thinking": {"type": "enabled", "clear_thinking": False}}

        case Dialect.ENABLE_THINKING:
            fields: dict[str, Any] = {"enable_thinking": True}
            if contract.has_effort_control:
                fields["reasoning_effort"] = level
            return fields

        case Dialect.CHAT_TEMPLATE_ARGS:
            args: dict[str, Any] = {"chat_template_args": {"enable_thinking": True}}
            if contract.has_effort_control:
                args["reasoning_effort"] = level
            return args

        case _:
            return {}


__all__ = [
    "ACTIVE_THINKING_LEVELS",
    "Dialect",
    "LEVEL_SENSITIVE_DIALECTS",
    "PROVIDER_DIALECTS",
    "TRANSPORT_DIALECTS",
    "accepts_thinking_level",
    "can_disable",
    "honoured_levels_for",
    "offered_levels",
    "offered_levels_for",
    "dialect_for",
    "model_transport",
    "resolve_level",
    "selectable_levels",
    "supported_levels",
    "thinking_budget",
    "thinking_request_fields",
]


# ---------------------------------------------------------------------------
# Qualified-model helpers
# ---------------------------------------------------------------------------
#
# The functions above take ``(provider_id, model)`` because that is what a
# request builder has. Everything outside the providers package holds a
# single ``"provider:model"`` string instead, and three separate validators
# each answered "may this model be asked for this level?" from a different
# source — one of which was narrower than what the wire honours, so the UI
# offered a level the API then rejected. These are that one answer.


def _split(model_id: str | None) -> tuple[str, str]:
    if not model_id or ":" not in model_id:
        return "", ""
    provider_id, _, model = model_id.partition(":")
    return provider_id, model


def offered_levels_for(model_id: str | None) -> tuple[str, ...]:
    """Levels a picker should show for *model_id*, weakest first.

    What the UI offers. Narrower than :func:`honoured_levels_for` because a
    choice that does not change the request is not worth showing — see
    :func:`offered_levels`.
    """
    provider_id, model = _split(model_id)
    if not provider_id:
        return ()
    levels = offered_levels(provider_id, model)
    if can_disable(provider_id, model):
        return ("none", *levels)
    return levels


def honoured_levels_for(model_id: str | None) -> tuple[str, ...]:
    """Levels a request for *model_id* may legitimately carry.

    What validation must accept. A superset of what the picker offers, on
    purpose: agent frontmatter and API clients may ask for a level the
    picker hides because it makes no difference on the wire — ``high`` on a
    GLM model still means "reason", and rejecting it would fail a request
    the provider would have served.
    """
    provider_id, model = _split(model_id)
    if not provider_id:
        return ()
    levels = selectable_levels(provider_id, model)
    if can_disable(provider_id, model):
        return ("none", *levels)
    return levels


def accepts_thinking_level(model_id: str | None, level: object) -> bool:
    """Whether *model_id* may be asked for *level*.

    ``True`` for an empty request (no preference expressed) and for any
    level the wire will honour. ``False`` only when the model genuinely
    exposes no such control, which is the one case worth an error.
    """
    normalized = normalize_thinking_level(level)
    if not normalized:
        return True
    return normalized in honoured_levels_for(model_id)
