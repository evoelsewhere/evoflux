//! Port of `app/core/desktop_auth.py` (`DesktopTokenMiddleware`).
//!
//! Python is the reference: this layer decides exactly as the middleware does,
//! including its quirks (exempt-path matching on the percent-decoded path, the
//! `?_token=` guard testing the raw query bytes, no query rewrite on exempt
//! paths). Not ported: the single-device lock claim for trusted tailnet
//! requests (`remote_use_service.claim`) stays in Python behind the gateway,
//! and the WebSocket check (`websocket_authorized`).
//!
//! Where Python raises (`hmac.compare_digest` on non-ASCII `str` is a
//! `TypeError`, i.e. a 500), this layer fails closed with the normal 401.

use std::convert::Infallible;
use std::future::Future;
use std::pin::Pin;
use std::str::FromStr;
use std::sync::Arc;
use std::task::{Context, Poll};

use axum::extract::Request;
use axum::http::header::AUTHORIZATION;
use axum::http::uri::PathAndQuery;
use axum::http::{HeaderMap, Uri};
use axum::response::{IntoResponse, Response};
use subtle::ConstantTimeEq;
use tower::{Layer, Service};

use crate::error::ApiError;

pub const REMOTE_USER_LOGIN_HEADER: &str = "Tailscale-User-Login";
pub const REMOTE_PROXY_MARKER_HEADER: &str = "X-EvoFlux-Remote-Proxy";
pub const REMOTE_PROXY_TOKEN_HEADER: &str = "X-EvoFlux-Remote-Token";
pub const REMOTE_DEVICE_LABEL_HEADER: &str = "X-EvoFlux-Device-Label";
pub const REMOTE_PROXY_MARKER: &str = "tsnet";
const QS_TOKEN_PARAM: &str = "_token";

const EXEMPT_EXACT: &[&str] = &[
    "/metrics",
    "/api/health/live",
    "/api/health/ready",
    "/",
    "/index.html",
    "/favicon.ico",
    "/favicon.svg",
    "/vite.svg",
    "/robots.txt",
    "/manifest.json",
];
const EXEMPT_PREFIXES: &[&str] = &["/api/health/", "/assets/", "/static/"];
const CUSTOM_AUTH_EXACT: &[&str] = &[
    "/api/team/webbridge/pairing/native",
    "/api/team/webbridge/relay-ticket",
    "/api/team/webbridge/interactions",
    "/api/team/webbridge/bindings",
    "/api/team/webbridge/sessions",
    "/api/team/webbridge/models",
    "/api/team/webbridge/appearance",
    "/api/team/webbridge/teach-drafts",
];
const CUSTOM_AUTH_PREFIXES: &[&str] = &[
    "/api/team/webbridge/bindings/",
    "/api/team/webbridge/sessions/",
];

/// Request extension set on requests attributed to a trusted tailnet session
/// (`request.state.remote_user_login`).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RemoteLogin(pub String);

#[derive(Debug)]
struct Inner {
    token: String,
    remote_proxy_secret: String,
    embedded_proxy_required: bool,
}

/// Desktop bearer-token authentication with remote-proxy header trust.
#[derive(Debug, Clone)]
pub struct DesktopAuth {
    inner: Arc<Inner>,
}

impl DesktopAuth {
    /// `token` of `None` or `""` disables token auth. `remote_proxy_secret` is
    /// the per-process secret shared with the bundled tsnet child.
    ///
    /// Whether an unrecognised proxy marker is trusted follows Python's
    /// `_embedded_proxy_required` (`EVOFLUX_REMOTE_USE_PROVIDER` /
    /// `EVOFLUX_TSNET_BIN`), read here once.
    pub fn new(token: Option<String>, remote_proxy_secret: String) -> Self {
        let provider = std::env::var("EVOFLUX_REMOTE_USE_PROVIDER").unwrap_or_default();
        let tsnet_bin = std::env::var("EVOFLUX_TSNET_BIN").unwrap_or_default();
        let required = provider.trim().to_lowercase() != "external" && !tsnet_bin.is_empty();
        Self::build(token, remote_proxy_secret, required)
    }

    /// Override whether non-`tsnet` proxy markers are rejected.
    pub fn with_embedded_proxy_required(self, required: bool) -> Self {
        Self::build(
            Some(self.inner.token.clone()),
            self.inner.remote_proxy_secret.clone(),
            required,
        )
    }

    fn build(token: Option<String>, remote_proxy_secret: String, required: bool) -> Self {
        Self {
            inner: Arc::new(Inner {
                token: token.unwrap_or_default(),
                remote_proxy_secret,
                embedded_proxy_required: required,
            }),
        }
    }

