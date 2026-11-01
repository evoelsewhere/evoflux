//! Port of app/api/routes/observability.py.

use std::path::PathBuf;
use std::sync::Arc;

use axum::extract::{Path, RawQuery, State};
use axum::http::{header, HeaderMap, HeaderValue, StatusCode, Uri};
use axum::response::{IntoResponse, Response};
use axum::routing::{any, on, MethodFilter, MethodRouter};
use axum::Router;
use evoflux_core::{blocking, ApiError};
use serde_json::{json, Value};

use crate::clock::{self, MICROS_PER_DAY};
use crate::params::{validate, IntParam};
use crate::retention::OtelConfig;
use crate::scan::{self, Limits};
use crate::{summary, traces};

pub(crate) struct ObservabilityState {
    pub(crate) spans_dir: PathBuf,
    pub(crate) config: OtelConfig,
    pub(crate) limits: Limits,
}

type Shared = Arc<ObservabilityState>;

const DAYS: IntParam = IntParam {
    name: "days",
    default: 7,
    min: 1,
    max: Some(90),
};
const DETAIL_DAYS: IntParam = IntParam {
    name: "days",
    default: 30,
    min: 1,
    max: Some(90),
};
const LIMIT: IntParam = IntParam {
    name: "limit",
    default: 50,
    min: 1,
    max: Some(200),
};
const OFFSET: IntParam = IntParam {
    name: "offset",
    default: 0,
    min: 0,
    max: None,
};

pub(crate) fn router(state: Shared) -> Router {
    Router::new()
        .route(
            "/api/observability/summary",
            get_only(on(MethodFilter::GET, summary_route)),
        )
        .route("/api/observability/summary/", any(redirect_summary))
        .route(
            "/api/observability/traces",
            get_only(on(MethodFilter::GET, traces_route)),
        )
        .route("/api/observability/traces/", any(redirect_traces))
        .route(
            "/api/observability/traces/{trace_id}",
            get_only(on(MethodFilter::GET, trace_detail_route)),
        )
        .with_state(state)
}

/// GET only; FastAPI answers every other method (HEAD included) with a 405.
fn get_only(get: MethodRouter<Shared>) -> MethodRouter<Shared> {
    get.head(method_not_allowed).fallback(method_not_allowed)
}

async fn method_not_allowed() -> Response {
    let mut response =
        ApiError::new(StatusCode::METHOD_NOT_ALLOWED, "Method Not Allowed").into_response();
    response
        .headers_mut()
        .insert(header::ALLOW, HeaderValue::from_static("GET"));
    response
}

async fn redirect_summary(headers: HeaderMap, uri: Uri) -> Response {
    redirect_to_slashless("/api/observability/summary", &headers, &uri)
}

async fn redirect_traces(headers: HeaderMap, uri: Uri) -> Response {
    redirect_to_slashless("/api/observability/traces", &headers, &uri)
}

/// FastAPI `redirect_slashes`: 307 to the same URL without the slash, keeping the query.
fn redirect_to_slashless(path: &str, headers: &HeaderMap, uri: &Uri) -> Response {
    let mut location = path.to_owned();
    if let Some(query) = uri.query() {
        location.push('?');
        location.push_str(query);
    }
    if let Some(host) = headers.get(header::HOST).and_then(|h| h.to_str().ok()) {
        location = format!("http://{host}{location}");
    }
    let mut response = StatusCode::TEMPORARY_REDIRECT.into_response();
    if let Ok(value) = HeaderValue::from_str(&location) {
        response.headers_mut().insert(header::LOCATION, value);
    }
    response
}

fn json_response(body: &Value) -> Result<Response, ApiError> {
    let bytes = serde_json::to_vec(body).map_err(|_| ApiError::internal())?;
    Ok(([(header::CONTENT_TYPE, "application/json")], bytes).into_response())
}

/// The window `[now - days, now]` in microseconds.
fn window(days: i64) -> (i64, i64) {
    let now = clock::now_micros();
    (now - days * MICROS_PER_DAY, now)
}

