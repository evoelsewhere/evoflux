//! Port of the chat-core routes of app/api/routes/team/chat.py: `POST /chat`
//! (`team_chat`), `GET /{session_id}/stream` (`team_stream`) and
//! `GET /{session_id}/history` (`team_history`), plus the `ChatForm` checks
//! of app/api/schemas/chat.py. Work-mode text turns only; everything else
//! answers with the reason (KNOWN_DIFFERENCES).

use std::collections::HashMap;
use std::convert::Infallible;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use axum::body::{Body, Bytes};
use axum::extract::{Path, Query, State};
use axum::http::{header, HeaderMap, HeaderValue, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::Json;
use evoflux_core::ApiError;
use futures_util::stream;
use serde_json::{json, Map, Value};

use crate::agent::{select_lead, work_leads};
use crate::store::{self, MessageRow, NewSession, SessionRow};
use crate::stream_store::Frame;
use crate::turn::{self, TurnInput};
use crate::workspace;
use crate::ChatState;

/// sse_starlette's default ping interval.
const PING_INTERVAL: Duration = Duration::from_secs(15);

fn err(status: StatusCode, detail: impl Into<String>) -> ApiError {
    ApiError::new(status, Value::String(detail.into()))
}

fn unprocessable(detail: impl Into<String>) -> ApiError {
    err(StatusCode::UNPROCESSABLE_ENTITY, detail)
}

fn db_error(error: evoflux_core::db::DbError) -> ApiError {
    tracing::error!(%error, "chat_core_db_error");
    match error {
        evoflux_core::db::DbError::Busy => err(StatusCode::SERVICE_UNAVAILABLE, "database_busy"),
        _ => err(StatusCode::INTERNAL_SERVER_ERROR, "Internal Server Error"),
    }
}

/// A parsed form: text fields (last value wins, as Starlette's `FormData`
/// lookup does for a single-valued field) and how many file parts it had.
#[derive(Debug, Default, PartialEq)]
pub(crate) struct Form {
    fields: HashMap<String, String>,
    files: usize,
}

impl Form {
    fn get(&self, name: &str) -> Option<&str> {
        self.fields.get(name).map(String::as_str)
    }
}

pub(crate) fn parse_form(headers: &HeaderMap, body: &[u8]) -> Form {
    let content_type = headers
        .get(header::CONTENT_TYPE)
        .and_then(|v| v.to_str().ok())
        .unwrap_or_default();
    let mime = content_type
        .split(';')
        .next()
        .unwrap_or_default()
        .trim()
        .to_ascii_lowercase();
    let mut form = Form::default();
    if mime == "application/x-www-form-urlencoded" {
        for (key, value) in form_urlencoded::parse(body) {
            form.fields
                .entry(key.into_owned())
                .or_insert_with(|| value.into_owned());
        }
    } else if mime == "multipart/form-data" {
        if let Some(boundary) = content_type
            .split(';')
            .filter_map(|p| p.trim().strip_prefix("boundary="))
            .next()
        {
            parse_multipart(&mut form, body, boundary.trim_matches('"'));
        }
    }
    form
}

fn find(haystack: &[u8], needle: &[u8], from: usize) -> Option<usize> {
    if needle.is_empty() {
        return None;
    }
    let tail = haystack.get(from..)?;
    tail.windows(needle.len())
        .position(|window| window == needle)
        .map(|offset| from + offset)
}

fn parse_multipart(form: &mut Form, body: &[u8], boundary: &str) {
    let delimiter = format!("--{boundary}");
    let delimiter = delimiter.as_bytes();
    let Some(mut pos) = find(body, delimiter, 0) else {
        return;
    };
    loop {
        pos += delimiter.len();
        if body.get(pos..pos + 2) == Some(b"--") {
            return;
        }
        let Some(header_end) = find(body, b"\r\n\r\n", pos) else {
            return;
        };
        let head =
            String::from_utf8_lossy(body.get(pos..header_end).unwrap_or_default()).into_owned();
        let content_start = header_end + 4;
        let mut next_delim = Vec::with_capacity(delimiter.len() + 2);
        next_delim.extend_from_slice(b"\r\n");
        next_delim.extend_from_slice(delimiter);
        let Some(content_end) = find(body, &next_delim, content_start) else {
            return;
        };
        let disposition = head
            .lines()
            .find(|l| l.to_ascii_lowercase().starts_with("content-disposition:"))
            .unwrap_or_default();
        let param = |key: &str| {
            disposition.split(';').find_map(|p| {
                let (k, v) = p.trim().split_once('=')?;
                (k.trim().eq_ignore_ascii_case(key)).then(|| v.trim().trim_matches('"').to_owned())
            })
        };
        if let Some(name) = param("name") {
            if param("filename").is_some() {
                form.files += 1;
            } else {
                let value = String::from_utf8_lossy(
                    body.get(content_start..content_end).unwrap_or_default(),
                );
                form.fields
                    .entry(name)
                    .or_insert_with(|| value.into_owned());
            }
        }
        pos = content_end + 2;
    }
}

/// Pydantic's lax `bool` from a form string.
fn form_bool(value: Option<&str>) -> Result<bool, ()> {
    match value.map(|v| v.trim().to_ascii_lowercase()) {
        None => Ok(false),
        Some(v) if ["1", "on", "t", "true", "y", "yes"].contains(&v.as_str()) => Ok(true),
        Some(v) if ["0", "off", "f", "false", "n", "no"].contains(&v.as_str()) => Ok(false),
        Some(_) => Err(()),
    }
}

/// `normalize_mode` without raising: the canonical mode, or the input itself.
fn normalize_mode(mode: &str) -> Option<String> {
    let normalized = mode.trim().to_lowercase();
    match normalized.as_str() {
        "normal" | "forge" | "work" => Some("work".to_owned()),
        "coding" => Some("coding".to_owned()),
        _ => None,
    }
}

/// `ChatForm` after validation.
#[derive(Debug, PartialEq)]
pub(crate) struct ChatForm {
    message: Option<String>,
    session_id: Option<String>,
    interrupt: bool,
    mode: String,
    workspace: Option<String>,
    model: Option<String>,
    thinking_level: Option<String>,
    shell: bool,
    folder_id: Option<String>,
    project_id: Option<String>,
    permission_mode: Option<String>,
}

/// `ChatForm.as_form`: field coercion errors first, then the model validator.
pub(crate) fn validate_form(form: &Form) -> Result<ChatForm, String> {
    let field = |name: &str| form.get(name).map(str::to_owned);
    let mut errors = Vec::new();
    let mut flag = |name: &str| {
        form_bool(form.get(name)).unwrap_or_else(|()| {
            errors.push("Input should be a valid boolean, unable to interpret input".to_owned());
            false
        })
    };
    let interrupt = flag("interrupt");
    let _fast_mode = flag("fast_mode");
    let shell = flag("shell");
    if !errors.is_empty() {
        return Err(errors.join("; "));
    }
    let value_error = |m: &str| format!("Value error, {m}");
    let message = field("message");
    let session_id = field("session_id");
    let truthy = |v: &Option<String>| v.as_deref().is_some_and(|s| !s.is_empty());
    if interrupt && truthy(&message) {
        return Err(value_error("interrupt and message are mutually exclusive."));
    }
    if interrupt && !truthy(&session_id) {
        return Err(value_error("session_id is required when interrupt=true."));
    }
    if !interrupt && !truthy(&message) {
        return Err(value_error("message is required when interrupt=false."));
    }
    if message.as_deref().is_some_and(|m| m.trim().is_empty()) {
        return Err(value_error("message must not be blank."));
    }
    if let Some(delivery) = form.get("delivery") {
        let delivery = delivery.trim().to_lowercase();
        if delivery != "steer" && delivery != "queue" {
            return Err(value_error("delivery must be 'steer' or 'queue'."));
        }
    }
    let mode = normalize_mode(form.get("mode").unwrap_or("work"))
        .ok_or_else(|| value_error("mode must be 'work' or 'coding'"))?;
    let workspace = field("workspace");
    let project_id = field("project_id");
    if mode == "coding" && !truthy(&workspace) && !truthy(&project_id) {
        return Err(value_error(
            "workspace is required when mode='coding' (or name a project_id).",
        ));
    }
    let model = field("model");
    if let Some(m) = model.as_deref().map(str::trim) {
        if !m.is_empty() && !m.contains(':') {
            return Err(value_error("model must use 'provider:model' format."));
        }
    }
    Ok(ChatForm {
        message,
        session_id,
        interrupt,
        mode,
        workspace,
        model,
        thinking_level: field("thinking_level"),
        shell,
        folder_id: field("folder_id"),
        project_id,
        permission_mode: field("permission_mode"),
    })
}

/// `parse_slash_invocation(content).command`.
pub(crate) fn slash_command(content: &str) -> Option<&str> {
    let rest = content.trim().strip_prefix('/')?;
    let end = rest
        .find(|c: char| !(c.is_ascii_alphanumeric() || c == '_' || c == '-'))
        .unwrap_or(rest.len());
    let (command, tail) = rest.split_at(end);
    let ok_tail = tail.is_empty()
        || tail.starts_with(char::is_whitespace)
        || tail
            .strip_prefix(':')
            .map(|t| {
                let sub_end = t
                    .find(|c: char| !(c.is_ascii_alphanumeric() || c == '_' || c == '-'))
                    .unwrap_or(t.len());
                sub_end > 0 && (t.len() == sub_end || t[sub_end..].starts_with(char::is_whitespace))
            })
            .unwrap_or(false);
    (!command.is_empty() && ok_tail).then_some(command)
}

fn not_in_rust(what: &str) -> ApiError {
    unprocessable(format!("{what} not available in the Rust server yet."))
}

/// The 422 for a workspace `workspace.rs` refuses; it says how to allow one.
fn workspace_refused(why: &str) -> ApiError {
    unprocessable(format!(
        "Workspace path is not allowed: it is {why}. {}",
        workspace::ALLOW_HINT
    ))
}

/// The first half of `_normalize_work_workspace_or_422`: expand `~`, require an
/// absolute path and apply the Rust-only allowlist in `workspace.rs`. The path
/// is resolved (`..` and links) and checked before anything is created; nothing
/// is written to disk.
fn resolve_work_workspace(
    requested: &str,
    home: &std::path::Path,
    allowed: &workspace::Allowed,
) -> Result<PathBuf, ApiError> {
    let path = workspace::resolve(requested, home)
        .ok_or_else(|| unprocessable("Workspace path must be absolute."))?;
    match allowed.refusal(&path) {
        Some(why) => Err(workspace_refused(why)),
        None => Ok(path),
    }
}

/// The second half: create the directory and return its resolved path. Runs
/// only once the request is certain to start a turn. The created folder is
/// resolved again and checked once more, and a folder this call created that
/// turns out to be refused is removed (only when empty).
async fn create_work_workspace(
    path: PathBuf,
    allowed: &workspace::Allowed,
) -> Result<String, ApiError> {
    let mut created = Vec::new();
    for ancestor in path.ancestors() {
        if tokio::fs::symlink_metadata(ancestor).await.is_ok() {
            break;
        }
        created.push(ancestor.to_path_buf());
    }
    tokio::fs::create_dir_all(&path)
        .await
        .map_err(|e| unprocessable(format!("Cannot create directory: {e}")))?;
    let resolved = workspace::strip_verbatim(
        tokio::fs::canonicalize(&path)
            .await
            .unwrap_or_else(|_| path.clone()),
    );
    if let Some(why) = allowed.refusal(&resolved) {
        for folder in created {
            // Not empty or not ours to remove: leave it.
            if tokio::fs::remove_dir(&folder).await.is_err() {
                break;
            }
        }
        return Err(workspace_refused(why));
    }
    Ok(resolved.to_string_lossy().into_owned())
}

pub(crate) async fn team_chat(
    State(state): State<Arc<ChatState>>,
    headers: HeaderMap,
    body: Bytes,
) -> Result<Response, ApiError> {
    let raw = parse_form(&headers, &body);
    let form = validate_form(&raw).map_err(unprocessable)?;
    let model_provided = raw.get("model").is_some();
    let thinking_provided = raw.get("thinking_level").is_some();
    let model = form
        .model
        .as_deref()
        .map(str::trim)
        .filter(|m| !m.is_empty())
        .map(str::to_owned);
    let thinking_level = form
        .thinking_level
        .as_deref()
        .map(str::trim)
        .filter(|t| !t.is_empty())
        .map(str::to_owned);
    if let Some(model) = &model {
        let settings = crate::agent::turn_settings(&state.settings).await;
        if evoflux_area_providers::factory::resolve(&settings, model, std::time::SystemTime::now())
            .is_err()
        {
            return Err(unprocessable("Choose a model from the registry."));
        }
    }
    let db = state
        .db
        .clone()
        .ok_or_else(|| err(StatusCode::SERVICE_UNAVAILABLE, "database_unavailable"))?;

    let mut session_hex = None;
    let mut existing: Option<SessionRow> = None;
    if let Some(raw_id) = form.session_id.as_deref().filter(|s| !s.is_empty()) {
        let hex = store::parse_uuid(raw_id).ok_or_else(|| unprocessable("Invalid session id."))?;
        let lookup = hex.clone();
        existing = db
            .read(move |conn| store::get_session(conn, &lookup))
            .await
            .map_err(db_error)?;
        session_hex = Some(hex);
    }

    let mut folder_hex = None;
    if existing.is_none() {
        if let Some(raw_folder) = form.folder_id.as_deref().filter(|s| !s.is_empty()) {
            folder_hex = Some(
                store::parse_uuid(raw_folder).ok_or_else(|| unprocessable("Invalid folder_id."))?,
            );
        }
        if let Some(raw_project) = form.project_id.as_deref().filter(|s| !s.is_empty()) {
            store::parse_uuid(raw_project).ok_or_else(|| unprocessable("Invalid project_id."))?;
        }
        if let Some(folder) = folder_hex.clone() {
            let mode = db
                .read(move |conn| store::folder_mode(conn, &folder))
                .await
                .map_err(db_error)?
                .ok_or_else(|| err(StatusCode::NOT_FOUND, "Folder not found."))?;
            if normalize_mode(&mode).as_deref().unwrap_or(mode.as_str()) != form.mode {
                return Err(unprocessable(
                    "Folder belongs to a different mode than the session.",
                ));
            }
        }
    }

    let mode = match &existing {
        Some(row) => normalize_mode(&row.mode).ok_or_else(|| {
            err(
                StatusCode::CONFLICT,
                format!("Session has unsupported persisted mode: {}", row.mode),
            )
        })?,
        None => form.mode.clone(),
    };
    if mode == "coding" {
        return Err(not_in_rust("Coding sessions are"));
    }
    let (mut workspace, new_workspace) = match &existing {
        Some(row) => (row.workspace.clone(), None),
        None => match form.workspace.as_deref() {
            Some(ws) => (
                None,
                Some(resolve_work_workspace(
                    ws,
                    &state.settings.home_dir,
                    &state.workspaces,
                )?),
            ),
            None => (None, None),
        },
    };
    let permission_mode = match (&existing, form.permission_mode.as_deref()) {
        (Some(row), _) => row.permission_mode.clone(),
        (None, None) => "auto".to_owned(),
        (None, Some(m)) if ["ask", "auto", "bypass"].contains(&m) => m.to_owned(),
        (None, Some(m)) => return Err(unprocessable(format!("Unknown permission_mode '{m}'."))),
    };
    if existing
        .as_ref()
        .and_then(|r| r.revert.as_ref())
        .is_some_and(store::truthy)
    {
        return Err(err(
            StatusCode::CONFLICT,
            "Sessions with an undo boundary are not available in the Rust server yet.",
        ));
    }

    let sid_hex = session_hex.unwrap_or_else(store::uuid7_hex);
    let sid = store::dashed(&sid_hex);
    if form.interrupt {
        state.interrupt(&sid);
        return Ok(Json(json!({"status": "interrupted", "session_id": sid})).into_response());
    }
    let message = form.message.clone().unwrap_or_default();
    match slash_command(&message) {
        Some("loop") => {
            return Err(err(
                StatusCode::GONE,
                "/loop has been removed. Use /goal <objective> instead.",
            ))
        }
        Some("goal") => return Err(not_in_rust("/goal is")),
        _ => {}
    }
    if form.shell {
        if raw.files > 0 {
            return Err(unprocessable("Shell commands cannot include file uploads."));
        }
        let command = message.trim();
        let command = command.strip_prefix('!').map_or(command, str::trim);
        if command.is_empty() {
            return Err(unprocessable("Shell command is required."));
        }
        return Err(not_in_rust("Shell commands are"));
    }
    if raw.files > 0 {
        return Err(not_in_rust("File uploads are"));
    }

    let requested_lead = existing.as_ref().and_then(|r| r.agent_name.clone());
    let lead = select_lead(
        work_leads(&state.settings.config_dir).await,
        requested_lead.as_deref(),
    )
    .ok_or_else(|| err(StatusCode::NOT_FOUND, "No work lead agents are configured."))?;

    if !state.begin_turn(&sid) {
        return Err(err(
            StatusCode::CONFLICT,
            "A turn is already running for this session; queued messages are not available in the Rust server yet.",
        ));
    }
    if let Some(path) = new_workspace {
        match create_work_workspace(path, &state.workspaces).await {
            Ok(created) => workspace = Some(created),
            Err(error) => {
                state.finish_turn(&sid);
                return Err(error);
            }
        }
    }
    if existing.is_none() {
        let new = NewSession {
            id: sid_hex.clone(),
            title: message.chars().take(100).collect(),
            agent_name: lead.name.clone(),
            workspace: workspace.clone(),
            folder_id: folder_hex,
            permission_mode,
            now: store::now_db(),
        };
        if let Err(error) = db.write(move |tx| store::ensure_session(tx, &new)).await {
            state.finish_turn(&sid);
            return Err(db_error(error));
        }
    }
    state.store.init_turn(&sid, false);
    state.store.push(
        &sid,
        "agent_status",
        &json!({"type": "agent_status", "agent": lead.name, "status": "working", "metadata": {"phase": "ingress"}}),
    );
    let cancel = state.cancel_token(&sid);
    let input = TurnInput {
        sid_hex,
        sid: sid.clone(),
        content: message,
        lead,
        model: model_provided.then_some(model),
        thinking_level: thinking_provided.then_some(thinking_level),
        workspace,
        cancel,
    };
    tokio::spawn(turn::run(state.clone(), input));
    tracing::info!(session_id = %sid, "team_chat_received");
    Ok((
        StatusCode::ACCEPTED,
        Json(json!({"status": "accepted", "session_id": sid})),
    )
        .into_response())
}

fn sse_frame(frame: &Frame) -> Bytes {
    Bytes::from(format!(
        "event: {}\r\ndata: {}\r\n\r\n",
        frame.event, frame.data
    ))
}

pub(crate) async fn team_stream(
    State(state): State<Arc<ChatState>>,
    Path(session_id): Path<String>,
) -> Response {
    let attached = state.store.attach(&session_id);
    let body = match attached {
        None => Body::empty(),
        Some((replay, rx)) => {
            let replay = stream::iter(
                replay
                    .into_iter()
                    .map(|f| Ok::<_, Infallible>(sse_frame(&f))),
            );
            let live = stream::unfold(rx, |mut rx| async move {
                match tokio::time::timeout(PING_INTERVAL, rx.recv()).await {
                    Ok(Some(frame)) => Some((Ok(sse_frame(&frame)), rx)),
                    Ok(None) => None,
                    Err(_) => {
                        let ping = format!(
                            ": ping - {}\r\n\r\n",
                            chrono::Utc::now().format("%Y-%m-%d %H:%M:%S%.6f%:z")
                        );
                        Some((Ok(Bytes::from(ping)), rx))
                    }
                }
            });
            Body::from_stream(futures_util::StreamExt::chain(replay, live))
        }
    };
    let mut response = Response::new(body);
    let h = response.headers_mut();
    h.insert(header::CACHE_CONTROL, HeaderValue::from_static("no-store"));
    h.insert(header::CONNECTION, HeaderValue::from_static("keep-alive"));
    h.insert("x-accel-buffering", HeaderValue::from_static("no"));
    h.insert(
        header::CONTENT_TYPE,
        HeaderValue::from_static("text/event-stream; charset=utf-8"),
    );
    response
}

/// FastAPI's 422 body for a path parameter that is not a UUID.
fn uuid_path_error(value: &str) -> Response {
    let msg = uuid_parse_reason(value);
    let body = json!({"detail": [{
        "type": "uuid_parsing",
        "loc": ["path", "session_id"],
        "msg": format!("Input should be a valid UUID, {msg}"),
        "input": value,
        "ctx": {"error": msg},
    }]});
    (StatusCode::UNPROCESSABLE_ENTITY, Json(body)).into_response()
}

/// The `uuid` crate's parse error text that Pydantic reports.
fn uuid_parse_reason(value: &str) -> String {
    let expected = "expected one of [0-9a-fA-F-]";
    for (i, c) in value.chars().enumerate() {
        if !(c.is_ascii_hexdigit() || c == '-') {
            return format!("invalid character: found `{c}` at {}", i + 1);
        }
        let _ = expected;
    }
    let groups: Vec<&str> = value.split('-').collect();
    if groups.len() == 1 {
        return format!(
            "invalid length: expected length 32 for simple format, found {}",
            value.len()
        );
    }
    format!("invalid group count: expected 5, found {}", groups.len())
}

fn message_json(m: &MessageRow) -> Value {
    let mut out = Map::new();
    out.insert("id".into(), json!(store::dashed(&m.id)));
    out.insert("session_id".into(), json!(store::dashed(&m.session_id)));
    out.insert("role".into(), json!(m.role));
    let extra = m.extra.as_ref();
    let continuation = extra
        .and_then(|e| e.get("is_continuation"))
        .is_some_and(store::truthy);
    let reasoning = if continuation {
        None
    } else {
        m.reasoning_content.clone()
    };
    for (key, value) in [
        ("content", m.content.clone().map(Value::String)),
        ("reasoning_content", reasoning.map(Value::String)),
        ("tool_calls", m.tool_calls.clone()),
        ("tool_call_id", m.tool_call_id.clone().map(Value::String)),
        ("name", m.name.clone().map(Value::String)),
    ] {
        if let Some(value) = value {
            out.insert(key.into(), value);
        }
    }
    out.insert("is_summary".into(), json!(m.is_summary));
    out.insert("exclude_from_context".into(), json!(m.exclude_from_context));
    if let Some(extra) = extra {
        out.insert("extra".into(), extra.clone());
    }
    out.insert("created_at".into(), json!(store::api_ts(&m.created_at)));
    let attachments = extra
        .and_then(|e| e.get("attachments"))
        .and_then(Value::as_array);
    if let Some(list) = attachments {
        let cleaned: Vec<Value> = list
            .iter()
            .map(|att| match att {
                Value::Object(map) => Value::Object(
                    map.iter()
                        .filter(|(k, _)| {
                            !["converted_text", "path", "workspace_path", "delivery"]
                                .contains(&k.as_str())
                        })
                        .map(|(k, v)| (k.clone(), v.clone()))
                        .collect(),
                ),
                other => other.clone(),
            })
            .collect();
        out.insert("attachments".into(), Value::Array(cleaned));
    }
    out.insert("file_message".into(), json!(attachments.is_some()));
    Value::Object(out)
}

fn session_json(s: &SessionRow, running: bool) -> Map<String, Value> {
    let mut out = Map::new();
    let opt = |v: &Option<String>| v.clone().map(Value::String);
    let mode = normalize_mode(&s.mode).unwrap_or_else(|| s.mode.clone());
    for (key, value) in [
        ("id", Some(json!(store::dashed(&s.id)))),
        ("title", opt(&s.title)),
        ("agent_name", opt(&s.agent_name)),
        ("scheduled_task_name", opt(&s.scheduled_task_name)),
        ("mode", Some(json!(mode))),
        ("workspace", opt(&s.workspace)),
        (
            "project_id",
            s.project_id.as_deref().map(|p| json!(store::dashed(p))),
        ),
        (
            "folder_id",
            s.folder_id.as_deref().map(|p| json!(store::dashed(p))),
        ),
        ("permission_mode", Some(json!(s.permission_mode))),
        ("model", opt(&s.model)),
        ("thinking_level", opt(&s.thinking_level)),
        ("revert", s.revert.clone()),
        ("tags", Some(s.tags.clone().unwrap_or_else(|| json!([])))),
        ("running", Some(json!(running))),
        ("source", opt(&s.source)),
        (
            "imported_at",
            s.imported_at.as_deref().map(|t| json!(store::api_ts(t))),
        ),
        ("created_at", Some(json!(store::api_ts(&s.created_at)))),
        ("updated_at", Some(json!(store::api_ts(&s.updated_at)))),
    ] {
        if let Some(value) = value {
            out.insert(key.into(), value);
        }
    }
    out
}

pub(crate) async fn team_history(
    State(state): State<Arc<ChatState>>,
    Path(session_id): Path<String>,
    Query(query): Query<HashMap<String, String>>,
) -> Result<Response, ApiError> {
    let Some(hex) = store::parse_uuid(&session_id) else {
        return Ok(uuid_path_error(&session_id));
    };
    let before = query.get("before").cloned();
    let cursor = match &before {
        None => None,
        Some(raw) => {
            let invalid = || unprocessable(format!("Invalid before cursor: {raw}"));
            let (ts, id) = match raw.rsplit_once('|') {
                Some((ts, id)) => (ts, Some(store::parse_uuid(id).ok_or_else(invalid)?)),
                None => (raw.as_str(), None),
            };
            Some((store::cursor_ts(ts).ok_or_else(invalid)?, id))
        }
    };
    let db = state
        .db
        .clone()
        .ok_or_else(|| err(StatusCode::SERVICE_UNAVAILABLE, "database_unavailable"))?;
    let history = db
        .read(move |conn| store::history(conn, &hex, cursor))
        .await
        .map_err(db_error)?
        .ok_or_else(|| err(StatusCode::NOT_FOUND, "Lead session not found."))?;
    let running = state.store.is_running(&store::dashed(&history.lead.id));
    let mut lead = session_json(&history.lead, running);
    lead.insert(
        "messages".into(),
        Value::Array(history.lead_messages.iter().map(message_json).collect()),
    );
    let members: Vec<Value> = history
        .members
        .iter()
        .map(|(session, messages)| {
            json!({
                "name": session.agent_name.clone().unwrap_or_else(|| store::dashed(&session.id)),
                "session_id": store::dashed(&session.id),
                "messages": messages.iter().map(message_json).collect::<Vec<_>>(),
            })
        })
        .collect();
    Ok(Json(json!({
        "lead": Value::Object(lead),
        "members": members,
        "goal": history.goal,
        "has_more": history.has_more,
        "next_cursor": history.next_cursor,
    }))
    .into_response())
}

#[cfg(test)]
mod more_tests;

#[cfg(test)]
#[allow(
    clippy::unwrap_used,
    clippy::indexing_slicing,
    clippy::disallowed_methods
)]
mod tests {
    use super::*;

