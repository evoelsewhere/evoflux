//! Provider settings for the desktop host: the catalog rows the Providers page
//! renders, the credentials and overrides it saves, and live model discovery.
//!
//! Storage is split by sensitivity:
//! - secrets live in `auth.json` (the owner-only credential store): API keys,
//!   OAuth tokens, Bedrock IAM keys (encoded as one opaque credential);
//! - everything else lives in the application database ([`crate::app_db`]):
//!   `provider_settings` (enabled, base-URL override, non-secret options such
//!   as the Codex account header), `provider_models` (models the provider
//!   reported, and deployments the user added) and `provider_discovery`.
//!
//! Models and their metadata come from models.dev ([`crate::models_dev`]).
//! Turning a catalog row into something runnable is
//! [`evo_runtime::provider_catalog`]'s job; this module only feeds it the
//! host-owned state. Saving never restarts the engine: callers hot-swap
//! provider runtimes through [`crate::session::reload_providers`].

use std::collections::BTreeMap;
use std::sync::OnceLock;

use evo_ai::providers::bedrock::{
    decode_iam_credential, encode_iam_credential, region_of, IamCredential,
};
use evo_runtime::models_dev::ModelsDev;
use evo_runtime::provider_catalog::{
    self, AuthKind, CatalogProvider, DiscoveredModel, ProviderState,
};
use serde_json::{json, Value};

use crate::config::{self, Credential};

/// Per-provider state the user set, other than secrets.
#[derive(Clone, Debug, Default)]
pub struct SavedProvider {
    pub base_url: Option<String>,
    pub enabled: bool,
    /// Non-secret options (`headers`, `region`, `account`).
    pub options: Value,
    /// Headers from `options.headers`, ready for declarations.
    pub headers: BTreeMap<String, String>,
    /// Models the provider reported plus user-added ones (minus hidden).
    pub models: Option<Vec<DiscoveredModel>>,
    /// User-added model ids (Foundry deployments).
    pub custom: Vec<String>,
    pub discovered_at: Option<i64>,
    pub discovery_error: Option<String>,
}

#[derive(Clone, Debug, Default)]
pub struct ProviderStore {
    pub providers: BTreeMap<String, SavedProvider>,
}

fn now() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0)
}

fn db() -> Result<rusqlite::Connection, String> {
    crate::app_db::open().map_err(|error| error.to_string())
}

fn read_store(db: &rusqlite::Connection) -> rusqlite::Result<ProviderStore> {
    let mut store = ProviderStore::default();
    let mut settings = db.prepare(
        "SELECT s.provider_id, s.enabled, s.base_url, s.options_json, d.status, d.error, d.last_success_at
         FROM provider_settings s LEFT JOIN provider_discovery d USING (provider_id)",
    )?;
    let rows = settings.query_map([], |row| {
        let options: Value = serde_json::from_str(&row.get::<_, String>(3)?).unwrap_or(json!({}));
        let headers = options
            .get("headers")
            .and_then(|h| serde_json::from_value(h.clone()).ok())
            .unwrap_or_default();
        let status: Option<String> = row.get(4)?;
        Ok((
            row.get::<_, String>(0)?,
            SavedProvider {
                enabled: row.get(1)?,
                base_url: row.get(2)?,
                options,
                headers,
                models: None,
                custom: Vec::new(),
                discovered_at: row.get(6)?,
                discovery_error: if status.as_deref() == Some("error") {
                    row.get(5)?
                } else {
                    None
                },
            },
        ))
    })?;
    for row in rows {
        let (id, saved) = row?;
        store.providers.insert(id, saved);
    }
    let mut models = db.prepare(
        "SELECT provider_id, model_id, display_name, source, metadata_json FROM provider_models
         WHERE hidden = 0 ORDER BY provider_id, position, model_id",
    )?;
    let rows = models.query_map([], |row| {
        let metadata: Option<String> = row.get(4)?;
        let mut model: DiscoveredModel = metadata
            .and_then(|text| serde_json::from_str(&text).ok())
            .unwrap_or_default();
        model.id = row.get(1)?;
        model.name = model.name.or(row.get(2)?);
        Ok((row.get::<_, String>(0)?, row.get::<_, String>(3)?, model))
    })?;
    for row in rows {
        let (id, source, model) = row?;
        if let Some(saved) = store.providers.get_mut(&id) {
            if source == "custom" {
                saved.custom.push(model.id.clone());
            }
            saved.models.get_or_insert_with(Vec::new).push(model);
        }
    }
    Ok(store)
}

/// Saved provider state. An unreadable database degrades to "nothing saved"
/// (logged) so the engine still starts and providers still resolve from
/// keys and the environment.
pub fn load_store() -> ProviderStore {
    match db().and_then(|db| read_store(&db).map_err(|error| error.to_string())) {
        Ok(store) => store,
        Err(error) => {
            eprintln!("warning: provider settings unavailable: {error}");
            ProviderStore::default()
        }
    }
}

fn ensure_row(tx: &rusqlite::Transaction<'_>, provider: &str) -> rusqlite::Result<()> {
    tx.execute(
        "INSERT INTO provider_settings (provider_id, enabled, created_at, updated_at)
         VALUES (?1, 0, ?2, ?2) ON CONFLICT (provider_id) DO NOTHING",
        rusqlite::params![provider, now()],
    )?;
    Ok(())
}

fn transact(
    write: impl FnOnce(&rusqlite::Transaction<'_>) -> rusqlite::Result<()>,
) -> Result<(), String> {
    let mut db = db()?;
    // IMMEDIATE: take evo.db's write lock up front, waiting out the busy
    // timeout. A deferred transaction reads first and fails at once with
    // "database is locked" when it upgrades after another process wrote.
    let tx = db
        .transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)
        .map_err(|error| error.to_string())?;
    write(&tx).map_err(|error| error.to_string())?;
    tx.commit().map_err(|error| error.to_string())
}

