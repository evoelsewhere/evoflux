//! Host and Origin checks in front of every route, Rust- or Python-owned.
//!
//! Owner decision 2026-11-01, a deliberate difference from Python's
//! `CORSMiddleware(allow_origins=["*"])` (`app/api/app.py`): any page open in
//! the user's browser could call the local API, and a DNS-rebound name could
//! read the answers. See `server/KNOWN_DIFFERENCES.md`.
//!
//! The UI reaches the gateway from loopback pages (the same origin, the Vite
//! dev and preview servers, which keep the page's `Origin` when they proxy
//! `/api`), from the Tauri window, from the WebBridge extension, and through
//! the bundled tsnet proxy, which keeps the tailnet `Host` and `Origin`.

use std::sync::Arc;

use axum::extract::Request;
use axum::http::header::{
    ACCESS_CONTROL_ALLOW_CREDENTIALS, ACCESS_CONTROL_ALLOW_HEADERS, ACCESS_CONTROL_ALLOW_METHODS,
    ACCESS_CONTROL_ALLOW_ORIGIN, ACCESS_CONTROL_MAX_AGE, ACCESS_CONTROL_REQUEST_HEADERS,
    ACCESS_CONTROL_REQUEST_METHOD, CONTENT_TYPE, HOST, ORIGIN, VARY,
};
use axum::http::{HeaderMap, HeaderValue, Method, StatusCode};
use axum::middleware::{self, Next};
use axum::response::{IntoResponse, Response};
use axum::Router;
use evoflux_core::ApiError;

/// Hosts that always name this machine, whatever the port.
const LOOPBACK_HOSTS: &[&str] = &["localhost", "127.0.0.1", "[::1]"];
/// The Tauri window: macOS/Linux, Windows, and Windows with the HTTPS scheme.
const TAURI_ORIGINS: &[&str] = &[
    "tauri://localhost",
    "http://tauri.localhost",
    "https://tauri.localhost",
];
/// `_WEBBRIDGE_EXTENSION_ID` in `app/api/routes/team/webbridge.py`.
const WEBBRIDGE_EXTENSION_ID: &str = "lghglpnddenmebbhkfachafichhglafi";
/// Starlette's `ALL_METHODS`, what `allow_methods=["*"]` answers a preflight with.
const PREFLIGHT_METHODS: &str = "DELETE, GET, HEAD, OPTIONS, PATCH, POST, PUT";
const PREFLIGHT_MAX_AGE: &str = "600";

/// Which `Host` and `Origin` values the gateway accepts.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct OriginPolicy {
    /// The `--host` the gateway is bound to, unless it is a wildcard.
    bound: Option<String>,
    /// Hosts of the `EVOFLUX_ALLOWED_ORIGINS` entries.
    origin_hosts: Vec<String>,
    /// `EVOFLUX_ALLOWED_ORIGINS`, lower-cased, without a trailing `/`.
    origins: Vec<String>,
    /// The bundled WebBridge extension plus `EVOFLUX_WEBBRIDGE_EXTENSION_IDS`.
    extension_ids: Vec<String>,
}

impl OriginPolicy {
    /// `bind_host` is the bound `--host`; `allowed_origins` is
    /// `EVOFLUX_ALLOWED_ORIGINS` and `extension_ids` is
    /// `EVOFLUX_WEBBRIDGE_EXTENSION_IDS`, both comma-separated.
    pub fn new(
        bind_host: &str,
        allowed_origins: Option<&str>,
        extension_ids: Option<&str>,
    ) -> Self {
        let bind_host = bind_host.trim().to_ascii_lowercase();
        let bound = match bind_host.as_str() {
            "" | "0.0.0.0" | "::" | "[::]" => None,
            host if host.contains(':') && !host.starts_with('[') => Some(format!("[{host}]")),
            host => Some(host.to_owned()),
        };
        let origins: Vec<String> = list(allowed_origins)
            .map(|origin| origin.trim_end_matches('/').to_ascii_lowercase())
            .collect();
        let origin_hosts = origins
            .iter()
            .filter_map(|origin| origin.split_once("://"))
            .filter_map(|(_, authority)| hostname(authority))
            .collect();
        let mut ids = vec![WEBBRIDGE_EXTENSION_ID.to_owned()];
        ids.extend(list(extension_ids).map(str::to_ascii_lowercase));
        Self {
            bound,
            origin_hosts,
            origins,
            extension_ids: ids,
        }
    }

