//! Shadow mode (design §3.4, workflow §5.3): for a unit owned by `shadow`,
//! Python answers the client and the Rust router runs the same GET in the
//! background. Both responses are normalized (the rules of
//! `contract-tests/normalize.py`) and differences are appended as JSONL to
//! `<state_dir>/shadow/<unit>.jsonl`. With `EVOFLUX_SHADOW_PYTHON_TWICE=1`
//! the request also runs against Python a second time, so differences that
//! show up between two Python answers are reported as noise.

use crate::record::JsonlWriter;
use axum::body::{Body, Bytes};
use axum::extract::Request;
use axum::http::header::CONTENT_TYPE;
use axum::http::{HeaderMap, Method, Uri};
use axum::response::Response;
use axum::Router;
use futures_util::StreamExt;
use http_body_util::{BodyStream, StreamBody};
use serde_json::{json, Map, Value};
use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::Duration;
use tower::ServiceExt;

/// Largest body kept for a comparison or a recording.
pub const BODY_LIMIT: usize = 4 * 1024 * 1024;
/// How long the Rust side may take to produce its whole response.
const RUST_DEADLINE: Duration = Duration::from_secs(15);
/// Longest value kept in a diff entry (serialized).
const VALUE_LIMIT: usize = 2000;

/// Shadow mode settings.
#[derive(Debug, Clone)]
pub struct ShadowOptions {
    /// Diffs go to `<state_dir>/shadow/<unit>.jsonl`.
    pub state_dir: PathBuf,
    /// Also replay each request against Python to measure noise.
    pub python_twice: bool,
}

impl ShadowOptions {
    /// `EVOFLUX_SHADOW_PYTHON_TWICE=1` turns the noise run on.
    pub fn from_env(state_dir: PathBuf) -> Self {
        let raw = std::env::var("EVOFLUX_SHADOW_PYTHON_TWICE").ok();
        Self {
            state_dir,
            python_twice: parse_flag(raw.as_deref()),
        }
    }
}

/// `1`, `true`, `yes` or `on` (any case) enable a flag.
pub fn parse_flag(raw: Option<&str>) -> bool {
    raw.is_some_and(|v| {
        matches!(
            v.trim().to_ascii_lowercase().as_str(),
            "1" | "true" | "yes" | "on"
        )
    })
}

/// The request as the client sent it (without the gateway header), kept so it
/// can be replayed and recorded.
#[derive(Debug, Clone)]
pub struct Snapshot {
    pub method: Method,
    pub uri: Uri,
    pub headers: HeaderMap,
}

impl Snapshot {
    pub fn of(req: &Request) -> Self {
        Self {
            method: req.method().clone(),
            uri: req.uri().clone(),
            headers: req.headers().clone(),
        }
    }

    pub fn path_and_query(&self) -> String {
        self.uri
            .path_and_query()
            .map_or_else(|| self.uri.path().to_owned(), |pq| pq.as_str().to_owned())
    }

    /// A body-less copy of the request.
    pub fn to_request(&self) -> Request {
        let mut req = Request::new(Body::empty());
        *req.method_mut() = self.method.clone();
        *req.uri_mut() = self.uri.clone();
        *req.headers_mut() = self.headers.clone();
        req
    }
}

/// A response read to the end (or to the size limit).
#[derive(Debug, Clone)]
pub struct Captured {
    pub status: u16,
    pub headers: HeaderMap,
    pub body: Vec<u8>,
    /// The body is incomplete (limit, deadline or the client went away).
    pub truncated: bool,
    /// The response could not be produced (a panic in the Rust handler).
    pub error: Option<String>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BodyKind {
    Json,
    Sse,
    Other,
}

impl Captured {
    fn failed(message: String) -> Self {
        Self {
            status: 0,
            headers: HeaderMap::new(),
            body: Vec::new(),
            truncated: false,
            error: Some(message),
        }
    }

    fn media_type(&self) -> String {
        self.headers
            .get(CONTENT_TYPE)
            .and_then(|v| v.to_str().ok())
            .and_then(|v| v.split(';').next())
            .map(|v| v.trim().to_ascii_lowercase())
            .unwrap_or_default()
    }

