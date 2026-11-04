//! Port of `app/agent/providers/registry.py`: the declarative provider table.
//!
//! Only the parts the catalog and its callers need are ported: transports,
//! the models.dev `npm` map, the curated registry, presentation order, and
//! the config synthesis for providers the registry does not name. Functions
//! that read the models.dev envelopes live on [`crate::Catalog`], which owns
//! them.

use indexmap::IndexMap;
use serde::Serialize;
use serde_json::{Map, Value};

use crate::registry_table::PROVIDER_TABLE;

/// A wire protocol EvoFlux can speak (`Transport` in Python).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize)]
#[serde(rename_all = "kebab-case")]
pub enum Transport {
    /// `POST {base}/chat/completions`.
    OpenaiCompletions,
    /// `POST {base}/responses`.
    OpenaiResponses,
    /// `POST {base}/v1/messages`.
    Anthropic,
    /// `POST {base}/models/{model}:streamGenerateContent`.
    GoogleGenai,
    /// Vertex AI: the Gemini shape behind Google Cloud credentials.
    GoogleVertex,
    /// AWS Bedrock Converse.
    Bedrock,
    /// Azure OpenAI deployments.
    Azure,
}

impl Transport {
    /// The string Python's `StrEnum` value has, e.g. `"openai-completions"`.
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::OpenaiCompletions => "openai-completions",
            Self::OpenaiResponses => "openai-responses",
            Self::Anthropic => "anthropic",
            Self::GoogleGenai => "google-genai",
            Self::GoogleVertex => "google-vertex",
            Self::Bedrock => "bedrock",
            Self::Azure => "azure",
        }
    }
}

/// The transport for a provider whose `npm` adapter is unknown or absent.
pub const DEFAULT_TRANSPORT: Transport = Transport::OpenaiCompletions;

/// models.dev `npm` adapter name to EvoFlux transport (`NPM_TRANSPORTS`), in
/// the Python dict's order.
pub const NPM_TRANSPORTS: &[(&str, Transport)] = &[
    ("@ai-sdk/openai-compatible", Transport::OpenaiCompletions),
    ("@ai-sdk/openai", Transport::OpenaiResponses),
    ("@ai-sdk/azure", Transport::Azure),
    ("@ai-sdk/anthropic", Transport::Anthropic),
    ("@ai-sdk/google-vertex/anthropic", Transport::Anthropic),
    ("@ai-sdk/google", Transport::GoogleGenai),
    ("@ai-sdk/google-vertex", Transport::GoogleVertex),
    ("@ai-sdk/amazon-bedrock", Transport::Bedrock),
    ("@ai-sdk/cerebras", Transport::OpenaiCompletions),
    ("@ai-sdk/cohere", Transport::OpenaiCompletions),
    ("@ai-sdk/deepinfra", Transport::OpenaiCompletions),
    ("@ai-sdk/gateway", Transport::OpenaiCompletions),
    ("@ai-sdk/groq", Transport::OpenaiCompletions),
    ("@ai-sdk/mistral", Transport::OpenaiCompletions),
    ("@ai-sdk/perplexity", Transport::OpenaiCompletions),
    ("@ai-sdk/togetherai", Transport::OpenaiCompletions),
    ("@ai-sdk/vercel", Transport::OpenaiCompletions),
    ("@ai-sdk/xai", Transport::OpenaiCompletions),
    ("@openrouter/ai-sdk-provider", Transport::OpenaiCompletions),
    ("venice-ai-sdk-provider", Transport::OpenaiCompletions),
];

/// How the settings UI must collect credentials (`AuthKind` in Python).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum AuthKind {
    /// A single API key.
    ApiKey,
    /// A browser or device flow.
    Oauth,
    /// More than one credential field.
    Cloud,
    /// No credentials; a daemon on this machine.
    Local,
}

/// One curated row as written in the generated table (all static).
#[derive(Debug)]
pub(crate) struct ConfigRow {
    pub id: &'static str,
    pub label: &'static str,
    pub transport: Transport,
    pub env_var: &'static str,
    pub base_url: &'static str,
    pub base_url_env_var: Option<&'static str>,
    pub models_dev_id: Option<&'static str>,
    pub attribution_headers: &'static [(&'static str, &'static str)],
    pub extra_headers: &'static [(&'static str, &'static str)],
    pub default_api_key: &'static str,
    pub responses_models: &'static [&'static str],
    pub auth: AuthKind,
    pub docs_url: &'static str,
    pub extra_transports: &'static [Transport],
    pub model_transports: &'static [(&'static str, Transport)],
    pub browser_login: bool,
}

