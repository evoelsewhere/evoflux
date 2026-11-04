//! Port of `app/agent/providers/catalog.py` (the rows the settings UI
//! renders) together with the models.dev lookups of `registry.py` and
//! `model_registry.py` that feed it.
//!
//! Rows come in three tiers, in the order of how much EvoFlux knows about
//! each: curated providers, installed plugins, then every remaining
//! models.dev provider reachable from a base URL and a key.

use std::collections::HashSet;
use std::sync::OnceLock;

use indexmap::IndexMap;
use serde::Serialize;
use serde_json::{Map, Value};

use crate::configured::CredentialLookup;
use crate::data::{bundled_envelopes, provider_envelopes, Envelope, Envelopes};
use crate::overrides_table::OVERRIDES;
use crate::registry::{
    config_from_models_dev, derived_base_url_env_var, is_curated, provider_registry,
    transport_for_npm, AuthKind, ProviderConfig,
};

/// How the UI collects credentials for a provider (`ProviderKind`).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Kind {
    /// A single text input for `env_var`.
    ApiKey,
    /// A browser or device flow.
    Oauth,
    /// No credentials needed.
    Local,
    /// More than one field.
    CloudCreds,
}

/// How much EvoFlux knows about a row (`source`).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Source {
    /// A curated provider.
    Builtin,
    /// An installed provider plugin.
    Plugin,
    /// A models.dev long-tail provider.
    Catalog,
}

/// One credential field of a provider's form.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct CredentialField {
    /// Environment variable name.
    pub name: String,
    /// Label shown next to the input.
    pub label: String,
    /// Whether the value is masked.
    pub secret: bool,
    /// Whether the form requires it.
    pub required: bool,
    /// Input placeholder.
    pub placeholder: String,
}

/// A credential field as written in the generated override table.
#[derive(Debug)]
pub(crate) struct CredentialRow {
    pub name: &'static str,
    pub label: &'static str,
    pub secret: bool,
    pub required: bool,
    pub placeholder: &'static str,
}

impl From<&CredentialRow> for CredentialField {
    fn from(row: &CredentialRow) -> Self {
        Self {
            name: row.name.to_owned(),
            label: row.label.to_owned(),
            secret: row.secret,
            required: row.required,
            placeholder: row.placeholder.to_owned(),
        }
    }
}

/// What a person wrote about a curated provider that neither the registry
/// nor models.dev can say (`_OVERRIDES`). A set field patches the derived
/// row.
#[derive(Debug)]
pub(crate) struct Override {
    pub description: Option<&'static str>,
    pub kind: Option<Kind>,
    pub credentials: Option<&'static [CredentialRow]>,
    pub fallback_models: Option<&'static [&'static str]>,
    pub oauth_command: Option<&'static str>,
    pub metadata_source_provider: Option<&'static str>,
    pub metadata_source_exclude: Option<&'static [&'static str]>,
    pub model_registry_aliases: Option<&'static [(&'static str, &'static str)]>,
    pub live_model_metadata: Option<bool>,
    pub auto_connect: Option<bool>,
}

impl Override {
    pub(crate) const EMPTY: Self = Self {
        description: None,
        kind: None,
        credentials: None,
        fallback_models: None,
        oauth_command: None,
        metadata_source_provider: None,
        metadata_source_exclude: None,
        model_registry_aliases: None,
        live_model_metadata: None,
        auto_connect: None,
    };
}

/// One provider's metadata (`ProviderEntry`). Fields Python leaves out of
/// some rows are optional and omitted from the JSON when `None`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct ProviderEntry {
    /// Provider id.
    pub id: String,
    /// Display label.
    pub label: String,
    /// One-line description.
    pub description: String,
    /// How credentials are collected.
    pub kind: Kind,
    /// Primary credential variable.
    pub env_var: String,
    /// Every credential variable, in form order.
    pub env_vars: Vec<String>,
    /// The credential form.
    pub credentials: Vec<CredentialField>,
    /// Curated model list for providers without full live discovery.
    pub fallback_models: Vec<String>,
    /// CLI fallback hint for OAuth providers.
    pub oauth_command: String,
    /// Link to the key dashboard (or model documentation).
    pub docs_url: String,
    /// Catalog provider id to re-key models under, when it differs.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub models_dev_provider_id: Option<String>,
    /// Source provider for same-model-id metadata aliases.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub metadata_source_provider: Option<String>,
    /// Fields not shared with the source provider.
    pub metadata_source_exclude: Vec<String>,
    /// Target model to `provider:model` source.
    pub model_registry_aliases: IndexMap<String, String>,
    /// Whether discovery also returns per-model capabilities.
    pub live_model_metadata: bool,
    /// Whether catalog loads may contact the provider.
    pub auto_connect: bool,
    /// Whether the provider can mint a key through a browser sign-in.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub browser_login: Option<bool>,
    /// How much EvoFlux knows about the row.
    pub source: Source,
    /// Wire protocol, for rows derived from the registry or the catalog.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub transport: Option<String>,
}

