"""Generate ``crates/evo-runtime/data/provider_catalog.json``.

The provider catalog holds *connection facts only*: which wire adapter,
endpoint, credential and headers each provider needs, and which models.dev
provider its models come from. It lists no models — models.dev is evo's model
database (``src/models_dev.rs``).

Connection facts are ported from EvoFlux (``app/agent/providers``):

- ``registry.py``  PROVIDER_REGISTRY / RECOMMENDED_PROVIDERS
- ``catalog.py``   _OVERRIDES (the descriptions a person wrote)
- models.dev ``api.json``  the long tail of OpenAI-compatible providers

Usage (EvoFlux's environment, so its modules import):

    curl -o api.json https://models.dev/api.json
    cd <evoflux> && uv run python <evo-harness>/crates/evo-runtime/scripts/gen_provider_catalog.py \\
        api.json <evo-harness>/crates/evo-runtime/data/provider_catalog.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from app.agent.providers import catalog as ef_catalog
from app.agent.providers import registry as ef

COMPLETIONS = "openai-completions"
RESPONSES = "openai-responses"
ANTHROPIC = "anthropic-messages"
BEDROCK = "bedrock-converse-stream"
GOOGLE = "google-generative-ai"

#: EvoFlux transport -> evo wire API (None: evo has no adapter for it).
TRANSPORTS = {
    ef.Transport.OPENAI_COMPLETIONS: COMPLETIONS,
    ef.Transport.OPENAI_RESPONSES: RESPONSES,
    ef.Transport.ANTHROPIC: ANTHROPIC,
    ef.Transport.GOOGLE_GENAI: GOOGLE,
    ef.Transport.GOOGLE_VERTEX: GOOGLE,
    ef.Transport.BEDROCK: BEDROCK,
    ef.Transport.AZURE: COMPLETIONS,
}

#: models.dev adapter name -> evo wire API, for providers in the long tail.
NPM = {
    "@ai-sdk/openai-compatible": COMPLETIONS,
    "@ai-sdk/openai": RESPONSES,
    "@ai-sdk/anthropic": ANTHROPIC,
    "@ai-sdk/google": GOOGLE,
}

#: Gemini's own API (evo-ai ``providers/google.rs``): thought signatures and
#: ``thinkingConfig`` exist only there, not on its OpenAI-compatible shim.
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"

#: Thinking dialect per vendor (EvoFlux ``thinking.py`` PROVIDER_DIALECTS and
#: the kimi/qwencloud handlers), matched on the provider id or its models.dev
#: id prefix so the vendors' plan rows (token plans, coding plans, CN hosts)
#: speak the same dialect as the main row.
DIALECTS = [
    ("deepseek", "deepseek"),
    ("xiaomi", "budget"),
    ("zai", "glm"),
    ("zhipu", "glm"),
    ("kimi", "kimi"),
    ("moonshot", "kimi"),
    ("qwencloud", "qwen"),
    ("alibaba", "qwen"),
]


def dialect_compat(provider_id: str) -> dict:
    for prefix, dialect in DIALECTS:
        if provider_id.startswith(prefix):
            # These endpoints all want earlier reasoning sent back as
            # ``reasoning_content``.
            return {"thinkingFormat": dialect, "requiresReasoningContent": True}
    return {}


#: QwenCloud families documented with ``preserve_thinking``
#: (qwencloud/qwencloud.py ``_supports_preserved_thinking``).
QWEN_PRESERVE_THINKING = [
    "qwen3.8-max", "qwen3.8-flash", "qwen3.7-max", "qwen3.7-plus", "qwen3.7-flash",
    "qwen3.6-max", "qwen3.6-plus", "qwen3.6-flash",
]

#: Chat Completions endpoints that take ``max_tokens`` and reject (or do not
#: document) ``max_completion_tokens`` — EvoFlux sets
#: ``uses_max_completion_tokens = False`` for each of these.
MAX_TOKENS_FIELD = {"deepseek", "opencode", "opencode-go", "stepfun", "qwencloud"}

#: EvoFlux providers evo deliberately does not offer.
EXCLUDED = {"fci"}

#: QwenCloud families documented with the newer combined limit
#: (qwencloud/qwencloud.py ``_uses_max_completion_tokens``).
QWEN_MAX_COMPLETION_TOKENS = [
    "qwen3.8-max", "qwen3.8-flash", "qwen3.7-max", "qwen3.7-plus", "qwen3.7-flash",
    "qwen3.6-plus", "qwen3.6-flash", "qwen3.5-plus", "qwen3.5-flash",
]


def key_aliases(names, primary):
    """Environment names that hold a credential, never other settings.

    models.dev lists every variable a provider reads (``AWS_REGION``, a
    resource name, a project id) beside its key. Only key- and token-shaped
    names may stand in for the key, or a region would be sent as a bearer.
    """
    return [n for n in names if n and n != primary and (n.endswith("_API_KEY") or n.endswith("_TOKEN"))]


ATTRIBUTION = {"HTTP-Referer": "https://github.com/evoelsewhere/evo-harness", "X-Title": "evo"}

#: Provider-specific behaviour EvoFlux implements in code, stated as data.
NATIVE = {
    # Xiaomi MiMo (xiaomi/oauth.py): signing in to the MiMo platform mints an
    # API key (and, for token plans, the account's base URL).
    "xiaomi": {"keyLogin": "xiaomi"},
    # Kimi Code (kimi/kimi.py): models.dev renamed its plan rows.
    "kimi": {"baseUrl": "https://api.kimi.com/coding/v1", "modelsDevId": "kimi-code-plan-global"},
    # OpenAI's Responses endpoint features (evo-ai's former built-in model).
    "openai": {
        "responsesCompat": {
            "supportsDeveloperRole": True,
            "supportsLongCacheRetention": True,
            "supportsStrictMode": True,
            "supportsOpenAIGrammarTools": True,
        },
    },
    # ChatGPT subscription over the Codex Responses endpoint (codex/codex.py):
    # no max_output_tokens, encrypted reasoning replayed with store=false.
    # models.dev has no Codex provider; OpenAI's GPT-5 family is what the
    # endpoint serves, and its live /models list refines that after sign-in.
    "codex": {
        "api": RESPONSES,
        "baseUrl": "https://chatgpt.com/backend-api/codex",
        "headers": {"originator": "evo"},
        # The ChatGPT sign-in is the only credential; a platform
        # OPENAI_API_KEY is not valid on this endpoint.
        "apiKeyEnvAliases": [],
        "responsesCompat": {"supportsMaxOutputTokens": False, "supportsDeveloperRole": True},
        "samplingParams": {"include": ["reasoning.encrypted_content"]},
        "login": "codex",
        "modelsDevId": "openai",
        "modelPrefixes": ["gpt-5", "codex-"],
    },
    # GitHub Copilot (copilot/copilot.py): the GitHub OAuth token is the
    # bearer; each model goes to /chat/completions or /responses as its live
    # `supported_endpoints` say.
    "copilot": {
        "api": COMPLETIONS,
        "baseUrl": "https://api.githubcopilot.com",
        # `x-initiator` and `Copilot-Vision-Request` are set per request
        # (evo-ai provider.rs `apply_copilot_request_headers`).
        "headers": {"Openai-Intent": "conversation-edits", "x-initiator": "user"},
        "login": "copilot",
        # A plain GITHUB_TOKEN is not a Copilot credential.
        "apiKeyEnvAliases": [],
    },
    # Azure AI Foundry (foundry/foundry.py): one OpenAI v1 surface per
    # resource; Claude deployments answer only Anthropic Messages. Models are
    # the user's deployments, so none are listed until discovered or added.
    "foundry": {
        "api": COMPLETIONS,
        "baseUrl": "",
        "endpoint": "foundry",
        "routes": [{"prefix": "claude", "api": ANTHROPIC, "base": "{origin}/anthropic"}],
        "requiresModelList": True,
    },
    # Vertex AI Gemini (vertexai/vertexai.py): the Gemini API under
    # `…/publishers/google`, a Google Cloud API key, express mode or a
    # project/location. Claude on Vertex needs Google OAuth; only Gemini here.
    "vertexai": {
        "api": GOOGLE,
        "description": "Gemini on Google Cloud — a Cloud API key, express mode or your project and location.",
        "baseUrl": "https://aiplatform.googleapis.com/v1/publishers/google",
        "endpoint": "vertex",
        "modelPrefixes": ["gemini"],
    },
    # Amazon Bedrock Converse stream (bedrock/bedrock.py), Bedrock API key or
    # IAM access keys.
    "bedrock": {
        "api": BEDROCK,
        "description": "Claude, Nova, Llama and more on AWS — sign in with a Bedrock API key or IAM access keys.",
        "baseUrl": "https://bedrock-runtime.us-east-1.amazonaws.com",
        "endpoint": "bedrock",
    },
}

UNSUPPORTED_REASON = {
    "oauth": "Subscription sign-in is not available in evo yet.",
    "cloud": "Cloud credentials are not available in evo yet.",
}


def strip_v1(url: str) -> str:
    trimmed = url.rstrip("/")
    return trimmed[: -len("/v1")] if trimmed.endswith("/v1") else trimmed


def headers_for(config) -> dict[str, str]:
    headers = {**config.attribution_headers, **config.extra_headers}
    for name in list(headers):
        lower = name.lower()
        if lower == "http-referer":
            headers[name] = ATTRIBUTION["HTTP-Referer"]
        elif lower == "x-title":
            headers[name] = ATTRIBUTION["X-Title"]
        elif lower == "x-source":
            headers[name] = "evo"
    if config.id in ("opencode", "opencode-go"):
        headers["x-opencode-client"] = "evo"
    return headers


def dev_base(dev: dict, provider_id: str) -> str:
    api = (dev.get(provider_id) or {}).get("api")
    return api.strip() if isinstance(api, str) and "${" not in api else ""


def curated(dev: dict) -> list[dict]:
    rows = []
    entries = {e["id"]: e for e in ef_catalog.builtin_providers()}
    for provider_id, config in ef.PROVIDER_REGISTRY.items():
        if provider_id in EXCLUDED:
            continue
        entry = entries[provider_id]
        dev_id = config.models_dev_provider_id
        api = TRANSPORTS.get(config.transport)
        # Never the environment: the catalog must not bake in a base-URL
        # override from the machine that generated it.
        base = config.base_url or dev_base(dev, dev_id)
        if provider_id == "googlegenai":
            api, base = GOOGLE, GEMINI_BASE
        if api == ANTHROPIC:
            base = strip_v1(base)
        dev_env = (dev.get(dev_id) or {}).get("env") or []
        row = {
            "id": provider_id,
            "label": entry["label"],
            "description": entry.get("description") or "",
            "auth": config.auth,
            "api": api or COMPLETIONS,
            "baseUrl": base,
            "apiKeyEnv": config.env_var or None,
            "apiKeyEnvAliases": key_aliases(dev_env, config.env_var),
            "baseUrlEnv": config.base_url_env_var,
            "docsUrl": entry.get("docs_url") or "",
            "modelsDocUrl": (dev.get(dev_id) or {}).get("doc") or "",
            "headers": headers_for(config),
            "routes": [
                # A null api: a family served over a protocol evo cannot speak.
                {"prefix": prefix, "api": TRANSPORTS.get(transport)}
                for prefix, transport in config.model_transports
            ],
            "supported": api is not None and config.auth not in ("oauth", "cloud"),
            "source": "curated",
            "modelsDevId": dev_id if dev_id in dev else None,
        }
        if config.default_api_key:
            row["defaultApiKey"] = config.default_api_key
        if config.auth == "local":
            row["anonymous"] = True
        if dialect_compat(provider_id):
            row["compat"] = dialect_compat(provider_id)
        if provider_id in ("opencode", "opencode-go"):
            row["sessionHeaders"] = ["x-opencode-session", "x-opencode-session-id"]
        if provider_id == "opencode-go":
            # Zen and Go are separate subscriptions with separate keys.
            row["apiKeyEnvAliases"] = []
        if provider_id in MAX_TOKENS_FIELD:
            row["compat"] = {**row.get("compat", {}), "maxTokensField": "max_tokens"}
        if provider_id == "qwencloud":
            row["maxCompletionTokensPrefixes"] = QWEN_MAX_COMPLETION_TOKENS
            row["preserveThinkingPrefixes"] = QWEN_PRESERVE_THINKING
        native = NATIVE.get(provider_id)
        if native is not None:
            row.update(native)
            if provider_id in ("codex", "copilot", "foundry", "bedrock", "vertexai"):
                row["supported"] = True
        if not row["supported"]:
            row["unsupportedReason"] = UNSUPPORTED_REASON.get(
                config.auth, "This provider's protocol is not available in evo yet."
            )
        rows.append(row)
    return rows


def long_tail(dev: dict, claimed: set[str]) -> list[dict]:
    rows = []
    for provider_id, envelope in sorted(dev.items()):
        if provider_id in claimed:
            continue
        api = NPM.get(envelope.get("npm") or "@ai-sdk/openai-compatible")
        base = dev_base(dev, provider_id)
        env = [name for name in envelope.get("env") or [] if isinstance(name, str) and name]
        if api is None or not base or not env:
            continue  # nothing evo can connect to from a URL and a key
        if api == ANTHROPIC:
            base = strip_v1(base)
        host = base.split("//", 1)[-1].split("/", 1)[0]
        rows.append(
            {
                "id": provider_id,
                "label": envelope.get("name") or provider_id,
                "description": f"{host} — {api.replace('-', ' ')} API, from models.dev.",
                "auth": "api_key",
                "api": api,
                "baseUrl": base,
                "apiKeyEnv": env[0],
                "apiKeyEnvAliases": key_aliases(env[1:], env[0]),
                "baseUrlEnv": provider_id.upper().replace("-", "_").replace(".", "_") + "_BASE_URL",
                "docsUrl": envelope.get("doc") or "",
                "modelsDocUrl": envelope.get("doc") or "",
                "headers": {},
                "routes": [],
                "supported": True,
                "source": "catalog",
                "modelsDevId": provider_id,
            }
        )
        if api == COMPLETIONS and dialect_compat(provider_id):
            rows[-1]["compat"] = dialect_compat(provider_id)
    return rows


def main() -> None:
    dev = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    out = Path(sys.argv[2])
    providers = curated(dev)
    claimed = {p["id"] for p in providers} | {p["modelsDevId"] for p in providers if p.get("modelsDevId")}
    providers += long_tail(dev, claimed)
    document = {
        "version": 2,
        "source": "evoflux app/agent/providers (registry.py, catalog.py) + models.dev provider envelopes",
        "recommended": list(ef.RECOMMENDED_PROVIDERS),
        "providers": providers,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(document, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"{len(providers)} providers -> {out} ({out.stat().st_size // 1024} KiB)")


if __name__ == "__main__":
    main()