    fn form(pairs: &[(&str, &str)]) -> Form {
        Form {
            fields: pairs
                .iter()
                .map(|(k, v)| ((*k).into(), (*v).into()))
                .collect(),
            files: 0,
        }
    }

    #[test]
    fn form_validation_follows_chat_form() {
        let check = |pairs: &[(&str, &str)]| validate_form(&form(pairs)).err();
        assert_eq!(
            check(&[]).unwrap(),
            "Value error, message is required when interrupt=false."
        );
        assert_eq!(
            check(&[("message", "")]).unwrap(),
            "Value error, message is required when interrupt=false."
        );
        assert_eq!(
            check(&[("message", "  ")]).unwrap(),
            "Value error, message must not be blank."
        );
        assert_eq!(
            check(&[("message", "x"), ("interrupt", "true")]).unwrap(),
            "Value error, interrupt and message are mutually exclusive."
        );
        assert_eq!(
            check(&[("interrupt", "yes")]).unwrap(),
            "Value error, session_id is required when interrupt=true."
        );
        assert_eq!(
            check(&[("message", "x"), ("interrupt", "maybe")]).unwrap(),
            "Input should be a valid boolean, unable to interpret input"
        );
        assert_eq!(
            check(&[("message", "x"), ("delivery", "later")]).unwrap(),
            "Value error, delivery must be 'steer' or 'queue'."
        );
        assert_eq!(
            check(&[("message", "x"), ("mode", "other")]).unwrap(),
            "Value error, mode must be 'work' or 'coding'"
        );
        assert_eq!(
            check(&[("message", "x"), ("mode", "coding")]).unwrap(),
            "Value error, workspace is required when mode='coding' (or name a project_id)."
        );
        assert_eq!(
            check(&[("message", "x"), ("model", "gpt")]).unwrap(),
            "Value error, model must use 'provider:model' format."
        );
        let ok = validate_form(&form(&[
            ("message", "x"),
            ("mode", " Forge "),
            ("delivery", " QUEUE "),
            ("model", "  "),
            ("shell", "off"),
            ("interrupt", "0"),
        ]))
        .unwrap();
        assert_eq!(ok.mode, "work");
        assert!(!ok.shell && !ok.interrupt);
        let interrupt = validate_form(&form(&[("interrupt", "on"), ("session_id", "s")])).unwrap();
        assert!(interrupt.interrupt);
        assert!(validate_form(&form(&[
            ("message", "x"),
            ("mode", "coding"),
            ("project_id", "p")
        ]))
        .is_ok());
    }