    /// A `Host` header naming this machine: a loopback name, the bound host,
    /// or the host of an allowed origin, on any port.
    pub fn host_allowed(&self, host: &str) -> bool {
        hostname(host).is_some_and(|name| {
            LOOPBACK_HOSTS.contains(&name.as_str())
                || self.bound.as_ref() == Some(&name)
                || self.origin_hosts.contains(&name)
        })
    }

    /// An `Origin` of the app: a loopback or bound-host page, the Tauri
    /// window, the WebBridge extension, an `EVOFLUX_ALLOWED_ORIGINS` entry,
    /// or, behind the bundled tsnet proxy, the page's own tailnet origin.
    pub fn origin_allowed(
        &self,
        origin: &str,
        request_host: Option<&str>,
        via_tsnet: bool,
    ) -> bool {
        let origin = origin.to_ascii_lowercase();
        if TAURI_ORIGINS.contains(&origin.as_str()) || self.origins.contains(&origin) {
            return true;
        }
        let Some((scheme, authority)) = origin.split_once("://") else {
            return false;
        };
        match scheme {
            "http" | "https" => {
                let Some(name) = hostname(authority) else {
                    return false;
                };
                (via_tsnet && request_host.is_some_and(|host| host.eq_ignore_ascii_case(authority)))
                    || LOOPBACK_HOSTS.contains(&name.as_str())
                    || self.bound.as_ref() == Some(&name)
            }
            "chrome-extension" => self.extension_ids.iter().any(|id| id == authority),
            _ => false,
        }
    }
}

fn list(raw: Option<&str>) -> impl Iterator<Item = &str> {
    raw.unwrap_or_default()
        .split(',')
        .map(str::trim)
        .filter(|item| !item.is_empty())
}

/// The lower-cased host of `host[:port]` or `[v6][:port]`, `None` for an
/// unclosed `[`. It is only ever compared with exact names, so anything odd
/// (a path, user info) simply matches nothing.
fn hostname(authority: &str) -> Option<String> {
    let host = match authority.strip_prefix('[') {
        Some(inner) => format!("[{}]", inner.split_once(']')?.0),
        None => authority
            .split_once(':')
            .map_or(authority, |(host, _)| host)
            .to_owned(),
    };
    Some(host.to_ascii_lowercase())
}

/// Put the checks in front of `router`. `via_tsnet` says whether a request
/// carries the bundled tsnet proxy's verified identity headers.
pub fn guard<F>(router: Router, policy: Arc<OriginPolicy>, via_tsnet: F) -> Router
where
    F: Fn(&HeaderMap) -> bool + Clone + Send + Sync + 'static,
{
    router.layer(middleware::from_fn(move |req, next| {
        check(req, next, Arc::clone(&policy), via_tsnet.clone())
    }))
}

async fn check<F>(req: Request, next: Next, policy: Arc<OriginPolicy>, via_tsnet: F) -> Response
where
    F: Fn(&HeaderMap) -> bool,
{
    let tsnet = via_tsnet(req.headers());
    let host = match req.headers().get(HOST) {
        Some(value) => match value.to_str() {
            Ok(host) => Some(host.to_owned()),
            Err(_) => return forbidden("Host not allowed.", "host_not_allowed"),
        },
        None => req.uri().authority().map(|a| a.as_str().to_owned()),
    };
    // No Host at all is a non-browser client; a browser always sends one.
    if let Some(host) = host.as_deref() {
        if !tsnet && !policy.host_allowed(host) {
            tracing::warn!(host, "request_host_rejected");
            return forbidden("Host not allowed.", "host_not_allowed");
        }
    }
    let origin = match req.headers().get(ORIGIN) {
        None => None,
        Some(value) => match value.to_str() {
            Ok(origin) => Some(origin.to_owned()),
            Err(_) => return forbidden("Origin not allowed.", "origin_not_allowed"),
        },
    };
    let Some(origin) = origin else {
        return with_cors(next.run(req).await, None);
    };
    if !policy.origin_allowed(&origin, host.as_deref(), tsnet) {
        tracing::warn!(origin, "request_origin_rejected");
        return forbidden("Origin not allowed.", "origin_not_allowed");
    }
    if req.method() == Method::OPTIONS && req.headers().contains_key(ACCESS_CONTROL_REQUEST_METHOD)
    {
        return preflight(
            &origin,
            req.headers().get(ACCESS_CONTROL_REQUEST_HEADERS).cloned(),
        );
    }
    with_cors(next.run(req).await, Some(&origin))
}

