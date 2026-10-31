//! Provider parity against the Python recordings.
//!
//! Every `tests/parity/<case>.json` (written by
//! `contract-tests/providers/record_parity.py`) holds a case, the mock
//! recording it replays, and what the Python provider did with it against
//! `contract-tests/mock_provider`. This test serves the same recording from an
//! in-process server that speaks the mock's wire format, runs the Rust
//! provider, and requires the same request bodies and the same event list.

#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::indexing_slicing,
    clippy::disallowed_methods,
    clippy::panic
)]

mod common;

use std::collections::HashMap;
use std::convert::Infallible;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use axum::body::Body;
use axum::extract::State;
use axum::http::{HeaderName, HeaderValue, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::routing::post;
use axum::{Json, Router};
use serde_json::{json, Value};

fn parity_dir() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/parity")
}

/// The recorded responses, as `MockProvider.load` split them.
fn responses(record: &Value) -> Vec<Vec<Value>> {
    serde_json::from_value(record["responses"].clone()).unwrap()
}

#[derive(Default)]
struct Mock {
    responses: Vec<Vec<Value>>,
    served: usize,
    requests: Vec<Value>,
}

/// The mock's `do_POST` for streamed requests.
async fn chat(State(mock): State<Arc<Mutex<Mock>>>, Json(payload): Json<Value>) -> Response {
    let entries = {
        let mut mock = mock.lock().unwrap();
        mock.requests.push(payload);
        let index = mock.served.min(mock.responses.len() - 1);
        mock.served += 1;
        mock.responses[index].clone()
    };
    if let Some(status) = entries[0].get("status") {
        let status = StatusCode::from_u16(status.as_u64().unwrap() as u16).unwrap();
        let mut response = (
            status,
            Json(entries[0].get("body").cloned().unwrap_or(json!({}))),
        )
            .into_response();
        if let Some(headers) = entries[0].get("headers").and_then(Value::as_object) {
            for (name, value) in headers {
                response.headers_mut().insert(
                    HeaderName::from_bytes(name.as_bytes()).unwrap(),
                    HeaderValue::from_str(value.as_str().unwrap()).unwrap(),
                );
            }
        }
        return response;
    }
    // Frames between two delays go out as one body chunk: the client must
    // cope with several events per read, as TCP delivers the mock's frames.
    let frames =
        futures_util::stream::unfold(entries.into_iter().peekable(), |mut rest| async move {
            let first = rest.next()?;
            if let Some(ms) = first.get("delay_ms").and_then(Value::as_u64) {
                tokio::time::sleep(Duration::from_millis(ms)).await;
                return Some((Ok::<_, Infallible>(String::new()), rest));
            }
            let mut chunk = String::new();
            let mut entry = Some(first);
            while let Some(current) = entry.take() {
                let data = match &current["data"] {
                    Value::String(raw) => raw.clone(),
                    other => serde_json::to_string(other).unwrap(),
                };
                if let Some(event) = current.get("event").and_then(Value::as_str) {
                    chunk.push_str(&format!("event: {event}\n"));
                }
                chunk.push_str(&format!("data: {data}\n\n"));
                entry = rest.next_if(|next| next.get("delay_ms").is_none());
            }
            Some((Ok(chunk), rest))
        });
    (
        [("content-type", "text/event-stream")],
        Body::from_stream(frames),
    )
        .into_response()
}

async fn serve(responses: Vec<Vec<Value>>) -> (String, Arc<Mutex<Mock>>) {
    let mock = Arc::new(Mutex::new(Mock {
        responses,
        ..Mock::default()
    }));
    let app = Router::new()
        .route("/v1/chat/completions", post(chat))
        .with_state(mock.clone());
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    tokio::spawn(async move { axum::serve(listener, app).await.unwrap() });
    (format!("http://{addr}/v1"), mock)
}

async fn closed_port_url() -> String {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    drop(listener);
    format!("http://{addr}/v1")
}

async fn check(path: &Path) -> Result<(), String> {
    let record: Value = serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap();
    let case = &record["case"];
    let expected = &record["expected"];
    let (base_url, mock) = if case["refuse"].as_bool().unwrap() {
        (closed_port_url().await, None)
    } else {
        let (url, mock) = serve(responses(&record)).await;
        (url, Some(mock))
    };
    let settings = common::settings_for(case, &base_url, HashMap::new());
    let events = common::run_case(case, &settings).await;
    let requests = mock
        .map(|m| m.lock().unwrap().requests.clone())
        .unwrap_or_default();
    let actual_events = common::numbers_as_f64(&Value::Array(events));
    let expected_events = common::numbers_as_f64(&expected["events"]);
    if actual_events != expected_events {
        return Err(format!(
            "events differ\n  rust:   {actual_events}\n  python: {expected_events}"
        ));
    }
    let actual_requests = common::numbers_as_f64(&Value::Array(requests));
    let expected_requests = common::numbers_as_f64(&expected["requests"]);
    if actual_requests != expected_requests {
        return Err(format!(
            "requests differ\n  rust:   {actual_requests}\n  python: {expected_requests}"
        ));
    }
    Ok(())
}

#[tokio::test(flavor = "multi_thread")]
async fn rust_provider_matches_every_python_recording() {
    let dir = parity_dir();
    let mut paths: Vec<PathBuf> = std::fs::read_dir(&dir)
        .unwrap()
        .map(|entry| entry.unwrap().path())
        .filter(|p| p.extension().is_some_and(|e| e == "json"))
        .collect();
    paths.sort();
    assert!(paths.len() >= 30, "parity recordings missing in {dir:?}");
    let checks = paths.iter().map(|path| async move {
        let name = path.file_stem().unwrap().to_string_lossy().into_owned();
        (name, check(path).await)
    });
    let failures: Vec<String> = futures_util::future::join_all(checks)
        .await
        .into_iter()
        .filter_map(|(name, result)| result.err().map(|e| format!("{name}: {e}")))
        .collect();
    assert!(failures.is_empty(), "{}", failures.join("\n\n"));
}