    #[test]
    fn parses_urlencoded_and_multipart_forms() {
        let mut headers = HeaderMap::new();
        headers.insert(
            header::CONTENT_TYPE,
            HeaderValue::from_static("application/x-www-form-urlencoded"),
        );
        let f = parse_form(&headers, b"message=say+hello%21&model=&message=second");
        assert_eq!(f.get("message"), Some("say hello!"));
        assert_eq!(f.get("model"), Some(""));
        let body = b"--XyZ\r\nContent-Disposition: form-data; name=\"message\"\r\n\r\nline1\r\nline2\r\n--XyZ\r\nContent-Disposition: form-data; name=\"files\"; filename=\"a.txt\"\r\nContent-Type: text/plain\r\n\r\nfile\r\n--XyZ\r\ncontent-disposition: form-data; name=mode\r\n\r\nwork\r\n--XyZ--\r\n";
        headers.insert(
            header::CONTENT_TYPE,
            HeaderValue::from_static("multipart/form-data; boundary=\"XyZ\""),
        );
        let f = parse_form(&headers, body);
        assert_eq!(f.get("message"), Some("line1\r\nline2"));
        assert_eq!(f.get("mode"), Some("work"));
        assert_eq!(f.files, 1);
        headers.insert(
            header::CONTENT_TYPE,
            HeaderValue::from_static("application/json"),
        );
        assert_eq!(
            parse_form(&headers, b"{\"message\": \"x\"}"),
            Form::default()
        );
        headers.insert(
            header::CONTENT_TYPE,
            HeaderValue::from_static("multipart/form-data; boundary=Q"),
        );
        assert_eq!(parse_form(&headers, b"garbage"), Form::default());
        assert_eq!(parse_form(&headers, b"--Q\r\nbroken"), Form::default());
    }