    pub fn body_kind(&self) -> BodyKind {
        let media = self.media_type();
        if media == "text/event-stream" {
            BodyKind::Sse
        } else if media == "application/json" || media.ends_with("+json") {
            BodyKind::Json
        } else {
            BodyKind::Other
        }
    }
}

/// Read `response` to the end, up to `limit` bytes and `deadline`.
pub async fn capture(response: Response, limit: usize, deadline: Duration) -> Captured {
    let (parts, body) = response.into_parts();
    let mut out = Captured {
        status: parts.status.as_u16(),
        headers: parts.headers,
        body: Vec::new(),
        truncated: false,
        error: None,
    };
    let mut stream = Box::pin(BodyStream::new(body));
    let read = async {
        while let Some(frame) = stream.next().await {
            let Ok(frame) = frame else {
                out.truncated = true;
                return;
            };
            if let Some(data) = frame.data_ref() {
                if out.body.len() + data.len() > limit {
                    out.truncated = true;
                    return;
                }
                out.body.extend_from_slice(data);
            }
        }
    };
    if tokio::time::timeout(deadline, read).await.is_err() {
        out.truncated = true;
    }
    out
}

type OnDone = Box<dyn FnOnce(Captured) + Send>;

/// Reports the bytes that passed through a response once it ends or is dropped.
struct Tap {
    head: Captured,
    limit: usize,
    on_done: Option<OnDone>,
}

impl Tap {
    fn push(&mut self, data: &Bytes) {
        if self.head.truncated {
            return;
        }
        if self.head.body.len() + data.len() > self.limit {
            self.head.truncated = true;
        } else {
            self.head.body.extend_from_slice(data);
        }
    }
}

impl Tap {
    fn finish(&mut self, complete: bool) {
        if let Some(on_done) = self.on_done.take() {
            let mut captured = Captured {
                headers: std::mem::take(&mut self.head.headers),
                body: std::mem::take(&mut self.head.body),
                ..self.head.clone()
            };
            captured.truncated |= !complete;
            on_done(captured);
        }
    }
}

impl Drop for Tap {
    /// The client went away before the body ended.
    fn drop(&mut self) {
        self.finish(false);
    }
}

/// Pass `response` through unchanged while keeping a copy of its body; `on_done`
/// gets the copy when the body ends or the client drops it. `on_done` runs
/// inside the runtime and must not block.
pub fn tap_response(response: Response, limit: usize, on_done: OnDone) -> Response {
    let (parts, body) = response.into_parts();
    let tap = Tap {
        head: Captured {
            status: parts.status.as_u16(),
            headers: parts.headers.clone(),
            body: Vec::new(),
            truncated: false,
            error: None,
        },
        limit,
        on_done: Some(on_done),
    };
    let stream = futures_util::stream::unfold(
        (Box::pin(BodyStream::new(body)), tap),
        |(mut inner, mut tap)| async move {
            match inner.next().await {
                Some(Ok(frame)) => {
                    if let Some(data) = frame.data_ref() {
                        tap.push(data);
                    }
                    Some((Ok(frame), (inner, tap)))
                }
                Some(Err(error)) => Some((Err(error), (inner, tap))),
                None => {
                    tap.finish(true);
                    None
                }
            }
        },
    );
    Response::from_parts(parts, Body::new(StreamBody::new(stream)))
}

/// The Rust side of one shadowed request, running in the background.
pub type RustRun = tokio::task::JoinHandle<Captured>;
/// The second Python answer for the noise run.
pub type NoiseRun = tokio::task::JoinHandle<Captured>;

/// Shadow comparison state: where diffs go and how many requests were compared.
#[derive(Debug)]
pub struct Shadow {
    opts: ShadowOptions,
    writer: JsonlWriter,
    compared: AtomicU64,
}

impl Shadow {
    pub fn new(opts: ShadowOptions) -> Self {
        Self {
            opts,
            writer: JsonlWriter::default(),
            compared: AtomicU64::new(0),
        }
    }

    pub fn python_twice(&self) -> bool {
        self.opts.python_twice
    }

    /// Requests whose comparison has finished (equal or not); for tests and tooling.
    pub fn compared(&self) -> u64 {
        self.compared.load(Ordering::SeqCst)
    }