/// Save the endpoint the host learned for `provider` (Copilot's per-account
/// API host). Discovered models are kept: the same account serves them.
pub fn set_base_url(provider: &str, url: Option<&str>) -> Result<(), String> {
    transact(|tx| {
        ensure_row(tx, provider)?;
        tx.execute(
            "UPDATE provider_settings SET base_url = ?2 WHERE provider_id = ?1",
            rusqlite::params![provider, url.filter(|url| !url.is_empty())],
        )?;
        Ok(())
    })
}

/// One saved option of `provider` (see [`set_options`]).
pub fn option(provider: &str, key: &str) -> Option<Value> {
    load_store()
        .providers
        .get(provider)?
        .options
        .get(key)
        .cloned()
}

/// Merge `patch` into `provider`'s options (a `null` value removes a key).
pub fn set_options(provider: &str, patch: Value) -> Result<(), String> {
    transact(|tx| {
        ensure_row(tx, provider)?;
        let current: String = tx.query_row(
            "SELECT options_json FROM provider_settings WHERE provider_id = ?1",
            [provider],
            |row| row.get(0),
        )?;
        let mut options: Value = serde_json::from_str(&current).unwrap_or(json!({}));
        if let (Some(target), Some(patch)) = (options.as_object_mut(), patch.as_object()) {
            for (key, value) in patch {
                if value.is_null() {
                    target.remove(key);
                } else {
                    target.insert(key.clone(), value.clone());
                }
            }
        }
        tx.execute(
            "UPDATE provider_settings SET options_json = ?2, enabled = 1, updated_at = ?3 WHERE provider_id = ?1",
            rusqlite::params![provider, options.to_string(), now()],
        )?;
        Ok(())
    })
}

/// Stable per-process id for providers that require a session header.
pub fn session_id() -> &'static str {
    static ID: OnceLock<String> = OnceLock::new();
    ID.get_or_init(|| format!("evo-v1:{}", uuid::Uuid::new_v4().simple()))
}

fn state_of<'a>(saved: Option<&'a SavedProvider>, db: &'a ModelsDev) -> ProviderState<'a> {
    ProviderState {
        base_url: saved.and_then(|saved| saved.base_url.as_deref()),
        discovered: saved.and_then(|saved| saved.models.as_deref()),
        headers: saved.map(|saved| &saved.headers),
        session_id: session_id(),
        models_dev: Some(db),
    }
}

/// Whether a catalog provider takes part in resolution. Keyless local
/// providers only once the user connected them, so an absent daemon does not
/// count as a ready provider.
fn participates(provider: &CatalogProvider, saved: Option<&SavedProvider>) -> bool {
    !provider.anonymous || saved.is_some_and(|saved| saved.enabled)
}

/// Provider manifests for every connectable catalog provider. Hosts declare
/// these before package manifests, so an installed package replaces a
/// catalog entry with the same id.
pub fn manifests() -> Vec<evo_extensions::ProviderManifest> {
    let store = load_store();
    let db = crate::models_dev::current();
    let values = crate::provider::CliValues;
    provider_catalog::catalog()
        .providers
        .iter()
        .filter(|provider| participates(provider, store.providers.get(&provider.id)))
        .filter_map(|provider| {
            provider.declaration(&state_of(store.providers.get(&provider.id), &db), &values)
        })
        .map(|declaration| evo_extensions::ProviderManifest {
            id: declaration.id,
            models: declaration.models,
            api_key_env: declaration.api_key_env,
            requires_auth: declaration.requires_auth,
        })
        .collect()
}

/// Catalog manifests followed by `packages`, a package winning on an id clash.
pub fn with_catalog(
    packages: &[evo_extensions::ProviderManifest],
) -> Vec<evo_extensions::ProviderManifest> {
    let mut all: Vec<_> = manifests()
        .into_iter()
        .filter(|manifest| !packages.iter().any(|package| package.id == manifest.id))
        .collect();
    all.extend(packages.iter().cloned());
    all
}

fn kind_label(kind: AuthKind) -> &'static str {
    match kind {
        AuthKind::ApiKey => "api_key",
        AuthKind::Oauth => "oauth",
        AuthKind::Local => "local",
        AuthKind::Cloud => "cloud",
    }
}