/// An installed provider plugin, reduced to what the catalog reads
/// (`ProviderPlugin`). Its factory and login callbacks are not part of the
/// catalog.
#[derive(Debug, Clone)]
pub struct PluginProvider {
    /// Plugin id.
    pub id: String,
    /// Display label.
    pub label: String,
    /// One-line description.
    pub description: String,
    /// `ApiKey` or `Oauth`.
    pub kind: Kind,
    /// Credential fields; the first names the primary variable.
    pub credentials: Vec<CredentialField>,
    /// Curated model list.
    pub fallback_models: Vec<String>,
    /// Catalog provider id to read metadata under.
    pub models_dev_provider_id: String,
    /// Source provider for metadata aliases.
    pub metadata_source_provider: String,
    /// Target model to `provider:model` source.
    pub model_registry_aliases: IndexMap<String, String>,
    /// Key dashboard link.
    pub docs_url: String,
    /// CLI fallback hint.
    pub oauth_command: String,
    /// The plugin's own "is it configured" check. When absent, every
    /// required credential must be set.
    pub is_configured: Option<fn(&dyn CredentialLookup) -> bool>,
}

/// Suffixes models.dev uses for credential variables, with the label each
/// gets (`_CREDENTIAL_LABELS`), in the order they are tried.
const CREDENTIAL_LABELS: &[(&str, &str)] = &[
    ("_ACCESS_KEY_ID", "Access key ID"),
    ("_SECRET_ACCESS_KEY", "Secret access key"),
    ("_RESOURCE_NAME", "Resource name"),
    ("_BASE_URL", "Base URL"),
    ("_API_KEY", "API key"),
    ("_TOKEN", "Access token"),
    ("_REGION", "Region"),
    ("_PROJECT", "Project"),
    ("_LOCATION", "Location"),
    ("_KEY", "API key"),
];

/// Suffixes that name a setting rather than a secret (`_PUBLIC_SUFFIXES`).
const PUBLIC_SUFFIXES: &[&str] = &[
    "_BASE_URL",
    "_REGION",
    "_PROJECT",
    "_LOCATION",
    "_RESOURCE_NAME",
];

/// Python's `str.title()` for the ASCII environment names this is used on.
fn title_case(text: &str) -> String {
    let mut out = String::with_capacity(text.len());
    let mut previous_cased = false;
    for c in text.chars() {
        let cased = c.is_uppercase() || c.is_lowercase();
        if cased && previous_cased {
            out.extend(c.to_lowercase());
        } else if cased {
            out.extend(c.to_uppercase());
        } else {
            out.push(c);
        }
        previous_cased = cased;
    }
    out
}

/// A display label for one environment variable, and whether it is secret
/// (`_credential_label`). Anything not obviously a setting is secret.
fn credential_label(name: &str) -> (String, bool) {
    let upper = name.to_uppercase();
    for (suffix, label) in CREDENTIAL_LABELS {
        if upper.ends_with(suffix) {
            return ((*label).to_owned(), !PUBLIC_SUFFIXES.contains(suffix));
        }
    }
    (title_case(&name.replace('_', " ")), true)
}

/// A one-line description built from what the catalog states
/// (`_catalog_description`).
fn catalog_description(envelope: Option<&Envelope>, api: &str) -> String {
    let after_scheme = api.split_once("//").map_or(api, |(_, rest)| rest);
    let host = after_scheme.split('/').next().unwrap_or_default();
    let npm = envelope.and_then(|e| e.get("npm")).and_then(Value::as_str);
    match npm.and_then(|n| n.strip_prefix("@ai-sdk/")) {
        Some(adapter) => format!("{host} \u{2014} {adapter} API, from models.dev."),
        None => format!("{host} \u{2014} from the models.dev catalog."),
    }
}