    /// Run `snapshot` against the Rust router. A panic or error in the Rust
    /// handler stays in the task and is reported as a `rust_error` diff.
    pub fn spawn_rust(&self, rust_routes: Router, snapshot: &Snapshot) -> RustRun {
        let req = snapshot.to_request();
        tokio::spawn(async move {
            let response = match rust_routes.oneshot(req).await {
                Ok(response) => response,
                Err(never) => match never {},
            };
            capture(response, BODY_LIMIT, RUST_DEADLINE).await
        })
    }

    /// Compare the Python answer with the Rust one (and the second Python
    /// answer, when present) and append a diff entry when they differ.
    pub async fn finish(
        &self,
        unit: &str,
        snapshot: &Snapshot,
        python: Captured,
        rust: RustRun,
        noise: Option<NoiseRun>,
    ) {
        let rust = rust
            .await
            .unwrap_or_else(|error| Captured::failed(format!("rust handler failed: {error}")));
        let noise = match noise {
            Some(run) => run.await.ok(),
            None => None,
        };
        let entry = build_entry(unit, snapshot, &python, &rust, noise.as_ref());
        if let Some(entry) = entry {
            let file = self
                .opts
                .state_dir
                .join("shadow")
                .join(format!("{unit}.jsonl"));
            self.writer.append(&file, &entry).await;
        }
        self.compared.fetch_add(1, Ordering::SeqCst);
    }
}

fn build_entry(
    unit: &str,
    snapshot: &Snapshot,
    python: &Captured,
    rust: &Captured,
    noise: Option<&Captured>,
) -> Option<Value> {
    let path = crate::record::redact_path(&snapshot.path_and_query());
    let base = |kind: &str| {
        let mut entry = Map::new();
        entry.insert("unit".into(), json!(unit));
        entry.insert("method".into(), json!(snapshot.method.as_str()));
        entry.insert("path".into(), json!(path));
        entry.insert("kind".into(), json!(kind));
        entry
    };
    if let Some(error) = &rust.error {
        let mut entry = base("rust_error");
        entry.insert("error".into(), json!(error));
        return Some(Value::Object(entry));
    }
    let python_view = response_view(python);
    let diffs = diff(&python_view, &response_view(rust));
    let noise_diffs = noise.map_or_else(Vec::new, |second| {
        diff(&python_view, &response_view(second))
    });
    let noisy: Vec<&str> = noise_diffs.iter().map(|d| d.path.as_str()).collect();
    let real: Vec<&Diff> = diffs
        .iter()
        .filter(|d| !noisy.contains(&d.path.as_str()))
        .collect();
    if real.is_empty() && noise_diffs.is_empty() {
        return None;
    }
    let kind = if real.is_empty() { "noise" } else { "mismatch" };
    let mut entry = base(kind);
    entry.insert("diffs".into(), json!(real));
    entry.insert("noise".into(), json!(noisy));
    entry.insert(
        "truncated".into(),
        json!(python.truncated || rust.truncated),
    );
    Some(Value::Object(entry))
}

/// What is compared for one response: status, media type and normalized body.
pub fn response_view(response: &Captured) -> Value {
    let body = match response.body_kind() {
        BodyKind::Sse => json!({ "events": parse_sse(&response.body) }),
        BodyKind::Json => serde_json::from_slice(&response.body).unwrap_or_else(|_| {
            Value::String(String::from_utf8_lossy(&response.body).into_owned())
        }),
        BodyKind::Other => Value::String(String::from_utf8_lossy(&response.body).into_owned()),
    };
    normalize(&json!({
        "status": response.status,
        "content_type": response.media_type(),
        "body": body,
    }))
}

/// An SSE body as a list of `{event, data}` (data parsed as JSON when it is).
pub fn parse_sse(body: &[u8]) -> Vec<Value> {
    let text = String::from_utf8_lossy(body).replace("\r\n", "\n");
    text.split("\n\n")
        .filter_map(|block| {
            let mut event = None;
            let mut data: Vec<&str> = Vec::new();
            for line in block.lines() {
                if let Some(rest) = line.strip_prefix("event:") {
                    event = Some(rest.trim().to_owned());
                } else if let Some(rest) = line.strip_prefix("data:") {
                    data.push(rest.strip_prefix(' ').unwrap_or(rest));
                }
            }
            if event.is_none() && data.is_empty() {
                return None;
            }
            let joined = data.join("\n");
            let data = serde_json::from_str(&joined).unwrap_or(Value::String(joined));
            Some(json!({ "event": event, "data": data }))
        })
        .collect()
}

/// One difference between two normalized values.
#[derive(Debug, Clone, PartialEq, serde::Serialize)]
pub struct Diff {
    pub path: String,
    pub python: Value,
    pub rust: Value,
}

/// Differences between `left` (Python) and `right` (Rust); paths look like `$.a[0].b`.
pub fn diff(left: &Value, right: &Value) -> Vec<Diff> {
    let mut out = Vec::new();
    walk_diff("$", left, right, &mut out);
    out
}

fn clip(value: &Value) -> Value {
    let text = value.to_string();
    if text.len() <= VALUE_LIMIT {
        value.clone()
    } else {
        let head: String = text.chars().take(VALUE_LIMIT).collect();
        Value::String(format!("{head}..."))
    }
}

fn walk_diff(path: &str, left: &Value, right: &Value, out: &mut Vec<Diff>) {
    match (left, right) {
        (Value::Object(a), Value::Object(b)) => {
            let mut keys: Vec<&String> = a.keys().chain(b.keys()).collect();
            keys.sort();
            keys.dedup();
            for key in keys {
                let child = format!("{path}.{key}");
                match (a.get(key), b.get(key)) {
                    (Some(x), Some(y)) => walk_diff(&child, x, y, out),
                    (x, y) => out.push(Diff {
                        path: child,
                        python: x.map_or(Value::Null, clip),
                        rust: y.map_or(Value::Null, clip),
                    }),
                }
            }
        }
        (Value::Array(a), Value::Array(b)) if a.len() == b.len() => {
            for (index, (x, y)) in a.iter().zip(b).enumerate() {
                walk_diff(&format!("{path}[{index}]"), x, y, out);
            }
        }
        _ if left == right => {}
        _ => out.push(Diff {
            path: path.to_owned(),
            python: clip(left),
            rust: clip(right),
        }),
    }
}

/// Port of `contract-tests/normalize.py` `normalize` with the default rules:
/// UUIDs become `<uuid:N>` (numbered by first appearance, visiting object keys
/// in sorted order) and ISO-8601 timestamps become `<ts:CLASS>`. List order is
/// kept.
pub fn normalize(value: &Value) -> Value {
    let mut uuids = HashMap::new();
    walk(value, &mut uuids)
}

fn walk(value: &Value, uuids: &mut HashMap<String, usize>) -> Value {
    match value {
        Value::Object(map) => {
            let mut keys: Vec<&String> = map.keys().collect();
            keys.sort();
            let mut out = Map::new();
            for key in keys {
                if let Some(child) = map.get(key) {
                    out.insert(key.clone(), walk(child, uuids));
                }
            }
            Value::Object(out)
        }
        Value::Array(items) => Value::Array(items.iter().map(|v| walk(v, uuids)).collect()),
        Value::String(text) => Value::String(scrub_text(text, uuids)),
        other => other.clone(),
    }
}

fn scrub_text(text: &str, uuids: &mut HashMap<String, usize>) -> String {
    let replaced = replace_uuids(text, uuids);
    replace_timestamps(&replaced)
}

fn all_digits(bytes: &[u8], at: usize, count: usize) -> bool {
    bytes
        .get(at..at + count)
        .is_some_and(|s| s.iter().all(u8::is_ascii_digit))
}

fn all_hex(bytes: &[u8], at: usize, count: usize) -> bool {
    bytes
        .get(at..at + count)
        .is_some_and(|s| s.iter().all(u8::is_ascii_hexdigit))
}

/// `[0-9a-fA-F]{8}-{4}-{4}-{4}-{12}` starting at `at`.
fn uuid_at(bytes: &[u8], at: usize) -> bool {
    let mut pos = at;
    for (index, len) in [8, 4, 4, 4, 12].into_iter().enumerate() {
        if index > 0 {
            if bytes.get(pos) != Some(&b'-') {
                return false;
            }
            pos += 1;
        }
        if !all_hex(bytes, pos, len) {
            return false;
        }
        pos += len;
    }
    true
}

fn replace_uuids(text: &str, uuids: &mut HashMap<String, usize>) -> String {
    let bytes = text.as_bytes();
    let mut out = String::with_capacity(text.len());
    let mut copied = 0;
    let mut index = 0;
    while index < bytes.len() {
        if uuid_at(bytes, index) {
            let found = text.get(index..index + 36).unwrap_or_default();
            let next = uuids.len() + 1;
            let number = *uuids.entry(found.to_ascii_lowercase()).or_insert(next);
            out.push_str(text.get(copied..index).unwrap_or_default());
            out.push_str(&format!("<uuid:{number}>"));
            index += 36;
            copied = index;
        } else {
            index += 1;
        }
    }
    out.push_str(text.get(copied..).unwrap_or_default());
    out
}

/// The zone forms that can start at `at`, greedy first: `Z`, `+hh:mm`, `+hhmm`.
fn zone_ends(bytes: &[u8], at: usize) -> Vec<(usize, bool)> {
    match bytes.get(at) {
        Some(b'Z') => vec![(at + 1, true)],
        Some(b'+' | b'-') if all_digits(bytes, at + 1, 2) => {
            let mut ends = Vec::new();
            if bytes.get(at + 3) == Some(&b':') && all_digits(bytes, at + 4, 2) {
                ends.push((at + 6, false));
            }
            if all_digits(bytes, at + 3, 2) {
                ends.push((at + 5, false));
            }
            ends
        }
        _ => Vec::new(),
    }
}

/// The token for a timestamp starting at `at`, and where it ends. Mirrors the
/// regex in `normalize.py`, including its backtracking order.
fn timestamp_at(bytes: &[u8], at: usize) -> Option<(usize, String)> {
    let date = all_digits(bytes, at, 4)
        && bytes.get(at + 4) == Some(&b'-')
        && all_digits(bytes, at + 5, 2)
        && bytes.get(at + 7) == Some(&b'-')
        && all_digits(bytes, at + 8, 2);
    if !date {
        return None;
    }
    let date_end = at + 10;
    let ok_after =
        |end: usize| !matches!(bytes.get(end), Some(b) if b.is_ascii_digit() || *b == b':');
    // (end, naive/utc-z/offset, fractional, separator is a space)
    let mut candidates: Vec<(usize, &str, bool, bool)> = Vec::new();
    if let Some(&sep @ (b'T' | b' ')) = bytes.get(date_end) {
        let t = date_end + 1;
        if all_digits(bytes, t, 2)
            && bytes.get(t + 2) == Some(&b':')
            && all_digits(bytes, t + 3, 2)
            && bytes.get(t + 5) == Some(&b':')
            && all_digits(bytes, t + 6, 2)
        {
            let time_end = t + 8;
            let mut frac_options = Vec::new();
            if bytes.get(time_end) == Some(&b'.') && all_digits(bytes, time_end + 1, 1) {
                let mut end = time_end + 1;
                while bytes.get(end).is_some_and(u8::is_ascii_digit) {
                    end += 1;
                }
                frac_options.push((end, true));
            }
            frac_options.push((time_end, false));
            for (frac_end, frac) in frac_options {
                for (zone_end, utc) in zone_ends(bytes, frac_end) {
                    let class = if utc { "utc-z" } else { "offset" };
                    candidates.push((zone_end, class, frac, sep == b' '));
                }
                candidates.push((frac_end, "naive", frac, sep == b' '));
            }
        }
    }
    for (end, class, frac, space) in candidates {
        if ok_after(end) {
            let mut parts = vec![class];
            if frac {
                parts.push("frac");
            }
            if space {
                parts.push("space");
            }
            return Some((end, format!("<ts:{}>", parts.join(","))));
        }
    }
    ok_after(date_end).then(|| (date_end, "<ts:date>".to_owned()))
}

fn replace_timestamps(text: &str) -> String {
    let bytes = text.as_bytes();
    let mut out = String::with_capacity(text.len());
    let mut copied = 0;
    let mut index = 0;
    while index < bytes.len() {
        let after_digit_or_dash = index > 0
            && bytes
                .get(index - 1)
                .is_some_and(|b| b.is_ascii_digit() || *b == b'-');
        match (after_digit_or_dash, timestamp_at(bytes, index)) {
            (false, Some((end, token))) => {
                out.push_str(text.get(copied..index).unwrap_or_default());
                out.push_str(&token);
                index = end;
                copied = end;
            }
            _ => index += 1,
        }
    }
    out.push_str(text.get(copied..).unwrap_or_default());
    out
}
