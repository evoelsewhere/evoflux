//! Traffic recording (`EVOFLUX_GATEWAY_RECORD_DIR`): request/response pairs
//! that went to Python, appended as JSONL to `<dir>/traffic.jsonl` with
//! credentials removed. SSE bodies are stored as event lists. Request bodies
//! are scrubbed and bounded. Run `scripts/migration/scrub.py` over a recording before
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
use sha2::{Digest, Sha256};
use std::path::{Path, PathBuf};
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};

/// Replaces a removed credential value.
pub const REMOVED: &str = "<removed>";

const REQUEST_BODY_LIMIT: usize = 1024 * 1024;

/// Scrub the same secret and personal-data patterns as the recording scrubber.
pub fn scrub_request_body(text: &str) -> String {
    let rules = [
        (
            r"(?s)-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
            "<private-key>",
        ),
        (r"\bsk-(?:ant-)?[A-Za-z0-9_-]{20,}", "<api-key>"),
        (
            r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})",
            "<api-key>",
        ),
        (r"\bAKIA[0-9A-Z]{16}\b", "<api-key>"),
        (r"\bAIza[0-9A-Za-z_-]{30,}", "<api-key>"),
        (r"\bxox[abprs]-[A-Za-z0-9-]{10,}", "<api-key>"),
        (r"(?i)\b(Bearer|Basic) [A-Za-z0-9._~+/=-]{8,}", "$1 <token>"),
        (
            r"(?i)([?&](?:_|%5f)(?:t|%74)(?:o|%6f)(?:k|%6b)(?:e|%65)(?:n|%6e)=)[^&\s\x22']+",
            "${1}<token>",
        ),
        (
            r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+",
            "<email>",
        ),
        (
            r"([A-Za-z]:(?:\\\\|\\|/)Users(?:\\\\|\\|/))[^\\/\s\x22']+",
            "${1}<user>",
        ),
        (r"(/(?:home|Users)/)[^/\\\s\x22']+", "${1}<user>"),
    ];
    let mut cleaned = text.to_owned();
    for (pattern, replacement) in rules {
        let Ok(regex) = regex::Regex::new(pattern) else {
            return "<redaction-error>".to_owned();
        };
        cleaned = regex.replace_all(&cleaned, replacement).into_owned();
    }
    cleaned
}

/// Bounded capture and incremental digest of a forwarded request body.
#[derive(Default)]
pub struct RequestBodyCapture {
    bytes: Vec<u8>,
    length: usize,
    hash: Sha256,
}

impl RequestBodyCapture {
    pub fn length(&self) -> usize {
        self.length
    }
    pub fn push(&mut self, data: &[u8]) {
        self.length = self.length.saturating_add(data.len());
        self.hash.update(data);
        if self.length <= REQUEST_BODY_LIMIT {
            self.bytes.extend_from_slice(data);
        } else {
            self.bytes.clear();
        }
    }

    pub fn finish(self) -> Value {
        if self.length <= REQUEST_BODY_LIMIT {
            if let Ok(text) = std::str::from_utf8(&self.bytes) {
                return json!({"text": scrub_request_body(text)});
            }
        }
        json!({"length": self.length, "sha256": format!("{:x}", self.hash.finalize())})
    }
}

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
    sequence: tokio::sync::Mutex<Option<u64>>,
}

impl Recorder {
    pub fn dir(&self) -> &Path {
        self.file.parent().unwrap_or(Path::new("."))
    }

    pub fn new(dir: &Path) -> Self {
        let file = dir.join("traffic.jsonl");
        Self {
            file,
            writer: JsonlWriter::default(),
            sequence: tokio::sync::Mutex::new(None),
        }
    }

    /// A recorder for `EVOFLUX_GATEWAY_RECORD_DIR`, when it is set and not empty.
    pub fn from_env() -> Option<Self> {
        let dir = std::env::var_os("EVOFLUX_GATEWAY_RECORD_DIR").filter(|d| !d.is_empty())?;
        Some(Self::new(Path::new(&dir)))
    }

    pub async fn next_sequence(&self) -> u64 {
        let mut slot = self.sequence.lock().await;
        if slot.is_none() {
            let mut max = None;
            if let Ok(file) = tokio::fs::File::open(&self.file).await {
                let mut lines = BufReader::new(file).lines();
                while let Ok(Some(line)) = lines.next_line().await {
                    if let Some(seq) = serde_json::from_str::<Value>(&line)
                        .ok()
                        .and_then(|v| v.get("seq").and_then(Value::as_u64))
                    {
                        max = Some(max.map_or(seq, |old: u64| old.max(seq)));
                    }
                }
            }
            *slot = Some(max.map_or(0, |v| v.saturating_add(1)));
        }
        let current = slot.unwrap_or(0);
        *slot = Some(current.saturating_add(1));
        current
    }

    pub async fn record(
        &self,
        request: &Snapshot,
        response: &Captured,
        sequence: u64,
        body: Value,
    ) {
        let entry = json!({
            "seq": sequence,
            "method": request.method.as_str(),
            "path": redact_path(&request.path_and_query()),
            "request_headers": redact_headers(&request.headers),
            "request_body": body,
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
