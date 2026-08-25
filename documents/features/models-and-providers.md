# Models and providers

EvoFlux uses a provider-neutral streaming schema while preserving each model's
actual capabilities. Model availability, model metadata and adapter support are
separate facts and are intersected before the UI or runtime enables a control.

## Built-in provider catalogue

| ID | Integration | Authentication |
|---|---|---|
| `anthropic` | Anthropic Messages | API key |
| `googlegenai` | Google Gemini | API key |
| `openai` | OpenAI Responses/Chat Completions | API key |
| `openrouter` | OpenRouter | API key |
| `zai` | Z.AI | API key |
| `nvidia` | NVIDIA OpenAI-compatible API | API key |
| `xai` | xAI | API key |
| `deepseek` | DeepSeek | API key |
| `xiaomi` | Xiaomi MiMo | API key |
| `fci` | FPT Cloud inference gateway | API key |
| `kimi` | Kimi Code | API key |
| `router9` | Router9 | API key/local endpoint policy |
| `cliproxy` | CLIProxy OpenAI-compatible endpoint | local/proxy |
| `ollama` | Ollama | local daemon |
| `copilot` | GitHub Copilot | device-flow OAuth |
| `codex` | OpenAI Codex/ChatGPT subscription | OAuth |
| `bedrock` | Amazon Bedrock Converse | AWS credential chain/profile |
| `foundry` | Microsoft Foundry | resource key and resource name |
| `vertexai` | Google Vertex AI | Google cloud credentials/project/location |

Portable provider plugins may extend the visible catalogue through the provider
plugin registry, but built-in factory IDs remain the fixed nineteen above.

## Model identity and selection

Runtime model IDs use `provider:model`. A default model can be set during
initialization, then overridden per agent or per session. Reasoning level and
other controls are validated against the effective capability profile before a
turn starts.

Settings can discover live models, test credentials, retain a visible-model
subset and show provider usage where an adapter supports it. Credentials are
stored in the config `.env` or the provider's OAuth/cloud store; API responses
mask secrets.

## Capability resolution

The resolver combines:

1. live provider catalogue facts;
2. bundled registry and refreshed `models.dev` metadata for missing fields;
3. local `model_registry.yaml` corrections;
4. the actual features implemented by the selected adapter.

Unknown capabilities default off. Name/prefix guessing is not sufficient to
enable vision, tools or reasoning. `Default` means omit an override; `Off` is
shown only when the provider has an explicit off wire value.

See [Provider model capability flow](../architecture/model-capability-flow.md).

## Generic runtime contract

Adapters translate generic system/human/assistant/tool messages, content parts,
tool schemas, reasoning settings, usage and streamed chunks to provider-specific
wire formats. Provider exceptions are normalized for retry/fallback and safe
display. Provider payload shapes do not leak into the team/session API.

Model calls can include bounded multimodal content only when both the model and
adapter advertise support. Tool call IDs/results are normalized across APIs.

## EASD role guidance for GPT-5.6 family

When the Codex OAuth catalogue exposes the GPT-5.6 family, EASD benchmarks and
high-assurance runs prefer:

| Role | Model | Typical reasoning |
|---|---|---|
| Lead/convergence owner | `codex:gpt-5.6-sol` | high/xhigh |
| Architect or independent verifier | `codex:gpt-5.6-sol` | high |
| Builder mission | `codex:gpt-5.6-terra` | medium/high |
| Narrow repeatable exploration | `codex:gpt-5.6-luna` or Terra | medium |

This is a role policy, not hard-coded routing. Provider availability, visible
models, per-agent configuration, capability validation, user overrides, and
budget remain authoritative. Official OpenAI documentation recommends GPT-5.6
for demanding multi-step agents, Terra for efficient read-heavy workers, and
Luna for narrow repeatable work.

## Source and tests

Primary code: `app/agent/providers/catalog.py`, `factory.py`, `capabilities.py`,
`model_registry.py`, `model_discovery.py`, provider subpackages, Settings routes
and model-picker components.

Every provider has adapter/factory tests; shared suites cover streaming,
capability resolution, discovery, tool content, unconfigured providers and
model metadata.
