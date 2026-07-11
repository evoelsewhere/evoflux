from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.config import settings

PROVIDER_MODEL_PLACEHOLDER = "__PROVIDER_MODEL__"


class TitleGenerationSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool = True
    model: str | None = None
    wait_timeout_seconds: float = 3.0


class DreamSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool = False
    model: str | None = None
    schedule: str = "0 2 * * *"

    @model_validator(mode="after")
    def _validate_model(self) -> "DreamSettings":
        if self.model and ":" not in self.model:
            raise ValueError("Dream model must be 'provider:model'.")
        return self


class MemoryVectorSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool = False
    backend: str = "disabled"
    embedding_model: str | None = None
    dim: int | None = None
    index_path: str | None = None


class CodeGraphSettings(BaseModel):
    """Runtime knobs for the code knowledge graph's file watcher.

    Search is lexical + structural only (FTS5 + the parsed symbol/edge
    graph) — no embedding/vector layer.
    """

    model_config = ConfigDict(extra="ignore")

    # Auto-reindex coding workspaces when their source files change on disk.
    watch_enabled: bool = True
    # Coalesce bursts of file events before reindexing (milliseconds).
    watch_debounce_ms: int = 1500
    # Extra delay after an agent run finishes before reindexing accumulated
    # changes. Allows final writes to settle so only one reindex fires.
    watch_resume_delay_ms: int = 5000


class CrossRepoSettings(BaseModel):
    """Cross-repo reference resolution for multi-repo CodingProjects.

    Tier A (static: Java FQN + manifest-identity matching) is always free and
    always runs. These settings only affect Tier B, which narrows candidates
    via FTS5 lexical search for whatever Tier A leaves unresolved.
    """

    model_config = ConfigDict(extra="ignore")

    enabled: bool = True
    candidate_k: int = 5
    # Safety valve for Tier B: even after the is_likely_external pre-filter,
    # a very large or freshly-linked project could have more unresolved rows
    # than are sane to run through FTS5 in one pass. The remainder is simply
    # picked up on the next resolve call.
    max_rows_per_run: int = 500


class ServerSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    host: str = "127.0.0.1"
    port: int = 4082
    access_key: str | None = None


class ProviderUiSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    visible_models: list[str] = Field(default_factory=list)


class MemoryExtractionSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    # Enable auto memory extraction after agent turns.
    enabled: bool = True
    # Minimum assistant messages in the session before extraction fires.
    min_assistant_messages: int = 3
    # Re-extract every N new assistant messages after the first extraction.
    every_n_messages: int = 10
    # Maximum characters of conversation to send to the extractor LLM.
    max_input_chars: int = 12000
    # Override the extraction model ('provider:model'). Null = use the chat model.
    model: str | None = None


class PromptSuggestionsSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    # Enable contextual follow-up suggestion chips after each response.
    enabled: bool = True
    # Maximum number of suggestions to generate (1–5).
    count: int = 3
    # Override the suggestions model ('provider:model'). Null = use the chat model.
    model: str | None = None


class LoopSettings(BaseModel):
    """Default configuration for the Loop Engine v2."""

    model_config = ConfigDict(extra="ignore")

    # Default max iterations when /loop starts
    default_max_iterations: int = 10
    # Enable prompt evolution by default
    default_evolve_prompt: bool = True
    # Default verifier command (null = no verifier)
    default_verify_command: str | None = None
    # Default token budget per loop (null = unlimited)
    default_max_total_tokens: int | None = None
    # No-progress threshold
    default_no_progress_threshold: int = 3
    # Max consecutive errors before stopping
    default_max_consecutive_errors: int = 3
    # Delay between iterations in seconds
    default_delay_between_iterations: float = 0.0


class RuntimeSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title_generation: TitleGenerationSettings = Field(
        default_factory=TitleGenerationSettings
    )
    dream: DreamSettings = Field(default_factory=DreamSettings)
    loop: LoopSettings = Field(default_factory=LoopSettings)
    memory_extraction: MemoryExtractionSettings = Field(
        default_factory=MemoryExtractionSettings
    )
    prompt_suggestions: PromptSuggestionsSettings = Field(
        default_factory=PromptSuggestionsSettings
    )
    memory_vector: MemoryVectorSettings = Field(default_factory=MemoryVectorSettings)
    server: ServerSettings = Field(default_factory=ServerSettings)
    providers: dict[str, ProviderUiSettings] = Field(default_factory=dict)
    code_graph: CodeGraphSettings = Field(default_factory=CodeGraphSettings)
    cross_repo: CrossRepoSettings = Field(default_factory=CrossRepoSettings)


def provider_visible_models(provider_id: str) -> list[str]:
    return (
        load_runtime_settings()
        .providers.get(provider_id, ProviderUiSettings())
        .visible_models
    )


def set_provider_visible_models(provider_id: str, models: list[str]) -> None:
    cfg = load_runtime_settings()
    cleaned = sorted({model.strip() for model in models if model.strip()})
    if cleaned:
        cfg.providers[provider_id] = ProviderUiSettings(visible_models=cleaned)
    else:
        cfg.providers.pop(provider_id, None)
    save_runtime_settings(cfg)


def runtime_settings_path() -> Path:
    return Path(settings.EVOFLUX_CONFIG_DIR) / "settings.yaml"


def load_runtime_settings(path: Path | None = None) -> RuntimeSettings:
    resolved = path or runtime_settings_path()
    if not resolved.exists():
        return RuntimeSettings()
    try:
        raw = yaml.safe_load(resolved.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"settings.yaml YAML parse error: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError("settings.yaml must contain a YAML mapping.")
    return RuntimeSettings.model_validate(raw)


def save_runtime_settings(cfg: RuntimeSettings, path: Path | None = None) -> Path:
    resolved = path or runtime_settings_path()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    data = cfg.model_dump(mode="json", exclude_none=True)
    resolved.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return resolved


def _seed_model_value(provider_model: str) -> str | None:
    provider_model = provider_model.strip()
    if not provider_model or provider_model == PROVIDER_MODEL_PLACEHOLDER:
        return None
    return provider_model


def ensure_runtime_settings(path: Path, *, provider_model: str) -> bool:
    if path.exists():
        return False
    model = _seed_model_value(provider_model)
    save_runtime_settings(
        RuntimeSettings(
            title_generation=TitleGenerationSettings(model=model),
            dream=DreamSettings(model=model),
        ),
        path,
    )
    return True
