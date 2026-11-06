//! Sign-in flows for subscription providers, ported from EvoFlux:
//!
//! - **OpenAI Codex** (`codex/oauth.py`): PKCE in the browser. The engine
//!   listens on `localhost:1455/auth/callback` (the redirect the Codex client
//!   registers), exchanges the code at `auth.openai.com`, stores the tokens
//!   in `auth.json` and the ChatGPT account id as a request header option.
//!   Access tokens expire; [`BuiltinOAuthRefresher`] renews them.
//! - **GitHub Copilot** (`copilot/oauth.py`): the GitHub device flow. The user
//!   enters a code at github.com/login/device; the long-lived GitHub token is
//!   the bearer for `api.githubcopilot.com`.
//!
//! Flows run in the background. Their state is kept here for the settings
//! page; when one finishes it lists the provider's models and asks the RPC
//! host, through [`notify`], to hot-swap provider runtimes.

use std::collections::{BTreeMap, HashMap};
use std::sync::{Mutex, OnceLock};
use std::time::Duration;

use base64::Engine as _;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio_util::sync::CancellationToken;

use evo_runtime::credentials::{OAuthRefresher, RefreshedOAuth};

const CODEX_CLIENT_ID: &str = "app_EMoamEEZ73f0CkXaXp7hrann";
const CODEX_ISSUER: &str = "https://auth.openai.com";
const CODEX_PORT: u16 = 1455;
const CODEX_ORIGINATOR: &str = "evo";
/// The OAuth app EvoFlux (and opencode) sign in to Copilot with.
const COPILOT_CLIENT_ID: &str = "Ov23li8tweQw6odWQebz";
const LOGIN_TIMEOUT: Duration = Duration::from_secs(10 * 60);

// ---------------------------------------------------------------------------
// Events to the RPC host
// ---------------------------------------------------------------------------

/// Something changed that the live provider runtimes should reflect.
#[derive(Clone, Debug)]
pub struct ProvidersChanged {
    pub provider: Option<String>,
    pub reason: &'static str,
}

fn sink() -> &'static OnceLock<tokio::sync::mpsc::UnboundedSender<ProvidersChanged>> {
    static SINK: OnceLock<tokio::sync::mpsc::UnboundedSender<ProvidersChanged>> = OnceLock::new();
    &SINK
}

/// Installed once by the RPC host's reload worker.
pub fn set_event_sink(sender: tokio::sync::mpsc::UnboundedSender<ProvidersChanged>) {
    let _ = sink().set(sender);
}

pub fn notify(provider: Option<&str>, reason: &'static str) {
    if let Some(sender) = sink().get() {
        let _ = sender.send(ProvidersChanged {
            provider: provider.map(str::to_string),
            reason,
        });
    }
}

// ---------------------------------------------------------------------------
// Flow state
// ---------------------------------------------------------------------------

/// What the settings page shows while a sign-in runs.
#[derive(Clone, Debug, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct LoginState {
    /// `pending`, `success` or `error`.
    pub status: &'static str,
    /// Page to open in the browser.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub url: Option<String>,
    /// Device-flow code to type on that page.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub user_code: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub account: Option<String>,
}

fn flows() -> &'static Mutex<HashMap<String, (LoginState, CancellationToken)>> {
    static FLOWS: OnceLock<Mutex<HashMap<String, (LoginState, CancellationToken)>>> = OnceLock::new();
    FLOWS.get_or_init(Default::default)
}

pub fn snapshot() -> BTreeMap<String, LoginState> {
    flows()
        .lock()
        .unwrap_or_else(|e| e.into_inner())
        .iter()
        .map(|(id, (state, _))| (id.clone(), state.clone()))
        .collect()
}

fn update(provider: &str, state: LoginState) {
    let mut flows = flows().lock().unwrap_or_else(|e| e.into_inner());
    if let Some(entry) = flows.get_mut(provider) {
        entry.0 = state;
    }
}

pub fn cancel(provider: &str) {
    if let Some((_, token)) = flows().lock().unwrap_or_else(|e| e.into_inner()).remove(provider) {
        token.cancel();
    }
}

