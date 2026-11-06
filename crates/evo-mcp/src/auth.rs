//! Signing in to remote MCP servers (OAuth 2.1, as the MCP authorization
//! specification describes it), on `rmcp`'s implementation: discovery of the
//! server's authorization metadata, client registration (a registered client
//! id, a client metadata document, or dynamic registration), PKCE, the code
//! exchange and refreshing tokens.
//!
//! The browser comes back to a one-time loopback address
//! (`http://127.0.0.1:<port>/callback`). Tokens are kept per connector in
//! `mcp-auth.json` next to the connectors file — the same place evo keeps
//! provider credentials (`auth.json`) — and are refreshed when they expire.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use std::time::Duration;

use rmcp::transport::auth::{
    AuthClient, AuthError, AuthorizationManager, AuthorizationRequest, CredentialStore, OAuthState,
    StoredCredentials,
};
use tokio::io::{AsyncReadExt, AsyncWriteExt};

/// How long the sign-in page may stay open.
pub const SIGN_IN_TIMEOUT: Duration = Duration::from_secs(5 * 60);

/// One connector's tokens in the shared file.
#[derive(Clone)]
pub struct FileCredentialStore {
    path: PathBuf,
    key: String,
}

impl FileCredentialStore {
    pub fn new(path: &Path, key: &str) -> Self {
        Self {
            path: path.to_path_buf(),
            key: key.to_string(),
        }
    }
}

fn read_all(path: &Path) -> BTreeMap<String, StoredCredentials> {
    std::fs::read_to_string(path)
        .ok()
        .and_then(|text| serde_json::from_str(&text).ok())
        .unwrap_or_default()
}

fn write_all(path: &Path, all: &BTreeMap<String, StoredCredentials>) -> Result<(), String> {
    if let Some(dir) = path.parent() {
        std::fs::create_dir_all(dir).map_err(|e| e.to_string())?;
    }
    let text = serde_json::to_string_pretty(all).map_err(|e| e.to_string())?;
    let tmp = path.with_extension("json.tmp");
    std::fs::write(&tmp, text).map_err(|e| e.to_string())?;
    std::fs::rename(&tmp, path).map_err(|e| e.to_string())
}

#[async_trait::async_trait]
impl CredentialStore for FileCredentialStore {
    async fn load(&self) -> Result<Option<StoredCredentials>, AuthError> {
        Ok(read_all(&self.path).remove(&self.key))
    }

    async fn save(&self, credentials: StoredCredentials) -> Result<(), AuthError> {
        let mut all = read_all(&self.path);
        all.insert(self.key.clone(), credentials);
        write_all(&self.path, &all).map_err(AuthError::CredentialStoreError)
    }

    async fn clear(&self) -> Result<(), AuthError> {
        let mut all = read_all(&self.path);
        if all.remove(&self.key).is_some() {
            write_all(&self.path, &all).map_err(AuthError::CredentialStoreError)?;
        }
        Ok(())
    }
}

/// Whether `key` has tokens saved.
pub fn signed_in(path: &Path, key: &str) -> bool {
    read_all(path)
        .get(key)
        .is_some_and(|c| c.token_response.is_some())
}

/// Forget `key`'s tokens.
pub fn sign_out(path: &Path, key: &str) -> Result<(), String> {
    let mut all = read_all(path);
    if all.remove(key).is_some() {
        write_all(path, &all)?;
    }
    Ok(())
}

/// Sign in to the server at `url` as connector `key`: `open` shows the
/// provider's sign-in page in the browser; this returns once the browser came
/// back and the tokens are saved (or after [`SIGN_IN_TIMEOUT`]).
pub async fn sign_in(
    url: &str,
    path: &Path,
    key: &str,
    open: impl FnOnce(String),
) -> Result<(), String> {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
        .await
        .map_err(|e| format!("no local port: {e}"))?;
    let port = listener.local_addr().map_err(|e| e.to_string())?.port();
    let redirect = format!("http://127.0.0.1:{port}/callback");

    let mut state = OAuthState::new(url, None)
        .await
        .map_err(|e| format!("authorization discovery failed: {e}"))?;
    if let OAuthState::Unauthorized(manager) = &mut state {
        manager.set_credential_store(FileCredentialStore::new(path, key));
    }
    state
        .start_authorization(AuthorizationRequest::new(redirect).with_client_name("evo"))
        .await
        .map_err(|e| format!("could not start the sign-in: {e}"))?;
    let page = match &state {
        OAuthState::Session(session) => session.get_authorization_url().to_string(),
        _ => return Err("the sign-in did not start".into()),
    };
    open(page);

    let callback = tokio::time::timeout(SIGN_IN_TIMEOUT, wait_for_callback(listener, port))
        .await
        .map_err(|_| "the sign-in was not finished in time".to_string())??;
    state
        .handle_callback_url(&callback)
        .await
        .map_err(|e| format!("the sign-in failed: {e}"))?;
    state
        .complete_authorization()
        .await
        .map_err(|e| e.to_string())?;
    Ok(())
}