    #[test]
    fn slash_commands_parse_like_python() {
        assert_eq!(slash_command("/loop every 5m"), Some("loop"));
        assert_eq!(slash_command("  /goal:pause "), Some("goal"));
        assert_eq!(slash_command("/goal"), Some("goal"));
        assert_eq!(slash_command("/goal:"), None);
        assert_eq!(slash_command("/goal!x"), None);
        assert_eq!(slash_command("/"), None);
        assert_eq!(slash_command("hello /goal"), None);
        assert_eq!(slash_command("/a-b_c\nmore"), Some("a-b_c"));
    }

    #[test]
    fn uuid_errors_name_the_first_bad_character() {
        assert_eq!(
            uuid_parse_reason("not-a-uuid"),
            "invalid character: found `n` at 1"
        );
        assert_eq!(
            uuid_parse_reason("abc"),
            "invalid length: expected length 32 for simple format, found 3"
        );
    }

    #[test]
    fn message_json_drops_nulls_and_internal_attachment_fields() {
        let row = MessageRow {
            id: "06ae6ab0833f7bd68000744dcbeedc81".into(),
            session_id: "06ae6ab0636d720e8000b0d548016ce8".into(),
            role: "user".into(),
            content: Some("hi".into()),
            reasoning_content: Some("r".into()),
            extra: Some(
                json!({"is_continuation": true, "attachments": [{"filename": "a", "path": "/x", "delivery": "native"}]}),
            ),
            created_at: "2026-11-01 02:59:20.203061".into(),
            ..MessageRow::default()
        };
        assert_eq!(
            serde_json::to_string(&message_json(&row)).unwrap(),
            r#"{"id":"06ae6ab0-833f-7bd6-8000-744dcbeedc81","session_id":"06ae6ab0-636d-720e-8000-b0d548016ce8","role":"user","content":"hi","is_summary":false,"exclude_from_context":false,"extra":{"is_continuation":true,"attachments":[{"filename":"a","path":"/x","delivery":"native"}]},"created_at":"2026-11-01T02:59:20.203061Z","attachments":[{"filename":"a"}],"file_message":true}"#
        );
    }