fn now() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0)
}

fn client() -> reqwest::Client {
    reqwest::Client::builder()
        .timeout(Duration::from_secs(30))
        .build()
        .expect("http client")
}

fn form(pairs: &[(&str, &str)]) -> String {
    pairs
        .iter()
        .map(|(k, v)| {
            format!(
                "{}={}",
                percent_encoding::utf8_percent_encode(k, percent_encoding::NON_ALPHANUMERIC),
                percent_encoding::utf8_percent_encode(v, percent_encoding::NON_ALPHANUMERIC)
            )
        })
        .collect::<Vec<_>>()
        .join("&")
}

/// Start (or restart) `provider`'s sign-in. Returns what to show.
pub async fn begin(provider: &str) -> Result<LoginState, String> {
    cancel(provider);
    let token = CancellationToken::new();
    let (state, task): (LoginState, std::pin::Pin<Box<dyn std::future::Future<Output = Result<String, String>> + Send>>) =
        match provider {
            "codex" => {
                let (state, task) = codex_begin(token.clone()).await?;
                (state, Box::pin(task))
            }
            "copilot" => {
                let (state, task) = copilot_begin(token.clone()).await?;
                (state, Box::pin(task))
            }
            "xiaomi" => {
                let (state, task) = xiaomi_begin(token.clone()).await?;
                (state, Box::pin(task))
            }
            other => return Err(format!("{other} has no sign-in flow")),
        };
    flows()
        .lock()
        .unwrap_or_else(|e| e.into_inner())
        .insert(provider.to_string(), (state.clone(), token.clone()));
    let id = provider.to_string();
    tokio::spawn(async move {
        let outcome = tokio::select! {
            _ = token.cancelled() => return,
            _ = tokio::time::sleep(LOGIN_TIMEOUT) => Err("Sign-in timed out".to_string()),
            outcome = task => outcome,
        };
        match outcome {
            Ok(account) => {
                // A successful sign-in lists the subscription's models.
                if let Ok(provider) = crate::provider_settings::find(&id) {
                    let _ = crate::provider_settings::discover(provider).await;
                }
                update(&id, LoginState { status: "success", url: None, user_code: None, error: None, account: Some(account) });
                notify(Some(&id), "login");
            }
            Err(error) => {
                update(&id, LoginState { status: "error", url: None, user_code: None, error: Some(error), account: None });
                notify(Some(&id), "login_failed");
            }
        }
    });
    Ok(state)
}

// ---------------------------------------------------------------------------
// Codex (PKCE)
// ---------------------------------------------------------------------------

fn b64url(bytes: &[u8]) -> String {
    base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(bytes)
}

/// Claims of a JWT, unverified (only read for display and the account id).
fn jwt_claims(token: &str) -> Option<Value> {
    let payload = token.split('.').nth(1)?;
    let bytes = base64::engine::general_purpose::URL_SAFE_NO_PAD
        .decode(payload.trim_end_matches('='))
        .ok()?;
    serde_json::from_slice(&bytes).ok()
}

fn codex_account(tokens: &Value) -> (Option<String>, Option<String>) {
    let mut account = None;
    let mut email = None;
    for key in ["id_token", "access_token"] {
        let Some(claims) = tokens.get(key).and_then(Value::as_str).and_then(jwt_claims) else { continue };
        account = account.or_else(|| {
            claims
                .get("chatgpt_account_id")
                .or_else(|| claims.pointer("/https:~1~1api.openai.com~1auth/chatgpt_account_id"))
                .or_else(|| claims.pointer("/organizations/0/id"))
                .and_then(Value::as_str)
                .map(str::to_string)
        });
        email = email.or_else(|| claims.get("email").and_then(Value::as_str).map(str::to_string));
    }
    (account, email)
}