fn forbidden(detail: &'static str, code: &'static str) -> Response {
    let mut response = ApiError::new(StatusCode::FORBIDDEN, detail)
        .with_code(code)
        .into_response();
    add_vary_origin(response.headers_mut());
    response
}

/// Starlette's preflight answer, with the origin echoed instead of `*`.
fn preflight(origin: &str, requested_headers: Option<HeaderValue>) -> Response {
    let mut response = (
        StatusCode::OK,
        [(CONTENT_TYPE, "text/plain; charset=utf-8")],
        "OK",
    )
        .into_response();
    response = with_cors(response, Some(origin));
    let headers = response.headers_mut();
    headers.insert(
        ACCESS_CONTROL_ALLOW_METHODS,
        HeaderValue::from_static(PREFLIGHT_METHODS),
    );
    headers.insert(
        ACCESS_CONTROL_MAX_AGE,
        HeaderValue::from_static(PREFLIGHT_MAX_AGE),
    );
    if let Some(requested) = requested_headers {
        headers.insert(ACCESS_CONTROL_ALLOW_HEADERS, requested);
    }
    response
}

/// Drop every `Access-Control-*` header the route (Python's `CORSMiddleware`
/// included) set, then allow only the checked `origin`.
fn with_cors(mut response: Response, origin: Option<&str>) -> Response {
    let headers = response.headers_mut();
    let upstream: Vec<_> = headers
        .keys()
        .filter(|name| name.as_str().starts_with("access-control-"))
        .cloned()
        .collect();
    for name in upstream {
        headers.remove(name);
    }
    if let Some(value) = origin.and_then(|o| HeaderValue::from_str(o).ok()) {
        headers.insert(ACCESS_CONTROL_ALLOW_ORIGIN, value);
        headers.insert(
            ACCESS_CONTROL_ALLOW_CREDENTIALS,
            HeaderValue::from_static("true"),
        );
    }
    add_vary_origin(headers);
    response
}

fn add_vary_origin(headers: &mut HeaderMap) {
    let present = headers.get_all(VARY).iter().any(|value| {
        value.to_str().is_ok_and(|v| {
            v.split(',')
                .any(|part| matches!(part.trim().to_ascii_lowercase().as_str(), "origin" | "*"))
        })
    });
    if !present {
        headers.append(VARY, HeaderValue::from_static("Origin"));
    }
}

#[cfg(test)]
mod tests {
    #![allow(clippy::unwrap_used, clippy::expect_used, clippy::indexing_slicing)]
    use super::*;
    use axum::body::{to_bytes, Body};
    use axum::http::Request as HttpRequest;
    use axum::routing::any;
    use tower::ServiceExt;

    fn policy() -> OriginPolicy {
        OriginPolicy::new("127.0.0.1", None, None)
    }

    #[test]
    fn loopback_hosts_pass_on_any_port() {
        let p = policy();
        for host in [
            "localhost",
            "LOCALHOST:4082",
            "127.0.0.1",
            "127.0.0.1:1",
            "[::1]",
            "[::1]:65535",
        ] {
            assert!(p.host_allowed(host), "{host}");
        }
    }

    #[test]
    fn other_or_malformed_hosts_are_refused() {
        let p = policy();
        for host in [
            "evil.example",
            "evil.example:4082",
            "localhost.evil.example",
            "localhost.",
            "127.0.0.2",
            "[::2]",
            "localhost/x",
            "user@localhost",
            "[::1",
            "[]",
            "[::1/]",
            "",
            ":4082",
        ] {
            assert!(!p.host_allowed(host), "{host}");
        }
    }

    #[test]
    fn the_bound_host_is_accepted_unless_it_is_a_wildcard() {
        let lan = OriginPolicy::new(" 192.168.1.5 ", None, None);
        assert!(lan.host_allowed("192.168.1.5:4082"));
        assert!(lan.origin_allowed("http://192.168.1.5:4082", None, false));
        assert!(!lan.host_allowed("192.168.1.6"));
        let named = OriginPolicy::new("MyBox.local", None, None);
        assert!(named.host_allowed("mybox.local:1"));
        let v6 = OriginPolicy::new("fe80::1", None, None);
        assert!(v6.host_allowed("[fe80::1]:4082"));
        let bracketed = OriginPolicy::new("[fe80::2]", None, None);
        assert!(bracketed.host_allowed("[FE80::2]"));
        for wildcard in ["0.0.0.0", "::", "[::]", ""] {
            let p = OriginPolicy::new(wildcard, None, None);
            assert_eq!(p.bound, None, "{wildcard:?}");
            assert!(!p.host_allowed("0.0.0.0"), "{wildcard:?}");
            assert!(p.host_allowed("localhost"), "{wildcard:?}");
        }
    }

