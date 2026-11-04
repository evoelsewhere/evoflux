//! Generated from `_OVERRIDES` in `app/agent/providers/catalog.py`
//! by `tests/dump_catalog.py --tables`. Do not edit by hand.

use crate::catalog::{CredentialRow, Kind, Override};

pub(crate) const OVERRIDES: &[(&str, Override)] = &[
    ("anthropic", Override { description: Some("Claude API via Anthropic Messages."), fallback_models: Some(&["claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5"]), ..Override::EMPTY }),
    ("bedrock", Override { credentials: Some(&[CredentialRow { name: "AWS_BEDROCK_REGION", label: "AWS Bedrock Region", secret: false, required: false, placeholder: "us-east-1" }, CredentialRow { name: "AWS_BEDROCK_PROFILE", label: "AWS Profile", secret: false, required: false, placeholder: "default" }, CredentialRow { name: "AWS_ACCESS_KEY_ID", label: "AWS Access Key ID", secret: false, required: false, placeholder: "AKIA..." }, CredentialRow { name: "AWS_SECRET_ACCESS_KEY", label: "AWS Secret Access Key", secret: true, required: false, placeholder: "••••••••" }]), description: Some("AWS Bedrock using an AWS profile or access keys. Region defaults to us-east-1."), fallback_models: Some(&["bedrock:anthropic.claude-sonnet-4-6", "bedrock:amazon.nova-pro-v1:0", "bedrock:amazon.nova-lite-v1:0"]), ..Override::EMPTY }),
    ("cerebras", Override { description: Some("Cerebras Inference — ultra-fast Llama inference."), ..Override::EMPTY }),
    ("cliproxy", Override { description: Some("Local proxy for Gemini CLI / Codex / Claude Code OAuth."), kind: Some(Kind::ApiKey), ..Override::EMPTY }),
    ("codex", Override { description: Some("Use your ChatGPT subscription via Codex OAuth."), live_model_metadata: Some(true), metadata_source_exclude: Some(&["thinking"]), metadata_source_provider: Some("openai"), oauth_command: Some("evoflux auth codex"), ..Override::EMPTY }),
    ("cohere", Override { description: Some("Cohere's Command A and Embed models."), ..Override::EMPTY }),
    ("copilot", Override { description: Some("Use your Copilot subscription — OAuth, no API key."), oauth_command: Some("evoflux auth copilot"), ..Override::EMPTY }),
    ("deepseek", Override { description: Some("DeepSeek's direct API."), ..Override::EMPTY }),
    ("fci", Override { description: Some("FPT's OpenAI-compatible inference gateway — Qwen, GLM, Gemma, gpt-oss, DeepSeek, and Llama models."), ..Override::EMPTY }),
    ("fireworks", Override { description: Some("Fireworks AI — fast inference for open models."), ..Override::EMPTY }),
    ("foundry", Override { credentials: Some(&[CredentialRow { name: "FOUNDRY_RESOURCE_NAME", label: "Resource name or endpoint URL", secret: false, required: true, placeholder: "my-resource or https://my-resource.services.ai.azure.com" }, CredentialRow { name: "FOUNDRY_API_KEY", label: "API key", secret: true, required: true, placeholder: "••••••••" }]), description: Some("Azure AI Foundry — OpenAI, DeepSeek, Grok, Claude and more on your Azure resource."), ..Override::EMPTY }),
    ("googlegenai", Override { description: Some("Google AI Studio — free tier available."), fallback_models: Some(&["gemini-3.1-flash-image-preview", "gemini-2.5-flash-image-preview", "veo-3.1-generate-preview", "veo-3.1-fast-generate-preview"]), ..Override::EMPTY }),
    ("groq", Override { description: Some("Groq's ultra-fast inference — Llama, Mixtral, Gemma, etc."), ..Override::EMPTY }),
    ("kimi", Override { description: Some("Kimi's subscription coding API — K3 and K2.7 Code with tool use and vision."), ..Override::EMPTY }),
    ("minimax", Override { description: Some("MiniMax M2 models — long context, multilingual."), ..Override::EMPTY }),
    ("mistral", Override { description: Some("Mistral's La Plateforme — Mistral, Mixtral, Codestral."), ..Override::EMPTY }),
    ("nvidia", Override { description: Some("NVIDIA-hosted open models."), ..Override::EMPTY }),
    ("ollama", Override { auto_connect: Some(false), description: Some("Run models locally with the Ollama daemon."), ..Override::EMPTY }),
    ("opencode", Override { description: Some("OpenCode Zen — pay-as-you-go gateway to Claude, GPT, Gemini and open coding models, plus free models."), ..Override::EMPTY }),
    ("opencode-go", Override { description: Some("OpenCode Go — low-cost subscription for open coding models such as Kimi, GLM, DeepSeek and MiniMax."), ..Override::EMPTY }),
    ("openai", Override { description: Some("GPT-5.x, GPT-4.1, etc."), ..Override::EMPTY }),
    ("openrouter", Override { description: Some("Many models, free tiers available."), ..Override::EMPTY }),
    ("perplexity", Override { description: Some("Perplexity Sonar models — search-augmented generation."), ..Override::EMPTY }),
    ("qwencloud", Override { description: Some("Qwen3.8 and other QwenCloud models via OpenAI-compatible APIs."), fallback_models: Some(&["qwen3.8-max", "qwen3.8-flash", "qwen3.7-plus"]), model_registry_aliases: Some(&[("qwen3.8-max-preview", "qwencloud:qwen3.8-max")]), ..Override::EMPTY }),
    ("router9", Override { description: Some("Local proxy aggregating 40+ providers."), kind: Some(Kind::ApiKey), ..Override::EMPTY }),
    ("sambanova", Override { description: Some("SambaNova Cloud — fast Llama and Mistral inference."), ..Override::EMPTY }),
    ("stepfun", Override { description: Some("StepFun's Step models — reasoning, vision and video input, tool calling. Point the base URL at the China host or a Step Plan endpoint if that is where your key lives."), ..Override::EMPTY }),
    ("together", Override { description: Some("Together AI — open models, fine-tuning, serverless inference."), ..Override::EMPTY }),
    ("vertexai", Override { description: Some("Google Cloud's enterprise-grade Gemini."), fallback_models: Some(&["gemini-3.5-flash", "gemini-3.1-pro-preview", "gemini-3-flash-preview", "gemini-3.1-flash-lite-preview", "gemini-2.5-pro", "imagen-4"]), ..Override::EMPTY }),
    ("xai", Override { description: Some("xAI's Grok family."), ..Override::EMPTY }),
    ("xiaomi", Override { description: Some("Xiaomi's MiMo model API — vision, reasoning, and tool calling."), ..Override::EMPTY }),
    ("zai", Override { description: Some("Z.AI's GLM-5 family."), ..Override::EMPTY }),
];
