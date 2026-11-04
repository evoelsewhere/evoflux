//! Port of `_provider_is_configured` in `app/api/routes/settings.py`: the
//! synchronous, static check of whether the user's environment holds
//! credentials for a provider. It never probes a daemon or the network.
//!
//! Python reads three places: `os.environ`, the credential store (the
//! process environment, then the saved `.env`) and the OAuth token files in
//! the cache directory. [`CredentialLookup`] is that surface, so the caller
//! decides where the values come from; [`EnvMap`] is the in-memory
//! implementation.

use std::collections::{HashMap, HashSet};

use crate::catalog::{Catalog, Kind, ProviderEntry};

/// Where the configured check reads credentials from.
pub trait CredentialLookup {
    /// `os.environ.get(name)`: the process environment only. The value may
    /// be empty; callers treat empty as unset.
    fn environ(&self, name: &str) -> Option<String>;

    /// `ProviderCredentialStore.get(name)`: the process environment, then
    /// the saved `.env`. Empty when neither holds a non-empty value.
    fn stored(&self, name: &str) -> String;

    /// Whether `<cache dir>/<file_name>` is a regular file.
    fn cache_file_exists(&self, file_name: &str) -> bool;
}

/// An in-memory [`CredentialLookup`].
#[derive(Debug, Default, Clone)]
pub struct EnvMap {
    /// The process environment.
    pub environ: HashMap<String, String>,
    /// The saved `.env` values.
    pub saved: HashMap<String, String>,
    /// File names present in the cache directory.
    pub cache_files: HashSet<String>,
}

impl CredentialLookup for EnvMap {
    fn environ(&self, name: &str) -> Option<String> {
        self.environ.get(name).cloned()
    }

    fn stored(&self, name: &str) -> String {
        [self.environ.get(name), self.saved.get(name)]
            .into_iter()
            .flatten()
            .find(|value| !value.is_empty())
            .cloned()
            .unwrap_or_default()
    }

    fn cache_file_exists(&self, file_name: &str) -> bool {
        self.cache_files.contains(file_name)
    }
}

/// Variables the Copilot provider accepts when its OAuth cache is missing.
const COPILOT_TOKEN_VARIABLES: [&str; 4] = [
    "COPILOT_GITHUB_TOKEN",
    "GH_TOKEN",
    "GITHUB_TOKEN",
    "GITHUB_COPILOT_TOKEN",
];

/// OAuth token cache file per provider.
const OAUTH_TOKEN_FILES: [(&str, &str); 2] = [
    ("codex", "codex_oauth.json"),
    ("copilot", "copilot_oauth.json"),
];

fn environ_set(lookup: &dyn CredentialLookup, name: &str) -> bool {
    lookup.environ(name).is_some_and(|value| !value.is_empty())
}

/// The environment value if set, else the stored one, as one truthiness
/// check (`os.environ.get(x) or store.get(x)`).
fn environ_or_stored(lookup: &dyn CredentialLookup, name: &str) -> bool {
    environ_set(lookup, name) || !lookup.stored(name).is_empty()
}

impl Catalog {
    /// Whether the provider `provider_id` is configured. An unknown id is
    /// not configured.
    #[must_use]
    pub fn is_configured(&self, provider_id: &str, lookup: &dyn CredentialLookup) -> bool {
        self.find(provider_id)
            .is_some_and(|entry| self.is_entry_configured(&entry, lookup))
    }

    /// Whether the user's credentials cover `entry`.
    #[must_use]
    pub fn is_entry_configured(
        &self,
        entry: &ProviderEntry,
        lookup: &dyn CredentialLookup,
    ) -> bool {
        // A plugin installed under this id decides, even over a curated row.
        if let Some(plugin) = self.plugin(&entry.id) {
            if let Some(check) = plugin.is_configured {
                return check(lookup);
            }
            return plugin
                .credentials
                .iter()
                .filter(|field| field.required)
                .all(|field| !lookup.stored(&field.name).is_empty());
        }
        match entry.kind {
            Kind::Local => true,
            Kind::Oauth => oauth_configured(&entry.id, lookup),
            Kind::CloudCreds => cloud_configured(entry, lookup),
            Kind::ApiKey => !entry.env_var.is_empty() && !lookup.stored(&entry.env_var).is_empty(),
        }
    }
}

fn oauth_configured(provider_id: &str, lookup: &dyn CredentialLookup) -> bool {
    if provider_id == "copilot"
        && COPILOT_TOKEN_VARIABLES
            .iter()
            .any(|name| environ_set(lookup, name))
    {
        return true;
    }
    OAUTH_TOKEN_FILES
        .iter()
        .find(|(id, _)| *id == provider_id)
        .is_some_and(|(_, file)| lookup.cache_file_exists(file))
}

fn cloud_configured(entry: &ProviderEntry, lookup: &dyn CredentialLookup) -> bool {
    match entry.id.as_str() {
        // The store also consults the saved `.env`, which survives a restart.
        "foundry" => {
            !lookup.stored("FOUNDRY_API_KEY").is_empty()
                && !lookup.stored("FOUNDRY_RESOURCE_NAME").is_empty()
        }
        "bedrock" => {
            environ_or_stored(lookup, "AWS_BEDROCK_PROFILE")
                || (environ_or_stored(lookup, "AWS_ACCESS_KEY_ID")
                    && environ_or_stored(lookup, "AWS_SECRET_ACCESS_KEY"))
        }
        // Vertex AI also needs gcloud ADC, which this check cannot see; the
        // UI's "Test connection" button is the source of truth.
        _ => entry.env_vars.iter().all(|name| environ_set(lookup, name)),
    }
}
