//! Tests of the HTTP side: headers, the wire model, options, error statuses
//! and the mapping of transport failures to `httpx` exception names.

use super::*;
use crate::factory::{ProviderConfig, PROVIDERS};
use axum::http::HeaderMap as AxumHeaders;
use axum::routing::post;
use axum::Router;
use std::sync::{Arc, Mutex};
use tokio::io::{AsyncReadExt, AsyncWriteExt};

fn config(id: &str) -> ProviderConfig {
    PROVIDERS.iter().find(|p| p.id == id).copied().unwrap()
}

fn provider(id: &str, base_url: String, client: evoflux_net::Client) -> CompatibleProvider {
    CompatibleProvider::new(
        client,
        Resolved {
            config: config(id),
            model: "resolved-model".to_owned(),
            api_key: "secret-key".to_owned(),
            base_url,
        },
    )
}

fn request(model: &str, options: Value) -> ChatRequest {
    ChatRequest {
        model: model.to_owned(),
        messages: vec![],
        tools: vec![],
        options,
    }
}

type Seen = Arc<Mutex<Vec<(AxumHeaders, Value)>>>;

async fn recording_server() -> (String, Seen) {
    let seen: Seen = Arc::default();
    let record = seen.clone();
    let app = Router::new().route(
        "/v1/chat/completions",
        post(move |headers: AxumHeaders, body: axum::Json<Value>| {
            let record = record.clone();
            async move {
                record.lock().unwrap().push((headers, body.0));
                "data: [DONE]\n\n"
            }
        }),
    );
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    tokio::spawn(async move { axum::serve(listener, app).await.unwrap() });
    (format!("http://{addr}/v1"), seen)
}

async fn drain(
    p: &CompatibleProvider,
    req: ChatRequest,
) -> Vec<Result<ProviderEvent, ProviderError>> {
    p.stream(req).await.unwrap().collect().await
}

fn done() -> ProviderEvent {
    ProviderEvent::Done {
        finish_reason: String::new(),
    }
}

#[tokio::test]
async fn sends_bearer_auth_json_and_attribution_headers() {
    let (url, seen) = recording_server().await;
    let p = provider("vercel", url, evoflux_net::build_client().unwrap());
    let events = drain(&p, request("", Value::Null)).await;
    assert_eq!(events, vec![Ok(done())]);
    let (headers, body) = seen.lock().unwrap().pop().unwrap();
    assert_eq!(headers["authorization"], "Bearer secret-key");
    assert_eq!(headers["content-type"], "application/json");
    assert_eq!(
        headers["http-referer"],
        "https://github.com/khuonghung/evoflux"
    );
    assert_eq!(headers["x-title"], "EvoFlux");
    assert_eq!(body["model"], "resolved-model");
}

#[tokio::test]
async fn the_request_model_loses_only_this_providers_prefix() {
    let (url, seen) = recording_server().await;
    let p = provider("router9", url, evoflux_net::build_client().unwrap());
    for model in ["router9:gpt:latest", "gpt:latest", "xiaomi:m"] {
        drain(&p, request(model, serde_json::json!({}))).await;
    }
    let seen = seen.lock().unwrap();
    let models: Vec<Value> = seen.iter().map(|(_, b)| b["model"].clone()).collect();
    assert_eq!(models, vec!["gpt:latest", "gpt:latest", "xiaomi:m"]);
    assert!(!seen[0].0.contains_key("x-title"));
}

#[tokio::test]
async fn options_must_be_an_object_or_null() {
    let p = provider(
        "router9",
        "http://127.0.0.1:9".to_owned(),
        evoflux_net::build_client().unwrap(),
    );
    let error = p
        .stream(request("", serde_json::json!([1])))
        .await
        .err()
        .unwrap();
    assert_eq!(
        error.to_string(),
        "invalid option options: expected an object"
    );
    assert!(options(&Value::Null).unwrap().is_empty());
    assert_eq!(options(&serde_json::json!({"a": 1})).unwrap().len(), 1);
}

/// A server that answers every connection with `reply`, then hangs up.
async fn raw_server(reply: &'static [u8]) -> String {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    tokio::spawn(async move {
        loop {
            let (mut socket, _) = listener.accept().await.unwrap();
            let mut buf = vec![0u8; 65536];
            let _ = socket.read(&mut buf).await;
            let _ = socket.write_all(reply).await;
            let _ = socket.shutdown().await;
        }
    });
    format!("http://{addr}/v1")
}

