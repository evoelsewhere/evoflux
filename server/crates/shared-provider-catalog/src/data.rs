//! The models.dev data bundled with the server, for offline cold starts.
//!
//! Port of `_bundled_provider_envelopes` and `provider_envelopes` in
//! `app/agent/providers/model_registry.py`. Both files are copies of the
//! ones the Python package ships; a test fails when they drift apart. See
//! `NOTES.md` for the refresh source and the size.

use std::sync::OnceLock;

use indexmap::IndexMap;
use serde_json::{Map, Value};

/// Provider envelopes (`id`, `name`, `env`, `npm`, `api`, `doc`) by catalog
/// id, as `app/agent/providers/provider_catalog.json` (about 42 KB).
const PROVIDER_CATALOG_JSON: &str = include_str!("../data/provider_catalog.json");

/// Flattened per-model metadata keyed by `provider:model`, as
/// `app/agent/providers/model_registry.json` (about 4.4 MB).
const MODEL_REGISTRY_JSON: &str = include_str!("../data/model_registry.json");

/// Provider-envelope fields worth keeping (`PROVIDER_ENVELOPE_FIELDS`).
const ENVELOPE_FIELDS: [&str; 6] = ["id", "name", "env", "npm", "api", "doc"];

/// One provider envelope.
pub type Envelope = Map<String, Value>;

/// Envelopes by lower-cased catalog id, in insertion order.
pub type Envelopes = IndexMap<String, Envelope>;

/// The raw bundled `provider_catalog.json` text.
#[must_use]
pub fn bundled_provider_catalog_json() -> &'static str {
    PROVIDER_CATALOG_JSON
}

/// The raw bundled `model_registry.json` text.
#[must_use]
pub fn bundled_model_registry_json() -> &'static str {
    MODEL_REGISTRY_JSON
}

/// The bundled model metadata, keyed by `provider:model`. Parsed on first
/// use; empty if the embedded text were ever unreadable.
#[must_use]
pub fn bundled_model_registry() -> &'static Map<String, Value> {
    static PARSED: OnceLock<Map<String, Value>> = OnceLock::new();
    PARSED.get_or_init(|| match serde_json::from_str(MODEL_REGISTRY_JSON) {
        Ok(Value::Object(map)) => map,
        _ => Map::new(),
    })
}

/// Parse a `{id: envelope}` document the way Python's
/// `_bundled_provider_envelopes` does: keys lower-cased, non-object values
/// dropped, anything else (not an object, bad JSON) empty.
pub(crate) fn envelopes_from_text(text: &str) -> Envelopes {
    let Ok(Value::Object(parsed)) = serde_json::from_str::<Value>(text) else {
        return Envelopes::new();
    };
    parsed
        .into_iter()
        .filter_map(|(key, value)| match value {
            Value::Object(envelope) => Some((key.to_lowercase(), envelope)),
            _ => None,
        })
        .collect()
}

/// The envelopes shipped with the package.
pub(crate) fn bundled_envelopes() -> &'static Envelopes {
    static PARSED: OnceLock<Envelopes> = OnceLock::new();
    PARSED.get_or_init(|| envelopes_from_text(PROVIDER_CATALOG_JSON))
}

/// Extract the provider-level rows from a full models.dev payload
/// (`provider_envelopes`): only [`ENVELOPE_FIELDS`] are kept, and the id is
/// the provider's `id` (or its key) lower-cased.
#[must_use]
pub fn provider_envelopes(data: &Value) -> Envelopes {
    let Value::Object(providers) = data else {
        return Envelopes::new();
    };
    let mut out = Envelopes::new();
    for (key, provider) in providers {
        let Value::Object(provider) = provider else {
            continue;
        };
        let provider_id = match provider.get("id") {
            Some(Value::String(id)) if !id.is_empty() => id.clone(),
            Some(Value::Number(id)) if id.as_f64() != Some(0.0) => id.to_string(),
            Some(Value::Bool(true)) => "True".to_owned(),
            _ => key.clone(),
        }
        .to_lowercase();
        let mut envelope = Envelope::new();
        for field in ENVELOPE_FIELDS {
            if let Some(value) = provider.get(field) {
                envelope.insert(field.to_owned(), value.clone());
            }
        }
        envelope.insert("id".to_owned(), Value::String(provider_id.clone()));
        out.insert(provider_id, envelope);
    }
    out
}