fn kind_for_auth(auth: AuthKind) -> Kind {
    match auth {
        AuthKind::ApiKey => Kind::ApiKey,
        AuthKind::Oauth => Kind::Oauth,
        AuthKind::Local => Kind::Local,
        AuthKind::Cloud => Kind::CloudCreds,
    }
}

fn override_for(provider_id: &str) -> Option<&'static Override> {
    OVERRIDES
        .iter()
        .find(|(id, _)| *id == provider_id)
        .map(|(_, ov)| ov)
}

fn strings(items: &[&str]) -> Vec<String> {
    items.iter().map(|s| (*s).to_owned()).collect()
}

/// The provider catalog: models.dev envelopes (bundled, optionally overlaid
/// with a fetched payload), installed plugins, and the rows derived from
/// them.
#[derive(Debug)]
pub struct Catalog {
    envelopes: Envelopes,
    plugins: Vec<PluginProvider>,
    builtin: OnceLock<Vec<ProviderEntry>>,
    catalog_rows: OnceLock<Vec<ProviderEntry>>,
}

/// The shared catalog over the bundled data, with no fetched payload and no
/// plugins.
#[must_use]
pub fn catalog() -> &'static Catalog {
    static SHARED: OnceLock<Catalog> = OnceLock::new();
    SHARED.get_or_init(|| Catalog::new(None, Vec::new()))
}

impl Catalog {
    /// Build a catalog. `fetched` is a full models.dev payload (the cache
    /// file Python reads); its envelopes replace the bundled ones with the
    /// same id and add the rest. Of several plugins sharing an id the first
    /// wins.
    #[must_use]
    pub fn new(fetched: Option<&Value>, plugins: Vec<PluginProvider>) -> Self {
        let mut envelopes = bundled_envelopes().clone();
        if let Some(payload) = fetched {
            for (provider_id, envelope) in provider_envelopes(payload) {
                envelopes.insert(provider_id, envelope);
            }
        }
        let mut seen = HashSet::new();
        let plugins = plugins
            .into_iter()
            .filter(|plugin| seen.insert(plugin.id.clone()))
            .collect();
        Self {
            envelopes,
            plugins,
            builtin: OnceLock::new(),
            catalog_rows: OnceLock::new(),
        }
    }

    /// Every provider envelope, keyed by catalog id
    /// (`all_provider_envelopes`).
    #[must_use]
    pub fn all_provider_envelopes(&self) -> &Envelopes {
        &self.envelopes
    }

    /// One models.dev envelope, or `None` when unknown
    /// (`models_dev_provider_entry`).
    #[must_use]
    pub fn models_dev_provider_entry(&self, provider_id: &str) -> Option<&Envelope> {
        let normalized = provider_id.trim().to_lowercase();
        if normalized.is_empty() {
            return None;
        }
        self.envelopes.get(&normalized)
    }

    /// The envelope backing `config`, if the catalog lists it
    /// (`catalog_entry`).
    #[must_use]
    pub fn catalog_entry(&self, config: &ProviderConfig) -> Option<&Envelope> {
        self.models_dev_provider_entry(config.models_dev_provider_id())
    }

    /// The endpoint models.dev publishes for this provider, or `""`
    /// (`catalog_base_url`).
    #[must_use]
    pub fn catalog_base_url(&self, config: &ProviderConfig) -> String {
        let api = self
            .catalog_entry(config)
            .and_then(|e| e.get("api"))
            .and_then(Value::as_str)
            .map_or("", str::trim);
        if api.contains("${") {
            String::new()
        } else {
            api.to_owned()
        }
    }

    /// Credential variable names models.dev lists (`catalog_env_vars`).
    #[must_use]
    pub fn catalog_env_vars(&self, config: &ProviderConfig) -> Vec<String> {
        self.catalog_entry(config)
            .map(env_names)
            .unwrap_or_default()
    }

    /// The provider's model documentation per models.dev
    /// (`catalog_docs_url`).
    #[must_use]
    pub fn catalog_docs_url(&self, config: &ProviderConfig) -> String {
        self.catalog_entry(config)
            .and_then(|e| e.get("doc"))
            .and_then(Value::as_str)
            .map_or("", str::trim)
            .to_owned()
    }

    /// Display name: EvoFlux's own when set, else the catalog's
    /// (`provider_label`).
    #[must_use]
    pub fn provider_label(&self, config: &ProviderConfig) -> String {
        if !config.label.is_empty() {
            return config.label.clone();
        }
        self.catalog_entry(config)
            .and_then(|e| e.get("name"))
            .and_then(Value::as_str)
            .filter(|name| !name.is_empty())
            .map_or_else(|| config.id.clone(), str::to_owned)
    }