/// The credential form a provider's row offers. Never carries a secret.
fn fields(
    provider: &CatalogProvider,
    saved: Option<&SavedProvider>,
    stored: Option<&Credential>,
    env_key: Option<String>,
) -> Vec<Value> {
    let stored_key = match stored {
        Some(Credential::ApiKey { key: Some(key), .. }) if !key.trim().is_empty() => {
            Some(key.as_str())
        }
        _ => None,
    };
    let iam = stored_key.and_then(decode_iam_credential);
    let profile = stored_key.and_then(|key| {
        key.strip_prefix(evo_ai::providers::aws_credentials::PROFILE_CREDENTIAL_PREFIX)
    });
    let secret = |name: &str,
                  label: &str,
                  required: bool,
                  has: bool,
                  env: Option<&str>,
                  from_env: Option<String>| {
        json!({"name": name, "label": label, "secret": true, "required": required,
               "env": env, "hasValue": has, "fromEnv": if has { None } else { from_env }})
    };
    let text = |name: &str,
                label: &str,
                required: bool,
                value: Option<String>,
                placeholder: &str,
                env: Option<&str>| {
        json!({"name": name, "label": label, "secret": false, "required": required,
               "env": env, "value": value, "placeholder": placeholder})
    };
    match (provider.login.as_deref(), provider.endpoint.as_deref()) {
        (Some(_), _) => Vec::new(),
        (_, Some("bedrock")) => {
            let region = saved
                .and_then(|saved| saved.base_url.as_deref())
                .and_then(region_of);
            vec![
                text(
                    "region",
                    "Region",
                    false,
                    region,
                    "us-east-1",
                    Some("AWS_REGION"),
                ),
                // A named profile from ~/.aws: keys, credential_process or SSO.
                text(
                    "profile",
                    "AWS profile (~/.aws: SSO, credential_process or keys)",
                    false,
                    profile.map(|p| {
                        if p.is_empty() {
                            "default".to_string()
                        } else {
                            p.to_string()
                        }
                    }),
                    "default",
                    Some("AWS_PROFILE"),
                ),
                secret(
                    "apiKey",
                    "Bedrock API key",
                    false,
                    stored_key.is_some() && iam.is_none() && profile.is_none(),
                    Some("AWS_BEARER_TOKEN_BEDROCK"),
                    env_key,
                ),
                secret(
                    "accessKeyId",
                    "Access key ID",
                    false,
                    iam.is_some(),
                    None,
                    None,
                ),
                secret(
                    "secretAccessKey",
                    "Secret access key",
                    false,
                    iam.is_some(),
                    None,
                    None,
                ),
                secret(
                    "sessionToken",
                    "Session token (optional)",
                    false,
                    iam.as_ref().is_some_and(|iam| iam.session_token.is_some()),
                    None,
                    None,
                ),
            ]
        }
        (_, Some("vertex")) => {
            let (project, location) = saved
                .and_then(|saved| saved.base_url.as_deref())
                .and_then(provider_catalog::vertex_parts)
                .unzip();
            vec![
                secret(
                    "apiKey",
                    "Google Cloud API key",
                    true,
                    stored_key.is_some(),
                    provider.api_key_env.as_deref(),
                    env_key,
                ),
                text(
                    "project",
                    "Project ID (optional — empty for express mode)",
                    false,
                    project,
                    "my-gcp-project",
                    Some("GOOGLE_CLOUD_PROJECT"),
                ),
                text(
                    "location",
                    "Location",
                    false,
                    location,
                    "global",
                    Some("GOOGLE_CLOUD_LOCATION"),
                ),
            ]
        }
        (_, Some("foundry")) => vec![
            text(
                "baseUrl",
                "Resource name or endpoint URL",
                true,
                saved.and_then(|saved| saved.base_url.clone()),
                "my-resource or https://my-resource.services.ai.azure.com",
                provider.base_url_env.as_deref(),
            ),
            secret(
                "apiKey",
                "API key",
                true,
                stored_key.is_some(),
                provider.api_key_env.as_deref(),
                env_key,
            ),
            text(
                "deployments",
                "Deployments",
                true,
                saved
                    .map(|saved| saved.custom.join(", "))
                    .filter(|list| !list.is_empty()),
                "gpt-5.1, claude-sonnet-4-6",
                None,
            ),
        ],
        _ => {
            let mut out = Vec::new();
            if provider.api_key_env.is_some() {
                out.push(secret(
                    "apiKey",
                    if provider.anonymous {
                        "API key (optional)"
                    } else {
                        "API key"
                    },
                    !provider.anonymous,
                    stored_key.is_some(),
                    provider.api_key_env.as_deref(),
                    env_key,
                ));
            }
            out.push(text(
                "baseUrl",
                "Base URL",
                false,
                saved.and_then(|saved| saved.base_url.clone()),
                &provider.base_url,
                provider.base_url_env.as_deref(),
            ));
            out
        }
    }
}

/// The rows of the Providers page.
pub fn list(packages: &[evo_extensions::ProviderManifest]) -> Value {
    let store = load_store();
    let auth = config::read_auth().unwrap_or_default();
    let models_cfg = config::load_models_config().unwrap_or_default();
    let manifests = with_catalog(packages);
    let states = crate::credentials::statuses(&models_cfg, &auth, &manifests);
    let values = crate::provider::CliValues;
    let db = crate::models_dev::current();
    let catalog = provider_catalog::catalog();
    let logins = crate::provider_login::snapshot();

    let rows: Vec<Value> = catalog
        .providers
        .iter()
        .map(|provider| {
            let saved = store.providers.get(&provider.id);
            let state = states.get(&provider.id);
            let ready = state.is_some_and(|state| state.is_ready());
            let connected = provider.supported
                && if provider.anonymous {
                    saved.is_some_and(|saved| saved.enabled)
                } else {
                    ready
                };
            let env_key = provider.key_env(&values).filter(|name| {
                evo_runtime::ValueSource::env(&values, name).is_some_and(|v| !v.trim().is_empty())
            });
            let state_of = state_of(saved, &db);
            let model_count = if provider.supported {
                provider.models(&state_of, &values).len()
            } else {
                0
            };
            json!({
                "id": provider.id,
                "label": provider.label,
                "description": provider.description,
                "kind": kind_label(provider.auth),
                "api": provider.api,
                "source": provider.source,
                "supported": provider.supported,
                "unsupportedReason": provider.unsupported_reason,
                "recommended": provider_catalog::rank(&provider.id) < catalog.recommended.len(),
                "rank": provider_catalog::rank(&provider.id),
                "docsUrl": provider.docs_url,
                "modelsDocUrl": provider.models_doc_url,
                "baseUrl": provider.effective_base_url(&state_of, &values),
                "login": provider.login,
                "keyLogin": provider.key_login,
                "usage": crate::provider_usage::supported(&provider.id),
                "loginState": logins.get(&provider.id),
                "account": saved.and_then(|saved| saved.options.get("account").cloned()),
                "connected": connected,
                "status": state.map(|state| state.status),
                "credentialSource": state.map(|state| state.source.as_json_str().to_string()),
                "modelCount": model_count,
                "discoveredAt": saved.and_then(|saved| saved.discovered_at),
                "discoveryError": saved.and_then(|saved| saved.discovery_error.clone()),
                "fields": fields(provider, saved, auth.get(&provider.id), env_key),
            })
        })
        .collect();
    let connected = rows
        .iter()
        .filter(|row| row["connected"].as_bool() == Some(true))
        .count();
    json!({
        "providers": rows,
        "recommended": catalog.recommended,
        "connected": connected,
        "modelsDev": crate::models_dev::status(),
    })
}

pub fn find(provider: &str) -> Result<&'static CatalogProvider, String> {
    provider_catalog::find(provider).ok_or_else(|| format!("unknown provider: {provider}"))
}

/// The endpoint `provider` uses now (saved override, environment, catalog).
pub fn base_url_of(provider: &CatalogProvider) -> String {
    let store = load_store();
    let db = crate::models_dev::current();
    let state = state_of(store.providers.get(&provider.id), &db);
    provider.effective_base_url(&state, &crate::provider::CliValues)
}

/// Field values from the settings form. Absent fields are left as they are;
/// an empty string clears a value.
pub type ProviderChange = BTreeMap<String, String>;