/// Everything needed to open a connection to one provider
/// (`ProviderConfig` in Python).
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct ProviderConfig {
    /// EvoFlux's provider id (the part before `:` in `provider:model`).
    pub id: String,
    /// Human-readable name.
    pub label: String,
    /// Wire protocol.
    pub transport: Transport,
    /// Primary credential environment variable.
    pub env_var: String,
    /// Default endpoint; empty when the catalog states it or an SDK does.
    pub base_url: String,
    /// Environment variable that overrides `base_url`.
    pub base_url_env_var: Option<String>,
    /// The provider's id in models.dev when it differs.
    pub models_dev_id: Option<String>,
    /// Static headers identifying EvoFlux to aggregators.
    pub attribution_headers: IndexMap<String, String>,
    /// Other always-on headers.
    pub extra_headers: IndexMap<String, String>,
    /// Placeholder credential for endpoints that ignore its value.
    pub default_api_key: String,
    /// Model-id substrings that must use the Responses API.
    pub responses_models: Vec<String>,
    /// How credentials are obtained.
    pub auth: AuthKind,
    /// Where a user gets a key.
    pub docs_url: String,
    /// Protocols the provider's adapters speak besides `transport`.
    pub extra_transports: Vec<Transport>,
    /// `(model-id prefix, transport)` routing, first match wins.
    pub model_transports: Vec<(String, Transport)>,
    /// Whether the provider can mint its own key through a browser sign-in.
    pub browser_login: bool,
}

fn owned_map(pairs: &[(&str, &str)]) -> IndexMap<String, String> {
    pairs
        .iter()
        .map(|(k, v)| ((*k).to_owned(), (*v).to_owned()))
        .collect()
}

impl From<&ConfigRow> for ProviderConfig {
    fn from(row: &ConfigRow) -> Self {
        Self {
            id: row.id.to_owned(),
            label: row.label.to_owned(),
            transport: row.transport,
            env_var: row.env_var.to_owned(),
            base_url: row.base_url.to_owned(),
            base_url_env_var: row.base_url_env_var.map(str::to_owned),
            models_dev_id: row.models_dev_id.map(str::to_owned),
            attribution_headers: owned_map(row.attribution_headers),
            extra_headers: owned_map(row.extra_headers),
            default_api_key: row.default_api_key.to_owned(),
            responses_models: row
                .responses_models
                .iter()
                .map(|s| (*s).to_owned())
                .collect(),
            auth: row.auth,
            docs_url: row.docs_url.to_owned(),
            extra_transports: row.extra_transports.to_vec(),
            model_transports: row
                .model_transports
                .iter()
                .map(|(p, t)| ((*p).to_owned(), *t))
                .collect(),
            browser_login: row.browser_login,
        }
    }
}

impl ProviderConfig {
    /// The catalog id to read this provider's model metadata under.
    #[must_use]
    pub fn models_dev_provider_id(&self) -> &str {
        match self.models_dev_id.as_deref() {
            Some(id) if !id.is_empty() => id,
            _ => &self.id,
        }
    }

    /// Whether one of this provider's adapters speaks `transport`.
    #[must_use]
    pub fn speaks(&self, transport: Transport) -> bool {
        transport == self.transport || self.extra_transports.contains(&transport)
    }

    /// The transport `model_transports` assigns `model`, if any.
    #[must_use]
    pub fn transport_for_model(&self, model: &str) -> Option<Transport> {
        let lowered = model.to_lowercase();
        self.model_transports
            .iter()
            .find(|(prefix, _)| lowered.starts_with(prefix.as_str()))
            .map(|(_, transport)| *transport)
    }

    /// Whether `model` must be sent to `/responses`.
    #[must_use]
    pub fn uses_responses_api(&self, model: &str) -> bool {
        if self.transport == Transport::OpenaiResponses {
            return true;
        }
        if self.responses_models.is_empty() {
            return false;
        }
        let lowered = model.to_lowercase();
        self.responses_models
            .iter()
            .any(|marker| lowered.contains(marker.as_str()))
    }

    /// Static headers every request to this provider should carry
    /// (`request_headers`): attribution headers, then extra headers.
    #[must_use]
    pub fn request_headers(&self) -> IndexMap<String, String> {
        let mut headers = self.attribution_headers.clone();
        for (name, value) in &self.extra_headers {
            headers.insert(name.clone(), value.clone());
        }
        headers
    }
}

/// The curated providers in registry order (`PROVIDER_REGISTRY`).
#[must_use]
pub fn provider_registry() -> Vec<ProviderConfig> {
    PROVIDER_TABLE.iter().map(ProviderConfig::from).collect()
}

/// Providers to offer first, strongest recommendation first.
pub const RECOMMENDED_PROVIDERS: &[&str] = &[
    "xiaomi",
    "anthropic",
    "openai",
    "googlegenai",
    "codex",
    "copilot",
    "openrouter",
    "deepseek",
    "zai",
    "qwencloud",
];

fn normalize(provider_id: &str) -> String {
    provider_id.trim().to_lowercase()
}

/// Sort key for the settings list: the position in
/// [`RECOMMENDED_PROVIDERS`], or one past the end for everything else.
#[must_use]
pub fn provider_rank(provider_id: &str) -> usize {
    let normalized = normalize(provider_id);
    RECOMMENDED_PROVIDERS
        .iter()
        .position(|id| *id == normalized)
        .unwrap_or(RECOMMENDED_PROVIDERS.len())
}

