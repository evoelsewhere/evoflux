//! Port of the section models in `app/core/runtime_settings.py`: fields,
//! defaults, constraints, model validators and `model_dump(mode="json",
//! exclude_none=True)` in declaration order.

use std::collections::BTreeMap;

use evoflux_shared_yaml::{Mapping, Value};

use crate::validate::{
    float_range, int_range, model_at, Bound, Fields, Loc, Range, ValidationError, ANY,
};

/// A settings model: validated from a parsed mapping, dumped back to one.
pub trait Section: Sized + Default {
    /// pydantic's class name, used in `model_type` errors.
    const CLASS: &'static str;

    /// Read the fields (errors are pushed to `fields`).
    fn fields(fields: &mut Fields<'_>) -> Self;

    /// `@model_validator(mode="after")`, run only when every field is valid.
    fn after(self) -> Result<Self, String> {
        Ok(self)
    }

    /// `model_dump(mode="json", exclude_none=True)`.
    fn dump(&self) -> Mapping;

    /// `Model.model_validate(input)`: the model or pydantic's errors.
    fn validate(input: &Value) -> Result<Self, Vec<ValidationError>> {
        let mut errors = Vec::new();
        match validate_at::<Self>(input, Vec::new(), &mut errors) {
            Some(value) if errors.is_empty() => Ok(value),
            _ => Err(errors),
        }
    }
}

pub(crate) fn validate_at<T: Section>(
    input: &Value,
    loc: Vec<Loc>,
    errors: &mut Vec<ValidationError>,
) -> Option<T> {
    let value = model_at(input, loc.clone(), T::CLASS, errors, T::fields)?;
    match value.after() {
        Ok(value) => Some(value),
        Err(message) => {
            errors.push(ValidationError {
                kind: "value_error",
                loc,
                msg: format!("Value error, {message}"),
                input: input.clone(),
                ctx: Some(serde_json::json!({ "error": message })),
            });
            None
        }
    }
}

/// A nested model field of a model.
fn nested<T: Section>(fields: &mut Fields<'_>, name: &str) -> T {
    let Some(input) = fields.raw(name) else {
        return T::default();
    };
    let mut loc = fields.loc().to_vec();
    loc.push(Loc::field(name));
    validate_at::<T>(input, loc, fields.errors).unwrap_or_default()
}

struct Dump(Mapping);

impl Dump {
    fn new() -> Self {
        Dump(Mapping::new())
    }
    fn put(mut self, name: &str, value: Value) -> Self {
        self.0.insert(Value::Str(name.to_owned()), value);
        self
    }
    fn bool(self, name: &str, value: bool) -> Self {
        self.put(name, Value::Bool(value))
    }
    fn int(self, name: &str, value: i128) -> Self {
        self.put(name, Value::Int(value))
    }
    fn float(self, name: &str, value: f64) -> Self {
        self.put(name, Value::Float(value))
    }
    fn str(self, name: &str, value: &str) -> Self {
        self.put(name, Value::Str(value.to_owned()))
    }
    fn opt_str(self, name: &str, value: Option<&str>) -> Self {
        match value {
            Some(v) => self.str(name, v),
            None => self,
        }
    }
    fn opt_int(self, name: &str, value: Option<i128>) -> Self {
        match value {
            Some(v) => self.int(name, v),
            None => self,
        }
    }
    fn list(self, name: &str, value: &[String]) -> Self {
        self.put(
            name,
            Value::Seq(value.iter().map(|s| Value::Str(s.clone())).collect()),
        )
    }
    fn map(self, name: &str, value: Mapping) -> Self {
        self.put(name, Value::Map(value))
    }
    fn done(self) -> Mapping {
        self.0
    }
}

fn ge_int(ge: i128) -> Range {
    Range {
        ge: Some(Bound::Int(ge)),
        le: None,
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct TitleGenerationSettings {
    pub enabled: bool,
    pub model: Option<String>,
}

impl Default for TitleGenerationSettings {
    fn default() -> Self {
        Self {
            enabled: true,
            model: None,
        }
    }
}

impl Section for TitleGenerationSettings {
    const CLASS: &'static str = "TitleGenerationSettings";
    fn fields(f: &mut Fields<'_>) -> Self {
        Self {
            enabled: f.bool("enabled", true),
            model: f.opt_string("model"),
        }
    }
    fn dump(&self) -> Mapping {
        Dump::new()
            .bool("enabled", self.enabled)
            .opt_str("model", self.model.as_deref())
            .done()
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct DreamSettings {
    pub enabled: bool,
    pub model: Option<String>,
    pub schedule: String,
}

impl Default for DreamSettings {
    fn default() -> Self {
        Self {
            enabled: false,
            model: None,
            schedule: "0 2 * * *".to_owned(),
        }
    }
}

impl Section for DreamSettings {
    const CLASS: &'static str = "DreamSettings";
    fn fields(f: &mut Fields<'_>) -> Self {
        Self {
            enabled: f.bool("enabled", false),
            model: f.opt_string("model"),
            schedule: f.string("schedule", "0 2 * * *"),
        }
    }
    fn after(self) -> Result<Self, String> {
        match &self.model {
            Some(model) if !model.is_empty() && !model.contains(':') => {
                Err("Dream model must be 'provider:model'.".to_owned())
            }
            _ => Ok(self),
        }
    }
    fn dump(&self) -> Mapping {
        Dump::new()
            .bool("enabled", self.enabled)
            .opt_str("model", self.model.as_deref())
            .str("schedule", &self.schedule)
            .done()
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct MemoryVectorSettings {
    pub enabled: bool,
    pub backend: String,
    pub embedding_model: Option<String>,
    pub dim: Option<i128>,
    pub index_path: Option<String>,
}

impl Default for MemoryVectorSettings {
    fn default() -> Self {
        Self {
            enabled: false,
            backend: "disabled".to_owned(),
            embedding_model: None,
            dim: None,
            index_path: None,
        }
    }
}

impl Section for MemoryVectorSettings {
    const CLASS: &'static str = "MemoryVectorSettings";
    fn fields(f: &mut Fields<'_>) -> Self {
        Self {
            enabled: f.bool("enabled", false),
            backend: f.string("backend", "disabled"),
            embedding_model: f.opt_string("embedding_model"),
            dim: f.opt_int("dim", ANY),
            index_path: f.opt_string("index_path"),
        }
    }
    fn dump(&self) -> Mapping {
        Dump::new()
            .bool("enabled", self.enabled)
            .str("backend", &self.backend)
            .opt_str("embedding_model", self.embedding_model.as_deref())
            .opt_int("dim", self.dim)
            .opt_str("index_path", self.index_path.as_deref())
            .done()
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct TeamSpawnModeSettings {
    pub work: &'static str,
    pub coding: &'static str,
}

impl Default for TeamSpawnModeSettings {
    fn default() -> Self {
        Self {
            work: "ask",
            coding: "ask",
        }
    }
}

impl Section for TeamSpawnModeSettings {
    const CLASS: &'static str = "TeamSpawnModeSettings";
    fn fields(f: &mut Fields<'_>) -> Self {
        Self {
            work: f.literal("work", "ask", &["ask", "auto"]),
            coding: f.literal("coding", "ask", &["ask", "auto"]),
        }
    }
    fn dump(&self) -> Mapping {
        Dump::new()
            .str("work", self.work)
            .str("coding", self.coding)
            .done()
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct FollowUpSettings {
    pub delivery: &'static str,
}

impl Default for FollowUpSettings {
    fn default() -> Self {
        Self { delivery: "queue" }
    }
}

impl Section for FollowUpSettings {
    const CLASS: &'static str = "FollowUpSettings";
    fn fields(f: &mut Fields<'_>) -> Self {
        Self {
            delivery: f.literal("delivery", "queue", &["steer", "queue"]),
        }
    }
    fn dump(&self) -> Mapping {
        Dump::new().str("delivery", self.delivery).done()
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct BackgroundTaskSettings {
    pub wake_idle: bool,
}

impl Default for BackgroundTaskSettings {
    fn default() -> Self {
        Self { wake_idle: true }
    }
}

impl Section for BackgroundTaskSettings {
    const CLASS: &'static str = "BackgroundTaskSettings";
    fn fields(f: &mut Fields<'_>) -> Self {
        Self {
            wake_idle: f.bool("wake_idle", true),
        }
    }
    fn dump(&self) -> Mapping {
        Dump::new().bool("wake_idle", self.wake_idle).done()
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct ResponseStyleSettings {
    pub style: &'static str,
}

impl Default for ResponseStyleSettings {
    fn default() -> Self {
        Self { style: "visual" }
    }
}

impl Section for ResponseStyleSettings {
    const CLASS: &'static str = "ResponseStyleSettings";
    fn fields(f: &mut Fields<'_>) -> Self {
        Self {
            style: f.literal("style", "visual", &["simple", "visual"]),
        }
    }
    fn dump(&self) -> Mapping {
        Dump::new().str("style", self.style).done()
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct GitSettings {
    pub network_timeout_seconds: f64,
    pub max_diff_bytes: i128,
    pub default_pull_strategy: &'static str,
    pub prune_on_fetch: bool,
    pub allow_force_push: bool,
}

impl Default for GitSettings {
    fn default() -> Self {
        Self {
            network_timeout_seconds: 120.0,
            max_diff_bytes: 2_000_000,
            default_pull_strategy: "ff_only",
            prune_on_fetch: true,
            allow_force_push: false,
        }
    }
}

impl Section for GitSettings {
    const CLASS: &'static str = "GitSettings";
    fn fields(f: &mut Fields<'_>) -> Self {
        Self {
            network_timeout_seconds: f.float(
                "network_timeout_seconds",
                120.0,
                float_range(10.0, 1800.0),
            ),
            max_diff_bytes: f.int("max_diff_bytes", 2_000_000, int_range(64_000, 50_000_000)),
            default_pull_strategy: f.literal(
                "default_pull_strategy",
                "ff_only",
                &["ff_only", "merge", "rebase"],
            ),
            prune_on_fetch: f.bool("prune_on_fetch", true),
            allow_force_push: f.bool("allow_force_push", false),
        }
    }
    fn dump(&self) -> Mapping {
        Dump::new()
            .float("network_timeout_seconds", self.network_timeout_seconds)
            .int("max_diff_bytes", self.max_diff_bytes)
            .str("default_pull_strategy", self.default_pull_strategy)
            .bool("prune_on_fetch", self.prune_on_fetch)
            .bool("allow_force_push", self.allow_force_push)
            .done()
    }
}

#[derive(Debug, Clone, PartialEq, Default)]
pub struct ContextSettings {
    pub summary_trigger_tokens: Option<i128>,
    pub summary_max_tokens: Option<i128>,
    pub keep_recent_turns: Option<i128>,
    pub tool_result_offload_chars: Option<i128>,
    pub keep_recent_tool_batches: Option<i128>,
}

impl Section for ContextSettings {
    const CLASS: &'static str = "ContextSettings";
    fn fields(f: &mut Fields<'_>) -> Self {
        Self {
            summary_trigger_tokens: f
                .opt_int("summary_trigger_tokens", int_range(20_000, 2_000_000)),
            summary_max_tokens: f.opt_int("summary_max_tokens", int_range(2_000, 120_000)),
            keep_recent_turns: f.opt_int("keep_recent_turns", int_range(0, 10)),
            tool_result_offload_chars: f
                .opt_int("tool_result_offload_chars", int_range(2_000, 500_000)),
            keep_recent_tool_batches: f.opt_int("keep_recent_tool_batches", int_range(1, 12)),
        }
    }
    fn dump(&self) -> Mapping {
        Dump::new()
            .opt_int("summary_trigger_tokens", self.summary_trigger_tokens)
            .opt_int("summary_max_tokens", self.summary_max_tokens)
            .opt_int("keep_recent_turns", self.keep_recent_turns)
            .opt_int("tool_result_offload_chars", self.tool_result_offload_chars)
            .opt_int("keep_recent_tool_batches", self.keep_recent_tool_batches)
            .done()
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct CodeReviewSettings {
    pub request_timeout_seconds: f64,
    pub retry_attempts: i128,
    pub retry_backoff_seconds: f64,
    pub max_concurrent_repositories: i128,
    pub max_pages_per_repository: i128,
    pub allow_mutations: bool,
    pub allow_insecure_connections: bool,
    pub require_successful_checks_before_merge: bool,
}

impl Default for CodeReviewSettings {
    fn default() -> Self {
        Self {
            request_timeout_seconds: 20.0,
            retry_attempts: 2,
            retry_backoff_seconds: 0.5,
            max_concurrent_repositories: 4,
            max_pages_per_repository: 5,
            allow_mutations: true,
            allow_insecure_connections: false,
            require_successful_checks_before_merge: false,
        }
    }
}

impl Section for CodeReviewSettings {
    const CLASS: &'static str = "CodeReviewSettings";
    fn fields(f: &mut Fields<'_>) -> Self {
        Self {
            request_timeout_seconds: f.float(
                "request_timeout_seconds",
                20.0,
                float_range(2.0, 300.0),
            ),
            retry_attempts: f.int("retry_attempts", 2, int_range(0, 5)),
            retry_backoff_seconds: f.float("retry_backoff_seconds", 0.5, float_range(0.0, 10.0)),
            max_concurrent_repositories: f.int("max_concurrent_repositories", 4, int_range(1, 32)),
            max_pages_per_repository: f.int("max_pages_per_repository", 5, int_range(1, 20)),
            allow_mutations: f.bool("allow_mutations", true),
            allow_insecure_connections: f.bool("allow_insecure_connections", false),
            require_successful_checks_before_merge: f
                .bool("require_successful_checks_before_merge", false),
        }
    }
    fn dump(&self) -> Mapping {
        Dump::new()
            .float("request_timeout_seconds", self.request_timeout_seconds)
            .int("retry_attempts", self.retry_attempts)
            .float("retry_backoff_seconds", self.retry_backoff_seconds)
            .int(
                "max_concurrent_repositories",
                self.max_concurrent_repositories,
            )
            .int("max_pages_per_repository", self.max_pages_per_repository)
            .bool("allow_mutations", self.allow_mutations)
            .bool(
                "allow_insecure_connections",
                self.allow_insecure_connections,
            )
            .bool(
                "require_successful_checks_before_merge",
                self.require_successful_checks_before_merge,
            )
            .done()
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct ServerSettings {
    pub host: String,
    pub port: i128,
    pub access_key: Option<String>,
}

impl Default for ServerSettings {
    fn default() -> Self {
        Self {
            host: "127.0.0.1".to_owned(),
            port: 4082,
            access_key: None,
        }
    }
}

impl Section for ServerSettings {
    const CLASS: &'static str = "ServerSettings";
    fn fields(f: &mut Fields<'_>) -> Self {
        Self {
            host: f.string("host", "127.0.0.1"),
            port: f.int("port", 4082, ANY),
            access_key: f.opt_string("access_key"),
        }
    }
    fn dump(&self) -> Mapping {
        Dump::new()
            .str("host", &self.host)
            .int("port", self.port)
            .opt_str("access_key", self.access_key.as_deref())
            .done()
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct WebBridgeSharingSettings {
    pub default: &'static str,
    pub blocked_domains: Vec<String>,
    pub allow_selection: bool,
    pub allow_readable_page: bool,
    pub allow_screenshot: bool,
    pub max_artifact_bytes: i128,
    pub artifact_retention_hours: i128,
}

impl Default for WebBridgeSharingSettings {
    fn default() -> Self {
        Self {
            default: "ask",
            blocked_domains: Vec::new(),
            allow_selection: true,
            allow_readable_page: true,
            allow_screenshot: true,
            max_artifact_bytes: 5_000_000,
            artifact_retention_hours: 24,
        }
    }
}

impl Section for WebBridgeSharingSettings {
    const CLASS: &'static str = "WebBridgeSharingSettings";
    fn fields(f: &mut Fields<'_>) -> Self {
        Self {
            default: f.literal("default", "ask", &["ask", "allow", "block"]),
            blocked_domains: f.list_str("blocked_domains"),
            allow_selection: f.bool("allow_selection", true),
            allow_readable_page: f.bool("allow_readable_page", true),
            allow_screenshot: f.bool("allow_screenshot", true),
            max_artifact_bytes: f.int("max_artifact_bytes", 5_000_000, int_range(1, 20_000_000)),
            artifact_retention_hours: f.int("artifact_retention_hours", 24, int_range(1, 24 * 30)),
        }
    }
    fn dump(&self) -> Mapping {
        Dump::new()
            .str("default", self.default)
            .list("blocked_domains", &self.blocked_domains)
            .bool("allow_selection", self.allow_selection)
            .bool("allow_readable_page", self.allow_readable_page)
            .bool("allow_screenshot", self.allow_screenshot)
            .int("max_artifact_bytes", self.max_artifact_bytes)
            .int("artifact_retention_hours", self.artifact_retention_hours)
            .done()
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct WebBridgeInteractionSettings {
    pub allow_background_triggers: bool,
    pub max_per_minute: i128,
}

impl Default for WebBridgeInteractionSettings {
    fn default() -> Self {
        Self {
            allow_background_triggers: false,
            max_per_minute: 30,
        }
    }
}

impl Section for WebBridgeInteractionSettings {
    const CLASS: &'static str = "WebBridgeInteractionSettings";
    fn fields(f: &mut Fields<'_>) -> Self {
        Self {
            allow_background_triggers: f.bool("allow_background_triggers", false),
            max_per_minute: f.int("max_per_minute", 30, int_range(1, 600)),
        }
    }
    fn dump(&self) -> Mapping {
        Dump::new()
            .bool("allow_background_triggers", self.allow_background_triggers)
            .int("max_per_minute", self.max_per_minute)
            .done()
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct WebBridgeSettings {
    pub enabled: bool,
    pub agent_browsing: bool,
    pub allowed_domains: Vec<String>,
    pub blocked_domains: Vec<String>,
    pub allow_evaluate: bool,
    pub require_tab_binding: bool,
    pub audit_log_size: i128,
    pub sharing: WebBridgeSharingSettings,
    pub interactions: WebBridgeInteractionSettings,
}

impl Default for WebBridgeSettings {
    fn default() -> Self {
        Self {
            enabled: true,
            agent_browsing: true,
            allowed_domains: Vec::new(),
            blocked_domains: Vec::new(),
            allow_evaluate: true,
            require_tab_binding: true,
            audit_log_size: 200,
            sharing: WebBridgeSharingSettings::default(),
            interactions: WebBridgeInteractionSettings::default(),
        }
    }
}

impl Section for WebBridgeSettings {
    const CLASS: &'static str = "WebBridgeSettings";
    fn fields(f: &mut Fields<'_>) -> Self {
        Self {
            enabled: f.bool("enabled", true),
            agent_browsing: f.bool("agent_browsing", true),
            allowed_domains: f.list_str("allowed_domains"),
            blocked_domains: f.list_str("blocked_domains"),
            allow_evaluate: f.bool("allow_evaluate", true),
            require_tab_binding: f.bool("require_tab_binding", true),
            audit_log_size: f.int("audit_log_size", 200, ANY),
            sharing: nested(f, "sharing"),
            interactions: nested(f, "interactions"),
        }
    }
    fn dump(&self) -> Mapping {
        Dump::new()
            .bool("enabled", self.enabled)
            .bool("agent_browsing", self.agent_browsing)
            .list("allowed_domains", &self.allowed_domains)
            .list("blocked_domains", &self.blocked_domains)
            .bool("allow_evaluate", self.allow_evaluate)
            .bool("require_tab_binding", self.require_tab_binding)
            .int("audit_log_size", self.audit_log_size)
            .map("sharing", self.sharing.dump())
            .map("interactions", self.interactions.dump())
            .done()
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct BuiltInBrowserSettings {
    pub allowed_domains: Vec<String>,
    pub blocked_domains: Vec<String>,
    pub allow_evaluate: bool,
    pub allow_storage: bool,
    pub allow_cookie_values: bool,
    pub allow_http_requests: bool,
    pub allow_clipboard_read: bool,
    pub allow_clipboard_write: bool,
    pub allow_file_uploads: bool,
    pub allow_downloads: bool,
    pub allow_agent_permission_accept: bool,
}

impl Default for BuiltInBrowserSettings {
    fn default() -> Self {
        Self {
            allowed_domains: Vec::new(),
            blocked_domains: Vec::new(),
            allow_evaluate: true,
            allow_storage: true,
            allow_cookie_values: false,
            allow_http_requests: true,
            allow_clipboard_read: false,
            allow_clipboard_write: true,
            allow_file_uploads: false,
            allow_downloads: true,
            allow_agent_permission_accept: false,
        }
    }
}

impl Section for BuiltInBrowserSettings {
    const CLASS: &'static str = "BuiltInBrowserSettings";
    fn fields(f: &mut Fields<'_>) -> Self {
        Self {
            allowed_domains: f.list_str("allowed_domains"),
            blocked_domains: f.list_str("blocked_domains"),
            allow_evaluate: f.bool("allow_evaluate", true),
            allow_storage: f.bool("allow_storage", true),
            allow_cookie_values: f.bool("allow_cookie_values", false),
            allow_http_requests: f.bool("allow_http_requests", true),
            allow_clipboard_read: f.bool("allow_clipboard_read", false),
            allow_clipboard_write: f.bool("allow_clipboard_write", true),
            allow_file_uploads: f.bool("allow_file_uploads", false),
            allow_downloads: f.bool("allow_downloads", true),
            allow_agent_permission_accept: f.bool("allow_agent_permission_accept", false),
        }
    }
    fn dump(&self) -> Mapping {
        Dump::new()
            .list("allowed_domains", &self.allowed_domains)
            .list("blocked_domains", &self.blocked_domains)
            .bool("allow_evaluate", self.allow_evaluate)
            .bool("allow_storage", self.allow_storage)
            .bool("allow_cookie_values", self.allow_cookie_values)
            .bool("allow_http_requests", self.allow_http_requests)
            .bool("allow_clipboard_read", self.allow_clipboard_read)
            .bool("allow_clipboard_write", self.allow_clipboard_write)
            .bool("allow_file_uploads", self.allow_file_uploads)
            .bool("allow_downloads", self.allow_downloads)
            .bool(
                "allow_agent_permission_accept",
                self.allow_agent_permission_accept,
            )
            .done()
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct ComputerAppSettings {
    pub enabled: bool,
    pub allowed_apps: Vec<String>,
    pub blocked_apps: Vec<String>,
    pub keep_hidden: bool,
    pub permission: &'static str,
}

impl Default for ComputerAppSettings {
    fn default() -> Self {
        Self {
            enabled: false,
            allowed_apps: Vec::new(),
            blocked_apps: Vec::new(),
            keep_hidden: true,
            permission: "ask",
        }
    }
}

impl Section for ComputerAppSettings {
    const CLASS: &'static str = "ComputerAppSettings";
    fn fields(f: &mut Fields<'_>) -> Self {
        Self {
            enabled: f.bool("enabled", false),
            allowed_apps: f.list_str("allowed_apps"),
            blocked_apps: f.list_str("blocked_apps"),
            keep_hidden: f.bool("keep_hidden", true),
            permission: f.literal("permission", "ask", &["ask", "allow"]),
        }
    }
    fn dump(&self) -> Mapping {
        Dump::new()
            .bool("enabled", self.enabled)
            .list("allowed_apps", &self.allowed_apps)
            .list("blocked_apps", &self.blocked_apps)
            .bool("keep_hidden", self.keep_hidden)
            .str("permission", self.permission)
            .done()
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct ImportAutoSyncSettings {
    pub enabled: bool,
    pub scan_interval_seconds: i128,
    pub notify_new_items: bool,
}

impl Default for ImportAutoSyncSettings {
    fn default() -> Self {
        Self {
            enabled: false,
            scan_interval_seconds: 300,
            notify_new_items: true,
        }
    }
}

impl Section for ImportAutoSyncSettings {
    const CLASS: &'static str = "ImportAutoSyncSettings";
    fn fields(f: &mut Fields<'_>) -> Self {
        Self {
            enabled: f.bool("enabled", false),
            scan_interval_seconds: f.int("scan_interval_seconds", 300, ge_int(30)),
            notify_new_items: f.bool("notify_new_items", true),
        }
    }
    fn dump(&self) -> Mapping {
        Dump::new()
            .bool("enabled", self.enabled)
            .int("scan_interval_seconds", self.scan_interval_seconds)
            .bool("notify_new_items", self.notify_new_items)
            .done()
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct ConductorSettings {
    pub enabled: bool,
    pub url: String,
    /// `Field(exclude=True)`: read, never written back.
    pub enrollment_token: Option<String>,
    pub machine_credential_path: Option<String>,
    pub sync_interval_seconds: f64,
    pub heartbeat_interval_seconds: f64,
    pub request_timeout_seconds: f64,
    pub enforcement_mode: &'static str,
    pub installation_key: Option<String>,
    pub installation_id: Option<String>,
    pub project_id: Option<String>,
    pub project_name: Option<String>,
    pub project_display_name: Option<String>,
    pub project_logo_url: Option<String>,
    pub member_id: Option<String>,
    pub member_display_name: Option<String>,
    pub member_primary_role: Option<&'static str>,
    pub collection_level: Option<&'static str>,
}

impl Default for ConductorSettings {
    fn default() -> Self {
        Self {
            enabled: false,
            url: String::new(),
            enrollment_token: None,
            machine_credential_path: None,
            sync_interval_seconds: 60.0,
            heartbeat_interval_seconds: 60.0,
            request_timeout_seconds: 15.0,
            enforcement_mode: "report",
            installation_key: None,
            installation_id: None,
            project_id: None,
            project_name: None,
            project_display_name: None,
            project_logo_url: None,
            member_id: None,
            member_display_name: None,
            member_primary_role: None,
            collection_level: None,
        }
    }
}

impl Section for ConductorSettings {
    const CLASS: &'static str = "ConductorSettings";
    fn fields(f: &mut Fields<'_>) -> Self {
        Self {
            enabled: f.bool("enabled", false),
            url: f.string("url", ""),
            enrollment_token: f.opt_string("enrollment_token"),
            machine_credential_path: f.opt_string("machine_credential_path"),
            sync_interval_seconds: f.float(
                "sync_interval_seconds",
                60.0,
                float_range(5.0, 86_400.0),
            ),
            heartbeat_interval_seconds: f.float(
                "heartbeat_interval_seconds",
                60.0,
                float_range(30.0, 300.0),
            ),
            request_timeout_seconds: f.float(
                "request_timeout_seconds",
                15.0,
                float_range(1.0, 120.0),
            ),
            enforcement_mode: f.literal("enforcement_mode", "report", &["report", "enforce"]),
            installation_key: f.opt_string("installation_key"),
            installation_id: f.opt_string("installation_id"),
            project_id: f.opt_string("project_id"),
            project_name: f.opt_string("project_name"),
            project_display_name: f.opt_string("project_display_name"),
            project_logo_url: f.opt_string("project_logo_url"),
            member_id: f.opt_string("member_id"),
            member_display_name: f.opt_string("member_display_name"),
            member_primary_role: f
                .opt_literal("member_primary_role", &["admin", "contribute", "user"]),
            collection_level: f.opt_literal("collection_level", &["L0", "L1", "L2"]),
        }
    }
    fn after(mut self) -> Result<Self, String> {
        let value = crate::url::strip_origin(&self.url);
        if !value.is_empty() && !crate::url::is_plain_http_origin(&value) {
            return Err(
                "Conductor URL must be an http:// or https:// origin without \
                 credentials, path, query, or fragment."
                    .to_owned(),
            );
        }
        self.url = value;
        Ok(self)
    }
    fn dump(&self) -> Mapping {
        Dump::new()
            .bool("enabled", self.enabled)
            .str("url", &self.url)
            .opt_str(
                "machine_credential_path",
                self.machine_credential_path.as_deref(),
            )
            .float("sync_interval_seconds", self.sync_interval_seconds)
            .float(
                "heartbeat_interval_seconds",
                self.heartbeat_interval_seconds,
            )
            .float("request_timeout_seconds", self.request_timeout_seconds)
            .str("enforcement_mode", self.enforcement_mode)
            .opt_str("installation_key", self.installation_key.as_deref())
            .opt_str("installation_id", self.installation_id.as_deref())
            .opt_str("project_id", self.project_id.as_deref())
            .opt_str("project_name", self.project_name.as_deref())
            .opt_str("project_display_name", self.project_display_name.as_deref())
            .opt_str("project_logo_url", self.project_logo_url.as_deref())
            .opt_str("member_id", self.member_id.as_deref())
            .opt_str("member_display_name", self.member_display_name.as_deref())
            .opt_str("member_primary_role", self.member_primary_role)
            .opt_str("collection_level", self.collection_level)
            .done()
    }
}

#[derive(Debug, Clone, PartialEq, Default)]
pub struct ProviderUiSettings {
    pub visible_models: Vec<String>,
}

impl Section for ProviderUiSettings {
    const CLASS: &'static str = "ProviderUiSettings";
    fn fields(f: &mut Fields<'_>) -> Self {
        Self {
            visible_models: f.list_str("visible_models"),
        }
    }
    fn dump(&self) -> Mapping {
        Dump::new()
            .list("visible_models", &self.visible_models)
            .done()
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct MemoryExtractionSettings {
    pub enabled: bool,
    pub min_assistant_messages: i128,
    pub every_n_messages: i128,
    pub max_input_chars: i128,
    pub model: Option<String>,
}

impl Default for MemoryExtractionSettings {
    fn default() -> Self {
        Self {
            enabled: true,
            min_assistant_messages: 3,
            every_n_messages: 10,
            max_input_chars: 12_000,
            model: None,
        }
    }
}

impl Section for MemoryExtractionSettings {
    const CLASS: &'static str = "MemoryExtractionSettings";
    fn fields(f: &mut Fields<'_>) -> Self {
        Self {
            enabled: f.bool("enabled", true),
            min_assistant_messages: f.int("min_assistant_messages", 3, ANY),
            every_n_messages: f.int("every_n_messages", 10, ANY),
            max_input_chars: f.int("max_input_chars", 12_000, ANY),
            model: f.opt_string("model"),
        }
    }
    fn dump(&self) -> Mapping {
        Dump::new()
            .bool("enabled", self.enabled)
            .int("min_assistant_messages", self.min_assistant_messages)
            .int("every_n_messages", self.every_n_messages)
            .int("max_input_chars", self.max_input_chars)
            .opt_str("model", self.model.as_deref())
            .done()
    }
}

/// `RuntimeSettings`, the whole of `settings.yaml`.
#[derive(Debug, Clone, PartialEq, Default)]
pub struct RuntimeSettings {
    pub title_generation: TitleGenerationSettings,
    pub dream: DreamSettings,
    pub memory_extraction: MemoryExtractionSettings,
    pub memory_vector: MemoryVectorSettings,
    pub server: ServerSettings,
    /// `dict[str, ProviderUiSettings]`, in file order.
    pub providers: Vec<(String, ProviderUiSettings)>,
    pub git: GitSettings,
    pub context: ContextSettings,
    pub code_reviews: CodeReviewSettings,
    pub browser: BuiltInBrowserSettings,
    pub webbridge: WebBridgeSettings,
    pub computer_app: ComputerAppSettings,
    pub import_auto_sync: ImportAutoSyncSettings,
    pub conductor: ConductorSettings,
    pub team_spawn: TeamSpawnModeSettings,
    pub follow_up: FollowUpSettings,
    pub background_tasks: BackgroundTaskSettings,
    pub response_style: ResponseStyleSettings,
}

impl RuntimeSettings {
    /// `cfg.providers.get(provider_id)`.
    pub fn provider(&self, id: &str) -> Option<&ProviderUiSettings> {
        self.providers.iter().find(|(k, _)| k == id).map(|(_, v)| v)
    }

    /// `cfg.providers[id] = value` (keeps the position of an existing id).
    pub fn set_provider(&mut self, id: &str, value: ProviderUiSettings) {
        match self.providers.iter_mut().find(|(k, _)| k == id) {
            Some(slot) => slot.1 = value,
            None => self.providers.push((id.to_owned(), value)),
        }
    }

    /// `cfg.providers.pop(id, None)`.
    pub fn remove_provider(&mut self, id: &str) -> Option<ProviderUiSettings> {
        let at = self.providers.iter().position(|(k, _)| k == id)?;
        Some(self.providers.remove(at).1)
    }

    /// The providers as a sorted map (convenience for lookups).
    pub fn providers_by_id(&self) -> BTreeMap<&str, &ProviderUiSettings> {
        self.providers
            .iter()
            .map(|(k, v)| (k.as_str(), v))
            .collect()
    }
}

/// `dict[str, ProviderUiSettings]` validation.
fn providers(f: &mut Fields<'_>) -> Vec<(String, ProviderUiSettings)> {
    let Some(input) = f.raw("providers") else {
        return Vec::new();
    };
    let mut loc = f.loc().to_vec();
    loc.push(Loc::field("providers"));
    let Value::Map(map) = input else {
        f.error(
            loc,
            "dict_type",
            "Input should be a valid dictionary".to_owned(),
            input,
            None,
        );
        return Vec::new();
    };
    let mut out = Vec::new();
    for (key, value) in map {
        let mut at = loc.clone();
        at.push(Loc::Key(key.clone()));
        let Value::Str(id) = key else {
            let mut key_loc = at.clone();
            key_loc.push(Loc::field("[key]"));
            f.error(
                key_loc,
                "string_type",
                "Input should be a valid string".to_owned(),
                key,
                None,
            );
            // pydantic still validates the value of a bad key.
            let _ = validate_at::<ProviderUiSettings>(value, at, f.errors);
            continue;
        };
        if let Some(settings) = validate_at::<ProviderUiSettings>(value, at, f.errors) {
            out.push((id.clone(), settings));
        }
    }
    out
}

impl Section for RuntimeSettings {
    const CLASS: &'static str = "RuntimeSettings";
    fn fields(f: &mut Fields<'_>) -> Self {
        Self {
            title_generation: nested(f, "title_generation"),
            dream: nested(f, "dream"),
            memory_extraction: nested(f, "memory_extraction"),
            memory_vector: nested(f, "memory_vector"),
            server: nested(f, "server"),
            providers: providers(f),
            git: nested(f, "git"),
            context: nested(f, "context"),
            code_reviews: nested(f, "code_reviews"),
            browser: nested(f, "browser"),
            webbridge: nested(f, "webbridge"),
            computer_app: nested(f, "computer_app"),
            import_auto_sync: nested(f, "import_auto_sync"),
            conductor: nested(f, "conductor"),
            team_spawn: nested(f, "team_spawn"),
            follow_up: nested(f, "follow_up"),
            background_tasks: nested(f, "background_tasks"),
            response_style: nested(f, "response_style"),
        }
    }
    fn dump(&self) -> Mapping {
        let mut providers = Mapping::new();
        for (id, settings) in &self.providers {
            providers.insert(Value::Str(id.clone()), Value::Map(settings.dump()));
        }
        Dump::new()
            .map("title_generation", self.title_generation.dump())
            .map("dream", self.dream.dump())
            .map("memory_extraction", self.memory_extraction.dump())
            .map("memory_vector", self.memory_vector.dump())
            .map("server", self.server.dump())
            .map("providers", providers)
            .map("git", self.git.dump())
            .map("context", self.context.dump())
            .map("code_reviews", self.code_reviews.dump())
            .map("browser", self.browser.dump())
            .map("webbridge", self.webbridge.dump())
            .map("computer_app", self.computer_app.dump())
            .map("import_auto_sync", self.import_auto_sync.dump())
            .map("conductor", self.conductor.dump())
            .map("team_spawn", self.team_spawn.dump())
            .map("follow_up", self.follow_up.dump())
            .map("background_tasks", self.background_tasks.dump())
            .map("response_style", self.response_style.dump())
            .done()
    }
}
