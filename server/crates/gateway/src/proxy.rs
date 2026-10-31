//! The gateway's front router: Rust-owned paths go to `rust_routes`, every
//! other path is forwarded to the Python sidecar (design §3).
//!
//! HTTP (including SSE) is forwarded by `axum-reverse-proxy` with the body
//! streamed both ways, the client `Host` and `X-Forwarded-*` headers kept as
//! sent, and no compression, timeout or body limit. WebSocket upgrades are
//! spliced at the byte level after the upstream answers `101`, so Python's own
//! handshake answers (a pre-accept close is a `403`) reach the client as-is.

use crate::record::{Recorder, RequestBodyCapture};
use crate::routing::{Owner, RoutingTable};
use crate::shadow::{capture, tap_response, Shadow, Snapshot, BODY_LIMIT};
use crate::supervisor::PythonSupervisor;
use axum::body::{Body, HttpBody};
use axum::extract::{Request, State};
use axum::http::header::{CONNECTION, UPGRADE};
use axum::http::{HeaderName, HeaderValue, Method, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::Router;
use axum_reverse_proxy::{HostBehaviour, ProxyError, ProxyPolicy, ReverseProxy, XForwardedFor};
use evoflux_core::ApiError;
use futures_util::StreamExt;
use http_body_util::{BodyStream, StreamBody};
use hyper_util::client::legacy::connect::HttpConnector;
use hyper_util::client::legacy::Client;
use hyper_util::rt::{TokioExecutor, TokioIo};
use std::net::SocketAddr;
use std::sync::atomic::{AtomicBool, Ordering};
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
    options: GatewayOptions,
}

/// Optional gateway features: shadow comparison and traffic recording.
#[derive(Clone, Default)]
pub struct GatewayOptions {
    /// Without it a `shadow` unit is answered by Python alone.
    pub shadow: Option<Arc<Shadow>>,
    pub recorder: Option<Arc<Recorder>>,
}

impl GatewayOptions {
    /// Shadow diffs go under `state_dir`; `EVOFLUX_SHADOW_PYTHON_TWICE` and
    /// `EVOFLUX_GATEWAY_RECORD_DIR` are read from the environment.
    pub fn from_env(state_dir: std::path::PathBuf) -> Self {
        Self {
            shadow: Some(Arc::new(Shadow::new(
                crate::shadow::ShadowOptions::from_env(state_dir),
            ))),
            recorder: Recorder::from_env().map(Arc::new),
        }
    }
}

/// Build the gateway router.
pub fn router(table: Arc<RoutingTable>, sup: Arc<PythonSupervisor>, rust_routes: Router) -> Router {
    router_with(table, sup, rust_routes, GatewayOptions::default())
}

/// Build the gateway router with shadow comparison and/or traffic recording.
pub fn router_with(
    table: Arc<RoutingTable>,
    sup: Arc<PythonSupervisor>,
    rust_routes: Router,
    options: GatewayOptions,
) -> Router {
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
        options,
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
        Owner::Python => forward_recorded(&state, req, None).await,
        Owner::Shadow => forward_shadow(&state, req).await,
    }
}

/// Which shadow comparison a request belongs to.
struct ShadowJob {
    shadow: Arc<Shadow>,
    unit: String,
    rust: crate::shadow::RustRun,
    noise: Option<crate::shadow::NoiseRun>,
}