const DONE_PAGE: &str = "<!doctype html><meta charset=utf-8><title>evo</title>\
<body style=\"font-family:system-ui;display:grid;place-items:center;height:90vh;color:#444\">\
<div style=\"text-align:center\"><h2>Signed in</h2><p>You can close this tab and go back to evo.</p></div>";

/// The first request to `/callback` on `listener`, as a full URL.
async fn wait_for_callback(listener: tokio::net::TcpListener, port: u16) -> Result<String, String> {
    loop {
        let (mut stream, _) = listener.accept().await.map_err(|e| e.to_string())?;
        let mut buf = vec![0u8; 16 * 1024];
        let mut read = 0;
        while read < buf.len() {
            let n = stream
                .read(&mut buf[read..])
                .await
                .map_err(|e| e.to_string())?;
            if n == 0 {
                break;
            }
            read += n;
            if buf[..read].windows(4).any(|w| w == b"\r\n\r\n") {
                break;
            }
        }
        let head = String::from_utf8_lossy(&buf[..read]);
        let target = head
            .lines()
            .next()
            .and_then(|line| line.split_whitespace().nth(1))
            .unwrap_or("/")
            .to_string();
        if target.starts_with("/callback") {
            let body = DONE_PAGE;
            let response = format!(
                "HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
                body.len()
            );
            let _ = stream.write_all(response.as_bytes()).await;
            let _ = stream.shutdown().await;
            return Ok(format!("http://127.0.0.1:{port}{target}"));
        }
        let _ = stream
            .write_all(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            .await;
    }
}

/// An HTTP client that adds `key`'s saved token (refreshing it when needed),
/// or `None` when the connector is not signed in.
pub async fn authorized_client(
    url: &str,
    path: &Path,
    key: &str,
) -> Result<Option<AuthClient<reqwest::Client>>, String> {
    if !signed_in(path, key) {
        return Ok(None);
    }
    let mut manager = AuthorizationManager::new(url)
        .await
        .map_err(|e| e.to_string())?;
    manager.set_credential_store(FileCredentialStore::new(path, key));
    if !manager
        .initialize_from_store()
        .await
        .map_err(|e| e.to_string())?
    {
        return Ok(None);
    }
    Ok(Some(AuthClient::new(reqwest::Client::default(), manager)))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn the_store_keeps_each_connector_apart() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("mcp-auth.json");
        let a = FileCredentialStore::new(&path, "a");
        let b = FileCredentialStore::new(&path, "b");
        assert!(a.load().await.unwrap().is_none());
        a.save(StoredCredentials::new(
            "client-a".into(),
            None,
            Vec::new(),
            None,
        ))
        .await
        .unwrap();
        b.save(StoredCredentials::new(
            "client-b".into(),
            None,
            Vec::new(),
            None,
        ))
        .await
        .unwrap();
        assert_eq!(a.load().await.unwrap().unwrap().client_id, "client-a");
        // No token yet: not signed in.
        assert!(!signed_in(&path, "a"));
        a.clear().await.unwrap();
        assert!(a.load().await.unwrap().is_none());
        assert_eq!(b.load().await.unwrap().unwrap().client_id, "client-b");
        sign_out(&path, "b").unwrap();
        assert!(read_all(&path).is_empty());
    }

    #[tokio::test]
    async fn the_callback_listener_returns_the_redirect_url() {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = listener.local_addr().unwrap().port();
        let waiting = tokio::spawn(wait_for_callback(listener, port));
        let mut stream = tokio::net::TcpStream::connect(("127.0.0.1", port))
            .await
            .unwrap();
        stream
            .write_all(b"GET /favicon.ico HTTP/1.1\r\nHost: x\r\n\r\n")
            .await
            .unwrap();
        let mut stream = tokio::net::TcpStream::connect(("127.0.0.1", port))
            .await
            .unwrap();
        stream
            .write_all(b"GET /callback?code=abc&state=xyz HTTP/1.1\r\nHost: x\r\n\r\n")
            .await
            .unwrap();
        let mut reply = String::new();
        stream.read_to_string(&mut reply).await.unwrap();
        assert!(reply.starts_with("HTTP/1.1 200"));
        assert_eq!(
            waiting.await.unwrap().unwrap(),
            format!("http://127.0.0.1:{port}/callback?code=abc&state=xyz")
        );
    }
}
