//! Shared, provider-scoped credential resolution for requests and auth UI.
//! Provider packages own their environment names and anonymous policy. The host
//! owns persistence and precedence, and never guesses a key from a wire protocol.
use crate::config::{AuthStore, Credential, ProviderConfig};
use crate::ProviderDeclaration as ProviderManifest;
use crate::ValueSource;

#[derive(Clone, Debug, PartialEq, Eq, serde::Serialize)]
pub enum CredentialSource {
    /// A host-supplied override scoped to the selected provider.
    Explicit,
    StoredApiKey,
    StoredOauth,
    ModelsJson,
    Environment(String),
    Headers,
    Anonymous,
    Missing,
}

/// Local readiness only; this does not claim that a server accepted the key.
#[derive(Clone, Copy, Debug, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub enum AuthStatus {
    Missing,
    Ready,
    Expired,
    Anonymous,
}

/// Safe for UI snapshots and change notifications; contains no credential values.
#[derive(Clone, Debug, PartialEq, Eq, serde::Serialize)]
pub struct AuthState {
    pub status: AuthStatus,
    pub source: CredentialSource,
}

impl AuthState {
    pub fn is_ready(&self) -> bool {
        matches!(self.status, AuthStatus::Ready | AuthStatus::Anonymous)
    }
}

pub(crate) fn state(
    provider: &str,
    config: Option<&ProviderConfig>,
    store: &AuthStore,
    manifest: Option<&ProviderManifest>,
    values: &dyn ValueSource,
    refreshable: bool,
    has_headers: impl FnOnce() -> bool,
) -> AuthState {
    let credential = resolve_refreshable(provider, config, store, manifest, values, refreshable);
    let source = if credential.source.is_present() {
        credential.source
    } else if has_headers() {
        CredentialSource::Headers
    } else {
        CredentialSource::Missing
    };
    let status = match source {
        CredentialSource::Anonymous => AuthStatus::Anonymous,
        CredentialSource::Missing => match store.get(provider) {
            Some(Credential::Oauth { expires, .. })
                if *expires != 0 && *expires <= values.now_unix_seconds() =>
            {
                AuthStatus::Expired
            }
            _ => AuthStatus::Missing,
        },
        _ => AuthStatus::Ready,
    };
    AuthState { status, source }
}

impl CredentialSource {
    pub fn is_present(&self) -> bool {
        !matches!(self, Self::Missing)
    }

    pub fn as_json_str(&self) -> &str {
        match self {
            Self::Explicit => "override",
            Self::StoredApiKey => "auth.json",
            Self::StoredOauth => "oauth",
            Self::ModelsJson => "models.json",
            Self::Environment(name) => name,
            Self::Headers => "headers",
            Self::Anonymous => "anonymous",
            Self::Missing => "none",
        }
    }
}

/// Seconds before expiry at which a stored OAuth credential is renewed, so a
/// token cannot expire between the check and the provider's request.
pub const OAUTH_REFRESH_MARGIN_SECS: i64 = 60;

/// Whether a stored OAuth credential expiring at `expires` (Unix seconds, `0`
/// for never) should be renewed before it is used at `now`.
pub fn oauth_needs_refresh(expires: i64, now: i64) -> bool {
    expires != 0 && expires <= now.saturating_add(OAUTH_REFRESH_MARGIN_SECS)
}

/// A renewed OAuth access token, already persisted by the host.
// Deliberately no Debug: this object contains secret material.
pub struct RefreshedOAuth {
    pub access: String,
    /// Unix seconds; `0` means the credential does not expire.
    pub expires: i64,
}

/// Host-owned renewal of stored OAuth credentials, typically through the
/// provider package that issued them. Requests call it before sending a stored
/// OAuth credential that has expired or is about to.
pub trait OAuthRefresher: Send + Sync {
    /// Whether the host can renew `provider`'s stored OAuth credential.
    fn supports(&self, provider: &str) -> bool;
    /// Renew and persist `provider`'s stored credential. This may block, so the
    /// runtime calls it off the async workers. The error is shown to the user
    /// and must not contain credential material.
    fn refresh(&self, provider: &str) -> Result<RefreshedOAuth, String>;
}

// Deliberately no Debug: this object contains secret material.
pub struct ResolvedCredential {
    pub key: Option<String>,
    pub source: CredentialSource,
    pub bearer: bool,
}

