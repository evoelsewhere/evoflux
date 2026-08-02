from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OpenAICompatibleProviderSpec:
    provider_id: str
    label: str
    env_var: str
    base_url: str
    base_url_env_var: str | None = None
    default_api_key: str = ""


OPENAI_COMPATIBLE_PROVIDER_SPECS: dict[str, OpenAICompatibleProviderSpec] = {
    "openrouter": OpenAICompatibleProviderSpec(
        provider_id="openrouter",
        label="OpenRouter",
        env_var="OPENROUTER_API_KEY",
        base_url="https://openrouter.ai/api/v1",
    ),
    "nvidia": OpenAICompatibleProviderSpec(
        provider_id="nvidia",
        label="NVIDIA",
        env_var="NVIDIA_API_KEY",
        base_url="https://integrate.api.nvidia.com/v1",
    ),
    "router9": OpenAICompatibleProviderSpec(
        provider_id="router9",
        label="9Router",
        env_var="ROUTER9_API_KEY",
        base_url="http://localhost:20128/v1",
        base_url_env_var="ROUTER9_BASE_URL",
    ),
    "cliproxy": OpenAICompatibleProviderSpec(
        provider_id="cliproxy",
        label="CLIProxyAPI",
        env_var="CLIPROXY_API_KEY",
        base_url="http://localhost:8317/v1",
        base_url_env_var="CLIPROXY_BASE_URL",
    ),
    "ollama": OpenAICompatibleProviderSpec(
        provider_id="ollama",
        label="Ollama",
        env_var="OLLAMA_API_KEY",
        base_url="http://localhost:11434/v1",
        base_url_env_var="OLLAMA_BASE_URL",
        default_api_key="ollama",
    ),
    "xai": OpenAICompatibleProviderSpec(
        provider_id="xai",
        label="xAI",
        env_var="XAI_API_KEY",
        base_url="https://api.x.ai/v1",
    ),
    "deepseek": OpenAICompatibleProviderSpec(
        provider_id="deepseek",
        label="DeepSeek",
        env_var="DEEPSEEK_API_KEY",
        base_url="https://api.deepseek.com/v1",
    ),
    "xiaomi": OpenAICompatibleProviderSpec(
        provider_id="xiaomi",
        label="Xiaomi MiMo",
        env_var="XIAOMI_API_KEY",
        base_url="https://api.xiaomi.com/v1",
        base_url_env_var="XIAOMI_BASE_URL",
    ),
    "kimi": OpenAICompatibleProviderSpec(
        provider_id="kimi",
        label="Kimi (Moonshot AI)",
        env_var="MOONSHOT_API_KEY",
        base_url="https://api.kimi.ai/v1",
        base_url_env_var="MOONSHOT_BASE_URL",
    ),
    "fci": OpenAICompatibleProviderSpec(
        provider_id="fci",
        label="FCI",
        env_var="FCI_API_KEY",
        base_url="https://mkp-api.fptcloud.com/v1",
        base_url_env_var="FCI_BASE_URL",
    ),
}