/// Python answers the client; Rust (and, for the noise run, Python again) runs
/// the same GET in the background. Anything but a plain GET is Python only.
async fn forward_shadow(state: &Arc<ProxyState>, req: Request) -> Response {
    let unit = state
        .table
        .unit_for(req.uri().path())
        .map(|u| u.name.clone());
    let shadow = state.options.shadow.clone();
    let (Some(unit), Some(shadow)) = (unit, shadow) else {
        return forward_recorded(state, req, None).await;
    };
    if req.method() != Method::GET || is_websocket_upgrade(&req) {
        return forward_recorded(state, req, None).await;
    }
    let snapshot = Snapshot::of(&req);
    let rust = shadow.spawn_rust(state.rust_routes.clone(), &snapshot);
    let noise = shadow.python_twice().then(|| {
        let state = Arc::clone(state);
        let again = snapshot.to_request();
        tokio::spawn(async move {
            let response = forward_to_python(&state, again).await;
            capture(response, BODY_LIMIT, std::time::Duration::from_secs(15)).await
        })
    });
    let job = ShadowJob {
        shadow,
        unit,
        rust,
        noise,
    };
    forward_recorded(state, req, Some(job)).await
}

/// Forward to Python; when recording or shadowing, keep a copy of the answer
/// for after the client has received it.
async fn forward_recorded(
    state: &Arc<ProxyState>,
    mut req: Request,
    job: Option<ShadowJob>,
) -> Response {
    let recorder = state.options.recorder.clone();
    if recorder.is_none() && job.is_none() {
        return forward_to_python(state, req).await;
    }
    let snapshot = Snapshot::of(&req);
    let sequence = match recorder.as_ref() {
        Some(recorder) => Some(recorder.next_sequence().await),
        None => None,
    };
    let capture = Arc::new(Mutex::new(RequestBodyCapture::default()));
    let complete = Arc::new(AtomicBool::new(false));
    if recorder.is_some() {
        let (parts, body) = req.into_parts();
        let expected = parts
            .headers
            .get("content-length")
            .and_then(|v| v.to_str().ok())
            .and_then(|v| v.parse::<usize>().ok());
        if expected == Some(0) || body.is_end_stream() {
            complete.store(true, Ordering::Release);
        }
        let captured = Arc::clone(&capture);
        let finished = Arc::clone(&complete);
        let stream =
            futures_util::stream::unfold(Box::pin(BodyStream::new(body)), move |mut inner| {
                let captured = Arc::clone(&captured);
                let finished = Arc::clone(&finished);
                async move {
                    match inner.next().await {
                        Some(frame) => {
                            if let Ok(frame) = &frame {
                                if let Some(data) = frame.data_ref() {
                                    if let Ok(mut capture) = captured.lock() {
                                        capture.push(data);
                                        if expected == Some(capture.length()) {
                                            finished.store(true, Ordering::Release);
                                        }
                                    }
                                }
                            }
                            Some((frame, inner))
                        }
                        None => {
                            finished.store(true, Ordering::Release);
                            None
                        }
                    }
                }
            });
        req = Request::from_parts(parts, Body::new(StreamBody::new(stream)));
    }
    let response = forward_to_python(state, req).await;
    if response.status() == StatusCode::SWITCHING_PROTOCOLS {
        return response;
    }
    // The comparison needs a runtime to spawn into; there is always one while serving.
    tap_response(
        response,
        BODY_LIMIT,
        Box::new(move |python| {
            let Ok(handle) = tokio::runtime::Handle::try_current() else {
                return;
            };
            handle.spawn(async move {
                if let (Some(recorder), Some(sequence)) = (&recorder, sequence) {
                    let body = if complete.load(Ordering::Acquire) {
                        let value = capture
                            .lock()
                            .ok()
                            .map(|mut value| std::mem::take(&mut *value));
                        match value {
                            Some(value) => evoflux_core::blocking::run(move || value.finish())
                                .await
                                .unwrap_or_else(
                                    |_| serde_json::json!({"error": "redaction_failed"}),
                                ),
                            None => serde_json::json!({"error": "capture_failed"}),
                        }
                    } else {
                        serde_json::json!({"incomplete": true})
                    };
                    recorder.record(&snapshot, &python, sequence, body).await;
                }
                if let Some(job) = job {
                    job.shadow
                        .finish(&job.unit, &snapshot, python, job.rust, job.noise)
                        .await;
                }
            });
        }),
    )
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
