//! Test fixtures: a real SQLite database with the chat tables, a scripted
//! Chat Completions server and the chat-core router wired to both.

#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::indexing_slicing,
    clippy::disallowed_methods,
    clippy::type_complexity,
    clippy::panic,
    dead_code
)]

use std::collections::{HashMap, VecDeque};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use axum::body::{to_bytes, Body};
use axum::Router;
use evoflux_core::config::Settings;
use evoflux_core::db::{Db, DbOptions};
use serde_json::{json, Value};
use tower::ServiceExt;

use crate::stream_store::Frame;
use crate::ChatState;

const SCHEMA: &str = "
CREATE TABLE chat_sessions (
    id CHAR(32) NOT NULL PRIMARY KEY, parent_session_id CHAR(32), agent_name VARCHAR,
    title VARCHAR, scheduled_task_name VARCHAR, created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL, mode VARCHAR NOT NULL, workspace VARCHAR, revert JSON,
    model VARCHAR, thinking_level VARCHAR, permission_mode VARCHAR NOT NULL,
    project_id CHAR(32), tags JSON, session_type VARCHAR, source_session_id CHAR(32),
    source_session_ref VARCHAR, folder_id CHAR(32), source VARCHAR, imported_at DATETIME,
    source_item_id VARCHAR);
CREATE TABLE session_messages (
    id CHAR(32) NOT NULL PRIMARY KEY, session_id CHAR(32) NOT NULL, role VARCHAR NOT NULL,
    content VARCHAR, reasoning_content VARCHAR, tool_calls JSON, tool_call_id VARCHAR,
    name VARCHAR, extra JSON, is_summary BOOLEAN NOT NULL, exclude_from_context BOOLEAN NOT NULL,
    created_at DATETIME NOT NULL);
CREATE TABLE session_folders (id CHAR(32) NOT NULL PRIMARY KEY, mode VARCHAR NOT NULL);
CREATE TABLE session_goals (
    session_id CHAR(32) NOT NULL PRIMARY KEY, objective VARCHAR NOT NULL, status VARCHAR NOT NULL,
    token_budget INTEGER, tokens_used INTEGER NOT NULL, time_used_seconds FLOAT NOT NULL,
    active_started_at DATETIME, pause_reason VARCHAR, blocker_streak INTEGER NOT NULL,
    status_details JSON, version INTEGER NOT NULL, created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL, completed_at DATETIME);
";

/// A database in a temp directory with the chat tables.
pub(crate) async fn open_db(dir: &std::path::Path) -> Arc<Db> {
    let db = Db::open(&dir.join("test.db"), DbOptions::default()).unwrap();
    db.write_exclusive(|tx| {
        tx.execute_batch(SCHEMA)?;
        Ok(())
    })
    .await
    .unwrap();
    Arc::new(db)
}