fn save_key(provider: &str, key: &str) -> Result<(), String> {
    if key.is_empty() {
        config::delete_credential(provider).map(|_| ())
    } else {
        config::upsert_credential(
            provider,
            Credential::ApiKey {
                key: Some(key.to_string()),
                env: None,
            },
        )
    }
    .map_err(|error| error.to_string())
}

fn validate_url(url: &str) -> Result<(), String> {
    let parsed = reqwest::Url::parse(url).map_err(|_| "Base URL is not a valid URL".to_string())?;
    if !matches!(parsed.scheme(), "http" | "https") {
        return Err("Base URL must start with http:// or https://".into());
    }
    Ok(())
}

/// Save `change` for `provider`.
pub fn apply(provider: &CatalogProvider, change: &ProviderChange) -> Result<(), String> {
    if !provider.supported {
        return Err(provider
            .unsupported_reason
            .clone()
            .unwrap_or_else(|| format!("{} is not available yet", provider.label)));
    }
    let get = |name: &str| change.get(name).map(|value| value.trim().to_string());
    let mut base_url = get("baseUrl").map(|url| url.trim_end_matches('/').to_string());

    match provider.endpoint.as_deref() {
        Some("bedrock") => {
            let access = get("accessKeyId").filter(|v| !v.is_empty());
            let secret = get("secretAccessKey").filter(|v| !v.is_empty());
            match (access, secret) {
                (Some(access_key_id), Some(secret_access_key)) => save_key(
                    &provider.id,
                    &encode_iam_credential(&IamCredential {
                        access_key_id,
                        secret_access_key,
                        session_token: get("sessionToken").filter(|v| !v.is_empty()),
                    }),
                )?,
                (Some(_), None) | (None, Some(_)) => {
                    return Err("Enter both the access key ID and the secret access key".into())
                }
                (None, None) => {
                    if let Some(key) = get("apiKey").filter(|key| !key.is_empty()) {
                        save_key(&provider.id, &key)?;
                    } else if let Some(profile) = get("profile").filter(|p| !p.trim().is_empty()) {
                        let profile = profile.trim();
                        if profile
                            .chars()
                            .any(|c| c.is_whitespace() || c == '[' || c == ']')
                        {
                            return Err("A profile name has no spaces or brackets".into());
                        }
                        save_key(
                            &provider.id,
                            &format!(
                                "{}{profile}",
                                evo_ai::providers::aws_credentials::PROFILE_CREDENTIAL_PREFIX
                            ),
                        )?;
                    }
                }
            }
            if let Some(region) = get("region") {
                if !region.is_empty()
                    && !region
                        .chars()
                        .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '-')
                {
                    return Err("Region looks like us-east-1".into());
                }
                base_url = Some(if region.is_empty() {
                    String::new()
                } else {
                    provider_catalog::bedrock_base_url(&region)
                });
            }
        }
        Some("foundry") => {
            if let Some(key) = get("apiKey") {
                save_key(&provider.id, &key)?;
            }
        }
        Some("vertex") => {
            if let Some(key) = get("apiKey") {
                save_key(&provider.id, &key)?;
            }
            if get("project").is_some() || get("location").is_some() {
                let valid =
                    |value: &str| value.chars().all(|c| c.is_ascii_alphanumeric() || c == '-');
                let project = get("project").unwrap_or_default();
                let location = get("location").unwrap_or_default();
                if !valid(project.trim()) || !valid(location.trim()) {
                    return Err(
                        "Project and location are ids like my-project and us-central1".into(),
                    );
                }
                base_url = Some(provider_catalog::vertex_base_url(&project, &location));
            }
        }
        _ => {
            if let Some(key) = get("apiKey") {
                save_key(&provider.id, &key)?;
            }
            if let Some(url) = base_url.as_deref().filter(|url| !url.is_empty()) {
                validate_url(url)?;
            }
        }
    }
    let deployments: Option<Vec<String>> = get("deployments").map(|list| {
        list.split([',', '\n'])
            .map(str::trim)
            .filter(|id| !id.is_empty())
            .map(str::to_string)
            .collect()
    });

    transact(|tx| {
        ensure_row(tx, &provider.id)?;
        if let Some(url) = base_url.as_deref() {
            let previous: Option<String> = tx.query_row(
                "SELECT base_url FROM provider_settings WHERE provider_id = ?1",
                [&provider.id],
                |row| row.get(0),
            )?;
            if previous.as_deref().unwrap_or("") != url {
                // Another endpoint may serve other models.
                tx.execute(
                    "DELETE FROM provider_models WHERE provider_id = ?1 AND source = 'discovered'",
                    [&provider.id],
                )?;
                tx.execute(
                    "DELETE FROM provider_discovery WHERE provider_id = ?1",
                    [&provider.id],
                )?;
            }
            tx.execute(
                "UPDATE provider_settings SET base_url = ?2 WHERE provider_id = ?1",
                rusqlite::params![provider.id, (!url.is_empty()).then_some(url)],
            )?;
        }
        if let Some(deployments) = &deployments {
            tx.execute(
                "DELETE FROM provider_models WHERE provider_id = ?1 AND source = 'custom'",
                [&provider.id],
            )?;
            for (position, id) in deployments.iter().enumerate() {
                tx.execute(
                    "INSERT INTO provider_models (provider_id, model_id, source, position, seen_at)
                     VALUES (?1, ?2, 'custom', ?3, ?4)
                     ON CONFLICT (provider_id, model_id) DO UPDATE SET source = 'custom', hidden = 0",
                    rusqlite::params![provider.id, id, position as i64, now()],
                )?;
            }
        }
        tx.execute(
            "UPDATE provider_settings SET enabled = 1, updated_at = ?2 WHERE provider_id = ?1",
            rusqlite::params![provider.id, now()],
        )?;
        Ok(())
    })
}

/// Forget everything saved for `provider` (its models and discovery cascade).
pub fn remove(provider: &CatalogProvider) -> Result<(), String> {
    config::delete_credential(&provider.id).map_err(|error| error.to_string())?;
    transact(|tx| {
        tx.execute(
            "DELETE FROM provider_settings WHERE provider_id = ?1",
            [&provider.id],
        )?;
        Ok(())
    })
}