/// Whether this provider is one EvoFlux suggests connecting first.
#[must_use]
pub fn is_recommended(provider_id: &str) -> bool {
    let normalized = normalize(provider_id);
    RECOMMENDED_PROVIDERS.contains(&normalized.as_str())
}

/// Curated provider ids, sorted (`provider_ids`).
#[must_use]
pub fn provider_ids() -> Vec<String> {
    let mut ids: Vec<String> = PROVIDER_TABLE.iter().map(|r| r.id.to_owned()).collect();
    ids.sort();
    ids
}

/// Look up a curated provider config by id, ignoring case and surrounding
/// whitespace (`get_provider_config`).
#[must_use]
pub fn get_provider_config(provider_id: &str) -> Option<ProviderConfig> {
    let normalized = normalize(provider_id);
    PROVIDER_TABLE
        .iter()
        .find(|row| row.id == normalized)
        .map(ProviderConfig::from)
}

/// Whether `provider_id` (exactly, no normalising) is a curated id.
pub(crate) fn is_curated(provider_id: &str) -> bool {
    PROVIDER_TABLE.iter().any(|row| row.id == provider_id)
}

/// Map a models.dev `npm` adapter name to a transport (`transport_for_npm`).
/// Anything absent, empty or unknown falls back to [`DEFAULT_TRANSPORT`].
#[must_use]
pub fn transport_for_npm(npm: Option<&str>) -> Transport {
    match npm {
        None | Some("") => DEFAULT_TRANSPORT,
        Some(name) => NPM_TRANSPORTS
            .iter()
            .find(|(npm, _)| *npm == name)
            .map_or(DEFAULT_TRANSPORT, |(_, transport)| *transport),
    }
}

/// The conventional `<PROVIDER>_BASE_URL` override name
/// (`_derived_base_url_env_var`).
#[must_use]
pub fn derived_base_url_env_var(provider_id: &str) -> String {
    format!("{}_BASE_URL", env_slug(provider_id))
}

fn env_slug(provider_id: &str) -> String {
    provider_id.to_uppercase().replace(['-', '.'], "_")
}

fn non_empty_str<'a>(map: &'a Map<String, Value>, key: &str) -> Option<&'a str> {
    map.get(key)
        .and_then(Value::as_str)
        .filter(|text| !text.is_empty())
}

/// Synthesize a config from one models.dev provider envelope
/// (`config_from_models_dev`). `None` when the entry has no usable endpoint
/// (missing, blank or templated on other credentials) or no credential name.
#[must_use]
pub fn config_from_models_dev(
    provider_id: &str,
    entry: &Map<String, Value>,
) -> Option<ProviderConfig> {
    let transport = transport_for_npm(entry.get("npm").and_then(Value::as_str));
    let base_url = entry
        .get("api")
        .and_then(Value::as_str)
        .map_or("", str::trim);
    if base_url.is_empty() || base_url.contains("${") {
        return None;
    }
    let env_var = entry
        .get("env")
        .and_then(Value::as_array)
        .and_then(|names| names.first())
        .and_then(Value::as_str)
        .unwrap_or("");
    if env_var.is_empty() {
        return None;
    }
    let normalized = normalize(provider_id);
    Some(ProviderConfig {
        id: normalized.clone(),
        label: non_empty_str(entry, "name")
            .unwrap_or(provider_id)
            .to_owned(),
        transport,
        env_var: env_var.to_owned(),
        base_url: base_url.to_owned(),
        base_url_env_var: Some(derived_base_url_env_var(&normalized)),
        models_dev_id: Some(normalized),
        attribution_headers: IndexMap::new(),
        extra_headers: IndexMap::new(),
        default_api_key: String::new(),
        responses_models: Vec::new(),
        auth: AuthKind::ApiKey,
        docs_url: String::new(),
        extra_transports: Vec::new(),
        model_transports: Vec::new(),
        browser_login: false,
    })
}

/// Build a config for a user-declared OpenAI-compatible endpoint
/// (`custom_provider`). The base URL is used verbatim.
#[must_use]
pub fn custom_provider(
    provider_id: &str,
    label: Option<&str>,
    base_url: &str,
    env_var: Option<&str>,
    transport: Transport,
) -> ProviderConfig {
    let normalized = normalize(provider_id);
    let slug = env_slug(&normalized);
    ProviderConfig {
        label: label
            .filter(|text| !text.is_empty())
            .unwrap_or(provider_id)
            .to_owned(),
        transport,
        env_var: env_var
            .filter(|text| !text.is_empty())
            .map_or_else(|| format!("{slug}_API_KEY"), str::to_owned),
        base_url: base_url.to_owned(),
        base_url_env_var: Some(format!("{slug}_BASE_URL")),
        id: normalized,
        models_dev_id: None,
        attribution_headers: IndexMap::new(),
        extra_headers: IndexMap::new(),
        default_api_key: String::new(),
        responses_models: Vec::new(),
        auth: AuthKind::ApiKey,
        docs_url: String::new(),
        extra_transports: Vec::new(),
        model_transports: Vec::new(),
        browser_login: false,
    }
}