    pub fn layer(&self) -> DesktopAuthLayer {
        DesktopAuthLayer { auth: self.clone() }
    }
}

#[derive(Debug, Clone)]
pub struct DesktopAuthLayer {
    auth: DesktopAuth,
}

impl<S> Layer<S> for DesktopAuthLayer {
    type Service = DesktopAuthService<S>;

    fn layer(&self, inner: S) -> Self::Service {
        DesktopAuthService {
            auth: self.auth.clone(),
            inner,
        }
    }
}

#[derive(Debug, Clone)]
pub struct DesktopAuthService<S> {
    auth: DesktopAuth,
    inner: S,
}

type BoxFuture<T> = Pin<Box<dyn Future<Output = T> + Send>>;

impl<S> Service<Request> for DesktopAuthService<S>
where
    S: Service<Request, Response = Response, Error = Infallible> + Clone + Send + 'static,
    S::Future: Send + 'static,
{
    type Response = Response;
    type Error = Infallible;
    type Future = BoxFuture<Result<Response, Infallible>>;

    fn poll_ready(&mut self, cx: &mut Context<'_>) -> Poll<Result<(), Self::Error>> {
        self.inner.poll_ready(cx)
    }

    fn call(&mut self, req: Request) -> Self::Future {
        let clone = self.inner.clone();
        let mut inner = std::mem::replace(&mut self.inner, clone);
        let decision = self.auth.decide(req);
        Box::pin(async move {
            match decision {
                Decision::Reject(err) => Ok(err.into_response()),
                Decision::Forward(req) => inner.call(req).await,
            }
        })
    }
}

enum Decision {
    Forward(Request),
    Reject(ApiError),
}

impl DesktopAuth {
    fn decide(&self, mut req: Request) -> Decision {
        let headers = req.headers();
        let remote_login = header_text(headers, REMOTE_USER_LOGIN_HEADER)
            .map(|v| py_strip(&v).to_owned())
            .unwrap_or_default();
        if !remote_login.is_empty() {
            let marker = header_text(headers, REMOTE_PROXY_MARKER_HEADER)
                .map(|v| py_strip(&v).to_owned())
                .unwrap_or_default();
            let provided = header_text(headers, REMOTE_PROXY_TOKEN_HEADER).unwrap_or_default();
            if !self.trusted_remote_proxy_headers(&marker, &provided) {
                tracing::warn!("remote_proxy_identity_rejected");
                return Decision::Reject(ApiError::untrusted_tailnet_identity());
            }
            req.extensions_mut().insert(RemoteLogin(remote_login));
            return Decision::Forward(req);
        }
        if self.inner.token.is_empty() {
            return Decision::Forward(req);
        }

        let path = percent_decode(req.uri().path().as_bytes());
        if path_is_exempt(&path) || path_is_custom_auth(&path) {
            return Decision::Forward(req);
        }

        let query = req.uri().query().unwrap_or("");
        let token = extract_token(req.headers(), query);
        if !token_matches(token.as_deref(), &self.inner.token) {
            tracing::warn!(path = %path, has_token = token.is_some(), "desktop_token_rejected");
            return Decision::Reject(ApiError::unauthorized());
        }
        // Scrub the query-string token so it never reaches downstream logs.
        match strip_token(req.uri()) {
            Ok(Some(uri)) => *req.uri_mut() = uri,
            Ok(None) => {}
            Err(()) => return Decision::Reject(ApiError::internal()),
        }
        Decision::Forward(req)
    }

    fn trusted_remote_proxy_headers(&self, marker: &str, provided: &str) -> bool {
        if marker == REMOTE_PROXY_MARKER {
            return constant_time_eq(
                provided.as_bytes(),
                self.inner.remote_proxy_secret.as_bytes(),
            );
        }
        !self.inner.embedded_proxy_required
    }
}

fn token_matches(provided: Option<&str>, expected: &str) -> bool {
    match provided {
        Some(p) if !p.is_empty() && !expected.is_empty() => {
            constant_time_eq(p.as_bytes(), expected.as_bytes())
        }
        _ => false,
    }
}

fn constant_time_eq(a: &[u8], b: &[u8]) -> bool {
    a.ct_eq(b).into()
}

fn path_is_api(path: &str) -> bool {
    path == "/api" || path.starts_with("/api/")
}