    /// Resolve `provider_id` against the curated registry, then models.dev
    /// (`resolve_provider`).
    #[must_use]
    pub fn resolve_provider(&self, provider_id: &str) -> Option<ProviderConfig> {
        let normalized = provider_id.trim().to_lowercase();
        if normalized.is_empty() {
            return None;
        }
        if let Some(curated) = crate::registry::get_provider_config(&normalized) {
            return Some(curated);
        }
        let entry = self.models_dev_provider_entry(&normalized)?;
        config_from_models_dev(&normalized, entry)
    }

    /// Resolve a credential: explicit value, then the environment under
    /// EvoFlux's name and every name models.dev lists, then the placeholder
    /// (`resolve_api_key`).
    #[must_use]
    pub fn resolve_api_key(
        &self,
        config: &ProviderConfig,
        explicit: Option<&str>,
        lookup: &dyn CredentialLookup,
    ) -> Option<String> {
        if let Some(key) = explicit.filter(|key| !key.is_empty()) {
            return Some(key.to_owned());
        }
        let names = std::iter::once(config.env_var.clone()).chain(self.catalog_env_vars(config));
        for name in names {
            if name.is_empty() {
                continue;
            }
            if let Some(value) = lookup.environ(&name).filter(|v| !v.is_empty()) {
                return Some(value);
            }
        }
        Some(config.default_api_key.clone()).filter(|key| !key.is_empty())
    }

    /// Resolve an endpoint: explicit, then the override variable, then the
    /// config, then the catalog (`resolve_base_url`).
    #[must_use]
    pub fn resolve_base_url(
        &self,
        config: &ProviderConfig,
        explicit: Option<&str>,
        lookup: &dyn CredentialLookup,
    ) -> String {
        if let Some(url) = explicit.map(str::trim).filter(|url| !url.is_empty()) {
            return url.to_owned();
        }
        if let Some(variable) = config.base_url_env_var.as_deref() {
            if let Some(value) = lookup.environ(variable) {
                let value = value.trim();
                if !value.is_empty() {
                    return value.to_owned();
                }
            }
        }
        if config.base_url.is_empty() {
            self.catalog_base_url(config)
        } else {
            config.base_url.clone()
        }
    }

    fn curated_credentials(&self, config: &ProviderConfig) -> Vec<CredentialField> {
        let mut fields = Vec::new();
        if !config.env_var.is_empty() {
            fields.push(CredentialField {
                name: config.env_var.clone(),
                label: format!("{} API key", config.label),
                secret: true,
                required: config.auth != AuthKind::Local,
                placeholder: String::new(),
            });
        }
        if let Some(variable) = config.base_url_env_var.as_deref().filter(|v| !v.is_empty()) {
            let placeholder = if config.base_url.is_empty() {
                self.catalog_base_url(config)
            } else {
                config.base_url.clone()
            };
            fields.push(CredentialField {
                name: variable.to_owned(),
                label: "Base URL".to_owned(),
                secret: false,
                required: false,
                placeholder,
            });
        }
        fields
    }

    fn curated_entry(&self, config: &ProviderConfig) -> ProviderEntry {
        let base_url = if config.base_url.is_empty() {
            self.catalog_base_url(config)
        } else {
            config.base_url.clone()
        };
        let docs_url = if config.docs_url.is_empty() {
            self.catalog_docs_url(config)
        } else {
            config.docs_url.clone()
        };
        let mut entry = ProviderEntry {
            id: config.id.clone(),
            label: self.provider_label(config),
            description: catalog_description(self.catalog_entry(config), &base_url),
            kind: kind_for_auth(config.auth),
            env_var: config.env_var.clone(),
            env_vars: Vec::new(),
            credentials: self.curated_credentials(config),
            fallback_models: Vec::new(),
            oauth_command: String::new(),
            docs_url,
            models_dev_provider_id: None,
            metadata_source_provider: None,
            metadata_source_exclude: Vec::new(),
            model_registry_aliases: IndexMap::new(),
            live_model_metadata: false,
            auto_connect: true,
            browser_login: Some(config.browser_login),
            source: Source::Builtin,
            transport: Some(config.transport.as_str().to_owned()),
        };
        // `models_dev_id` says where to read the catalog row; re-keying that
        // catalog provider's models under this id is right only for a rename,
        // not when the catalog id is itself a curated provider.
        if let Some(catalog_id) = config.models_dev_id.as_deref().filter(|id| !id.is_empty()) {
            if !is_curated(catalog_id) {
                entry.models_dev_provider_id = Some(catalog_id.to_owned());
            }
        }
        if let Some(ov) = override_for(&config.id) {
            apply_override(&mut entry, ov);
        }
        entry.env_vars = entry.credentials.iter().map(|f| f.name.clone()).collect();
        entry
    }