    #[tokio::test]
    async fn work_workspace_must_be_absolute_and_is_created() {
        let dir = tempfile::tempdir().unwrap();
        let config = dir.path().join("config");
        let home = dir.path().join("home");
        let roots = home.join("roots");
        let allowed = allowed(&home, &config, &[roots.clone(), home.join("w")]);
        let resolve = |ws: &str| resolve_work_workspace(ws, &home, &allowed);
        assert!(resolve("relative/dir").is_err());
        let target = roots.join("a").join("b");
        let path = resolve(&target.to_string_lossy()).unwrap();
        assert!(!target.exists());
        let made = create_work_workspace(path, &allowed).await.unwrap();
        assert!(std::path::Path::new(&made).is_dir());
        let w = resolve("~/w").unwrap();
        assert!(create_work_workspace(w, &allowed)
            .await
            .unwrap()
            .ends_with('w'));
    }

    /// The allowlist of these settings: `roots` as `EVOFLUX_WORKSPACE_ROOTS`.
    fn allowed(
        home: &std::path::Path,
        config: &std::path::Path,
        roots: &[PathBuf],
    ) -> workspace::Allowed {
        let vars = std::collections::HashMap::from([
            (
                "EVOFLUX_CONFIG_DIR".to_owned(),
                config.to_string_lossy().into_owned(),
            ),
            (
                "EVOFLUX_WORKSPACE_ROOTS".to_owned(),
                std::env::join_paths(roots)
                    .unwrap()
                    .to_string_lossy()
                    .into_owned(),
            ),
        ]);
        let settings =
            evoflux_core::config::Settings::from_vars(&vars, Some(home), config).unwrap();
        workspace::Allowed::current(&settings)
    }