/// Record a discovery attempt; on success replace the discovered models
/// (user-added ones are kept).
fn record_discovery(
    provider: &CatalogProvider,
    outcome: &Result<Vec<DiscoveredModel>, String>,
) -> Result<(), String> {
    transact(|tx| {
        ensure_row(tx, &provider.id)?;
        let at = now();
        match outcome {
            Ok(models) => {
                tx.execute(
                    "DELETE FROM provider_models WHERE provider_id = ?1 AND source = 'discovered'",
                    [&provider.id],
                )?;
                for (position, model) in models.iter().enumerate() {
                    let mut metadata = model.clone();
                    metadata.id = String::new();
                    metadata.name = None;
                    tx.execute(
                        "INSERT INTO provider_models
                           (provider_id, model_id, display_name, source, metadata_json, position, seen_at)
                         VALUES (?1, ?2, ?3, 'discovered', ?4, ?5, ?6)
                         ON CONFLICT (provider_id, model_id) DO UPDATE SET seen_at = excluded.seen_at,
                           metadata_json = excluded.metadata_json",
                        rusqlite::params![
                            provider.id, model.id, model.name,
                            serde_json::to_string(&metadata).ok(), position as i64, at
                        ],
                    )?;
                }
                tx.execute(
                    "INSERT INTO provider_discovery
                       (provider_id, status, error, model_count, last_attempt_at, last_success_at)
                     VALUES (?1, 'ok', NULL, ?2, ?3, ?3)
                     ON CONFLICT (provider_id) DO UPDATE SET status = 'ok', error = NULL,
                       model_count = excluded.model_count, last_attempt_at = excluded.last_attempt_at,
                       last_success_at = excluded.last_success_at",
                    rusqlite::params![provider.id, models.len() as i64, at],
                )?;
                tx.execute(
                    "UPDATE provider_settings SET enabled = 1, updated_at = ?2 WHERE provider_id = ?1",
                    rusqlite::params![provider.id, at],
                )?;
            }
            Err(error) => {
                tx.execute(
                    "INSERT INTO provider_discovery (provider_id, status, error, last_attempt_at)
                     VALUES (?1, 'error', ?2, ?3)
                     ON CONFLICT (provider_id) DO UPDATE SET status = 'error',
                       error = excluded.error, last_attempt_at = excluded.last_attempt_at",
                    rusqlite::params![provider.id, error, at],
                )?;
            }
        }
        Ok(())
    })
}

/// The credential a request to `provider` would send, by the same
/// precedence as execution (saved, then environment), or the placeholder.
pub fn request_key(provider: &CatalogProvider) -> Option<String> {
    let values = crate::provider::CliValues;
    let auth = config::read_auth().unwrap_or_default();
    let models_cfg = config::load_models_config().unwrap_or_default();
    let declaration = evo_runtime::ProviderDeclaration {
        id: provider.id.clone(),
        models: Vec::new(),
        api_key_env: provider.key_env(&values),
        requires_auth: !provider.anonymous,
    };
    evo_runtime::credentials::resolve(
        &provider.id,
        models_cfg.providers.get(&provider.id),
        &auth,
        Some(&declaration),
        &values,
    )
    .key
    .or_else(|| provider.default_api_key.clone())
}

const DISCOVERY_TIMEOUT: std::time::Duration = std::time::Duration::from_secs(15);

/// Ask the provider which models it serves and save the list. A successful
/// call also proves the credential and endpoint work. `Ok(None)` means the
/// provider has no listing evo uses (models.dev or deployments decide).
pub async fn discover(provider: &CatalogProvider) -> Result<Option<Vec<DiscoveredModel>>, String> {
    if !provider.supported {
        return Err(format!("{} is not available yet", provider.label));
    }
    if matches!(
        provider.endpoint.as_deref(),
        Some("bedrock") | Some("foundry") | Some("vertex")
    ) {
        return Ok(None);
    }
    let store = load_store();
    let saved = store.providers.get(&provider.id);
    let db = crate::models_dev::current();
    let state = state_of(saved, &db);
    let mut base = provider.effective_base_url(&state, &crate::provider::CliValues);
    if base.is_empty() {
        return Err("This provider has no endpoint configured".into());
    }
    let key = if provider.login.as_deref() == Some("codex") {
        crate::provider_login::fresh_codex_token()
            .await
            .ok()
            .or_else(|| request_key(provider))
    } else {
        request_key(provider)
    };
    // Copilot Business and Enterprise seats are served from their own host
    // (`api.business.githubcopilot.com`); the public host answers /models and
    // /responses for them but not /chat/completions. Follow the account.
    if provider.login.as_deref() == Some("copilot") {
        if let Some(token) = key.as_deref() {
            if let Some(api) = crate::provider_login::copilot_account_api(token).await {
                if api != base {
                    set_base_url(&provider.id, Some(&api))?;
                    base = api;
                }
            }
        }
    }
    if key.is_none() && !provider.anonymous {
        return Err(if provider.login.is_some() {
            "Sign in first".into()
        } else {
            "Add an API key first".into()
        });
    }
    let client = reqwest::Client::builder()
        .timeout(DISCOVERY_TIMEOUT)
        .build()
        .map_err(|_| "Could not create an HTTP client".to_string())?;
    let (url, parse): (String, fn(&Value) -> Vec<DiscoveredModel>) = match provider.login.as_deref()
    {
        Some("codex") => (
            format!("{base}/models?client_version=1.0.0"),
            parse_codex_models,
        ),
        Some("copilot") => (format!("{base}/models"), parse_copilot_models),
        _ if provider.default_api() == evo_ai::Api::GoogleGenerativeAi => (
            format!("{}/models?pageSize=1000", base.trim_end_matches('/')),
            parse_gemini_models,
        ),
        _ => (provider.models_url(&base), parse_model_list),
    };
    let mut request = client
        .get(&url)
        .header("user-agent", evo_ai::http::user_agent());
    for (name, value) in provider
        .headers
        .iter()
        .chain(saved.map(|s| &s.headers).into_iter().flatten())
    {
        request = request.header(name, value);
    }
    if let Some(key) = key.as_deref() {
        request = if provider.default_api() == evo_ai::Api::AnthropicMessages {
            request
                .header("x-api-key", key)
                .header("anthropic-version", "2023-06-01")
        } else if provider.default_api() == evo_ai::Api::GoogleGenerativeAi {
            request.header("x-goog-api-key", key)
        } else {
            request.bearer_auth(key)
        };
    }
    let outcome = if provider.id == "ollama" {
        discover_ollama(&client, &base).await
    } else {
        fetch_models(provider, request, &base, &url, parse).await
    };
    record_discovery(provider, &outcome)?;
    outcome.map(Some)
}