/// Store Codex tokens and the account header; returns the account to show.
fn codex_save(tokens: &Value, previous_refresh: Option<&str>) -> Result<(String, i64), String> {
    let access = tokens
        .get("access_token")
        .and_then(Value::as_str)
        .ok_or("OpenAI returned no access token")?
        .to_string();
    let refresh = tokens
        .get("refresh_token")
        .and_then(Value::as_str)
        .or(previous_refresh)
        .unwrap_or_default()
        .to_string();
    let expires = now() + tokens.get("expires_in").and_then(Value::as_i64).unwrap_or(3600);
    crate::config::upsert_oauth_token("codex", access.clone(), refresh, expires)
        .map_err(|error| error.to_string())?;
    let (account, email) = codex_account(tokens);
    let mut options = json!({});
    if let Some(account) = &account {
        options["headers"] = json!({"ChatGPT-Account-Id": account});
    }
    if let Some(email) = &email {
        options["account"] = json!(email);
    }
    crate::provider_settings::set_options("codex", options)?;
    Ok((access, expires))
}

async fn codex_exchange(pairs: &[(&str, &str)]) -> Result<Value, String> {
    let response = client()
        .post(format!("{CODEX_ISSUER}/oauth/token"))
        .header("content-type", "application/x-www-form-urlencoded")
        .body(form(pairs))
        .send()
        .await
        .map_err(|error| format!("Could not reach OpenAI: {error}"))?;
    let status = response.status();
    let body: Value = response.json().await.unwrap_or(Value::Null);
    if !status.is_success() {
        let message = body
            .get("error_description")
            .or_else(|| body.pointer("/error/message"))
            .or_else(|| body.get("error"))
            .and_then(Value::as_str)
            .unwrap_or("token request failed");
        return Err(format!("OpenAI rejected the sign-in ({status}): {message}"));
    }
    Ok(body)
}

const CALLBACK_PAGE: &str = "<!doctype html><meta charset=utf-8><title>evo</title><body style=\"font:16px system-ui;padding:3em\"><h2>Signed in to evo</h2><p>You can close this tab and return to the app.</p><script>setTimeout(()=>window.close(),1500)</script>";
const CALLBACK_FAILED: &str = "<!doctype html><meta charset=utf-8><title>evo</title><body style=\"font:16px system-ui;padding:3em\"><h2>Sign-in failed</h2><p>Return to evo and try again.</p>";