    /// Curated providers, in registry order, without plugins
    /// (`builtin_providers`).
    #[must_use]
    pub fn builtin_providers(&self) -> &[ProviderEntry] {
        self.builtin.get_or_init(|| {
            provider_registry()
                .iter()
                .map(|config| self.curated_entry(config))
                .collect()
        })
    }

    /// Every models.dev provider EvoFlux can reach, as settings rows,
    /// sorted by catalog id (`catalog_providers`). Curated providers and the
    /// catalog ids they claim are excluded.
    #[must_use]
    pub fn catalog_providers(&self) -> &[ProviderEntry] {
        self.catalog_rows.get_or_init(|| {
            let registry = provider_registry();
            let mut claimed: HashSet<String> = HashSet::new();
            for config in &registry {
                claimed.insert(config.id.clone());
                claimed.insert(config.models_dev_provider_id().to_owned());
            }
            claimed.extend(OVERRIDES.iter().map(|(id, _)| (*id).to_owned()));
            let mut ids: Vec<&String> = self.envelopes.keys().collect();
            ids.sort();
            ids.into_iter()
                .filter(|id| !claimed.contains(id.as_str()))
                .filter_map(|id| self.envelopes.get(id))
                .filter_map(catalog_entry_from_envelope)
                .collect()
        })
    }

    /// The full catalog in display order: curated, plugins, then the
    /// models.dev long tail unless `include_catalog` is false
    /// (`all_providers`).
    #[must_use]
    pub fn all_providers(&self, include_catalog: bool) -> Vec<ProviderEntry> {
        let mut entries = self.builtin_providers().to_vec();
        let mut known: HashSet<String> = entries.iter().map(|e| e.id.clone()).collect();
        for plugin in &self.plugins {
            if known.contains(&plugin.id) {
                continue;
            }
            entries.push(plugin_entry(plugin));
            known.insert(plugin.id.clone());
        }
        if include_catalog {
            entries.extend(
                self.catalog_providers()
                    .iter()
                    .filter(|entry| !known.contains(&entry.id))
                    .cloned(),
            );
        }
        entries
    }

    /// One entry by exact id, or `None` (`find`).
    #[must_use]
    pub fn find(&self, provider_id: &str) -> Option<ProviderEntry> {
        if let Some(entry) = self
            .builtin_providers()
            .iter()
            .find(|entry| entry.id == provider_id)
        {
            return Some(entry.clone());
        }
        if let Some(plugin) = self.plugin(provider_id) {
            return Some(plugin_entry(plugin));
        }
        self.catalog_providers()
            .iter()
            .find(|entry| entry.id == provider_id)
            .cloned()
    }

    /// Primary credential variable per curated provider
    /// (`provider_key_vars`).
    #[must_use]
    pub fn provider_key_vars(&self) -> IndexMap<String, String> {
        self.builtin_providers()
            .iter()
            .filter(|entry| !entry.env_var.is_empty())
            .map(|entry| (entry.id.clone(), entry.env_var.clone()))
            .collect()
    }

    /// The plugin installed under `provider_id`, if any.
    pub(crate) fn plugin(&self, provider_id: &str) -> Option<&PluginProvider> {
        self.plugins.iter().find(|plugin| plugin.id == provider_id)
    }
}

fn env_names(envelope: &Map<String, Value>) -> Vec<String> {
    envelope
        .get("env")
        .and_then(Value::as_array)
        .map(|names| {
            names
                .iter()
                .filter_map(Value::as_str)
                .filter(|name| !name.is_empty())
                .map(str::to_owned)
                .collect()
        })
        .unwrap_or_default()
}