async fn fetch_models(
    provider: &CatalogProvider,
    request: reqwest::RequestBuilder,
    base: &str,
    url: &str,
    parse: fn(&Value) -> Vec<DiscoveredModel>,
) -> Result<Vec<DiscoveredModel>, String> {
    let response = request.send().await.map_err(|error| {
        if error.is_timeout() {
            format!("{} did not answer within 15 seconds", provider.label)
        } else if error.is_connect() {
            format!("Could not reach {base}")
        } else {
            format!("Request to {} failed", provider.label)
        }
    })?;
    let status = response.status();
    if status == reqwest::StatusCode::UNAUTHORIZED || status == reqwest::StatusCode::FORBIDDEN {
        return Err(format!(
            "{} rejected the credential ({status})",
            provider.label
        ));
    }
    if !status.is_success() {
        return Err(format!("{} answered {status} for {url}", provider.label));
    }
    let body: Value = response.json().await.map_err(|_| {
        format!(
            "{} returned a model list evo could not read",
            provider.label
        )
    })?;
    let models = parse(&body);
    if models.is_empty() {
        return Err(format!("{} returned no models", provider.label));
    }
    Ok(models)
}

fn finish(mut models: Vec<DiscoveredModel>) -> Vec<DiscoveredModel> {
    models.sort_by(|a, b| a.id.cmp(&b.id));
    models.dedup_by(|a, b| a.id == b.id);
    models
}

/// `{"data":[{"id"}]}` (OpenAI, Anthropic) or `{"models":[{"name"}]}` (Gemini).
fn parse_model_list(body: &Value) -> Vec<DiscoveredModel> {
    let items = body
        .get("data")
        .or_else(|| body.get("models"))
        .and_then(Value::as_array);
    finish(
        items
            .into_iter()
            .flatten()
            .filter(|item| catalog_item_is_agent_model(item))
            .filter_map(|item| {
                let id = item
                    .get("id")
                    .or_else(|| item.get("name"))
                    .and_then(Value::as_str)?;
                let id = id.strip_prefix("models/").unwrap_or(id).trim();
                (!id.is_empty()).then(|| catalog_item_metadata(id, item))
            })
            .collect(),
    )
}

fn positive(value: Option<&Value>) -> Option<u64> {
    value.and_then(Value::as_u64).filter(|n| *n > 0)
}

fn strings(value: Option<&Value>) -> Vec<String> {
    value
        .and_then(Value::as_array)
        .map(|list| {
            list.iter()
                .filter_map(Value::as_str)
                .map(|s| s.to_ascii_lowercase())
                .collect()
        })
        .unwrap_or_default()
}

/// Rich OpenAI-compatible catalogs (OpenRouter, Kimi, vLLM, gateways) state
/// what a model takes; plain ones list ids only, and then nothing is
/// inferred (EvoFlux `_metadata_from_openai_catalog_item`).
fn catalog_item_metadata(id: &str, item: &Value) -> DiscoveredModel {
    let top = item.get("top_provider");
    let context_window = positive(item.get("context_length"))
        .or_else(|| positive(item.get("context_window")))
        .or_else(|| positive(item.get("max_context_length")))
        .or_else(|| positive(item.get("max_model_len")))
        .or_else(|| top.and_then(|t| positive(t.get("context_length"))));
    let max_tokens = top
        .and_then(|t| positive(t.get("max_completion_tokens")))
        .or_else(|| positive(item.get("max_output_tokens")))
        .or_else(|| positive(item.get("max_completion_tokens")));
    let parameters = strings(item.get("supported_parameters"));
    let reasoning = item
        .get("supports_reasoning")
        .and_then(Value::as_bool)
        .or_else(|| {
            (!parameters.is_empty()).then(|| {
                parameters.iter().any(|p| {
                    matches!(
                        p.as_str(),
                        "reasoning" | "include_reasoning" | "reasoning_effort"
                    )
                })
            })
        });
    let efforts = item.get("reasoning").filter(|r| r.is_object()).map(|r| {
        let mut efforts = strings(r.get("supported_efforts"));
        if r.get("mandatory") == Some(&Value::Bool(false)) && !efforts.iter().any(|e| e == "none") {
            efforts.push("none".into());
        }
        efforts
    });
    let inputs = {
        let modalities = strings(item.pointer("/architecture/input_modalities"));
        if modalities.is_empty() {
            strings(item.get("input_modalities"))
        } else {
            modalities
        }
    };
    let vision = if inputs.is_empty() {
        item.get("supports_image_in").and_then(Value::as_bool)
    } else {
        Some(inputs.iter().any(|m| m == "image"))
    };
    DiscoveredModel {
        id: id.to_string(),
        name: item
            .get("display_name")
            .or_else(|| item.get("displayName"))
            .or_else(|| item.get("name").filter(|n| n.as_str() != Some(id)))
            .and_then(Value::as_str)
            .map(str::to_string),
        context_window,
        max_tokens,
        vision,
        reasoning,
        efforts: efforts.filter(|e| !e.is_empty()),
        ..Default::default()
    }
}

/// A catalog entry the agent can use: text out and, when the catalog says
/// which parameters a model takes, tool calls.
fn catalog_item_is_agent_model(item: &Value) -> bool {
    let outputs = {
        let modalities = strings(item.pointer("/architecture/output_modalities"));
        if modalities.is_empty() {
            strings(item.get("output_modalities"))
        } else {
            modalities
        }
    };
    if !outputs.is_empty() && !outputs.iter().any(|m| m == "text") {
        return false;
    }
    let parameters = strings(item.get("supported_parameters"));
    parameters.is_empty() || parameters.iter().any(|p| p == "tools")
}