async fn codex_begin(
    token: CancellationToken,
) -> Result<(LoginState, impl std::future::Future<Output = Result<String, String>> + Send), String> {
    let verifier = format!(
        "{}{}",
        uuid::Uuid::new_v4().simple(),
        uuid::Uuid::new_v4().simple()
    );
    let challenge = b64url(&Sha256::digest(verifier.as_bytes()));
    let state = uuid::Uuid::new_v4().simple().to_string();
    let redirect = format!("http://localhost:{CODEX_PORT}/auth/callback");
    // The browser may resolve localhost to either family.
    let v4 = tokio::net::TcpListener::bind(("127.0.0.1", CODEX_PORT)).await;
    let v6 = tokio::net::TcpListener::bind(("::1", CODEX_PORT)).await;
    if v4.is_err() && v6.is_err() {
        return Err(format!(
            "Port {CODEX_PORT} is in use (another Codex sign-in may be open). Close it and try again."
        ));
    }
    let url = format!(
        "{CODEX_ISSUER}/oauth/authorize?{}",
        form(&[
            ("response_type", "code"),
            ("client_id", CODEX_CLIENT_ID),
            ("redirect_uri", &redirect),
            ("scope", "openid profile email offline_access api.connectors.read api.connectors.invoke"),
            ("code_challenge", &challenge),
            ("code_challenge_method", "S256"),
            ("id_token_add_organizations", "true"),
            ("codex_cli_simplified_flow", "true"),
            ("state", &state),
            ("originator", CODEX_ORIGINATOR),
        ])
    );
    let shown = LoginState { status: "pending", url: Some(url), user_code: None, error: None, account: None };
    let task = async move {
        let code = loop {
            let accepted = tokio::select! {
                _ = token.cancelled() => return Err("cancelled".to_string()),
                stream = async { v4.as_ref().map_err(|_| ())?.accept().await.map_err(|_| ()) }, if v4.is_ok() => stream,
                stream = async { v6.as_ref().map_err(|_| ())?.accept().await.map_err(|_| ()) }, if v6.is_ok() => stream,
            };
            let Ok((mut stream, _)) = accepted else { continue };
            let mut buffer = vec![0u8; 8192];
            let read = tokio::time::timeout(Duration::from_secs(5), stream.read(&mut buffer))
                .await
                .ok()
                .and_then(Result::ok)
                .unwrap_or(0);
            let request = String::from_utf8_lossy(&buffer[..read]).to_string();
            let target = request.split_whitespace().nth(1).unwrap_or("/").to_string();
            let parsed = reqwest::Url::parse(&format!("http://localhost{target}")).ok();
            let query: HashMap<String, String> = parsed
                .as_ref()
                .map(|url| url.query_pairs().into_owned().collect())
                .unwrap_or_default();
            if parsed.as_ref().map(|url| url.path()) != Some("/auth/callback") {
                let _ = stream.write_all(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n").await;
                continue;
            }
            let ok = query.get("state") == Some(&state) && query.contains_key("code");
            let page = if ok { CALLBACK_PAGE } else { CALLBACK_FAILED };
            let _ = stream
                .write_all(
                    format!(
                        "HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{page}",
                        page.len()
                    )
                    .as_bytes(),
                )
                .await;
            if let Some(error) = query.get("error") {
                return Err(format!("OpenAI denied the sign-in: {error}"));
            }
            if ok {
                break query["code"].clone();
            }
        };
        drop((v4, v6));
        let tokens = codex_exchange(&[
            ("grant_type", "authorization_code"),
            ("code", &code),
            ("redirect_uri", &redirect),
            ("client_id", CODEX_CLIENT_ID),
            ("code_verifier", &verifier),
        ])
        .await?;
        codex_save(&tokens, None)?;
        Ok(codex_account(&tokens).1.unwrap_or_else(|| "ChatGPT account".into()))
    };
    Ok((shown, task))
}

/// Renew the stored Codex token. Blocking: the runtime calls it off the
/// async workers.
fn codex_refresh(handle: &tokio::runtime::Handle) -> Result<RefreshedOAuth, String> {
    let store = crate::config::read_auth().map_err(|error| error.to_string())?;
    let Some(crate::config::Credential::Oauth { refresh, expires, access }) = store.get("codex").cloned() else {
        return Err("not signed in to Codex".into());
    };
    // Another request may have refreshed it already.
    if expires > now() + 120 {
        return Ok(RefreshedOAuth { access, expires });
    }
    let tokens = handle.block_on(codex_exchange(&[
        ("grant_type", "refresh_token"),
        ("refresh_token", &refresh),
        ("client_id", CODEX_CLIENT_ID),
    ]))?;
    let (access, expires) = codex_save(&tokens, Some(&refresh))?;
    Ok(RefreshedOAuth { access, expires })
}

/// A Codex access token that is valid now, renewed first when it is about to
/// expire (usage and model listing call ChatGPT outside a chat request).
pub(crate) async fn fresh_codex_token() -> Result<String, String> {
    let handle = tokio::runtime::Handle::current();
    tokio::task::spawn_blocking(move || codex_refresh(&handle))
        .await
        .map_err(|error| error.to_string())?
        .map(|refreshed| refreshed.access)
}

// ---------------------------------------------------------------------------
// Copilot (GitHub device flow)
// ---------------------------------------------------------------------------

fn github(request: reqwest::RequestBuilder) -> reqwest::RequestBuilder {
    request
        .header("accept", "application/json")
        .header("user-agent", evo_ai::http::user_agent())
}

async fn copilot_begin(
    token: CancellationToken,
) -> Result<(LoginState, impl std::future::Future<Output = Result<String, String>> + Send), String> {
    let http = client();
    let device: Value = github(http.post("https://github.com/login/device/code"))
        .json(&json!({"client_id": COPILOT_CLIENT_ID, "scope": "read:user"}))
        .send()
        .await
        .map_err(|error| format!("Could not reach GitHub: {error}"))?
        .json()
        .await
        .map_err(|_| "GitHub returned an unexpected answer".to_string())?;
    let device_code = device
        .get("device_code")
        .and_then(Value::as_str)
        .ok_or("GitHub did not start the device flow")?
        .to_string();
    let user_code = device.get("user_code").and_then(Value::as_str).unwrap_or_default().to_string();
    let uri = device
        .get("verification_uri")
        .and_then(Value::as_str)
        .unwrap_or("https://github.com/login/device")
        .to_string();
    let mut interval = device.get("interval").and_then(Value::as_u64).unwrap_or(5).max(1);
    let shown = LoginState { status: "pending", url: Some(uri), user_code: Some(user_code), error: None, account: None };
    let task = async move {
        let access = loop {
            tokio::select! {
                _ = token.cancelled() => return Err("cancelled".to_string()),
                _ = tokio::time::sleep(Duration::from_secs(interval + 1)) => {}
            }
            let poll: Value = github(http.post("https://github.com/login/oauth/access_token"))
                .json(&json!({
                    "client_id": COPILOT_CLIENT_ID,
                    "device_code": device_code,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                }))
                .send()
                .await
                .map_err(|error| format!("Could not reach GitHub: {error}"))?
                .json()
                .await
                .unwrap_or(Value::Null);
            if let Some(access) = poll.get("access_token").and_then(Value::as_str) {
                break access.to_string();
            }
            match poll.get("error").and_then(Value::as_str) {
                Some("authorization_pending") | None => {}
                Some("slow_down") => interval += 5,
                Some("expired_token") => return Err("The code expired. Start again.".into()),
                Some("access_denied") => return Err("GitHub sign-in was cancelled.".into()),
                Some(other) => return Err(format!("GitHub refused the sign-in: {other}")),
            }
        };
        // Copilot must accept the token, or the account has no subscription.
        let check = github(http.get("https://api.githubcopilot.com/models"))
            .bearer_auth(&access)
            .send()
            .await
            .map_err(|error| format!("Could not reach GitHub Copilot: {error}"))?;
        if !check.status().is_success() {
            return Err(format!(
                "GitHub Copilot refused this account ({}). Check that it has a Copilot subscription.",
                check.status()
            ));
        }
        crate::config::upsert_oauth_token("copilot", access.clone(), String::new(), 0)
            .map_err(|error| error.to_string())?;
        let login = github(http.get("https://api.github.com/user"))
            .bearer_auth(&access)
            .send()
            .await
            .ok();
        let login = match login {
            Some(response) => response
                .json::<Value>()
                .await
                .ok()
                .and_then(|user| user.get("login").and_then(Value::as_str).map(str::to_string)),
            None => None,
        };
        let account = login.unwrap_or_else(|| "GitHub account".into());
        crate::provider_settings::set_options("copilot", json!({"account": account}))?;
        if let Some(api) = copilot_account_api(&access).await {
            crate::provider_settings::set_base_url("copilot", Some(&api))?;
        }
        Ok(account)
    };
    Ok((shown, task))
}

/// The Copilot API host of the signed-in account (`endpoints.api` of
/// `copilot_internal/user`): `https://api.githubcopilot.com` for individual
/// plans, `https://api.business.githubcopilot.com` / `…enterprise…` for
/// organisation seats. `None` when GitHub does not say.
pub(crate) async fn copilot_account_api(token: &str) -> Option<String> {
    let http = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(15))
        .build()
        .ok()?;
    let user: Value = github(http.get("https://api.github.com/copilot_internal/user"))
        .bearer_auth(token)
        .send()
        .await
        .ok()?
        .error_for_status()
        .ok()?
        .json()
        .await
        .ok()?;
    let api = user.pointer("/endpoints/api")?.as_str()?.trim_end_matches('/');
    (api.starts_with("https://") && api.contains("githubcopilot.com")).then(|| api.to_string())
}