    async fn chat_state(home: &std::path::Path, config: &std::path::Path) -> Arc<ChatState> {
        let vars = std::collections::HashMap::from([
            (
                "EVOFLUX_CONFIG_DIR".to_owned(),
                config.to_string_lossy().into_owned(),
            ),
            (
                "EVOFLUX_WORKSPACE_ROOTS".to_owned(),
                home.join("ws").to_string_lossy().into_owned(),
            ),
        ]);
        let settings =
            evoflux_core::config::Settings::from_vars(&vars, Some(home), config).unwrap();
        let db =
            evoflux_core::db::Db::open(&config.join("db"), evoflux_core::db::DbOptions::default())
                .unwrap();
        db.write_exclusive(|tx| {
            tx.execute_batch(
                "CREATE TABLE chat_sessions (id, parent_session_id, agent_name, title,                  scheduled_task_name, created_at, updated_at, mode, workspace, revert, model,                  thinking_level, permission_mode, project_id, tags, folder_id, source,                  imported_at)",
            )?;
            Ok(())
        })
        .await
        .unwrap();
        Arc::new(ChatState {
            workspaces: crate::workspace::Allowed::current(&settings),
            settings: Arc::new(settings),
            db: Some(Arc::new(db)),
            store: Arc::new(crate::stream_store::StreamStore::default()),
            http: evoflux_net::build_client().unwrap(),
            active: std::sync::Mutex::new(std::collections::HashMap::new()),
        })
    }