/// Only these identities have a built-in environment fallback. Other providers
/// need a loaded declaration or an explicit models.json apiKey reference.
pub fn builtin_api_key_env(provider: &str) -> Option<&'static str> {
    match provider {
        "anthropic" => Some("ANTHROPIC_API_KEY"),
        "openai" => Some("OPENAI_API_KEY"),
        _ => None,
    }
}

fn nonempty(value: Option<String>) -> Option<String> {
    value.filter(|key| !key.trim().is_empty())
}

pub fn resolve(
    provider: &str,
    config: Option<&ProviderConfig>,
    store: &AuthStore,
    manifest: Option<&ProviderManifest>,
    values: &dyn ValueSource,
) -> ResolvedCredential {
    resolve_refreshable(provider, config, store, manifest, values, false)
}

/// As [`resolve`], except that an expired stored OAuth credential still counts
/// when `refreshable`: the execution binding renews it before it is sent.
pub(crate) fn resolve_refreshable(
    provider: &str,
    config: Option<&ProviderConfig>,
    store: &AuthStore,
    manifest: Option<&ProviderManifest>,
    values: &dyn ValueSource,
    refreshable: bool,
) -> ResolvedCredential {
    let bearer = config
        .and_then(|config| config.auth_header)
        .unwrap_or(false);
    let credential = |key, source, bearer| ResolvedCredential {
        key: Some(key),
        source,
        bearer,
    };
    match store.get(provider) {
        Some(Credential::ApiKey {
            key: Some(key),
            env,
        }) => {
            if let Some(key) = nonempty(crate::values::resolve_config_value(
                key,
                env.as_ref(),
                values,
                true,
            )) {
                return credential(key, CredentialSource::StoredApiKey, bearer);
            }
        }
        Some(Credential::Oauth {
            access,
            refresh,
            expires,
        }) if !access.trim().is_empty() => {
            let now = values.now_unix_seconds();
            if *expires == 0 || *expires > now || (refreshable && !refresh.trim().is_empty()) {
                return credential(access.clone(), CredentialSource::StoredOauth, true);
            }
        }
        _ => {}
    }
    if let Some(key) = config
        .and_then(|config| config.api_key.as_deref())
        .and_then(|raw| nonempty(crate::values::resolve_config_value(raw, None, values, true)))
    {
        return credential(key, CredentialSource::ModelsJson, bearer);
    }
    // A package declaration is authoritative even for a built-in identity.
    if manifest.is_none() && provider == "anthropic" {
        if let Some(key) = nonempty(values.env("ANTHROPIC_AUTH_TOKEN")) {
            return credential(
                key,
                CredentialSource::Environment("ANTHROPIC_AUTH_TOKEN".into()),
                true,
            );
        }
    }
    let env = match manifest {
        Some(manifest) => manifest.api_key_env.as_deref(),
        None => builtin_api_key_env(provider),
    };
    if let Some(name) = env {
        if let Some(key) = nonempty(values.env(name)) {
            return credential(key, CredentialSource::Environment(name.into()), bearer);
        }
    }
    // Bedrock also signs with the AWS default chain: access keys or a named
    // profile in the environment (resolved per request by evo-ai).
    if provider == "bedrock" {
        let set = |name: &str| nonempty(values.env(name)).is_some();
        if (set("AWS_ACCESS_KEY_ID") && set("AWS_SECRET_ACCESS_KEY")) || set("AWS_PROFILE") {
            return credential(
                "aws-profile:".to_string(),
                CredentialSource::Environment("AWS_PROFILE".into()),
                false,
            );
        }
    }
    ResolvedCredential {
        key: None,
        source: if manifest.is_some_and(|manifest| !manifest.requires_auth) {
            CredentialSource::Anonymous
        } else {
            CredentialSource::Missing
        },
        bearer,
    }
}

pub fn has_header_auth(headers: Option<&std::collections::BTreeMap<String, String>>) -> bool {
    headers.is_some_and(|headers| {
        headers.iter().any(|(name, value)| {
            ["authorization", "x-api-key", "cf-aig-authorization"]
                .contains(&name.to_ascii_lowercase().as_str())
                && !value.trim().is_empty()
        })
    })
}