async fn summary_route(
    State(state): State<Shared>,
    RawQuery(query): RawQuery,
) -> Result<Response, ApiError> {
    let days = *validate(query.as_deref(), &[DAYS])?
        .first()
        .ok_or_else(ApiError::internal)?;
    let (start, end) = window(days);
    let body = blocking::run(move || {
        let files = scan::candidate_files(&state.spans_dir, start, &state.limits);
        if files.is_empty() {
            return summary::empty_summary(start, end, state.config.sample_ratio);
        }
        let spans = scan::read_spans(&files, start * 1_000, end * 1_000, &state.limits);
        summary::summary_body(start, end, state.config.sample_ratio, &spans)
    })
    .await?;
    json_response(&body)
}

async fn traces_route(
    State(state): State<Shared>,
    RawQuery(query): RawQuery,
) -> Result<Response, ApiError> {
    let values = validate(query.as_deref(), &[DAYS, LIMIT, OFFSET])?;
    let (Some(&days), Some(&limit), Some(&offset)) = (values.first(), values.get(1), values.get(2))
    else {
        return Err(ApiError::internal());
    };
    let (start, end) = window(days);
    let (items, total) = blocking::run(move || {
        let files = scan::candidate_files(&state.spans_dir, start, &state.limits);
        if files.is_empty() {
            return (Vec::new(), 0);
        }
        let spans = scan::read_spans(&files, start * 1_000, end * 1_000, &state.limits);
        traces::list_page(
            &spans,
            usize::try_from(limit).unwrap_or(50),
            usize::try_from(offset).unwrap_or(usize::MAX),
        )
    })
    .await?;
    let has_next = u128::try_from(offset + limit).is_ok_and(|reach| reach < total as u128);
    json_response(&json!({
        "traces": items,
        "limit": limit,
        "offset": offset,
        "total": total,
        "has_next": has_next,
    }))
}

async fn trace_detail_route(
    State(state): State<Shared>,
    Path(trace_id): Path<String>,
    RawQuery(query): RawQuery,
) -> Result<Response, ApiError> {
    // Starlette matches the decoded path, so an encoded slash is not a trace id.
    // Query validation still comes first for ids that are routes.
    let days = *validate(query.as_deref(), &[DETAIL_DAYS])?
        .first()
        .ok_or_else(ApiError::internal)?;
    if trace_id.contains('/') {
        return Err(ApiError::new(StatusCode::NOT_FOUND, "Not Found"));
    }
    let (start, end) = window(days);
    let wanted = trace_id.clone();
    let detail = blocking::run(move || {
        let files = scan::candidate_files(&state.spans_dir, start, &state.limits);
        if files.is_empty() {
            return None;
        }
        traces::get_trace(&files, start * 1_000, end * 1_000, &state.limits, &wanted)
    })
    .await?;
    match detail {
        Some(body) => json_response(&body),
        None => Err(ApiError::new(
            StatusCode::NOT_FOUND,
            json!({"reason": "trace_not_found", "trace_id": trace_id}),
        )),
    }
}

#[cfg(test)]
#[allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::indexing_slicing,
    clippy::disallowed_methods
)]
mod tests {
    use super::*;
    use crate::{router_with_limits, OtelConfig};
    use axum::body::{to_bytes, Body};
    use axum::http::{Method, Request};
    use tower::ServiceExt;

    struct Fixture {
        dir: tempfile::TempDir,
        router: Router,
    }

    fn span(name: &str, trace: &str, ago_secs: i64, extra: &str) -> String {
        let end = (clock::now_micros() - ago_secs * 1_000_000) * 1_000;
        format!(
            "{{\"name\":\"{name}\",\"trace_id\":\"{trace}\",\"span_id\":\"0x{ago_secs}\",\"parent_id\":null,\"kind\":\"INTERNAL\",\"start_time\":{},\"end_time\":{end},\"duration_ms\":1000,\"status\":\"OK\",\"attributes\":{{{extra}}}}}\n",
            end - 1_000_000_000
        )
    }