fn apply_override(entry: &mut ProviderEntry, ov: &Override) {
    if let Some(text) = ov.description {
        entry.description = text.to_owned();
    }
    if let Some(kind) = ov.kind {
        entry.kind = kind;
    }
    if let Some(rows) = ov.credentials {
        entry.credentials = rows.iter().map(CredentialField::from).collect();
    }
    if let Some(models) = ov.fallback_models {
        entry.fallback_models = strings(models);
    }
    if let Some(command) = ov.oauth_command {
        entry.oauth_command = command.to_owned();
    }
    if let Some(source) = ov.metadata_source_provider {
        entry.metadata_source_provider = Some(source.to_owned());
    }
    if let Some(excluded) = ov.metadata_source_exclude {
        entry.metadata_source_exclude = strings(excluded);
    }
    if let Some(aliases) = ov.model_registry_aliases {
        entry.model_registry_aliases = aliases
            .iter()
            .map(|(k, v)| ((*k).to_owned(), (*v).to_owned()))
            .collect();
    }
    if let Some(flag) = ov.live_model_metadata {
        entry.live_model_metadata = flag;
    }
    if let Some(flag) = ov.auto_connect {
        entry.auto_connect = flag;
    }
}

fn plugin_entry(plugin: &PluginProvider) -> ProviderEntry {
    ProviderEntry {
        id: plugin.id.clone(),
        label: plugin.label.clone(),
        description: plugin.description.clone(),
        kind: plugin.kind,
        env_var: plugin
            .credentials
            .first()
            .map(|field| field.name.clone())
            .unwrap_or_default(),
        env_vars: plugin.credentials.iter().map(|f| f.name.clone()).collect(),
        credentials: plugin.credentials.clone(),
        fallback_models: plugin.fallback_models.clone(),
        oauth_command: plugin.oauth_command.clone(),
        docs_url: plugin.docs_url.clone(),
        models_dev_provider_id: Some(plugin.models_dev_provider_id.clone()),
        metadata_source_provider: Some(plugin.metadata_source_provider.clone()),
        metadata_source_exclude: Vec::new(),
        model_registry_aliases: plugin.model_registry_aliases.clone(),
        live_model_metadata: false,
        auto_connect: true,
        browser_login: None,
        source: Source::Plugin,
        transport: None,
    }
}

/// Build a settings row from one models.dev envelope
/// (`_catalog_entry_from_envelope`). `None` for an envelope EvoFlux cannot
/// connect from: no endpoint, an endpoint templated on credentials, or no
/// credential variable.
fn catalog_entry_from_envelope(envelope: &Envelope) -> Option<ProviderEntry> {
    let provider_id = envelope
        .get("id")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .trim()
        .to_lowercase();
    if provider_id.is_empty() {
        return None;
    }
    let api = envelope
        .get("api")
        .and_then(Value::as_str)
        .map_or("", str::trim);
    if api.is_empty() || api.contains("${") {
        return None;
    }
    let names = env_names(envelope);
    if names.is_empty() {
        return None;
    }
    let mut credentials: Vec<CredentialField> = names
        .iter()
        .enumerate()
        .map(|(index, name)| {
            let (label, secret) = credential_label(name);
            CredentialField {
                name: name.clone(),
                label,
                secret,
                required: index == 0,
                placeholder: String::new(),
            }
        })
        .collect();
    let base_url_var = derived_base_url_env_var(&provider_id);
    if !names.contains(&base_url_var) {
        credentials.push(CredentialField {
            name: base_url_var.clone(),
            label: "Base URL".to_owned(),
            secret: false,
            required: false,
            placeholder: api.to_owned(),
        });
    }
    let mut env_vars = names.clone();
    env_vars.push(base_url_var);
    let docs_url = envelope
        .get("doc")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_owned();
    let label = envelope
        .get("name")
        .and_then(Value::as_str)
        .filter(|name| !name.is_empty())
        .unwrap_or(&provider_id)
        .to_owned();
    let transport = transport_for_npm(envelope.get("npm").and_then(Value::as_str));
    Some(ProviderEntry {
        id: provider_id.clone(),
        label,
        description: catalog_description(Some(envelope), api),
        kind: Kind::ApiKey,
        env_var: names.first().cloned().unwrap_or_default(),
        env_vars,
        credentials,
        fallback_models: Vec::new(),
        oauth_command: String::new(),
        docs_url,
        models_dev_provider_id: Some(provider_id),
        metadata_source_provider: None,
        metadata_source_exclude: Vec::new(),
        model_registry_aliases: IndexMap::new(),
        live_model_metadata: false,
        // Opening the settings page must not fan out to 160-odd endpoints.
        auto_connect: false,
        browser_login: None,
        source: Source::Catalog,
        transport: Some(transport.as_str().to_owned()),
    })
}