/// `data:` lines of a Chat Completions stream that says `text`.
pub(crate) fn sse_text(text: &str) -> String {
    sse(&[
        json!({"choices": [{"index": 0, "delta": {"role": "assistant", "content": text}}]}),
        json!({"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
               "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}}),
    ])
}

/// A stream that thinks, then calls one tool.
pub(crate) fn sse_thinking_tool(thought: &str, id: &str, name: &str, arguments: &str) -> String {
    let mut out = sse(&[
        json!({"choices": [{"index": 0, "delta": {"role": "assistant", "reasoning_content": thought}}]}),
    ]);
    out.truncate(out.len() - "data: [DONE]\n\n".len());
    out.push_str(&sse_tool(id, name, arguments));
    out
}

/// A stream that makes several tool calls in one reply.
pub(crate) fn sse_tool_calls(calls: &[(&str, &str, &str)]) -> String {
    let deltas: Vec<Value> = calls
        .iter()
        .enumerate()
        .map(|(index, (id, name, arguments))| {
            json!({"index": index, "id": id, "type": "function",
                   "function": {"name": name, "arguments": arguments}})
        })
        .collect();
    sse(&[
        json!({"choices": [{"index": 0, "delta": {"role": "assistant", "tool_calls": deltas}}]}),
        json!({"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
               "usage": {"prompt_tokens": 4, "completion_tokens": 1, "total_tokens": 5}}),
    ])
}

/// A stream that calls one tool.
pub(crate) fn sse_tool(id: &str, name: &str, arguments: &str) -> String {
    sse(&[
        json!({"choices": [{"index": 0, "delta": {"role": "assistant", "tool_calls": [
            {"index": 0, "id": id, "type": "function",
             "function": {"name": name, "arguments": arguments}}]}}]}),
        json!({"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
               "usage": {"prompt_tokens": 4, "completion_tokens": 1, "total_tokens": 5}}),
    ])
}

fn sse(chunks: &[Value]) -> String {
    let mut out = String::new();
    for chunk in chunks {
        let mut chunk = chunk.clone();
        chunk["id"] = json!("chatcmpl-1");
        chunk["object"] = json!("chat.completion.chunk");
        chunk["created"] = json!(1);
        chunk["model"] = json!("mock-model");
        out.push_str(&format!("data: {chunk}\n\n"));
    }
    out.push_str("data: [DONE]\n\n");
    out
}

#[derive(Clone)]
struct Stub {
    script: Arc<Mutex<VecDeque<String>>>,
    seen: Arc<Mutex<Vec<Value>>>,
    delay: Duration,
}

async fn completions(
    axum::extract::State(stub): axum::extract::State<Stub>,
    axum::Json(body): axum::Json<Value>,
) -> axum::response::Response {
    use axum::response::IntoResponse;
    stub.seen.lock().unwrap().push(body.clone());
    if body["stream"] == json!(false) {
        return axum::Json(
            json!({"choices": [{"message": {"content": "\"Mock title.\""}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}}),
        )
        .into_response();
    }
    // A loop that never ends fails the test instead of hanging it.
    let streamed = stub
        .seen
        .lock()
        .unwrap()
        .iter()
        .filter(|b| b["stream"] == json!(true))
        .count();
    if streamed > 20 {
        let error =
            json!({"error": {"message": "too many calls", "type": "invalid_request_error"}});
        return (axum::http::StatusCode::BAD_REQUEST, axum::Json(error)).into_response();
    }
    tokio::time::sleep(stub.delay).await;
    let next = stub.script.lock().unwrap().pop_front();
    let text = next.unwrap_or_else(|| sse_text("ok"));
    (
        [(axum::http::header::CONTENT_TYPE, "text/event-stream")],
        text,
    )
        .into_response()
}

pub(crate) struct Env {
    pub dir: tempfile::TempDir,
    pub db: Arc<Db>,
    pub state: Arc<ChatState>,
    app: Router,
    script: Arc<Mutex<VecDeque<String>>>,
    pub seen: Arc<Mutex<Vec<Value>>>,
}

impl Env {
    pub(crate) async fn new() -> Env {
        Env::with_delay(Duration::ZERO).await
    }

    pub(crate) async fn with_delay(delay: Duration) -> Env {
        let dir = tempfile::tempdir().unwrap();
        let db = open_db(dir.path()).await;
        let script = Arc::new(Mutex::new(VecDeque::new()));
        let seen = Arc::new(Mutex::new(Vec::new()));
        let stub = Stub {
            script: script.clone(),
            seen: seen.clone(),
            delay,
        };
        let provider = Router::new()
            .route("/v1/chat/completions", axum::routing::post(completions))
            .with_state(stub);
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        tokio::spawn(async move { axum::serve(listener, provider).await });
        let config = dir.path().join("config");
        std::fs::create_dir_all(config.join("agents")).unwrap();
        std::fs::write(
            config.join("agents").join("evoflux.md"),
            "---\nname: evoflux\nrole: lead\nmodel: router9:mock-model\n---\n\nBe brief.\n",
        )
        .unwrap();
        let vars = HashMap::from([
            (
                "EVOFLUX_CONFIG_DIR".to_owned(),
                config.to_string_lossy().into_owned(),
            ),
            (
                "EVOFLUX_WORKSPACE_DIR".to_owned(),
                dir.path().join("workspaces").to_string_lossy().into_owned(),
            ),
            ("ROUTER9_BASE_URL".to_owned(), format!("http://{addr}/v1")),
            ("ROUTER9_API_KEY".to_owned(), "k".to_owned()),
        ]);
        let home = dir.path().join("home");
        std::fs::create_dir_all(&home).unwrap();
        let settings = Settings::from_vars(&vars, Some(&home), dir.path()).unwrap();
        let state = crate::new_state(
            Arc::new(settings),
            Some(db.clone()),
            evoflux_net::build_client().unwrap(),
        );
        let app = crate::routes(state.clone());
        Env {
            dir,
            db,
            state,
            app,
            script,
            seen,
        }
    }

    /// Queue the next streamed model reply.
    pub(crate) fn script(&self, reply: String) {
        self.script.lock().unwrap().push_back(reply);
    }

    pub(crate) async fn request(&self, method: &str, uri: &str, form: &str) -> (u16, Value) {
        let ct = "application/x-www-form-urlencoded";
        self.send(method, uri, ct, form.as_bytes().to_vec()).await
    }

    pub(crate) async fn send(
        &self,
        method: &str,
        uri: &str,
        content_type: &str,
        body: Vec<u8>,
    ) -> (u16, Value) {
        let request = axum::http::Request::builder()
            .method(method)
            .uri(uri)
            .header("content-type", content_type)
            .body(Body::from(body))
            .unwrap();
        let response = self.app.clone().oneshot(request).await.unwrap();
        let status = response.status().as_u16();
        let bytes = tokio::time::timeout(
            Duration::from_secs(8),
            to_bytes(response.into_body(), usize::MAX),
        )
        .await
        .expect("response body did not end")
        .unwrap();
        let value = serde_json::from_slice(&bytes)
            .unwrap_or_else(|_| Value::String(String::from_utf8_lossy(&bytes).into_owned()));
        (status, value)
    }

    /// POST a multipart form of text fields and one file part.
    pub(crate) async fn post_multipart(&self, fields: &[(&str, &str)], file: bool) -> (u16, Value) {
        let mut body = String::new();
        for (name, value) in fields {
            body.push_str(&format!(
                "--B\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n"
            ));
        }
        if file {
            body.push_str(
                "--B\r\nContent-Disposition: form-data; name=\"files\"; filename=\"a.txt\"\r\n\r\nhi\r\n",
            );
        }
        body.push_str("--B--\r\n");
        self.send(
            "POST",
            "/api/team/chat",
            "multipart/form-data; boundary=B",
            body.into_bytes(),
        )
        .await
    }

    pub(crate) async fn post(&self, form: &str) -> (u16, Value) {
        self.request("POST", "/api/team/chat", form).await
    }

    pub(crate) async fn get(&self, uri: &str) -> (u16, Value) {
        self.request("GET", uri, "").await
    }

    /// Wait until no turn is in flight.
    pub(crate) async fn idle(&self) {
        for _ in 0..75 {
            if self.state.active().is_empty() {
                return;
            }
            tokio::time::sleep(Duration::from_millis(20)).await;
        }
        panic!("turn did not finish");
    }

    /// Run one text turn: its response and every frame the stream carried,
    /// attached right after the request was accepted, until `done`.
    pub(crate) async fn chat_frames(&self, form: &str) -> (Value, Vec<Frame>) {
        let (status, body) = self.post(form).await;
        assert_eq!(status, 202, "{body}");
        let sid = body["session_id"].as_str().unwrap().to_owned();
        let (mut frames, mut rx) = self.state.store.attach(&sid).unwrap();
        while let Ok(Some(frame)) = tokio::time::timeout(Duration::from_secs(2), rx.recv()).await {
            frames.push(frame);
        }
        self.idle().await;
        (body, frames)
    }

    /// Wait until the session's title is no longer `old`.
    pub(crate) async fn wait_title(&self, sid_hex: &str, old: &str) -> String {
        for _ in 0..250 {
            let id = sid_hex.to_owned();
            let title: Option<String> = self
                .query(move |c| {
                    c.query_row("SELECT title FROM chat_sessions WHERE id = ?1", [id], |r| {
                        r.get(0)
                    })
                })
                .await;
            if let Some(title) = title.filter(|t| t != old) {
                return title;
            }
            tokio::time::sleep(Duration::from_millis(20)).await;
        }
        panic!("title never changed");
    }

    pub(crate) async fn query<T: Send + 'static>(
        &self,
        f: impl FnOnce(&rusqlite::Connection) -> rusqlite::Result<T> + Send + 'static,
    ) -> T {
        self.db.read(move |conn| Ok(f(conn)?)).await.unwrap()
    }
}
