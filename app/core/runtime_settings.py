from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.config import settings

PROVIDER_MODEL_PLACEHOLDER = "__PROVIDER_MODEL__"


class TitleGenerationSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool = True
    model: str | None = None


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


class CodeQueryPolicySettings(BaseModel):
    """Validated retrieval policy shared by model tools and query services."""

    model_config = ConfigDict(extra="ignore")

    min_budget_tokens: int = Field(default=500, ge=100, le=12_000)
    tool_min_budget_tokens: int = Field(default=2_500, ge=500, le=12_000)
    max_budget_tokens: int = Field(default=12_000, ge=500, le=64_000)
    tokens_per_file: int = Field(default=900, ge=100, le=4_000)
    candidates_per_file: int = Field(default=3, ge=1, le=10)
    min_candidates: int = Field(default=20, ge=1, le=100)
    max_candidates: int = Field(default=30, ge=1, le=100)
    min_weighted_coverage: float = Field(default=0.5, ge=0.0, le=1.0)
    sparse_query_max_terms: int = Field(default=3, ge=1, le=32)
    sparse_query_min_hits: int = Field(default=1, ge=1, le=32)
    corroborating_min_hits: int = Field(default=3, ge=1, le=32)
    corroborating_min_coverage: float = Field(default=0.1, ge=0.0, le=1.0)
    graph_relevance_ratio: float = Field(default=0.3, ge=0.0, le=1.0)
    lexical_fallback_score: float = Field(default=20.0, ge=0.0)
    max_structural_per_file: int = Field(default=12, ge=1, le=100)
    max_ordinary_per_structural_file: int = Field(default=2, ge=0, le=20)
    max_ordinary_without_structural: int = Field(default=1, ge=0, le=20)
    max_required_structural: int = Field(default=8, ge=1, le=50)
    max_required_spines_per_file: int = Field(default=2, ge=1, le=20)
    max_trace_hops: int = Field(default=3, ge=1, le=12)
    max_shortest_path_hops: int = Field(default=6, ge=1, le=30)
    max_trace_callees: int = Field(default=12, ge=1, le=100)
    max_named_roots: int = Field(default=5, ge=1, le=30)
    max_neighbors_per_root: int = Field(default=4, ge=1, le=30)
    max_promoted_stages: int = Field(default=8, ge=1, le=50)
    anchor_scan_min: int = Field(default=120, ge=1, le=5_000)
    anchor_scan_multiplier: int = Field(default=12, ge=1, le=100)
    min_shared_path_segments: int = Field(default=2, ge=0, le=20)
    file_relevance_ratio: float = Field(default=0.1, ge=0.0, le=1.0)
    max_candidate_files: int = Field(default=12, ge=1, le=50)
    root_role_weight: float = Field(default=3.0, ge=0.0)
    spine_role_weight: float = Field(default=2.0, ge=0.0)
    neighbor_role_weight: float = Field(default=1.1, ge=0.0)
    match_role_weight: float = Field(default=0.8, ge=0.0)
    max_symbol_lines: int = Field(default=180, ge=1, le=2_000)
    max_file_lines: int = Field(default=36, ge=1, le=500)
    min_snippet_lines: int = Field(default=12, ge=1, le=200)
    estimated_chars_per_line: int = Field(default=55, ge=10, le=500)
    estimated_chars_per_token: int = Field(default=4, ge=1, le=16)
    min_output_chars: int = Field(default=800, ge=0, le=20_000)
    min_file_allocation_cap_chars: int = Field(default=1_000, ge=0, le=20_000)
    output_stop_reserve_chars: int = Field(default=250, ge=0, le=10_000)
    merged_output_stop_reserve_chars: int = Field(default=180, ge=0, le=10_000)
    candidate_metadata_base_chars: int = Field(default=120, ge=0, le=10_000)
    lexical_context_before_lines: int = Field(default=2, ge=0, le=100)
    lexical_context_after_lines: int = Field(default=3, ge=0, le=100)
    max_cross_repo_edges: int = Field(default=50, ge=1, le=1_000)
    file_match_bonus: float = Field(default=36.0, ge=0.0)
    symbol_match_bonus: float = Field(default=24.0, ge=0.0)
    qualified_match_bonus: float = Field(default=48.0, ge=0.0)
    weak_identifier_chars: int = Field(default=3, ge=1, le=64)
    strong_identifier_chars: int = Field(default=6, ge=1, le=128)
    search_overfetch_multiplier: int = Field(default=5, ge=1, le=50)
    search_overfetch_min: int = Field(default=50, ge=1, le=1_000)
    search_overfetch_max: int = Field(default=500, ge=1, le=10_000)
    max_expanded_query_terms: int = Field(default=24, ge=1, le=128)
    lexical_output_min_lines: int = Field(default=60, ge=1, le=10_000)
    lexical_output_multiplier: int = Field(default=12, ge=1, le=100)
    lsp_max_locations: int = Field(default=20, ge=1, le=1_000)
    fallback_root_count: int = Field(default=2, ge=1, le=30)
    fallback_required_matches: int = Field(default=3, ge=1, le=30)
    max_enriched_candidates: int = Field(default=5, ge=1, le=50)
    max_relationships_per_candidate: int = Field(default=12, ge=1, le=100)
    max_relationships_per_kind: int = Field(default=6, ge=1, le=100)
    score_exact_name: float = Field(default=120.0, ge=0.0)
    score_exact_qualified_name: float = Field(default=115.0, ge=0.0)
    score_qualified_suffix: float = Field(default=100.0, ge=0.0)
    score_name_prefix: float = Field(default=80.0, ge=0.0)
    score_name_fragment: float = Field(default=65.0, ge=0.0)
    score_identifier_hit: float = Field(default=8.0, ge=0.0)
    score_identifier_cap: float = Field(default=35.0, ge=0.0)
    score_path_hit: float = Field(default=4.0, ge=0.0)
    score_path_cap: float = Field(default=18.0, ge=0.0)
    score_signature_hit: float = Field(default=3.0, ge=0.0)
    score_signature_cap: float = Field(default=12.0, ge=0.0)
    score_doc_hit: float = Field(default=2.0, ge=0.0)
    score_doc_cap: float = Field(default=8.0, ge=0.0)
    score_requested_kind: float = Field(default=12.0, ge=0.0)
    score_requested_language: float = Field(default=8.0, ge=0.0)
    score_requested_path: float = Field(default=15.0, ge=0.0)
    score_file_penalty: float = Field(default=5.0, ge=0.0)
    lexical_score_base: float = Field(default=20.0, ge=0.0)
    lexical_score_scale: float = Field(default=0.4, ge=0.0)
    overlay_score_base: float = Field(default=70.0, ge=0.0)
    overlay_relationship_score: float = Field(default=102.0, ge=0.0)
    lsp_score: float = Field(default=110.0, ge=0.0)
    graph_confidence_base: float = Field(default=0.5, ge=0.0, le=1.0)
    graph_confidence_rank_weight: float = Field(default=0.25, ge=0.0, le=1.0)
    graph_confidence_coverage_weight: float = Field(default=0.2, ge=0.0, le=1.0)
    graph_confidence_cap: float = Field(default=0.96, ge=0.0, le=1.0)
    overlay_confidence_base: float = Field(default=0.5, ge=0.0, le=1.0)
    overlay_confidence_coverage_weight: float = Field(default=0.45, ge=0.0, le=1.0)
    overlay_confidence_cap: float = Field(default=0.95, ge=0.0, le=1.0)
    overlay_relationship_confidence: float = Field(default=0.86, ge=0.0, le=1.0)
    lsp_confidence: float = Field(default=0.92, ge=0.0, le=1.0)
    lexical_confidence_base: float = Field(default=0.5, ge=0.0, le=1.0)
    lexical_confidence_divisor: float = Field(default=400.0, gt=0.0)
    lexical_confidence_cap: float = Field(default=0.85, ge=0.0, le=1.0)
    anchor_score_base: float = Field(default=68.0, ge=0.0)
    anchor_confidence_base: float = Field(default=0.68, ge=0.0, le=1.0)
    anchor_confidence_coverage_weight: float = Field(default=0.3, ge=0.0, le=1.0)
    anchor_confidence_cap: float = Field(default=0.9, ge=0.0, le=1.0)
    graph_neighbor_confidence: float = Field(default=0.9, ge=0.0, le=1.0)
    partial_confidence_cap: float = Field(default=0.78, ge=0.0, le=1.0)
    cross_repo_primary_bonus: float = Field(default=3.0, ge=0.0)
    inbound_score_factor: float = Field(default=0.75, ge=0.0)
    inbound_score_floor: float = Field(default=30.0, ge=0.0)
    inbound_score_cap: float = Field(default=68.0, ge=0.0)
    direct_score_factor: float = Field(default=0.9, ge=0.0)
    direct_score_floor: float = Field(default=48.0, ge=0.0)
    direct_score_cap: float = Field(default=110.0, ge=0.0)
    neighbor_score_factor: float = Field(default=0.82, ge=0.0)
    neighbor_score_floor: float = Field(default=32.0, ge=0.0)
    neighbor_score_cap: float = Field(default=72.0, ge=0.0)
    trace_score_factor: float = Field(default=0.88, ge=0.0)
    trace_score_floor: float = Field(default=86.0, ge=0.0)
    shortest_path_score: float = Field(default=115.0, ge=0.0)

    @model_validator(mode="after")
    def _validate_bounds(self) -> "CodeQueryPolicySettings":
        if self.min_budget_tokens > self.max_budget_tokens:
            raise ValueError("min_budget_tokens cannot exceed max_budget_tokens")
        if self.tool_min_budget_tokens > self.max_budget_tokens:
            raise ValueError("tool_min_budget_tokens cannot exceed max_budget_tokens")
        if self.min_candidates > self.max_candidates:
            raise ValueError("min_candidates cannot exceed max_candidates")
        if self.weak_identifier_chars > self.strong_identifier_chars:
            raise ValueError(
                "weak_identifier_chars cannot exceed strong_identifier_chars"
            )
        if self.search_overfetch_min > self.search_overfetch_max:
            raise ValueError("search_overfetch_min cannot exceed search_overfetch_max")
        for prefix in ("inbound", "direct", "neighbor"):
            if getattr(self, f"{prefix}_score_floor") > getattr(
                self, f"{prefix}_score_cap"
            ):
                raise ValueError(
                    f"{prefix}_score_floor cannot exceed {prefix}_score_cap"
                )
        return self


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
    # Build the index automatically the first time a never-indexed workspace
    # is opened in a coding session (background job; UI shows progress).
    auto_index_enabled: bool = True


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