/// Ollama's own API: `/api/tags` lists models, `/api/show` says what each
/// does (tools, thinking, vision) and its context length — the OpenAI shim
/// says none of it.
async fn discover_ollama(
    client: &reqwest::Client,
    base: &str,
) -> Result<Vec<DiscoveredModel>, String> {
    let root = base
        .trim_end_matches('/')
        .trim_end_matches("/v1")
        .to_string();
    let tags: Value = client
        .get(format!("{root}/api/tags"))
        .send()
        .await
        .map_err(|_| format!("Could not reach Ollama at {root}"))?
        .json()
        .await
        .map_err(|_| "Ollama returned a model list evo could not read".to_string())?;
    let names: Vec<String> = tags
        .get("models")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(|m| {
            m.get("name")
                .or_else(|| m.get("model"))
                .and_then(Value::as_str)
                .map(str::to_string)
        })
        .collect();
    let mut models = Vec::new();
    for name in names {
        let show: Value = match client
            .post(format!("{root}/api/show"))
            .json(&json!({"model": name}))
            .send()
            .await
        {
            Ok(response) => response.json().await.unwrap_or(Value::Null),
            Err(_) => Value::Null,
        };
        let capabilities = strings(show.get("capabilities"));
        if !capabilities.is_empty() && !capabilities.iter().any(|c| c == "completion") {
            continue; // embeddings
        }
        let context_window = show
            .get("model_info")
            .and_then(Value::as_object)
            .and_then(|info| {
                info.iter()
                    .filter(|(key, _)| key.ends_with(".context_length"))
                    .filter_map(|(_, value)| value.as_u64())
                    .max()
            });
        let known = !capabilities.is_empty();
        models.push(DiscoveredModel {
            id: name,
            context_window,
            vision: known.then(|| capabilities.iter().any(|c| c == "vision")),
            reasoning: known.then(|| capabilities.iter().any(|c| c == "thinking")),
            ..Default::default()
        });
    }
    if models.is_empty() {
        return Err("Ollama has no models installed (ollama pull <model>)".into());
    }
    Ok(finish(models))
}

/// Gemini `GET /models`: `{"models":[{"name":"models/…","supportedGenerationMethods",
/// "inputTokenLimit","outputTokenLimit","thinking"}]}`. Only models that
/// chat (`generateContent`) are listed — not embeddings, TTS or Imagen.
fn parse_gemini_models(body: &Value) -> Vec<DiscoveredModel> {
    finish(
        body.get("models")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .filter(|item| {
                item.get("supportedGenerationMethods")
                    .and_then(Value::as_array)
                    .is_some_and(|methods| methods.iter().any(|m| m == "generateContent"))
            })
            .filter_map(|item| {
                let name = item.get("name").and_then(Value::as_str)?;
                let id = name.strip_prefix("models/").unwrap_or(name).trim();
                (!id.is_empty()).then(|| DiscoveredModel {
                    id: id.to_string(),
                    name: item
                        .get("displayName")
                        .and_then(Value::as_str)
                        .map(str::to_string),
                    context_window: item.get("inputTokenLimit").and_then(Value::as_u64),
                    max_tokens: item.get("outputTokenLimit").and_then(Value::as_u64),
                    reasoning: item.get("thinking").and_then(Value::as_bool),
                    ..Default::default()
                })
            })
            .collect(),
    )
}

/// ChatGPT Codex `GET /models`: `{"models":[{"slug","context_window",…}]}`.
fn parse_codex_models(body: &Value) -> Vec<DiscoveredModel> {
    finish(
        body.get("models")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            // Hidden or not served over the API: not for the picker.
            .filter(|item| {
                !matches!(
                    item.get("visibility").and_then(Value::as_str),
                    Some("hide" | "hidden")
                ) && item.get("supported_in_api") != Some(&Value::Bool(false))
            })
            .filter_map(|item| {
                let id = item.get("slug").and_then(Value::as_str)?.to_string();
                let efforts: Vec<String> = item
                    .get("supported_reasoning_levels")
                    .and_then(Value::as_array)
                    .into_iter()
                    .flatten()
                    .filter_map(|level| {
                        level
                            .as_str()
                            .or_else(|| level.get("effort").and_then(Value::as_str))
                            .map(str::to_string)
                    })
                    .collect();
                let inputs = strings(item.get("input_modalities"));
                // The endpoint accepts this share of the window (EvoFlux
                // CODEX_EFFECTIVE_CONTEXT_WINDOW_PERCENT).
                let percent = item
                    .get("effective_context_window_percent")
                    .and_then(Value::as_u64)
                    .unwrap_or(95);
                let context_window = item
                    .get("context_window")
                    .and_then(Value::as_u64)
                    .map(|w| w * percent / 100);
                Some(DiscoveredModel {
                    name: item
                        .get("display_name")
                        .and_then(Value::as_str)
                        .map(str::to_string),
                    context_window,
                    reasoning: Some(true),
                    api: Some("openai-responses".into()),
                    vision: (!inputs.is_empty()).then(|| inputs.iter().any(|m| m == "image")),
                    efforts: (!efforts.is_empty()).then_some(efforts),
                    id,
                    ..Default::default()
                })
            })
            .collect(),
    )
}