    async fn post_chat(state: &Arc<ChatState>, sid: &str, workspace: &std::path::Path) -> u16 {
        let mut headers = HeaderMap::new();
        headers.insert(
            "content-type",
            "application/x-www-form-urlencoded".parse().unwrap(),
        );
        let body = form_urlencoded::Serializer::new(String::new())
            .append_pair("message", "hi")
            .append_pair("session_id", sid)
            .append_pair("workspace", &workspace.to_string_lossy())
            .finish();
        match team_chat(State(state.clone()), headers, Bytes::from(body)).await {
            Ok(response) => response.status().as_u16(),
            Err(error) => error.into_response().status().as_u16(),
        }
    }

    #[tokio::test]
    async fn the_workspace_is_created_only_after_the_lead_and_409_checks() {
        let config = tempfile::tempdir().unwrap();
        let home = tempfile::tempdir().unwrap();
        let state = chat_state(home.path(), config.path()).await;
        let sid = "06ae6ab0-636d-720e-8000-b0d548016ce8";
        // A root of `EVOFLUX_WORKSPACE_ROOTS` (see `chat_state`).
        let workspace = home.path().join("ws");

        // No lead agent: 404, nothing created.
        assert_eq!(post_chat(&state, sid, &workspace).await, 404);
        assert!(!workspace.exists());

        // A lead exists but a turn is already running: 409, nothing created.
        let agents = config.path().join("agents");
        std::fs::create_dir(&agents).unwrap();
        std::fs::write(
            agents.join("lead.md"),
            "---
role: lead
---
Hi
",
        )
        .unwrap();
        assert!(state.begin_turn(sid));
        assert_eq!(post_chat(&state, sid, &workspace).await, 409);
        assert!(!workspace.exists());
    }