class GitSettings(BaseModel):
    """Operational and safety defaults for local/remote Git commands."""

    model_config = ConfigDict(extra="ignore")

    network_timeout_seconds: float = Field(default=120.0, ge=10.0, le=1800.0)
    max_diff_bytes: int = Field(default=2_000_000, ge=64_000, le=50_000_000)
    default_pull_strategy: Literal["ff_only", "merge", "rebase"] = "ff_only"
    prune_on_fetch: bool = True
    allow_force_push: bool = False


class CodeReviewSettings(BaseModel):
    """Provider-neutral PR/MR API reliability and mutation guardrails."""

    model_config = ConfigDict(extra="ignore")

    request_timeout_seconds: float = Field(default=20.0, ge=2.0, le=300.0)
    retry_attempts: int = Field(default=2, ge=0, le=5)
    retry_backoff_seconds: float = Field(default=0.5, ge=0.0, le=10.0)
    max_concurrent_repositories: int = Field(default=4, ge=1, le=32)
    max_pages_per_repository: int = Field(default=5, ge=1, le=20)
    allow_mutations: bool = True
    allow_insecure_connections: bool = False
    require_successful_checks_before_merge: bool = False


class ServerSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    host: str = "127.0.0.1"
    port: int = 4082
    access_key: str | None = None


class WebBridgeSharingSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    default: Literal["ask", "allow", "block"] = "ask"
    blocked_domains: list[str] = Field(default_factory=list)
    allow_selection: bool = True
    allow_readable_page: bool = True
    allow_screenshot: bool = True
    max_artifact_bytes: int = Field(default=5_000_000, ge=1, le=20_000_000)
    artifact_retention_hours: int = Field(default=24, ge=1, le=24 * 30)


class WebBridgeInteractionSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    allow_background_triggers: bool = False
    max_per_minute: int = Field(default=30, ge=1, le=600)


class WebBridgeSettings(BaseModel):
    """Guardrails for the WebBridge tool, which drives the user's *real*,
    logged-in browser. Defaults are permissive (open loopback dev) so the
    feature keeps working out of the box; production installs tighten these.
    """

    model_config = ConfigDict(extra="ignore")

    # Master switch. When False the webbridge tool refuses every action.
    enabled: bool = True
    # When non-empty, ONLY these domains may be driven (suffix match, so
    # "example.com" also matches "app.example.com"). Empty = allow all.
    allowed_domains: list[str] = Field(default_factory=list)
    # Always-refused domains (suffix match). Takes precedence over the
    # allowlist — use for banking/webmail the agent must never touch.
    blocked_domains: list[str] = Field(default_factory=list)
    # Allow the `evaluate` action (arbitrary JS in the real browser). Off in
    # locked-down installs; the far safer selector/snapshot actions stay on.
    allow_evaluate: bool = True
    # Recent actions kept in the in-memory audit ring buffer (GET /audit).
    audit_log_size: int = 200
    sharing: WebBridgeSharingSettings = Field(default_factory=WebBridgeSharingSettings)
    interactions: WebBridgeInteractionSettings = Field(
        default_factory=WebBridgeInteractionSettings
    )


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


class RuntimeSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title_generation: TitleGenerationSettings = Field(
        default_factory=TitleGenerationSettings
    )
    dream: DreamSettings = Field(default_factory=DreamSettings)
    memory_extraction: MemoryExtractionSettings = Field(
        default_factory=MemoryExtractionSettings
    )
    memory_vector: MemoryVectorSettings = Field(default_factory=MemoryVectorSettings)
    server: ServerSettings = Field(default_factory=ServerSettings)
    providers: dict[str, ProviderUiSettings] = Field(default_factory=dict)
    code_graph: CodeGraphSettings = Field(default_factory=CodeGraphSettings)
    cross_repo: CrossRepoSettings = Field(default_factory=CrossRepoSettings)
    git: GitSettings = Field(default_factory=GitSettings)
    code_reviews: CodeReviewSettings = Field(default_factory=CodeReviewSettings)
    webbridge: WebBridgeSettings = Field(default_factory=WebBridgeSettings)


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
    serialized = yaml.safe_dump(data, sort_keys=False)
    fd, temporary_name = tempfile.mkstemp(
        dir=resolved.parent,
        prefix=f".{resolved.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, resolved)
    finally:
        temporary.unlink(missing_ok=True)
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