    fn fixture(lines: &[String]) -> Fixture {
        fixture_with(lines, Limits::default())
    }

    fn fixture_with(lines: &[String], limits: Limits) -> Fixture {
        let dir = tempfile::tempdir().unwrap();
        let spans = dir.path().join("otel").join("spans");
        std::fs::create_dir_all(&spans).unwrap();
        let name = format!("{}.jsonl", clock::partition_key(clock::now_micros()));
        std::fs::write(spans.join(name), lines.concat()).unwrap();
        let router = router_with_limits(dir.path(), OtelConfig::default(), limits);
        Fixture { dir, router }
    }

    async fn call(router: &Router, method: Method, uri: &str) -> (StatusCode, HeaderMap, Value) {
        let request = Request::builder()
            .method(method)
            .uri(uri)
            .header(header::HOST, "127.0.0.1:1")
            .body(Body::empty())
            .unwrap();
        let response = router.clone().oneshot(request).await.unwrap();
        let (parts, body) = response.into_parts();
        let bytes = to_bytes(body, usize::MAX).await.unwrap();
        let value = serde_json::from_slice(&bytes).unwrap_or(Value::Null);
        (parts.status, parts.headers, value)
    }

    async fn get(router: &Router, uri: &str) -> (StatusCode, Value) {
        let (status, _, body) = call(router, Method::GET, uri).await;
        (status, body)
    }