/// GitHub Copilot `GET /models`: picker models with their endpoints.
fn parse_copilot_models(body: &Value) -> Vec<DiscoveredModel> {
    finish(
        body.get("data")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .filter(|item| item.get("model_picker_enabled").and_then(Value::as_bool) != Some(false))
            .filter(|item| {
                item.pointer("/capabilities/type")
                    .and_then(Value::as_str)
                    .is_none_or(|t| t == "chat")
            })
            .filter_map(|item| {
                let id = item.get("id").and_then(Value::as_str)?.to_string();
                // Spelled with or without the leading slash ("/responses",
                // "responses"); compare without it.
                let endpoints: Vec<&str> = item
                    .get("supported_endpoints")
                    .and_then(Value::as_array)
                    .map(|list| {
                        list.iter()
                            .filter_map(Value::as_str)
                            .map(|endpoint| endpoint.trim_start_matches('/'))
                            .collect()
                    })
                    .unwrap_or_default();
                let api = if endpoints.is_empty() || endpoints.contains(&"chat/completions") {
                    "openai-completions"
                } else if endpoints.contains(&"responses") {
                    "openai-responses"
                } else if endpoints.contains(&"v1/messages") || endpoints.contains(&"messages") {
                    "anthropic-messages"
                } else {
                    "openai-completions"
                };
                let limits = item.pointer("/capabilities/limits");
                let supports = item.pointer("/capabilities/supports");
                Some(DiscoveredModel {
                    name: item.get("name").and_then(Value::as_str).map(str::to_string),
                    api: Some(api.into()),
                    context_window: limits
                        .and_then(|l| l.get("max_context_window_tokens"))
                        .and_then(Value::as_u64),
                    max_tokens: limits
                        .and_then(|l| l.get("max_output_tokens"))
                        .and_then(Value::as_u64),
                    vision: supports
                        .and_then(|s| s.get("vision"))
                        .and_then(Value::as_bool),
                    reasoning: supports.map(|s| {
                        s.get("reasoning_effort").is_some() || s.get("thinking").is_some()
                    }),
                    // The efforts this account's Copilot accepts for the model.
                    efforts: supports
                        .map(|s| strings(s.get("reasoning_effort")))
                        .filter(|efforts| !efforts.is_empty()),
                    id,
                })
            })
            .collect(),
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rich_catalogs_carry_limits_reasoning_and_vision() {
        let models = parse_model_list(&json!({"data": [
            {"id": "a/model", "context_length": 200000, "top_provider": {"max_completion_tokens": 32000},
             "supported_parameters": ["tools", "reasoning"], "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["text"]},
             "reasoning": {"supported_efforts": ["low", "high"], "mandatory": false}},
            {"id": "b/no-tools", "supported_parameters": ["temperature"]},
            {"id": "c/image-gen", "architecture": {"output_modalities": ["image"]}},
            {"id": "kimi-k3", "supports_reasoning": true, "supports_image_in": false},
            {"id": "plain"}
        ]}));
        let ids: Vec<&str> = models.iter().map(|m| m.id.as_str()).collect();
        assert_eq!(ids, ["a/model", "kimi-k3", "plain"]);
        let rich = &models[0];
        assert_eq!(
            (
                rich.context_window,
                rich.max_tokens,
                rich.vision,
                rich.reasoning
            ),
            (Some(200000), Some(32000), Some(true), Some(true))
        );
        assert_eq!(
            rich.efforts.as_deref(),
            Some(&["low".to_string(), "high".to_string(), "none".to_string()][..])
        );
        assert_eq!(
            (models[1].reasoning, models[1].vision),
            (Some(true), Some(false))
        );
        assert_eq!(
            (models[2].reasoning, models[2].context_window),
            (None, None)
        );
    }

    #[test]
    fn codex_listing_hides_hidden_models() {
        let models = parse_codex_models(&json!({"models": [
            {"slug": "gpt-6", "context_window": 400000, "supported_reasoning_levels": [{"effort": "low"}, {"effort": "high"}], "input_modalities": ["text", "image"]},
            {"slug": "internal", "visibility": "hide"},
            {"slug": "no-api", "supported_in_api": false}
        ]}));
        assert_eq!(models.len(), 1);
        assert_eq!(models[0].efforts.as_deref().map(<[String]>::len), Some(2));
        assert_eq!(models[0].vision, Some(true));
    }

    #[test]
    fn parses_openai_and_gemini_model_lists() {
        let ids: Vec<_> = parse_model_list(&json!({"data":[{"id":"b"},{"id":"a"},{"id":"a"}]}))
            .into_iter()
            .map(|m| m.id)
            .collect();
        assert_eq!(ids, ["a", "b"]);
        let models = parse_model_list(
            &json!({"models":[{"name":"models/gemini-3-pro","displayName":"Gemini 3 Pro"}]}),
        );
        assert_eq!(models[0].id, "gemini-3-pro");
    }

    #[test]
    fn copilot_routes_each_model_by_its_endpoints() {
        let models = parse_copilot_models(&json!({"data": [
            {"id":"gpt-5.5","model_picker_enabled":true,"supported_endpoints":["/responses"],
             "capabilities":{"type":"chat","limits":{"max_context_window_tokens":400000},"supports":{"vision":true}}},
            {"id":"claude-sonnet-5","model_picker_enabled":true,"supported_endpoints":["/chat/completions","/v1/messages"]},
            {"id":"gpt-6-codex","model_picker_enabled":true,"supported_endpoints":["responses"]},
            {"id":"hidden","model_picker_enabled":false}
        ]}));
        assert_eq!(models.len(), 3);
        let unslashed = models.iter().find(|m| m.id == "gpt-6-codex").unwrap();
        assert_eq!(unslashed.api.as_deref(), Some("openai-responses"));
        let gpt = models.iter().find(|m| m.id == "gpt-5.5").unwrap();
        assert_eq!(gpt.api.as_deref(), Some("openai-responses"));
        assert_eq!(gpt.context_window, Some(400_000));
        assert_eq!(
            models
                .iter()
                .find(|m| m.id == "claude-sonnet-5")
                .unwrap()
                .api
                .as_deref(),
            Some("openai-completions")
        );
    }

    #[test]
    fn codex_reads_slugs_and_effective_window() {
        let models =
            parse_codex_models(&json!({"models":[{"slug":"gpt-5.5","context_window":400000}]}));
        assert_eq!(models[0].id, "gpt-5.5");
        assert_eq!(models[0].context_window, Some(380_000));
    }

    #[test]
    fn keyless_local_providers_participate_only_once_enabled() {
        let ollama = provider_catalog::find("ollama").unwrap();
        assert!(!participates(ollama, None));
        let saved = SavedProvider {
            enabled: true,
            ..Default::default()
        };
        assert!(participates(ollama, Some(&saved)));
    }
}