fn transport(error: &ProviderError) -> (String, bool) {
    match error {
        ProviderError::Transport {
            error_type,
            transient,
            ..
        } => (error_type.clone(), *transient),
        other => (format!("not a transport error: {other:?}"), false),
    }
}

fn expected(name: &str, transient: bool) -> (String, bool) {
    (name.to_owned(), transient)
}

#[tokio::test]
async fn transport_errors_map_to_httpx_names() {
    let client = evoflux_net::build_client().unwrap();
    // Nothing listens.
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let closed = format!("http://{}/v1", listener.local_addr().unwrap());
    drop(listener);
    let p = provider("router9", closed, client.clone());
    let error = p.stream(request("", Value::Null)).await.err().unwrap();
    assert_eq!(transport(&error), expected("ConnectError", true));

    // The peer hangs up without a response.
    let p = provider("router9", raw_server(b"").await, client.clone());
    let error = p.stream(request("", Value::Null)).await.err().unwrap();
    assert_eq!(transport(&error), expected("RemoteProtocolError", true));

    // The body ends early: a body error is a ReadError even when the caller
    // was not reading the body.
    let short = b"HTTP/1.1 200 OK\r\ncontent-length: 100\r\n\r\n: keep-alive\n";
    let response = client.get(raw_server(short).await).send().await.unwrap();
    let body_error = response.bytes().await.unwrap_err();
    assert_eq!(
        transport(&transport_error(&body_error, false)),
        expected("ReadError", true)
    );
    let p = provider("router9", raw_server(short).await, client.clone());
    let events = drain(&p, request("", Value::Null)).await;
    let [Err(error)] = &events[..] else {
        unreachable!("{events:?}")
    };
    assert_eq!(transport(error), expected("ReadError", true));

    // A URL the client cannot use is not retried, unless it failed mid-body.
    let p = provider("router9", "notaurl".to_owned(), client.clone());
    let error = p.stream(request("", Value::Null)).await.err().unwrap();
    assert_eq!(transport(&error), expected("UnsupportedProtocol", false));
    let builder = client.get("notaurl").send().await.unwrap_err();
    assert_eq!(
        transport(&transport_error(&builder, true)),
        expected("ReadError", true)
    );
}

#[tokio::test]
async fn a_silent_server_is_a_read_timeout() {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    tokio::spawn(async move {
        let (_socket, _) = listener.accept().await.unwrap();
        tokio::time::sleep(Duration::from_secs(5)).await;
    });
    let client = evoflux_net::build_client_with(evoflux_net::Timeouts {
        connect: Duration::from_secs(5),
        read: Duration::from_millis(100),
    })
    .unwrap();
    let p = provider("router9", format!("http://{addr}/v1"), client);
    let error = p.stream(request("", Value::Null)).await.err().unwrap();
    assert_eq!(transport(&error), expected("ReadTimeout", true));
}

#[tokio::test]
async fn an_error_status_carries_body_and_retry_after() {
    let reply =
        b"HTTP/1.1 429 Too Many Requests\r\nretry-after: 3\r\ncontent-length: 4\r\n\r\nslow";
    let p = provider(
        "router9",
        raw_server(reply).await,
        evoflux_net::build_client().unwrap(),
    );
    let error = p.stream(request("", Value::Null)).await.err().unwrap();
    assert_eq!(
        error,
        ProviderError::Status {
            status: 429,
            body: "slow".into(),
            retry_after: Some("3".into()),
        }
    );
    assert_eq!(error.status_code(), Some(429));
    assert_eq!(error.kind(), "HTTPStatusError");
}

#[tokio::test]
async fn a_redirect_is_read_as_an_empty_stream() {
    let reply = b"HTTP/1.1 307 Temporary Redirect\r\nlocation: /x\r\ncontent-length: 0\r\n\r\n";
    let p = provider(
        "router9",
        raw_server(reply).await,
        evoflux_net::build_client().unwrap(),
    );
    assert_eq!(drain(&p, request("", Value::Null)).await, vec![Ok(done())]);
}