    fn usage() -> &'static str {
        "\"run_id\":\"r1\",\"gen_ai.usage.input_tokens\":10,\"gen_ai.usage.output_tokens\":2"
    }

    #[tokio::test]
    async fn summary_aggregates_the_seeded_spans() {
        let fx = fixture(&[
            span("agent_run A", "0xaa", 30, "\"run_id\":\"r1\""),
            span("chat m", "0xaa", 20, usage()),
        ]);
        let (status, body) = get(&fx.router, "/api/observability/summary?days=1").await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(body["totals"]["turns"], 1);
        assert_eq!(body["totals"]["llm_calls"], 1);
        assert_eq!(body["totals"]["input_tokens"], 10);
        assert_eq!(body["bucket_size"], "hour");
        assert_eq!(body["sample_ratio"], 1.0);
        assert!(body["window_start"].as_str().unwrap().ends_with("+00:00"));
        let (_, week) = get(&fx.router, "/api/observability/summary").await;
        assert_eq!(week["bucket_size"], "day");
        assert_eq!(week["time_series"].as_array().unwrap().len(), 8);
    }

    #[tokio::test]
    async fn without_a_spans_dir_every_route_is_empty() {
        let dir = tempfile::tempdir().unwrap();
        let config = OtelConfig {
            sample_ratio: 0.5,
            ..OtelConfig::default()
        };
        let router = router_with_limits(dir.path(), config, Limits::default());
        let (status, body) = get(&router, "/api/observability/summary?days=7").await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(body["sample_ratio"], 0.5);
        assert_eq!(body["time_series"], json!([]));
        assert_eq!(body["totals"]["turns"], 0);
        let (status, body) = get(&router, "/api/observability/traces").await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(
            body,
            json!({"traces": [], "limit": 50, "offset": 0, "total": 0, "has_next": false})
        );
        let (status, _) = get(&router, "/api/observability/traces/0xaa").await;
        assert_eq!(status, StatusCode::NOT_FOUND);
    }

    #[tokio::test]
    async fn traces_paginate_and_report_has_next() {
        let lines: Vec<String> = (1..=3)
            .map(|n| {
                span(
                    "agent_run A",
                    &format!("0x{n}"),
                    n * 10,
                    &format!("\"run_id\":\"r{n}\""),
                )
            })
            .collect();
        let fx = fixture(&lines);
        let (_, body) = get(&fx.router, "/api/observability/traces?limit=2").await;
        assert_eq!(body["total"], 3);
        assert_eq!(body["has_next"], true);
        assert_eq!(body["traces"][0]["trace_id"], "0x1");
        assert_eq!(body["traces"].as_array().unwrap().len(), 2);
        let (_, body) = get(&fx.router, "/api/observability/traces?limit=2&offset=1").await;
        assert_eq!(body["has_next"], false);
        assert_eq!(body["offset"], 1);
        assert_eq!(body["traces"][0]["trace_id"], "0x2");
        let (_, body) = get(&fx.router, "/api/observability/traces?limit=1&offset=2").await;
        assert_eq!(body["has_next"], false);
        let (_, body) = get(&fx.router, "/api/observability/traces?limit=3").await;
        assert_eq!(body["has_next"], false);
        let (_, body) = get(&fx.router, "/api/observability/traces?offset=99").await;
        assert_eq!(body["total"], 3);
        assert_eq!(body["traces"], json!([]));
    }

    #[tokio::test]
    async fn trace_detail_finds_ids_with_or_without_the_prefix() {
        let fx = fixture(&[span("agent_run A", "0xab", 10, "\"run_id\":\"r1\"")]);
        for id in ["0xab", "ab", "AB", "0XAB"] {
            let (status, body) = get(&fx.router, &format!("/api/observability/traces/{id}")).await;
            assert_eq!(status, StatusCode::OK, "{id}");
            assert_eq!(body["trace_id"], "0xab");
            assert_eq!(body["spans"][0]["attributes"]["run_id"], "r1");
        }
        let (status, body) = get(&fx.router, "/api/observability/traces/nope?days=90").await;
        assert_eq!(status, StatusCode::NOT_FOUND);
        assert_eq!(
            body,
            json!({"detail": {"reason": "trace_not_found", "trace_id": "nope"}})
        );
    }

    /// An old span in the same partition file: only the window start can keep it out.
    fn with_an_old_span() -> Fixture {
        let old = span("agent_run Old", "0xold", 2 * 86_400, "\"run_id\":\"ro\"");
        let fresh = span("agent_run New", "0xnew", 10, "\"run_id\":\"rn\"");
        fixture(&[old, fresh])
    }

    #[tokio::test]
    async fn the_window_start_excludes_older_spans_of_the_same_file() {
        let fx = with_an_old_span();
        let (_, body) = get(&fx.router, "/api/observability/summary?days=1").await;
        assert_eq!(body["totals"]["turns"], 1);
        let (_, body) = get(&fx.router, "/api/observability/summary?days=3").await;
        assert_eq!(body["totals"]["turns"], 2);
        let (_, body) = get(&fx.router, "/api/observability/traces?days=1").await;
        assert_eq!(body["total"], 1);
        let (_, body) = get(&fx.router, "/api/observability/traces?days=3").await;
        assert_eq!(body["total"], 2);
        let (status, _) = get(&fx.router, "/api/observability/traces/0xold?days=1").await;
        assert_eq!(status, StatusCode::NOT_FOUND);
        let (status, _) = get(&fx.router, "/api/observability/traces/0xold?days=3").await;
        assert_eq!(status, StatusCode::OK);
    }

    #[tokio::test]
    async fn trace_detail_default_window_is_thirty_days() {
        let fx = fixture(&[]);
        let spans = fx.dir.path().join("otel").join("spans");
        let old = clock::now_micros() - 35 * MICROS_PER_DAY;
        let name = format!("{}.jsonl", clock::partition_key(old));
        let end = old * 1_000;
        std::fs::write(
            spans.join(name),
            format!(
                "{{\"name\":\"x\",\"trace_id\":\"0xold\",\"span_id\":\"0x1\",\"start_time\":{},\"end_time\":{end},\"duration_ms\":1}}\n",
                end - 1
            ),
        )
        .unwrap();
        let (status, _) = get(&fx.router, "/api/observability/traces/0xold").await;
        assert_eq!(status, StatusCode::NOT_FOUND);
        let (status, _) = get(&fx.router, "/api/observability/traces/0xold?days=40").await;
        assert_eq!(status, StatusCode::OK);
    }

    #[tokio::test]
    async fn validation_runs_before_the_lookup_and_reports_python_bodies() {
        let fx = fixture(&[]);
        let (status, body) = get(&fx.router, "/api/observability/traces/anything?days=0").await;
        assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
        assert_eq!(body["detail"][0]["type"], "greater_than_equal");
        let (status, body) = get(&fx.router, "/api/observability/summary?days=91").await;
        assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
        assert_eq!(body["detail"][0]["ctx"], json!({"le": 90}));
        let (status, body) = get(&fx.router, "/api/observability/traces?limit=201&offset=-1").await;
        assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
        assert_eq!(body["detail"].as_array().unwrap().len(), 2);
        for ok in ["days=1", "days=90"] {
            let (status, _) = get(&fx.router, &format!("/api/observability/summary?{ok}")).await;
            assert_eq!(status, StatusCode::OK);
        }
        let (status, _) = get(&fx.router, "/api/observability/traces?limit=200").await;
        assert_eq!(status, StatusCode::OK);
        let (status, _) = get(&fx.router, "/api/observability/traces?limit=1").await;
        assert_eq!(status, StatusCode::OK);
    }

    #[tokio::test]
    async fn an_encoded_slash_in_the_id_is_not_a_route() {
        let fx = fixture(&[]);
        let (status, body) = get(&fx.router, "/api/observability/traces/a%2Fb").await;
        assert_eq!(status, StatusCode::NOT_FOUND);
        assert_eq!(body, json!({"detail": "Not Found"}));
    }

    #[tokio::test]
    async fn only_get_is_allowed() {
        let fx = fixture(&[]);
        for uri in [
            "/api/observability/summary",
            "/api/observability/traces",
            "/api/observability/traces/0xaa",
        ] {
            for method in [Method::POST, Method::PUT, Method::DELETE, Method::HEAD] {
                let (status, headers, body) = call(&fx.router, method.clone(), uri).await;
                assert_eq!(status, StatusCode::METHOD_NOT_ALLOWED, "{method} {uri}");
                assert_eq!(headers[header::ALLOW], "GET");
                if method != Method::HEAD {
                    assert_eq!(body, json!({"detail": "Method Not Allowed"}));
                }
            }
        }
    }

    #[tokio::test]
    async fn trailing_slashes_redirect_with_307_keeping_the_query() {
        let fx = fixture(&[]);
        for (uri, target) in [
            (
                "/api/observability/summary/?days=3",
                "http://127.0.0.1:1/api/observability/summary?days=3",
            ),
            (
                "/api/observability/traces/",
                "http://127.0.0.1:1/api/observability/traces",
            ),
        ] {
            let (status, headers, _) = call(&fx.router, Method::GET, uri).await;
            assert_eq!(status, StatusCode::TEMPORARY_REDIRECT, "{uri}");
            assert_eq!(headers[header::LOCATION], target);
        }
    }

    #[tokio::test]
    async fn responses_are_compact_json() {
        let fx = fixture(&[]);
        let request = Request::builder()
            .uri("/api/observability/traces")
            .body(Body::empty())
            .unwrap();
        let response = fx.router.clone().oneshot(request).await.unwrap();
        assert_eq!(response.headers()[header::CONTENT_TYPE], "application/json");
        let bytes = to_bytes(response.into_body(), usize::MAX).await.unwrap();
        assert_eq!(
            &bytes[..],
            br#"{"traces":[],"limit":50,"offset":0,"total":0,"has_next":false}"#
        );
    }

    #[tokio::test]
    async fn reads_are_bounded_by_the_span_cap() {
        let lines: Vec<String> = (1..=5)
            .map(|n| span("agent_run A", &format!("0x{n}"), n, "\"run_id\":\"r\""))
            .collect();
        let limits = Limits {
            max_spans: 2,
            ..Limits::default()
        };
        let fx = fixture_with(&lines, limits);
        let (_, body) = get(&fx.router, "/api/observability/traces").await;
        assert_eq!(body["total"], 2);
    }
}