    #[tokio::test]
    async fn restricted_workspaces_get_a_422_and_create_nothing() {
        let dir = tempfile::tempdir().unwrap();
        let home = dir.path().join("home");
        let config = dir.path().join("config");
        std::fs::create_dir_all(&home).unwrap();
        let allowed = allowed(&home, &config, &[home.join("projects")]);
        let root = dir
            .path()
            .ancestors()
            .last()
            .unwrap()
            .to_string_lossy()
            .into_owned();
        for bad in [
            "~".to_owned(),
            "~/".to_owned(),
            root,
            "~/.ssh".to_owned(),
            "~/.ssh/keys/new".to_owned(),
            "~/projects/../.aws".to_owned(),
            config.to_string_lossy().into_owned(),
            dir.path().to_string_lossy().into_owned(),
        ] {
            let error = resolve_work_workspace(&bad, &home, &allowed).unwrap_err();
            assert_eq!(error.status, StatusCode::UNPROCESSABLE_ENTITY, "{bad}");
            assert!(
                error
                    .detail
                    .as_str()
                    .unwrap()
                    .starts_with("Workspace path is not allowed"),
                "{bad}"
            );
            assert!(
                error
                    .detail
                    .as_str()
                    .unwrap()
                    .contains("EVOFLUX_WORKSPACE_ROOTS"),
                "{bad}"
            );
        }
        assert!(!home.join(".ssh").exists());
        assert!(!home.join(".aws").exists());
        let ok = resolve_work_workspace("~/projects/x", &home, &allowed).unwrap();
        let ok = create_work_workspace(ok, &allowed).await.unwrap();
        assert!(std::path::Path::new(&ok).is_dir());
    }

    #[test]
    fn windows_rewritten_names_and_network_paths_are_refused_before_anything_is_created() {
        if !cfg!(windows) {
            return;
        }
        let dir = tempfile::tempdir().unwrap();
        let home = dir.path().join("home");
        let config = dir.path().join("config");
        std::fs::create_dir_all(&home).unwrap();
        let allowed = allowed(&home, &config, &[home.join("projects")]);
        let admin_share = home.to_string_lossy().replacen(':', "$", 1);
        let bad = [
            r"~\.ssh.".to_owned(),
            r"~\.ssh ".to_owned(),
            r"~\.kube::$INDEX_ALLOCATION".to_owned(),
            r"~\.ssh\keys.".to_owned(),
            r"~\ok:stream".to_owned(),
            format!(r"\\localhost\{admin_share}"),
            format!(r"\\127.0.0.1\{admin_share}"),
            format!(r"\\?\UNC\localhost\{admin_share}"),
            r"\\server\share\project".to_owned(),
            r"\\.\COM1".to_owned(),
        ];
        for requested in bad {
            let error = resolve_work_workspace(&requested, &home, &allowed).unwrap_err();
            assert_eq!(
                error.status,
                StatusCode::UNPROCESSABLE_ENTITY,
                "{requested}"
            );
        }
        assert_eq!(std::fs::read_dir(&home).unwrap().count(), 0);
    }

    #[tokio::test]
    async fn a_refused_folder_found_after_creation_is_removed_only_if_this_call_made_it() {
        let dir = tempfile::tempdir().unwrap();
        let home = dir.path().join("home");
        let config = dir.path().join("config");
        std::fs::create_dir_all(&home).unwrap();
        let allowed = allowed(&home, &config, &[home.join(".ssh")]);
        // Skips the pre-check on purpose: only the second check can catch this.
        let made = home.join(".ssh").join("new");
        assert!(create_work_workspace(made, &allowed).await.is_err());
        assert!(!home.join(".ssh").exists());
        // A folder that was already there stays, with what is in it.
        std::fs::create_dir_all(home.join(".aws").join("keep")).unwrap();
        let again = home.join(".aws").join("new");
        assert!(create_work_workspace(again, &allowed).await.is_err());
        assert!(home.join(".aws").join("keep").is_dir());
        assert!(!home.join(".aws").join("new").exists());
    }
}