// ---------------------------------------------------------------------------
// Xiaomi MiMo (browser sign-in that mints an API key)
// ---------------------------------------------------------------------------
//
// Ported from EvoFlux `xiaomi/oauth.py` (itself from MiMo-Code's plugin):
// 1. an X25519 key pair; the public half goes to `{platform}/authorize` as
//    base64url SPKI DER;
// 2. the person signs in to Xiaomi; the platform redirects to our loopback
//    with `?u=<ephemeral public(32) ‖ nonce(12) ‖ ciphertext ‖ tag(16)>`;
// 3. X25519 → SHA-256 → AES-256-GCM key; the plaintext is
//    `{"sk": key, "uid": account, "url": optional base URL}`.
// The key never travels in clear in a URL.

fn mimo_platform() -> String {
    std::env::var("MIMO_PLATFORM_URL")
        .ok()
        .filter(|url| !url.is_empty())
        .unwrap_or_else(|| "https://platform.xiaomimimo.com".into())
        .trim_end_matches('/')
        .to_string()
}

/// The protocol's client identifier (not shown to the person).
const MIMO_CLIENT: &str = "mimocode";

/// The name the key carries in the MiMo console, stable per install so
/// signing in again rotates the same key.
fn mimo_key_name() -> String {
    let saved = crate::provider_settings::option("xiaomi", "keyName");
    if let Some(name) = saved.as_ref().and_then(Value::as_str).filter(|n| !n.is_empty()) {
        return name.to_string();
    }
    let name = format!("evo-key-{}", &uuid::Uuid::new_v4().simple().to_string()[..8]);
    let _ = crate::provider_settings::set_options("xiaomi", json!({"keyName": name}));
    name
}