    #[test]
    fn app_origins_pass() {
        let p = policy();
        for origin in [
            "http://localhost:5173",
            "http://127.0.0.1:41234",
            "https://localhost",
            "http://[::1]:4082",
            "HTTP://LOCALHOST:5173",
            "tauri://localhost",
            "http://tauri.localhost",
            "https://tauri.localhost",
            "chrome-extension://lghglpnddenmebbhkfachafichhglafi",
        ] {
            assert!(
                p.origin_allowed(origin, Some("127.0.0.1:4082"), false),
                "{origin}"
            );
        }
    }

    #[test]
    fn foreign_origins_are_refused() {
        let p = policy();
        for origin in [
            "https://evil.example",
            "http://localhost.evil.example",
            "http://127.0.0.1.nip.io",
            "null",
            "file://",
            "tauri://evil",
            "http://tauri.localhost:1",
            "ws://localhost",
            "chrome-extension://abcdefghijklmnopabcdefghijklmnop",
            "http://localhost/path",
            "",
        ] {
            assert!(
                !p.origin_allowed(origin, Some("127.0.0.1:4082"), false),
                "{origin}"
            );
        }
    }

    #[test]
    fn allowed_origins_setting_adds_exact_origins_and_their_hosts() {
        let p = OriginPolicy::new(
            "127.0.0.1",
            Some(" https://Box.Tail.ts.net/ , ,http://lan.example:8080"),
            None,
        );
        assert!(p.origin_allowed("https://box.tail.ts.net", None, false));
        assert!(p.origin_allowed("http://lan.example:8080", None, false));
        assert!(!p.origin_allowed("http://box.tail.ts.net", None, false));
        assert!(!p.origin_allowed("http://lan.example:8081", None, false));
        assert!(p.host_allowed("box.tail.ts.net"));
        assert!(p.host_allowed("lan.example:8080"));
        assert!(!p.host_allowed("tail.ts.net"));
        let empty = OriginPolicy::new("127.0.0.1", Some(" , "), None);
        assert!(empty.origins.is_empty() && empty.origin_hosts.is_empty());
    }

    #[test]
    fn extension_ids_setting_adds_extensions() {
        let p = OriginPolicy::new(
            "127.0.0.1",
            None,
            Some("abcdefghijklmnopabcdefghijklmnop, X"),
        );
        for allowed in [
            "chrome-extension://abcdefghijklmnopabcdefghijklmnop",
            "chrome-extension://lghglpnddenmebbhkfachafichhglafi",
            "chrome-extension://x",
        ] {
            assert!(p.origin_allowed(allowed, None, false), "{allowed}");
        }
        assert!(!p.origin_allowed("moz-extension://x", None, false));
    }

    #[test]
    fn tsnet_requests_may_use_their_own_tailnet_origin_only() {
        let p = policy();
        let host = Some("box.tail.ts.net");
        assert!(p.origin_allowed("https://box.tail.ts.net", host, true));
        assert!(p.origin_allowed("http://Box.Tail.ts.net", host, true));
        assert!(!p.origin_allowed("https://box.tail.ts.net", host, false));
        assert!(!p.origin_allowed("https://evil.example", host, true));
        assert!(!p.origin_allowed("https://box.tail.ts.net", None, true));
        assert!(!p.origin_allowed("ftp://box.tail.ts.net", host, true));
    }

    async fn upstream() -> Response {
        (
            [
                ("access-control-allow-origin", "*"),
                ("access-control-allow-credentials", "true"),
                ("access-control-expose-headers", "x-secret"),
                ("x-upstream", "1"),
            ],
            "upstream",
        )
            .into_response()
    }

    fn app(tsnet: bool) -> Router {
        guard(
            Router::new().route("/{*path}", any(upstream)),
            Arc::new(policy()),
            move |_: &HeaderMap| tsnet,
        )
    }

    async fn send(app: Router, req: HttpRequest<Body>) -> (StatusCode, HeaderMap, String) {
        let response = app.oneshot(req).await.unwrap();
        let status = response.status();
        let headers = response.headers().clone();
        let body = to_bytes(response.into_body(), usize::MAX).await.unwrap();
        (status, headers, String::from_utf8(body.to_vec()).unwrap())
    }