fn path_is_exempt(path: &str) -> bool {
    EXEMPT_EXACT.contains(&path)
        || EXEMPT_PREFIXES.iter().any(|p| path.starts_with(p))
        // Non-API paths are SPA shell routes.
        || !path_is_api(path)
}

fn path_is_custom_auth(path: &str) -> bool {
    CUSTOM_AUTH_EXACT.contains(&path) || CUSTOM_AUTH_PREFIXES.iter().any(|p| path.starts_with(p))
}

/// Starlette decodes header bytes as latin-1.
fn header_text(headers: &HeaderMap, name: &str) -> Option<String> {
    headers
        .get(name)
        .map(|v| v.as_bytes().iter().map(|&b| char::from(b)).collect())
}

/// Python's `str.strip()` for the characters a latin-1 header can contain.
fn py_strip(s: &str) -> &str {
    s.trim_matches(|c: char| c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c))
}

fn extract_token(headers: &HeaderMap, query: &str) -> Option<String> {
    if let Some(auth) = header_text(headers, AUTHORIZATION.as_str()).filter(|v| !v.is_empty()) {
        let (scheme, value) = auth.split_once(' ').unwrap_or((auth.as_str(), ""));
        if scheme.to_lowercase() == "bearer" && !value.is_empty() {
            return Some(py_strip(value).to_owned());
        }
    }
    parse_qsl(query)
        .into_iter()
        .find(|(k, _)| k == QS_TOKEN_PARAM)
        .map(|(_, v)| v)
        .filter(|v| !v.is_empty())
}

/// Rewrite the URI without `_token`, as `_strip_token_from_scope` does.
/// `Ok(None)` when Python would leave the query untouched.
fn strip_token(uri: &Uri) -> Result<Option<Uri>, ()> {
    let Some(raw) = uri.query() else {
        return Ok(None);
    };
    if !raw.contains(QS_TOKEN_PARAM) {
        return Ok(None);
    }
    let kept: Vec<(String, String)> = parse_qsl(raw)
        .into_iter()
        .filter(|(k, _)| k != QS_TOKEN_PARAM)
        .collect();
    let query = urlencode(&kept);
    let path = uri.path();
    let path_and_query = if query.is_empty() {
        path.to_owned()
    } else {
        format!("{path}?{query}")
    };
    let mut parts = uri.clone().into_parts();
    parts.path_and_query = Some(PathAndQuery::from_str(&path_and_query).map_err(|_| ())?);
    Uri::from_parts(parts).map(Some).map_err(|_| ())
}

/// `urllib.parse.parse_qsl(raw, keep_blank_values=True)`.
fn parse_qsl(raw: &str) -> Vec<(String, String)> {
    raw.split('&')
        .filter(|segment| !segment.is_empty())
        .map(|segment| {
            let (name, value) = segment.split_once('=').unwrap_or((segment, ""));
            (form_decode(name), form_decode(value))
        })
        .collect()
}

fn form_decode(s: &str) -> String {
    percent_decode(s.replace('+', " ").as_bytes())
}

/// `urllib.parse.unquote`: `%XX` runs decoded as UTF-8 with replacement.
fn percent_decode(input: &[u8]) -> String {
    let mut out = Vec::with_capacity(input.len());
    let mut i = 0;
    while let Some(&byte) = input.get(i) {
        if byte == b'%' {
            let hi = input.get(i + 1).and_then(|b| hex_value(*b));
            let lo = input.get(i + 2).and_then(|b| hex_value(*b));
            if let (Some(hi), Some(lo)) = (hi, lo) {
                out.push(hi * 16 + lo);
                i += 3;
                continue;
            }
        }
        out.push(byte);
        i += 1;
    }
    String::from_utf8_lossy(&out).into_owned()
}

fn hex_value(b: u8) -> Option<u8> {
    match b {
        b'0'..=b'9' => Some(b - b'0'),
        b'a'..=b'f' => Some(b - b'a' + 10),
        b'A'..=b'F' => Some(b - b'A' + 10),
        _ => None,
    }
}

/// `urllib.parse.urlencode(pairs)` (`quote_plus`: keeps `A-Za-z0-9_.-~`).
fn urlencode(pairs: &[(String, String)]) -> String {
    pairs
        .iter()
        .map(|(k, v)| format!("{}={}", quote_plus(k), quote_plus(v)))
        .collect::<Vec<_>>()
        .join("&")
}

fn quote_plus(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    for &b in s.as_bytes() {
        match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'_' | b'.' | b'-' | b'~' => {
                out.push(char::from(b));
            }
            b' ' => out.push('+'),
            _ => out.push_str(&format!("%{b:02X}")),
        }
    }
    out
}