/// X25519 SubjectPublicKeyInfo DER prefix (RFC 8410).
const X25519_SPKI_PREFIX: [u8; 12] = [0x30, 0x2a, 0x30, 0x05, 0x06, 0x03, 0x2b, 0x65, 0x6e, 0x03, 0x21, 0x00];

/// Open the platform's sealed reply with our private key.
fn mimo_decrypt(
    private: ring::agreement::EphemeralPrivateKey,
    blob: &str,
) -> Result<HashMap<String, String>, String> {
    use ring::{aead, agreement};
    let raw = base64::engine::general_purpose::URL_SAFE_NO_PAD
        .decode(blob.trim_end_matches('='))
        .map_err(|_| "The sign-in reply was not valid base64url.".to_string())?;
    if raw.len() < 60 {
        return Err("The sign-in reply was too short.".into());
    }
    let (peer, rest) = raw.split_at(32);
    let (nonce, sealed) = rest.split_at(12);
    let key = agreement::agree_ephemeral(
        private,
        &agreement::UnparsedPublicKey::new(&agreement::X25519, peer),
        |shared| Sha256::digest(shared),
    )
    .map_err(|_| "The sign-in reply was issued for another attempt.".to_string())?;
    let key = aead::LessSafeKey::new(
        aead::UnboundKey::new(&aead::AES_256_GCM, &key).map_err(|_| "bad key".to_string())?,
    );
    let mut sealed = sealed.to_vec();
    let nonce = aead::Nonce::try_assume_unique_for_key(nonce).map_err(|_| "bad nonce".to_string())?;
    let plain = key
        .open_in_place(nonce, aead::Aad::empty(), &mut sealed)
        .map_err(|_| "The sign-in reply was issued for another attempt.".to_string())?;
    let payload: Value = serde_json::from_slice(plain)
        .map_err(|_| "The sign-in reply was not the expected JSON.".to_string())?;
    let object = payload.as_object().ok_or("The sign-in reply was not a JSON object.")?;
    Ok(object
        .iter()
        .filter_map(|(k, v)| match v {
            Value::String(s) => Some((k.clone(), s.clone())),
            Value::Null => None,
            other => Some((k.clone(), other.to_string())),
        })
        .collect())
}

