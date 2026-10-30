#![allow(clippy::unwrap_used, clippy::expect_used, clippy::panic)]

use axum::body::{to_bytes, Body};
use axum::http::{Request, StatusCode};
use axum::routing::any;
use axum::Router;
use evoflux_core::auth::DesktopAuth;
use tower::ServiceExt;

const TOKEN: &str = "s3cret-token";
const SECRET: &str = "proc-secret";
const UNAUTHORIZED: &str = "{\"detail\":\"Unauthorized \u{2014} EvoFlux access key required.\"}";
const UNTRUSTED: &str = "{\"detail\":\"Untrusted tailnet identity.\"}";

/// Echoes the downstream query string so tests can see what the layer forwarded.
async fn echo(req: Request<Body>) -> String {
    req.uri().query().unwrap_or("<none>").to_owned()
}

fn app(token: Option<&str>) -> Router {
    app_with(DesktopAuth::new(
        token.map(str::to_owned),
        SECRET.to_owned(),
    ))
}

fn app_with(auth: DesktopAuth) -> Router {
    Router::new().fallback(any(echo)).layer(auth.layer())
}

async fn call(app: Router, req: Request<Body>) -> (StatusCode, String) {
    let res = app.oneshot(req).await.unwrap();
    let status = res.status();
    let bytes = to_bytes(res.into_body(), usize::MAX).await.unwrap();
    (status, String::from_utf8(bytes.to_vec()).unwrap())
}

fn get(uri: &str) -> Request<Body> {
    Request::get(uri).body(Body::empty()).unwrap()
}

fn with_auth(uri: &str, header: &str) -> Request<Body> {
    Request::get(uri)
        .header("authorization", header)
        .body(Body::empty())
        .unwrap()
}

#[tokio::test]
async fn auth_required() {
    let (status, body) = call(app(Some(TOKEN)), get("/api/sessions")).await;
    assert_eq!(status, StatusCode::UNAUTHORIZED);
    assert_eq!(body, UNAUTHORIZED);
}

#[tokio::test]
async fn auth_bearer_accepted_and_wrong_rejected() {
    let ok = with_auth("/api/sessions", &format!("Bearer {TOKEN}"));
    assert_eq!(call(app(Some(TOKEN)), ok).await.0, StatusCode::OK);
    // Scheme is case-insensitive; surrounding whitespace of the value is stripped.
    let ok = with_auth("/api/sessions", &format!("bEaReR {TOKEN} "));
    assert_eq!(call(app(Some(TOKEN)), ok).await.0, StatusCode::OK);
    for header in ["Bearer wrong", "Bearer ", "Basic s3cret-token", TOKEN] {
        let bad = with_auth("/api/sessions", header);
        assert_eq!(
            call(app(Some(TOKEN)), bad).await.0,
            StatusCode::UNAUTHORIZED,
            "{header}"
        );
    }
}

#[tokio::test]
async fn auth_token_query_param_is_stripped_downstream() {
    let uri = format!("/api/x?a=1&_token={TOKEN}&b=%20z+y");
    let (status, body) = call(app(Some(TOKEN)), get(&uri)).await;
    assert_eq!(status, StatusCode::OK);
    // Python re-encodes the kept pairs with urlencode (quote_plus).
    assert_eq!(body, "a=1&b=+z+y");
    let (_, body) = call(app(Some(TOKEN)), get(&format!("/api/x?_token={TOKEN}"))).await;
    assert_eq!(body, "<none>");
}

#[tokio::test]
async fn auth_query_reencoding_matches_python_urlencode() {
    // urlencode keeps `_.-~` and alphanumerics, encodes `*`, `/`, and non-ASCII as UTF-8.
    let uri = format!("/api/x?_token={TOKEN}&k=a~b*c/d&caf%C3%A9=%C3%A9&flag&dup=1&dup=2");
    let (_, body) = call(app(Some(TOKEN)), get(&uri)).await;
    assert_eq!(body, "k=a~b%2Ac%2Fd&caf%C3%A9=%C3%A9&flag=&dup=1&dup=2");
}

#[tokio::test]
async fn auth_bearer_wins_over_query_and_non_bearer_falls_back_to_query() {
    let uri = format!("/api/x?_token={TOKEN}");
    let req = with_auth(&uri, "Bearer wrong");
    assert_eq!(
        call(app(Some(TOKEN)), req).await.0,
        StatusCode::UNAUTHORIZED
    );
    let req = with_auth(&uri, "Basic abc");
    assert_eq!(call(app(Some(TOKEN)), req).await.0, StatusCode::OK);
}

#[tokio::test]
async fn auth_repeated_token_param_uses_the_last_value() {
    // Starlette `QueryParams.get` returns the last occurrence.
    let good_last = format!("/api/x?_token=wrong&_token={TOKEN}");
    assert_eq!(
        call(app(Some(TOKEN)), get(&good_last)).await.0,
        StatusCode::OK
    );
    let bad_last = format!("/api/x?_token={TOKEN}&_token=wrong");
    assert_eq!(
        call(app(Some(TOKEN)), get(&bad_last)).await.0,
        StatusCode::UNAUTHORIZED
    );
}