    fn request(method: &str, host: Option<&str>, origin: Option<&str>) -> HttpRequest<Body> {
        let mut builder = HttpRequest::builder().method(method).uri("/api/x");
        if let Some(host) = host {
            builder = builder.header(HOST, host);
        }
        if let Some(origin) = origin {
            builder = builder.header(ORIGIN, origin);
        }
        builder.body(Body::empty()).unwrap()
    }

    fn cors_names(headers: &HeaderMap) -> Vec<String> {
        let mut names: Vec<_> = headers
            .keys()
            .map(|n| n.as_str().to_owned())
            .filter(|n| n.starts_with("access-control-"))
            .collect();
        names.sort();
        names
    }

    #[tokio::test]
    async fn no_origin_passes_and_upstream_cors_is_stripped() {
        let (status, headers, body) =
            send(app(false), request("GET", Some("127.0.0.1:4082"), None)).await;
        assert_eq!((status, body.as_str()), (StatusCode::OK, "upstream"));
        assert!(cors_names(&headers).is_empty(), "{headers:?}");
        assert_eq!(headers["x-upstream"], "1");
        assert_eq!(headers[VARY], "Origin");
    }

    #[tokio::test]
    async fn no_host_at_all_is_a_non_browser_client() {
        let (status, _, _) = send(app(false), request("GET", None, None)).await;
        assert_eq!(status, StatusCode::OK);
    }

    #[tokio::test]
    async fn allowed_origin_is_echoed_with_credentials() {
        for method in ["GET", "POST", "DELETE"] {
            let (status, headers, _) = send(
                app(false),
                request(
                    method,
                    Some("127.0.0.1:4082"),
                    Some("http://localhost:5173"),
                ),
            )
            .await;
            assert_eq!(status, StatusCode::OK);
            assert_eq!(
                cors_names(&headers),
                [
                    "access-control-allow-credentials",
                    "access-control-allow-origin"
                ]
            );
            assert_eq!(
                headers[ACCESS_CONTROL_ALLOW_ORIGIN],
                "http://localhost:5173"
            );
            assert_eq!(headers[ACCESS_CONTROL_ALLOW_CREDENTIALS], "true");
            assert_eq!(headers[VARY], "Origin");
        }
    }