async fn xiaomi_begin(
    token: CancellationToken,
) -> Result<(LoginState, impl std::future::Future<Output = Result<String, String>> + Send), String> {
    let rng = ring::rand::SystemRandom::new();
    let private = ring::agreement::EphemeralPrivateKey::generate(&ring::agreement::X25519, &rng)
        .map_err(|_| "Could not create a key pair".to_string())?;
    let public = private
        .compute_public_key()
        .map_err(|_| "Could not create a key pair".to_string())?;
    let mut spki = X25519_SPKI_PREFIX.to_vec();
    spki.extend_from_slice(public.as_ref());
    // Loopback only: this socket receives the account's API key.
    let v4 = tokio::net::TcpListener::bind(("127.0.0.1", 0))
        .await
        .map_err(|error| format!("Could not open a local port: {error}"))?;
    let port = v4.local_addr().map_err(|e| e.to_string())?.port();
    let v6 = tokio::net::TcpListener::bind(("::1", port)).await;
    let redirect = format!("http://localhost:{port}/");
    let platform = mimo_platform();
    let url = format!(
        "{platform}/authorize?{}",
        form(&[
            ("pk", &b64url(&spki)),
            ("redirect_uri", &redirect),
            ("kn", MIMO_CLIENT),
            ("key_name", &mimo_key_name()),
        ])
    );
    let shown = LoginState { status: "pending", url: Some(url), user_code: None, error: None, account: None };
    let task = async move {
        let blob = loop {
            let accepted = tokio::select! {
                _ = token.cancelled() => return Err("cancelled".to_string()),
                stream = v4.accept() => stream.map_err(|_| ()),
                stream = async { v6.as_ref().map_err(|_| ())?.accept().await.map_err(|_| ()) }, if v6.is_ok() => stream,
            };
            let Ok((mut stream, _)) = accepted else { continue };
            let mut buffer = vec![0u8; 16_384];
            let read = tokio::time::timeout(Duration::from_secs(5), stream.read(&mut buffer))
                .await
                .ok()
                .and_then(Result::ok)
                .unwrap_or(0);
            let request = String::from_utf8_lossy(&buffer[..read]).to_string();
            let target = request.split_whitespace().nth(1).unwrap_or("/").to_string();
            let query: HashMap<String, String> = reqwest::Url::parse(&format!("http://localhost{target}"))
                .map(|url| url.query_pairs().into_owned().collect())
                .unwrap_or_default();
            let Some(blob) = query.get("u").filter(|u| !u.is_empty()).cloned() else {
                // A favicon or another stray request.
                let _ = stream.write_all(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n").await;
                continue;
            };
            break (blob, stream);
        };
        let (blob, mut stream) = blob;
        drop((v4, v6));
        let outcome = mimo_decrypt(private, &blob);
        let status = if outcome.is_ok() { "status=success" } else { "status=error&message=decrypt_failed" };
        let _ = stream
            .write_all(
                format!(
                    "HTTP/1.1 302 Found\r\nLocation: {platform}/authorize/callback?{status}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                )
                .as_bytes(),
            )
            .await;
        let payload = outcome?;
        let key = payload.get("sk").map(|k| k.trim()).filter(|k| !k.is_empty())
            .ok_or("The platform returned no API key for this account.")?;
        crate::config::upsert_credential(
            "xiaomi",
            crate::config::Credential::ApiKey { key: Some(key.to_string()), env: None },
        )
        .map_err(|error| error.to_string())?;
        // Token plans are served from the account's own host.
        if let Some(base) = payload.get("url").map(|u| u.trim().trim_end_matches('/')).filter(|u| u.starts_with("https://")) {
            crate::provider_settings::set_base_url("xiaomi", Some(base))?;
        }
        let account = payload.get("uid").cloned().unwrap_or_else(|| "MiMo account".into());
        crate::provider_settings::set_options("xiaomi", json!({"account": account}))?;
        Ok(account)
    };
    Ok((shown, task))
}

// ---------------------------------------------------------------------------
// Token renewal
// ---------------------------------------------------------------------------

/// Renews credentials of the providers this module signs in to, delegating
/// everything else to a package refresher when one is installed.
pub struct BuiltinOAuthRefresher {
    handle: tokio::runtime::Handle,
    fallback: Option<std::sync::Arc<dyn OAuthRefresher>>,
}

impl BuiltinOAuthRefresher {
    pub fn new(fallback: Option<std::sync::Arc<dyn OAuthRefresher>>) -> Option<Self> {
        Some(Self {
            handle: tokio::runtime::Handle::try_current().ok()?,
            fallback,
        })
    }
}

impl OAuthRefresher for BuiltinOAuthRefresher {
    fn supports(&self, provider: &str) -> bool {
        provider == "codex" || self.fallback.as_ref().is_some_and(|f| f.supports(provider))
    }

    fn refresh(&self, provider: &str) -> Result<RefreshedOAuth, String> {
        match provider {
            "codex" => codex_refresh(&self.handle),
            other => match &self.fallback {
                Some(fallback) => fallback.refresh(other),
                None => Err(format!("{other} cannot be renewed")),
            },
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The platform's side of the exchange: seal `json` for our public key.
    fn seal_for(public: &[u8], json: &str) -> String {
        use ring::{aead, agreement, rand::SystemRandom};
        let rng = SystemRandom::new();
        let ephemeral = agreement::EphemeralPrivateKey::generate(&agreement::X25519, &rng).unwrap();
        let ephemeral_public = ephemeral.compute_public_key().unwrap().as_ref().to_vec();
        let key = agreement::agree_ephemeral(
            ephemeral,
            &agreement::UnparsedPublicKey::new(&agreement::X25519, public),
            |shared| Sha256::digest(shared),
        )
        .unwrap();
        let key = aead::LessSafeKey::new(aead::UnboundKey::new(&aead::AES_256_GCM, &key).unwrap());
        let nonce = [7u8; 12];
        let mut sealed = json.as_bytes().to_vec();
        key.seal_in_place_append_tag(aead::Nonce::assume_unique_for_key(nonce), aead::Aad::empty(), &mut sealed)
            .unwrap();
        let mut blob = ephemeral_public;
        blob.extend_from_slice(&nonce);
        blob.extend_from_slice(&sealed);
        b64url(&blob)
    }

    #[test]
    fn mimo_reply_decrypts_with_our_key_only() {
        use ring::{agreement, rand::SystemRandom};
        let rng = SystemRandom::new();
        let ours = agreement::EphemeralPrivateKey::generate(&agreement::X25519, &rng).unwrap();
        let public = ours.compute_public_key().unwrap().as_ref().to_vec();
        let blob = seal_for(&public, r#"{"sk":"sk-test","uid":"42","url":"https://token-plan-sgp.xiaomimimo.com/v1"}"#);
        let payload = mimo_decrypt(ours, &blob).unwrap();
        assert_eq!(payload["sk"], "sk-test");
        assert_eq!(payload["uid"], "42");

        let other = agreement::EphemeralPrivateKey::generate(&agreement::X25519, &rng).unwrap();
        assert!(mimo_decrypt(other, &blob).is_err(), "another attempt's key cannot open it");
        let spki = [X25519_SPKI_PREFIX.as_slice(), &public].concat();
        assert_eq!(spki.len(), 44);
    }

    #[test]
    fn reads_the_chatgpt_account_from_id_token_claims() {
        let claims = json!({"email": "dev@example.com", "https://api.openai.com/auth": {"chatgpt_account_id": "acct_1"}});
        let token = format!("h.{}.s", b64url(claims.to_string().as_bytes()));
        let (account, email) = codex_account(&json!({"id_token": token}));
        assert_eq!(account.as_deref(), Some("acct_1"));
        assert_eq!(email.as_deref(), Some("dev@example.com"));
    }

    #[test]
    fn form_encodes_reserved_characters() {
        assert_eq!(form(&[("redirect_uri", "http://localhost:1455/a b")]), "redirect%5Furi=http%3A%2F%2Flocalhost%3A1455%2Fa%20b");
    }
}
