//! Traffic recording (`EVOFLUX_GATEWAY_RECORD_DIR`): request/response pairs
//! that went to Python, appended as JSONL to `<dir>/traffic.jsonl` with
//! credentials removed. SSE bodies are stored as event lists. Request bodies
//! are not recorded. Run `scripts/migration/scrub.py` over a recording before
//! sharing it.
//!
//! Only credentials in headers and the `_token` query value are removed here.
//! Recorded GET bodies can still contain secrets, personal data and
//! absolute paths (API keys echoed by a settings endpoint, for example), so
//! `scripts/migration/scrub.py` must run over a recording before anything is
//! shared or committed.

use crate::shadow::{Captured, Snapshot};
use axum::http::HeaderMap;
use percent_encoding::percent_decode_str;
use serde_json::{json, Map, Value};
use std::path::{Path, PathBuf};
use tokio::io::AsyncWriteExt;

/// Replaces a removed credential value.
pub const REMOVED: &str = "<removed>";

/// Appends JSON lines to files; one writer at a time so lines never interleave.
#[derive(Debug, Default)]
pub struct JsonlWriter {
    lock: tokio::sync::Mutex<()>,
}

impl JsonlWriter {
    /// Append `entry` as one line to `path`, creating its directory. Failures
    /// are logged: shadowing and recording never affect the client.
    pub async fn append(&self, path: &Path, entry: &Value) {
        let _guard = self.lock.lock().await;
        if let Err(error) = write_line(path, entry).await {
            tracing::warn!(%error, path = %path.display(), "jsonl_append_failed");
        }
    }
}

async fn write_line(path: &Path, entry: &Value) -> std::io::Result<()> {
    if let Some(parent) = path.parent() {
        tokio::fs::create_dir_all(parent).await?;
    }
    let mut line = serde_json::to_vec(entry)?;
    line.push(b'\n');
    let mut file = tokio::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(path)
        .await?;
    file.write_all(&line).await?;
    file.flush().await
}

/// Writes recorded traffic.
#[derive(Debug)]
pub struct Recorder {
    file: PathBuf,
    writer: JsonlWriter,
}

impl Recorder {
    pub fn dir(&self) -> &Path {
        self.file.parent().unwrap_or(Path::new("."))
    }

    pub fn new(dir: &Path) -> Self {
        Self {
            file: dir.join("traffic.jsonl"),
            writer: JsonlWriter::default(),
        }
    }

    /// A recorder for `EVOFLUX_GATEWAY_RECORD_DIR`, when it is set and not empty.
    pub fn from_env() -> Option<Self> {
        let dir = std::env::var_os("EVOFLUX_GATEWAY_RECORD_DIR").filter(|d| !d.is_empty())?;
        Some(Self::new(Path::new(&dir)))
    }

    pub async fn record(&self, request: &Snapshot, response: &Captured) {
        let entry = json!({
            "method": request.method.as_str(),
            "path": redact_path(&request.path_and_query()),
            "request_headers": redact_headers(&request.headers),
            "status": response.status,
            "response_headers": redact_headers(&response.headers),
            "body": body_for_recording(response),
            "truncated": response.truncated,
        });
        self.writer.append(&self.file, &entry).await;
    }
}

fn is_secret_header(name: &str) -> bool {
    matches!(
        name,
        "authorization" | "proxy-authorization" | "cookie" | "set-cookie"
    ) || name.contains("token")
        || name.contains("secret")
        || name.contains("api-key")
        || name == "x-evoflux-gateway"
}

/// Header map as a JSON object with credential values replaced by [`REMOVED`].
pub fn redact_headers(headers: &HeaderMap) -> Value {
    let mut out = Map::new();
    for (name, value) in headers {
        let shown = if is_secret_header(name.as_str()) {
            REMOVED.to_owned()
        } else {
            String::from_utf8_lossy(value.as_bytes()).into_owned()
        };
        out.insert(name.as_str().to_owned(), Value::String(shown));
    }
    Value::Object(out)
}

/// `path?query` with the value of every `_token` query parameter removed.
pub fn redact_path(path_and_query: &str) -> String {
    let Some((path, query)) = path_and_query.split_once('?') else {
        return path_and_query.to_owned();
    };
    let query = query
        .split('&')
        .map(|pair| match pair.split_once('=') {
            // Keys may be percent-encoded (`%5Ftoken`); the server decodes them.
            Some((key, _)) if percent_decode_str(key).decode_utf8_lossy() == "_token" => {
                format!("{key}={REMOVED}")
            }
            _ => pair.to_owned(),
        })
        .collect::<Vec<_>>()
        .join("&");
    format!("{path}?{query}")
}

fn body_for_recording(response: &Captured) -> Value {
    match response.body_kind() {
        crate::shadow::BodyKind::Sse => {
            json!({ "sse_events": crate::shadow::parse_sse(&response.body) })
        }
        crate::shadow::BodyKind::Json => {
            serde_json::from_slice(&response.body).unwrap_or(Value::Null)
        }
        crate::shadow::BodyKind::Other => match std::str::from_utf8(&response.body) {
            Ok(text) => json!({ "text": text }),
            Err(_) => json!({ "binary_bytes": response.body.len() }),
        },
    }
}
