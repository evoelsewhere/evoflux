//! The gateway's front router: Rust-owned paths go to `rust_routes`, every
//! other path is forwarded to the Python sidecar (design §3).
//!
//! HTTP (including SSE) is forwarded by `axum-reverse-proxy` with the body
//! streamed both ways, the client `Host` and `X-Forwarded-*` headers kept as
//! sent, and no compression, timeout or body limit. WebSocket upgrades are
//! spliced at the byte level after the upstream answers `101`, so Python's own
//! handshake answers (a pre-accept close is a `403`) reach the client as-is.

use crate::routing::{Owner, RoutingTable};
use crate::supervisor::PythonSupervisor;
use axum::body::Body;
use axum::extract::{Request, State};
use axum::http::header::{CONNECTION, UPGRADE};
use axum::http::{HeaderName, HeaderValue, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::Router;
use axum_reverse_proxy::{HostBehaviour, ProxyError, ProxyPolicy, ReverseProxy, XForwardedFor};
use evoflux_core::ApiError;
use hyper_util::client::legacy::connect::HttpConnector;
use hyper_util::client::legacy::Client;
use hyper_util::rt::{TokioExecutor, TokioIo};
use std::net::SocketAddr;
use std::sync::{Arc, Mutex};
use std::time::Duration;
use tower::ServiceExt;

/// `app/core/gateway_mode.py` `GATEWAY_HEADER`.
pub const GATEWAY_HEADER: HeaderName = HeaderName::from_static("x-evoflux-gateway");

/// Connecting to the loopback upstream; responses themselves have no deadline.
/// The kernel completes a loopback connect even while Python's event loop is
/// busy, so this only expires when nothing listens. Windows retries a refused
/// loopback connect for about 2 s, which would break the 1 s
/// `backend_unavailable` budget while a crash is being detected (Review Focus 1).
const CONNECT_TIMEOUT: Duration = Duration::from_millis(500);

type HttpProxy = ReverseProxy<HttpConnector>;

struct ProxyState {
    table: Arc<RoutingTable>,
    sup: Arc<PythonSupervisor>,
    rust_routes: Router,
    secret: HeaderValue,
    client: Client<HttpConnector, Body>,
    /// The forwarder for the current Python address; rebuilt after a restart.
    http: Mutex<Option<(SocketAddr, HttpProxy)>>,
}

/// Build the gateway router.
pub fn router(table: Arc<RoutingTable>, sup: Arc<PythonSupervisor>, rust_routes: Router) -> Router {
    // A secret that is not a valid header value can never match Python's
    // check; send an empty value so Python answers 403 instead of us panicking.
    let secret =
        HeaderValue::from_str(sup.gateway_secret()).unwrap_or(HeaderValue::from_static(""));
    let mut connector = HttpConnector::new();
    connector.set_nodelay(true);
    connector.set_connect_timeout(Some(CONNECT_TIMEOUT));
    let client = Client::builder(TokioExecutor::new()).build(connector);
    let state = Arc::new(ProxyState {
        table,
        sup,
        rust_routes,
        secret,
        client,
        http: Mutex::new(None),
    });
    Router::new().fallback(dispatch).with_state(state)
}

async fn dispatch(State(state): State<Arc<ProxyState>>, mut req: Request) -> Response {
    // Only the gateway may assert that a request came through it.
    req.headers_mut().remove(&GATEWAY_HEADER);
    match state.table.owner_for(req.uri().path()) {
        Owner::Rust => match state.rust_routes.clone().oneshot(req).await {
            Ok(response) => response,
            Err(never) => match never {},
        },
        Owner::Python | Owner::Shadow => forward_to_python(&state, req).await,
    }
}

async fn forward_to_python(state: &ProxyState, mut req: Request) -> Response {
    let Some(addr) = state.sup.upstream() else {
        return ApiError::backend_unavailable().into_response();
    };
    req.headers_mut()
        .insert(GATEWAY_HEADER, state.secret.clone());
    if is_websocket_upgrade(&req) {
        return splice_websocket(req, addr).await;
    }
    let Some(proxy) = state.http_proxy(addr) else {
        return ApiError::internal().into_response();
    };
    let response = match proxy.proxy_request(req).await {
        Ok(response) => response,
        Err(never) => match never {},
    };
    // A 502 the forwarder made itself (connect refused, reset before the
    // headers) means Python is gone; a 502 from Python passes through.
    if response.extensions().get::<ProxyError>().is_some() {
        return ApiError::backend_unavailable().into_response();
    }
    response
}

impl ProxyState {
    fn http_proxy(&self, addr: SocketAddr) -> Option<HttpProxy> {
        let mut slot = self.http.lock().ok()?;
        if let Some((current, proxy)) = slot.as_ref() {
            if *current == addr {
                return Some(proxy.clone());
            }
        }
        let policy = ProxyPolicy::new()
            .with_host_behaviour(HostBehaviour::Preserve)
            .with_x_forwarded_for(XForwardedFor::Preserve);
        let proxy =
            ReverseProxy::new_with_client("/", format!("http://{addr}"), self.client.clone())
                .with_policy(policy);
        *slot = Some((addr, proxy.clone()));
        Some(proxy)
    }
}

fn is_websocket_upgrade(req: &Request) -> bool {
    let has_token = |name: HeaderName, token: &str| {
        req.headers().get_all(name).iter().any(|value| {
            value
                .to_str()
                .is_ok_and(|v| v.split(',').any(|t| t.trim().eq_ignore_ascii_case(token)))
        })
    };
    has_token(UPGRADE, "websocket") && has_token(CONNECTION, "upgrade")
}

/// Send the upgrade request to Python as-is; on `101`, splice the two
/// upgraded connections byte for byte, otherwise return Python's answer.
async fn splice_websocket(mut req: Request, addr: SocketAddr) -> Response {
    let client_upgrade = hyper::upgrade::on(&mut req);
    let (parts, _body) = req.into_parts();
    let mut upstream_req = hyper::Request::new(Body::empty());
    *upstream_req.method_mut() = parts.method;
    *upstream_req.uri_mut() = parts
        .uri
        .path_and_query()
        .and_then(|pq| pq.as_str().parse().ok())
        .unwrap_or_default();
    *upstream_req.headers_mut() = parts.headers;

    let stream =
        match tokio::time::timeout(CONNECT_TIMEOUT, tokio::net::TcpStream::connect(addr)).await {
            Ok(Ok(stream)) => stream,
            _ => return ApiError::backend_unavailable().into_response(),
        };
    let _ = stream.set_nodelay(true);
    let Ok((mut sender, conn)) = hyper::client::conn::http1::handshake(TokioIo::new(stream)).await
    else {
        return ApiError::backend_unavailable().into_response();
    };
    tokio::spawn(async move {
        if let Err(error) = conn.with_upgrades().await {
            tracing::debug!(%error, "websocket_upstream_connection_closed");
        }
    });
    let mut upstream_res = match sender.send_request(upstream_req).await {
        Ok(response) => response,
        Err(_) => return ApiError::backend_unavailable().into_response(),
    };
    if upstream_res.status() != StatusCode::SWITCHING_PROTOCOLS {
        return upstream_res.map(Body::new);
    }
    let upstream_upgrade = hyper::upgrade::on(&mut upstream_res);
    tokio::spawn(async move {
        let (client, upstream) = match tokio::try_join!(client_upgrade, upstream_upgrade) {
            Ok(pair) => pair,
            Err(error) => {
                tracing::debug!(%error, "websocket_upgrade_failed");
                return;
            }
        };
        let mut client = TokioIo::new(client);
        let mut upstream = TokioIo::new(upstream);
        if let Err(error) = tokio::io::copy_bidirectional(&mut client, &mut upstream).await {
            tracing::debug!(%error, "websocket_splice_closed");
        }
    });
    let (parts, _) = upstream_res.into_parts();
    Response::from_parts(parts, Body::empty())
}