#[tokio::test]
async fn auth_empty_or_wrong_query_token_rejected() {
    for uri in [
        "/api/x?_token=",
        "/api/x?_token=nope",
        "/api/x?token=s3cret-token",
    ] {
        assert_eq!(
            call(app(Some(TOKEN)), get(uri)).await.0,
            StatusCode::UNAUTHORIZED,
            "{uri}"
        );
    }
}

#[tokio::test]
async fn auth_exempt_paths_pass_without_token_and_keep_their_query() {
    for path in [
        "/metrics",
        "/api/health/live",
        "/api/health/ready",
        "/api/health/anything",
        "/",
        "/index.html",
        "/favicon.ico",
        "/assets/app.js",
        "/static/x.css",
        "/some/spa/route",
        "/manifest.json",
    ] {
        assert_eq!(
            call(app(Some(TOKEN)), get(path)).await.0,
            StatusCode::OK,
            "{path}"
        );
    }
    // Exempt paths are not rewritten: the query is forwarded untouched.
    let (_, body) = call(app(Some(TOKEN)), get("/api/health/live?_token=zzz")).await;
    assert_eq!(body, "_token=zzz");
}

#[tokio::test]
async fn auth_exemptions_are_literal_not_prefix() {
    for path in ["/api/healthz", "/api", "/api/", "/api/health"] {
        let status = call(app(Some(TOKEN)), get(path)).await.0;
        assert_eq!(status, StatusCode::UNAUTHORIZED, "{path}");
    }
    // `/metrics-evil` is not an API path, so it passes as an SPA route, like Python.
    assert_eq!(
        call(app(Some(TOKEN)), get("/metrics-evil")).await.0,
        StatusCode::OK
    );
}

#[tokio::test]
async fn auth_path_is_percent_decoded_before_matching() {
    // Starlette matches on the decoded path.
    let status = call(app(Some(TOKEN)), get("/%61pi/sessions")).await.0;
    assert_eq!(status, StatusCode::UNAUTHORIZED);
    let status = call(app(Some(TOKEN)), get("/api/%68ealth/live")).await.0;
    assert_eq!(status, StatusCode::OK);
}

#[tokio::test]
async fn auth_custom_auth_webbridge_paths_skip_the_token_check() {
    for path in [
        "/api/team/webbridge/pairing/native",
        "/api/team/webbridge/relay-ticket",
        "/api/team/webbridge/bindings/abc",
        "/api/team/webbridge/sessions/abc",
    ] {
        assert_eq!(
            call(app(Some(TOKEN)), get(path)).await.0,
            StatusCode::OK,
            "{path}"
        );
    }
    let other = call(app(Some(TOKEN)), get("/api/team/webbridge/other"))
        .await
        .0;
    assert_eq!(other, StatusCode::UNAUTHORIZED);
}

#[tokio::test]
async fn auth_disabled_without_token_is_a_noop() {
    for token in [None, Some("")] {
        let (status, body) = call(app(token), get("/api/anything?_token=x")).await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(body, "_token=x");
    }
}

fn remote(marker: Option<&str>, token: Option<&str>) -> Request<Body> {
    let mut b = Request::get("/api/sessions").header("Tailscale-User-Login", "me@example.com");
    if let Some(m) = marker {
        b = b.header("X-EvoFlux-Remote-Proxy", m);
    }
    if let Some(t) = token {
        b = b.header("X-EvoFlux-Remote-Token", t);
    }
    b.body(Body::empty()).unwrap()
}

#[tokio::test]
async fn auth_remote_marker_without_right_token_is_401_untrusted() {
    for token in [None, Some("wrong"), Some("")] {
        let (status, body) = call(app(Some(TOKEN)), remote(Some("tsnet"), token)).await;
        assert_eq!(status, StatusCode::UNAUTHORIZED);
        assert_eq!(body, UNTRUSTED);
    }
    // Rejected even when token auth is disabled: the remote check runs first.
    let (status, body) = call(app(None), remote(Some("tsnet"), Some("wrong"))).await;
    assert_eq!(
        (status, body.as_str()),
        (StatusCode::UNAUTHORIZED, UNTRUSTED)
    );
}

#[tokio::test]
async fn auth_remote_with_process_secret_skips_the_bearer_check() {
    let (status, _) = call(app(Some(TOKEN)), remote(Some(" tsnet "), Some(SECRET))).await;
    assert_eq!(status, StatusCode::OK);
}

#[tokio::test]
async fn auth_remote_login_must_be_non_empty_after_strip() {
    let req = Request::get("/api/sessions")
        .header("Tailscale-User-Login", "   ")
        .body(Body::empty())
        .unwrap();
    assert_eq!(
        call(app(Some(TOKEN)), req).await.0,
        StatusCode::UNAUTHORIZED
    );
}

#[tokio::test]
async fn auth_remote_unknown_marker_trust_follows_embedded_proxy_requirement() {
    let lax = DesktopAuth::new(Some(TOKEN.to_owned()), SECRET.to_owned())
        .with_embedded_proxy_required(false);
    assert_eq!(
        call(app_with(lax), remote(Some("other"), None)).await.0,
        StatusCode::OK
    );
    let strict = DesktopAuth::new(Some(TOKEN.to_owned()), SECRET.to_owned())
        .with_embedded_proxy_required(true);
    let (status, body) = call(app_with(strict), remote(Some("other"), None)).await;
    assert_eq!(status, StatusCode::UNAUTHORIZED);
    assert_eq!(body, UNTRUSTED);
}