    #[tokio::test]
    async fn evil_origin_is_403_for_every_method() {
        for method in ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"] {
            let (status, headers, body) = send(
                app(false),
                request(method, Some("127.0.0.1:4082"), Some("https://evil.example")),
            )
            .await;
            assert_eq!(status, StatusCode::FORBIDDEN, "{method}");
            assert!(cors_names(&headers).is_empty(), "{method}");
            assert_eq!(headers[VARY], "Origin");
            assert_eq!(headers[CONTENT_TYPE], "application/json");
            let expected = r#"{"detail":"Origin not allowed.","code":"origin_not_allowed"}"#;
            // axum drops the body of a HEAD answer.
            assert_eq!(body, if method == "HEAD" { "" } else { expected });
        }
    }

    #[tokio::test]
    async fn evil_host_is_403_even_with_an_allowed_or_no_origin() {
        for origin in [None, Some("http://localhost:5173")] {
            let (status, headers, body) = send(
                app(false),
                request("GET", Some("evil.example:4082"), origin),
            )
            .await;
            assert_eq!(status, StatusCode::FORBIDDEN);
            assert_eq!(headers[VARY], "Origin");
            assert_eq!(
                body,
                r#"{"detail":"Host not allowed.","code":"host_not_allowed"}"#
            );
        }
    }

    #[tokio::test]
    async fn non_ascii_host_or_origin_is_403() {
        let mut req = request("GET", None, None);
        req.headers_mut()
            .insert(HOST, HeaderValue::from_bytes(b"\xe9vil").unwrap());
        let (status, _, body) = send(app(false), req).await;
        assert_eq!(status, StatusCode::FORBIDDEN);
        assert!(body.contains("host_not_allowed"), "{body}");
        let mut req = request("GET", Some("localhost"), None);
        req.headers_mut()
            .insert(ORIGIN, HeaderValue::from_bytes(b"http://\xe9").unwrap());
        let (status, _, body) = send(app(false), req).await;
        assert_eq!(status, StatusCode::FORBIDDEN);
        assert!(body.contains("origin_not_allowed"), "{body}");
    }

    #[tokio::test]
    async fn uri_authority_is_checked_when_there_is_no_host_header() {
        let req = HttpRequest::builder()
            .uri("http://evil.example/api/x")
            .body(Body::empty())
            .unwrap();
        assert_eq!(send(app(false), req).await.0, StatusCode::FORBIDDEN);
        let req = HttpRequest::builder()
            .uri("http://localhost:4082/api/x")
            .body(Body::empty())
            .unwrap();
        assert_eq!(send(app(false), req).await.0, StatusCode::OK);
    }

    #[tokio::test]
    async fn tsnet_requests_skip_the_host_check() {
        let (status, headers, _) = send(
            app(true),
            request(
                "POST",
                Some("box.tail.ts.net"),
                Some("https://box.tail.ts.net"),
            ),
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(
            headers[ACCESS_CONTROL_ALLOW_ORIGIN],
            "https://box.tail.ts.net"
        );
        let (status, _, _) = send(
            app(true),
            request(
                "POST",
                Some("box.tail.ts.net"),
                Some("https://evil.example"),
            ),
        )
        .await;
        assert_eq!(status, StatusCode::FORBIDDEN);
        let (status, _, _) = send(app(false), request("GET", Some("box.tail.ts.net"), None)).await;
        assert_eq!(status, StatusCode::FORBIDDEN);
    }

    #[tokio::test]
    async fn preflight_is_answered_by_the_gateway() {
        let mut req = request("OPTIONS", Some("127.0.0.1:4082"), Some("tauri://localhost"));
        req.headers_mut().insert(
            ACCESS_CONTROL_REQUEST_METHOD,
            HeaderValue::from_static("POST"),
        );
        req.headers_mut().insert(
            ACCESS_CONTROL_REQUEST_HEADERS,
            HeaderValue::from_static("authorization,content-type"),
        );
        let (status, headers, body) = send(app(false), req).await;
        assert_eq!((status, body.as_str()), (StatusCode::OK, "OK"));
        assert!(!headers.contains_key("x-upstream"));
        assert_eq!(headers[ACCESS_CONTROL_ALLOW_ORIGIN], "tauri://localhost");
        assert_eq!(headers[ACCESS_CONTROL_ALLOW_CREDENTIALS], "true");
        assert_eq!(headers[ACCESS_CONTROL_ALLOW_METHODS], PREFLIGHT_METHODS);
        assert_eq!(headers[ACCESS_CONTROL_MAX_AGE], "600");
        assert_eq!(
            headers[ACCESS_CONTROL_ALLOW_HEADERS],
            "authorization,content-type"
        );
        assert_eq!(headers[CONTENT_TYPE], "text/plain; charset=utf-8");
        assert_eq!(headers[VARY], "Origin");

        let mut bare = request("OPTIONS", Some("localhost"), Some("tauri://localhost"));
        bare.headers_mut().insert(
            ACCESS_CONTROL_REQUEST_METHOD,
            HeaderValue::from_static("GET"),
        );
        let (_, headers, _) = send(app(false), bare).await;
        assert!(!headers.contains_key(ACCESS_CONTROL_ALLOW_HEADERS));

        // OPTIONS without Access-Control-Request-Method is an ordinary request.
        let (status, headers, body) = send(
            app(false),
            request("OPTIONS", Some("localhost"), Some("tauri://localhost")),
        )
        .await;
        assert_eq!((status, body.as_str()), (StatusCode::OK, "upstream"));
        assert_eq!(headers["x-upstream"], "1");
    }

    #[test]
    fn vary_origin_is_added_once() {
        let mut headers = HeaderMap::new();
        add_vary_origin(&mut headers);
        add_vary_origin(&mut headers);
        assert_eq!(headers.get_all(VARY).iter().count(), 1);
        let mut accept = HeaderMap::new();
        accept.insert(VARY, HeaderValue::from_static("Accept-Encoding"));
        add_vary_origin(&mut accept);
        let values: Vec<_> = accept.get_all(VARY).iter().collect();
        assert_eq!(values, ["Accept-Encoding", "Origin"]);
        for existing in ["accept, ORIGIN", "*"] {
            let mut h = HeaderMap::new();
            h.insert(VARY, HeaderValue::from_static(existing));
            add_vary_origin(&mut h);
            assert_eq!(h.get_all(VARY).iter().count(), 1, "{existing}");
        }
    }
}
