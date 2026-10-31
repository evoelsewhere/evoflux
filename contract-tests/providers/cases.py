"""Provider parity cases: one model call each, replayed by the mock provider.

``recording`` names a JSONL script under ``mock_provider/recordings`` (shared)
or ``providers/recordings`` (``providers/`` prefix). ``refuse`` points the
provider at a closed port instead of the mock. ``messages`` include the system
message the agent loop prepends, so the Rust provider receives exactly what the
Python provider sent.
"""

from __future__ import annotations

from typing import Any

SYSTEM = {"role": "system", "content": "You are a test."}
HELLO = [SYSTEM, {"role": "user", "content": "Say hello."}]
DATE_TOOL = {
    "type": "function",
    "function": {
        "name": "date",
        "description": "Current date.",
        "parameters": {"type": "object", "properties": {}},
    },
}

#: A history exercising message conversion: images, tool results, an
#: assistant turn with nothing to send, an orphan tool output and an assistant
#: turn whose tool result is missing.
HISTORY: list[dict[str, Any]] = [
    SYSTEM,
    {
        "role": "user",
        "content": "Look.",
        "parts": [
            {"type": "text", "text": "Look at these."},
            {"type": "image_url", "url": "https://example.test/a.png", "detail": "low"},
            {"type": "image_url", "url": "https://example.test/b.png"},
            {"type": "image_data", "data": "aGVsbG8=", "media_type": "image/png"},
        ],
    },
    {
        "role": "assistant",
        "content": "Reading.",
        "reasoning_content": "I should read.",
        "tool_calls": [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "read", "arguments": '{"path": "a"}'},
            },
            {
                "id": "call_2",
                "type": "function",
                "function": {"name": "date", "arguments": ""},
            },
        ],
    },
    {"role": "tool", "tool_call_id": "call_1", "name": "read", "content": "file a"},
    {
        "role": "tool",
        "tool_call_id": "call_2",
        "name": "date",
        "content": "2026",
        "parts": [
            {"type": "text", "text": "2026-10-31"},
            {"type": "image_url", "url": "https://example.test/c.png"},
            {"type": "image_data", "data": "aGk=", "media_type": "image/jpeg"},
        ],
    },
    {"role": "tool", "tool_call_id": "call_9", "name": "orphan", "content": "x"},
    {"role": "assistant", "content": ""},
    {"role": "assistant", "content": None, "reasoning_content": "only thoughts"},
    {"role": "user", "content": "Continue."},
    {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call_3",
                "type": "function",
                "function": {"name": "date", "arguments": "{}"},
            }
        ],
    },
    {"role": "user", "content": "Single text tool part next."},
    {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call_4",
                "type": "function",
                "function": {"name": "date", "arguments": "{}"},
            }
        ],
    },
    {
        "role": "tool",
        "tool_call_id": "call_4",
        "name": "date",
        "content": "x",
        "parts": [{"type": "text", "text": "just text"}],
    },
]

TOOLS = [
    DATE_TOOL,
    {"type": "function", "function": {"name": "bare"}},
    {"type": "retrieval", "function": {"name": "skipped"}},
]


def case(name: str, recording: str | None, **extra: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "name": name,
        "model": "router9:mock-model",
        "recording": recording,
        "messages": HELLO,
        "tools": [],
        "options": {},
        "refuse": False,
    }
    base.update(extra)
    return base


CASES: list[dict[str, Any]] = [
    case("text_hello", "openai_text_hello"),
    case("tool_call", "openai_tool_call_then_text", tools=[DATE_TOOL]),
    case("reasoning_usage", "providers/reasoning_then_text"),
    case("parallel_tool_calls", "providers/parallel_tool_calls", tools=[DATE_TOOL]),
    case("copilot_split_args", "providers/copilot_split_args"),
    case("no_done_no_finish", "providers/no_done_no_finish"),
    case("invalid_chunk", "providers/invalid_chunk"),
    case("error_400_context", "providers/error_400_context"),
    case("error_400_request", "providers/error_400_request"),
    case("error_401", "providers/error_401"),
    case("error_403_plain", "providers/error_403_plain"),
    case("error_404_detail", "providers/error_404_detail"),
    case("error_413", "providers/error_413"),
    case("error_422_message", "providers/error_422_message"),
    case("error_500_always", "providers/error_500_always"),
    case("error_503_then_text", "providers/error_503_then_text"),
    case("rate_limit_retry_after", "provider_error_429"),
    case("rate_limit_then_text", "providers/rate_limit_then_text"),
    case("rate_limit_quota", "providers/rate_limit_quota"),
    case("rate_limit_too_long", "providers/rate_limit_too_long"),
    case("rate_limit_backoff", "providers/rate_limit_backoff"),
    case("connect_refused", None, refuse=True),
    case(
        "router9_request_body",
        "openai_text_hello",
        messages=HISTORY,
        tools=TOOLS,
        options={
            "temperature": 0.2,
            "max_tokens": 512,
            "thinking_level": "xhigh",
            "prompt_cache_key": "session-1",
            "service_tier": " Flex ",
        },
    ),
    case(
        "router9_sampling_defaults",
        "openai_text_hello",
        model="router9:qwen3-coder",
        options={"top_p": 0.5, "thinking_level": "none", "service_tier": "auto"},
    ),
    case(
        "router9_flatten_glm",
        "openai_text_hello",
        model="router9:glm-5",
        messages=HISTORY,
        options={"thinking_level": "minimal"},
    ),
    case(
        "xiaomi_request_body",
        "openai_text_hello",
        model="xiaomi:mimo-mock",
        messages=HISTORY,
        tools=TOOLS,
        options={
            "temperature": 0.3,
            "max_tokens": 1000,
            "thinking_level": "max",
            "prompt_cache_key": "ignored",
            "service_tier": "flex",
        },
    ),
    case(
        "xiaomi_thinking_off",
        "openai_text_hello",
        model="xiaomi:mimo-mock",
        options={"thinking_level": "off"},
    ),
    case(
        "xiaomi_thinking_minimal",
        "providers/reasoning_then_text",
        model="xiaomi:mimo-mock",
        options={"thinking_level": "minimal"},
    ),
    case(
        "mistral_generic",
        "openai_text_hello",
        model="mistral:mock-model",
        options={"thinking_level": "low"},
    ),
    case(
        "perplexity_no_thinking",
        "openai_text_hello",
        model="perplexity:sonar",
        options={"thinking_level": "high"},
    ),
]

#: Which env vars point each provider at the mock.
PROVIDER_ENV = {
    "router9": ("ROUTER9_API_KEY", "ROUTER9_BASE_URL"),
    "xiaomi": ("XIAOMI_API_KEY", "XIAOMI_BASE_URL"),
    "mistral": ("MISTRAL_API_KEY", "MISTRAL_BASE_URL"),
    "perplexity": ("PERPLEXITY_API_KEY", "PERPLEXITY_BASE_URL"),
}
