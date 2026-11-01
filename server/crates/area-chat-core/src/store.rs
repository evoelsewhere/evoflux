//! Port of the `chat_sessions` / `session_messages` access in
//! app/services/chat_service.py (`save_message`, `get_messages_for_llm`,
//! `get_team_history`) and `goal_service.get_goal`.
//!
//! Rows are written exactly as SQLAlchemy writes them, so Python reads them
//! back unchanged: UUIDs as 32 hex digits, timestamps as naive UTC
//! `YYYY-MM-DD HH:MM:SS.ffffff`, JSON columns as `json.dumps` text (`null`
//! for an empty `extra`, `tool_calls` or `revert`; SQL NULL for empty `tags`)
//! and booleans as 0/1.

use std::sync::atomic::{AtomicU64, Ordering};

use chrono::{DateTime, NaiveDate, NaiveDateTime, Utc};
use evoflux_core::db::{rowid, DbError, Tx};
use rusqlite::{params, Connection, OptionalExtension, Row};
use serde_json::{json, Map, Value};

use crate::pyjson;

/// `_HISTORY_MAX_ROWS`, `_HISTORY_TARGET_BYTES`, `_HISTORY_MIN_ROWS`.
const HISTORY_MAX_ROWS: usize = 160;
const HISTORY_TARGET_BYTES: usize = 192 * 1024;
const HISTORY_MIN_ROWS: usize = 24;

/// The storage format of SQLAlchemy's SQLite `DateTime`.
const DB_TS: &str = "%Y-%m-%d %H:%M:%S%.6f";

/// Now, as stored.
pub(crate) fn now_db() -> String {
    Utc::now().naive_utc().format(DB_TS).to_string()
}

static LAST_UUID7: AtomicU64 = AtomicU64::new(0);

/// `uuid.uuid7()`: 48-bit Unix milliseconds, then a counter that keeps ids
/// made in the same millisecond ascending, then random bits. Returns the
/// stored hex form.
pub(crate) fn uuid7_hex() -> String {
    let ms = u64::try_from(Utc::now().timestamp_millis()).unwrap_or(0) & 0xFFFF_FFFF_FFFF;
    // (ms << 16) | 12-bit counter, kept strictly increasing across calls.
    let mut current = LAST_UUID7.load(Ordering::Relaxed);
    let stamp = loop {
        let candidate = (ms << 16).max(current + 1);
        match LAST_UUID7.compare_exchange(current, candidate, Ordering::Relaxed, Ordering::Relaxed)
        {
            Ok(_) => break candidate,
            Err(seen) => current = seen,
        }
    };
    let ts = stamp >> 16;
    let counter = stamp & 0x0FFF;
    let rand_a = fastrand::u64(..) & 0x3FFF_FFFF_FFFF_FFFF;
    let hi = (ts << 16) | 0x7000 | counter;
    let lo = 0x8000_0000_0000_0000 | rand_a;
    format!("{hi:016x}{lo:016x}")
}

/// `UUID(hex)` as text with dashes.
pub(crate) fn dashed(hex: &str) -> String {
    match (
        hex.get(0..8),
        hex.get(8..12),
        hex.get(12..16),
        hex.get(16..20),
        hex.get(20..32),
    ) {
        (Some(a), Some(b), Some(c), Some(d), Some(e)) => format!("{a}-{b}-{c}-{d}-{e}"),
        _ => hex.to_owned(),
    }
}

/// Parse a UUID the way Python's `UUID(str)` does for the forms clients send
/// (hex with optional dashes, braces or `urn:uuid:`); returns stored hex.
pub(crate) fn parse_uuid(value: &str) -> Option<String> {
    let mut s = value.trim();
    if let Some(rest) = s.strip_prefix("urn:uuid:") {
        s = rest;
    }
    let s = s.trim_start_matches('{').trim_end_matches('}');
    let hex: String = s.chars().filter(|c| *c != '-').collect();
    (hex.len() == 32 && hex.chars().all(|c| c.is_ascii_hexdigit())).then(|| hex.to_lowercase())
}

/// A stored timestamp as Pydantic serializes the UTC datetime Python reads back.
pub(crate) fn api_ts(stored: &str) -> String {
    match parse_db_ts(stored) {
        Some(ts) if ts.and_utc().timestamp_subsec_micros() == 0 => {
            ts.format("%Y-%m-%dT%H:%M:%SZ").to_string()
        }
        Some(ts) => ts.format("%Y-%m-%dT%H:%M:%S%.6fZ").to_string(),
        None => stored.to_owned(),
    }
}

fn parse_db_ts(stored: &str) -> Option<NaiveDateTime> {
    NaiveDateTime::parse_from_str(stored, "%Y-%m-%d %H:%M:%S%.f").ok()
}

/// `datetime.fromisoformat(value)` bound as a stored timestamp (aware values
/// are converted to UTC, naive ones taken as they are).
pub(crate) fn cursor_ts(value: &str) -> Option<String> {
    let value = value.trim();
    if let Ok(aware) = DateTime::parse_from_rfc3339(&value.replacen(' ', "T", 1)) {
        return Some(
            aware
                .with_timezone(&Utc)
                .naive_utc()
                .format(DB_TS)
                .to_string(),
        );
    }
    for format in [
        "%Y-%m-%dT%H:%M:%S%.f",
        "%Y-%m-%d %H:%M:%S%.f",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d %H:%M",
    ] {
        if let Ok(naive) = NaiveDateTime::parse_from_str(value, format) {
            return Some(naive.format(DB_TS).to_string());
        }
    }
    NaiveDate::parse_from_str(value, "%Y-%m-%d")
        .ok()
        .and_then(|d| d.and_hms_opt(0, 0, 0))
        .map(|naive| naive.format(DB_TS).to_string())
}

fn json_column(value: Option<String>) -> Option<Value> {
    value
        .and_then(|text| serde_json::from_str::<Value>(&text).ok())
        .filter(|v| !v.is_null())
}

/// A `chat_sessions` row.
#[derive(Debug, Clone, Default)]
pub(crate) struct SessionRow {
    pub id: String,
    pub agent_name: Option<String>,
    pub title: Option<String>,
    pub scheduled_task_name: Option<String>,
    pub created_at: String,
    pub updated_at: String,
    pub mode: String,
    pub workspace: Option<String>,
    pub revert: Option<Value>,
    pub model: Option<String>,
    pub thinking_level: Option<String>,
    pub permission_mode: String,
    pub project_id: Option<String>,
    pub tags: Option<Value>,
    pub folder_id: Option<String>,
    pub source: Option<String>,
    pub imported_at: Option<String>,
}

const SESSION_COLUMNS: &str = "id, parent_session_id, agent_name, title, scheduled_task_name, \
     created_at, updated_at, mode, workspace, revert, model, thinking_level, permission_mode, \
     project_id, tags, folder_id, source, imported_at";

fn session_from_row(row: &Row<'_>) -> rusqlite::Result<SessionRow> {
    Ok(SessionRow {
        id: row.get(0)?,
        agent_name: row.get(2)?,
        title: row.get(3)?,
        scheduled_task_name: row.get(4)?,
        created_at: row.get(5)?,
        updated_at: row.get(6)?,
        mode: row.get(7)?,
        workspace: row.get(8)?,
        revert: json_column(row.get(9)?),
        model: row.get(10)?,
        thinking_level: row.get(11)?,
        permission_mode: row.get(12)?,
        project_id: row.get(13)?,
        tags: json_column(row.get(14)?),
        folder_id: row.get(15)?,
        source: row.get(16)?,
        imported_at: row.get(17)?,
    })
}

pub(crate) fn get_session(conn: &Connection, id: &str) -> Result<Option<SessionRow>, DbError> {
    let sql = format!("SELECT {SESSION_COLUMNS} FROM chat_sessions WHERE id = ?1");
    Ok(conn.query_row(&sql, [id], session_from_row).optional()?)
}

fn child_sessions(conn: &Connection, id: &str) -> Result<Vec<SessionRow>, DbError> {
    let sql = format!(
        "SELECT {SESSION_COLUMNS} FROM chat_sessions WHERE parent_session_id = ?1 ORDER BY created_at ASC"
    );
    let mut stmt = conn.prepare(&sql)?;
    let rows = stmt.query_map([id], session_from_row)?;
    Ok(rows.collect::<Result<_, _>>()?)
}

/// `session_folders.mode` of a folder, or `None` when it does not exist.
pub(crate) fn folder_mode(conn: &Connection, id: &str) -> Result<Option<String>, DbError> {
    Ok(conn
        .query_row(
            "SELECT mode FROM session_folders WHERE id = ?1",
            [id],
            |r| r.get(0),
        )
        .optional()?)
}

/// The fields of a `ChatSession` the first message creates (`_ensure_db_session`).
#[derive(Debug, Clone)]
pub(crate) struct NewSession {
    pub id: String,
    pub title: String,
    pub agent_name: String,
    pub workspace: Option<String>,
    pub folder_id: Option<String>,
    pub permission_mode: String,
    pub now: String,
}

/// Insert the session unless it exists, as `_ensure_db_session` does.
pub(crate) fn ensure_session(tx: &Tx<'_>, s: &NewSession) -> Result<(), DbError> {
    if get_session(tx, &s.id)?.is_some() {
        return Ok(());
    }
    rowid::insert(
        tx,
        "chat_sessions",
        &[
            "id",
            "parent_session_id",
            "agent_name",
            "title",
            "scheduled_task_name",
            "created_at",
            "updated_at",
            "mode",
            "workspace",
            "revert",
            "model",
            "thinking_level",
            "permission_mode",
            "project_id",
            "tags",
            "session_type",
            "source_session_id",
            "source_session_ref",
            "folder_id",
            "source",
            "imported_at",
            "source_item_id",
        ],
        &[
            &s.id,
            &None::<String>,
            &s.agent_name,
            &s.title,
            &None::<String>,
            &s.now,
            &s.now,
            &"work",
            &s.workspace,
            &"null",
            &None::<String>,
            &None::<String>,
            &s.permission_mode,
            &None::<String>,
            &None::<String>,
            &"main",
            &None::<String>,
            &None::<String>,
            &s.folder_id,
            &None::<String>,
            &None::<String>,
            &None::<String>,
        ],
    )
}

/// The lead-row update of `handle_user_message`: mode and workspace, plus
/// the model and thinking level when the request named them.
pub(crate) fn touch_session_for_turn(
    tx: &Tx<'_>,
    id: &str,
    workspace: Option<&str>,
    model: Option<Option<&str>>,
    thinking_level: Option<Option<&str>>,
    now: &str,
) -> Result<(), DbError> {
    tx.execute(
        "UPDATE chat_sessions SET mode = 'work', workspace = ?2, updated_at = ?3 WHERE id = ?1",
        params![id, workspace, now],
    )?;
    if let Some(model) = model {
        tx.execute(
            "UPDATE chat_sessions SET model = ?2 WHERE id = ?1",
            params![id, model],
        )?;
    }
    if let Some(level) = thinking_level {
        tx.execute(
            "UPDATE chat_sessions SET thinking_level = ?2 WHERE id = ?1",
            params![id, level],
        )?;
    }
    Ok(())
}

/// A `session_messages` row.
#[derive(Debug, Clone, Default, PartialEq)]
pub(crate) struct MessageRow {
    pub id: String,
    pub session_id: String,
    pub role: String,
    pub content: Option<String>,
    pub reasoning_content: Option<String>,
    pub tool_calls: Option<Value>,
    pub tool_call_id: Option<String>,
    pub name: Option<String>,
    pub extra: Option<Value>,
    pub is_summary: bool,
    pub exclude_from_context: bool,
    pub created_at: String,
}

const MESSAGE_COLUMNS: &str = "id, session_id, role, content, reasoning_content, tool_calls, \
     tool_call_id, name, extra, is_summary, exclude_from_context, created_at";

fn message_from_row(row: &Row<'_>) -> rusqlite::Result<MessageRow> {
    Ok(MessageRow {
        id: row.get(0)?,
        session_id: row.get(1)?,
        role: row.get(2)?,
        content: row.get(3)?,
        reasoning_content: row.get(4)?,
        tool_calls: json_column(row.get(5)?),
        tool_call_id: row.get(6)?,
        name: row.get(7)?,
        extra: json_column(row.get(8)?),
        is_summary: row.get(9)?,
        exclude_from_context: row.get(10)?,
        created_at: row.get(11)?,
    })
}

fn json_text(value: Option<&Value>) -> String {
    value.map_or_else(|| "null".to_owned(), pyjson::dumps)
}

/// `save_message`.
pub(crate) fn insert_message(tx: &Tx<'_>, m: &MessageRow) -> Result<(), DbError> {
    rowid::insert(
        tx,
        "session_messages",
        &[
            "id",
            "session_id",
            "role",
            "content",
            "reasoning_content",
            "tool_calls",
            "tool_call_id",
            "name",
            "extra",
            "is_summary",
            "exclude_from_context",
            "created_at",
        ],
        &[
            &m.id,
            &m.session_id,
            &m.role,
            &m.content,
            &m.reasoning_content,
            &json_text(m.tool_calls.as_ref()),
            &m.tool_call_id,
            &m.name,
            &json_text(m.extra.as_ref()),
            &m.is_summary,
            &m.exclude_from_context,
            &m.created_at,
        ],
    )
}

/// Replace a message's `extra` (the turn total stamped on the last reply).
pub(crate) fn update_message_extra(tx: &Tx<'_>, id: &str, extra: &Value) -> Result<(), DbError> {
    tx.execute(
        "UPDATE session_messages SET extra = ?2 WHERE id = ?1",
        params![id, pyjson::dumps(extra)],
    )?;
    Ok(())
}

/// `persist_turn_usage_snapshot`: a late turn total on the newest reply.
pub(crate) fn stamp_latest_assistant(
    tx: &Tx<'_>,
    session_id: &str,
    snapshot: &Value,
) -> Result<bool, DbError> {
    let sql = format!(
        "SELECT {MESSAGE_COLUMNS} FROM session_messages WHERE session_id = ?1 \
         AND role = 'assistant' AND NOT is_summary ORDER BY created_at DESC, id DESC LIMIT 1"
    );
    let Some(row) = tx
        .query_row(&sql, [session_id], message_from_row)
        .optional()?
    else {
        return Ok(false);
    };
    let mut extra = match row.extra {
        Some(Value::Object(map)) => map,
        _ => Map::new(),
    };
    extra.insert("turn_usage".into(), snapshot.clone());
    update_message_extra(tx, &row.id, &Value::Object(extra))?;
    Ok(true)
}

/// The title update of `generate_and_save_title`; `updated_at` follows, as
/// the column's `onupdate` does. False when the session is gone.
pub(crate) fn set_title(
    tx: &Tx<'_>,
    session_id: &str,
    title: &str,
    now: &str,
) -> Result<bool, DbError> {
    let changed = tx.execute(
        "UPDATE chat_sessions SET title = ?2, updated_at = ?3 WHERE id = ?1",
        params![session_id, title, now],
    )?;
    Ok(changed > 0)
}

/// `get_messages_for_llm` without a revert boundary: the latest visible
/// summary, then every other visible non-summary row, oldest first.
pub(crate) fn llm_rows(conn: &Connection, session_id: &str) -> Result<Vec<MessageRow>, DbError> {
    let summary_sql = format!(
        "SELECT {MESSAGE_COLUMNS} FROM session_messages WHERE session_id = ?1 AND is_summary \
         AND NOT exclude_from_context ORDER BY created_at DESC, id DESC LIMIT 1"
    );
    let summary = conn
        .query_row(&summary_sql, [session_id], message_from_row)
        .optional()?;
    let filter = if summary.is_some() {
        " AND NOT is_summary"
    } else {
        ""
    };
    let sql = format!(
        "SELECT {MESSAGE_COLUMNS} FROM session_messages WHERE session_id = ?1 \
         AND NOT exclude_from_context{filter} ORDER BY created_at ASC, id ASC"
    );
    let mut stmt = conn.prepare(&sql)?;
    let rest = stmt
        .query_map([session_id], message_from_row)?
        .collect::<Result<Vec<_>, _>>()?;
    Ok(summary.into_iter().chain(rest).collect())
}

/// `_history_row_weight`.
fn row_weight(row: &MessageRow) -> usize {
    let mut total = 256;
    for value in [
        &row.content,
        &row.reasoning_content,
        &row.tool_call_id,
        &row.name,
    ]
    .into_iter()
    .flatten()
    {
        total += value.len();
    }
    for value in [&row.tool_calls, &row.extra].into_iter().flatten() {
        total += serde_json::to_string(value).map_or(0, |s| s.len());
    }
    total
}

/// `_bounded_history_page`.
fn bounded_page(rows: &[MessageRow]) -> Vec<MessageRow> {
    let mut page = Vec::new();
    let mut weight = 0;
    for row in rows.iter().take(HISTORY_MAX_ROWS) {
        let w = row_weight(row);
        if page.len() >= HISTORY_MIN_ROWS && weight + w > HISTORY_TARGET_BYTES {
            break;
        }
        page.push(row.clone());
        weight += w;
    }
    page
}

fn in_list(n: usize) -> String {
    (1..=n)
        .map(|i| format!("?{i}"))
        .collect::<Vec<_>>()
        .join(", ")
}

/// Rows of `session_ids` strictly before `(at, id)` (or before `at` alone),
/// newest first, at most `limit` when given, and at or after `floor`.
fn rows_before(
    conn: &Connection,
    session_ids: &[String],
    before: Option<(&str, Option<&str>)>,
    floor: Option<(&str, &str)>,
    limit: Option<usize>,
) -> Result<Vec<MessageRow>, DbError> {
    let n = session_ids.len();
    let mut sql = format!(
        "SELECT {MESSAGE_COLUMNS} FROM session_messages WHERE session_id IN ({})",
        in_list(n)
    );
    let mut args: Vec<String> = session_ids.to_vec();
    if let Some((at, id)) = before {
        args.push(at.to_owned());
        let p = args.len();
        match id {
            None => sql.push_str(&format!(" AND created_at < ?{p}")),
            Some(id) => {
                args.push(id.to_owned());
                let q = args.len();
                sql.push_str(&format!(
                    " AND (created_at < ?{p} OR (created_at = ?{p} AND id < ?{q}))"
                ));
            }
        }
    }
    if let Some((at, id)) = floor {
        args.push(at.to_owned());
        args.push(id.to_owned());
        let (p, q) = (args.len() - 1, args.len());
        sql.push_str(&format!(
            " AND (created_at > ?{p} OR (created_at = ?{p} AND id >= ?{q}))"
        ));
    }
    sql.push_str(" ORDER BY created_at DESC, id DESC");
    if let Some(limit) = limit {
        sql.push_str(&format!(" LIMIT {limit}"));
    }
    let mut stmt = conn.prepare(&sql)?;
    let rows = stmt.query_map(rusqlite::params_from_iter(args.iter()), message_from_row)?;
    Ok(rows.collect::<Result<_, _>>()?)
}

/// `_extend_history_page_to_turn_boundaries`.
fn extend_to_turn_boundaries(
    conn: &Connection,
    session_ids: &[String],
    mut page: Vec<MessageRow>,
) -> Result<Vec<MessageRow>, DbError> {
    while let Some(current_oldest) = page.last().cloned() {
        let mut oldest_by_session: Vec<&MessageRow> = Vec::new();
        for row in page.iter().rev() {
            if !oldest_by_session
                .iter()
                .any(|r| r.session_id == row.session_id)
            {
                oldest_by_session.push(row);
            }
        }
        let broken: Vec<&MessageRow> = oldest_by_session
            .into_iter()
            .filter(|r| r.role != "user" && !r.is_summary)
            .collect();
        if broken.is_empty() {
            break;
        }
        let mut anchors: Vec<MessageRow> = Vec::new();
        for row in broken {
            let sql = format!(
                "SELECT {MESSAGE_COLUMNS} FROM session_messages WHERE session_id = ?1 \
                 AND (created_at < ?2 OR (created_at = ?2 AND id < ?3)) \
                 AND (role = 'user' OR is_summary) ORDER BY created_at DESC, id DESC LIMIT 1"
            );
            if let Some(anchor) = conn
                .query_row(
                    &sql,
                    params![row.session_id, row.created_at, row.id],
                    message_from_row,
                )
                .optional()?
            {
                anchors.push(anchor);
            }
        }
        let Some(earliest) = anchors
            .into_iter()
            .min_by(|a, b| (&a.created_at, &a.id).cmp(&(&b.created_at, &b.id)))
        else {
            break;
        };
        let extension = rows_before(
            conn,
            session_ids,
            Some((&current_oldest.created_at, Some(&current_oldest.id))),
            Some((&earliest.created_at, &earliest.id)),
            None,
        )?;
        if extension.is_empty() {
            break;
        }
        page.extend(extension);
    }
    Ok(page)
}

/// `get_team_history` (members and goal included).
pub(crate) struct History {
    pub lead: SessionRow,
    pub lead_messages: Vec<MessageRow>,
    pub members: Vec<(SessionRow, Vec<MessageRow>)>,
    pub goal: Option<Value>,
    pub has_more: bool,
    pub next_cursor: Option<String>,
}

/// `before` already parsed into a stored timestamp and optional message id.
pub(crate) fn history(
    conn: &Connection,
    lead_id: &str,
    before: Option<(String, Option<String>)>,
) -> Result<Option<History>, DbError> {
    let Some(lead) = get_session(conn, lead_id)? else {
        return Ok(None);
    };
    let subs = child_sessions(conn, lead_id)?;
    let mut session_ids = vec![lead_id.to_owned()];
    session_ids.extend(subs.iter().map(|s| s.id.clone()));
    let raw = rows_before(
        conn,
        &session_ids,
        before.as_ref().map(|(at, id)| (at.as_str(), id.as_deref())),
        None,
        Some(HISTORY_MAX_ROWS + 1),
    )?;
    let mut page = bounded_page(&raw);
    let mut has_more = raw.len() > page.len();
    if has_more {
        page = extend_to_turn_boundaries(conn, &session_ids, page)?;
        has_more = match page.last() {
            Some(last) => !rows_before(
                conn,
                &session_ids,
                Some((&last.created_at, Some(&last.id))),
                None,
                Some(1),
            )?
            .is_empty(),
            None => false,
        };
    }
    let visible: Vec<&MessageRow> = page
        .iter()
        .filter(|r| {
            !r.extra
                .as_ref()
                .and_then(|e| e.get("hidden_from_user"))
                .is_some_and(truthy)
        })
        .collect();
    let for_session = |id: &str| -> Vec<MessageRow> {
        visible
            .iter()
            .rev()
            .filter(|r| r.session_id == id)
            .map(|r| (*r).clone())
            .collect()
    };
    let lead_messages = for_session(lead_id);
    let members = subs
        .into_iter()
        .map(|s| {
            let messages = for_session(&s.id);
            (s, messages)
        })
        .collect();
    let next_cursor = match (has_more, page.last()) {
        (true, Some(last)) => Some(format!(
            "{}|{}",
            iso_naive(&last.created_at),
            dashed(&last.id)
        )),
        _ => None,
    };
    let goal = goal(conn, lead_id)?;
    Ok(Some(History {
        lead,
        lead_messages,
        members,
        goal,
        has_more,
        next_cursor,
    }))
}

/// `datetime.isoformat()` of a stored timestamp (naive; no fraction when zero).
fn iso_naive(stored: &str) -> String {
    match parse_db_ts(stored) {
        Some(ts) if ts.and_utc().timestamp_subsec_micros() == 0 => {
            ts.format("%Y-%m-%dT%H:%M:%S").to_string()
        }
        Some(ts) => ts.format("%Y-%m-%dT%H:%M:%S%.6f").to_string(),
        None => stored.to_owned(),
    }
}

/// Python truthiness of a JSON value.
pub(crate) fn truthy(value: &Value) -> bool {
    match value {
        Value::Null => false,
        Value::Bool(b) => *b,
        Value::Number(n) => n.as_f64().is_some_and(|f| f != 0.0),
        Value::String(s) => !s.is_empty(),
        Value::Array(a) => !a.is_empty(),
        Value::Object(o) => !o.is_empty(),
    }
}

/// `GoalResponse` of `goal_service.snapshot`, or `None` without a goal.
fn goal(conn: &Connection, session_id: &str) -> Result<Option<Value>, DbError> {
    let row = conn
        .query_row(
            "SELECT session_id, objective, status, token_budget, tokens_used, time_used_seconds, \
             active_started_at, pause_reason, blocker_streak, status_details, version, \
             created_at, updated_at, completed_at FROM session_goals WHERE session_id = ?1",
            [session_id],
            |r| {
                Ok((
                    r.get::<_, String>(0)?,
                    r.get::<_, String>(1)?,
                    r.get::<_, String>(2)?,
                    r.get::<_, Option<i64>>(3)?,
                    r.get::<_, i64>(4)?,
                    r.get::<_, f64>(5)?,
                    r.get::<_, Option<String>>(6)?,
                    r.get::<_, Option<String>>(7)?,
                    r.get::<_, i64>(8)?,
                    r.get::<_, Option<String>>(9)?,
                    r.get::<_, i64>(10)?,
                    r.get::<_, String>(11)?,
                    r.get::<_, String>(12)?,
                    r.get::<_, Option<String>>(13)?,
                ))
            },
        )
        .optional()?;
    let Some((
        sid,
        objective,
        status,
        budget,
        used,
        seconds,
        started,
        pause,
        streak,
        details,
        version,
        created,
        updated,
        completed,
    )) = row
    else {
        return Ok(None);
    };
    let mut elapsed = seconds;
    if status == "active" {
        if let Some(started) = started.as_deref().and_then(parse_db_ts) {
            let since = Utc::now().naive_utc() - started;
            elapsed += (since.num_microseconds().unwrap_or(0) as f64 / 1e6).max(0.0);
        }
    }
    let details = json_column(details).filter(truthy);
    let mut goal = Map::new();
    goal.insert("session_id".into(), json!(dashed(&sid)));
    goal.insert("objective".into(), json!(objective));
    goal.insert("status".into(), json!(status));
    goal.insert("token_budget".into(), json!(budget));
    goal.insert("tokens_used".into(), json!(used));
    goal.insert("time_used_seconds".into(), json!(elapsed));
    goal.insert("pause_reason".into(), json!(pause));
    goal.insert("blocker_streak".into(), json!(streak));
    goal.insert("status_details".into(), details.unwrap_or(Value::Null));
    goal.insert("version".into(), json!(version));
    goal.insert("created_at".into(), json!(api_ts(&created)));
    goal.insert("updated_at".into(), json!(api_ts(&updated)));
    goal.insert(
        "completed_at".into(),
        json!(completed.as_deref().map(api_ts)),
    );
    Ok(Some(Value::Object(goal)))
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

    #[test]
    fn uuid7_is_versioned_and_ascending() {
        let a = uuid7_hex();
        let b = uuid7_hex();
        assert_eq!(a.len(), 32);
        assert!(a < b, "{a} {b}");
        assert_eq!(&a[12..13], "7");
        assert!(matches!(&a[16..17], "8" | "9" | "a" | "b"));
        assert_eq!(dashed(&a).len(), 36);
        assert_eq!(parse_uuid(&dashed(&a)).unwrap(), a);
    }

    #[test]
    fn parse_uuid_accepts_python_forms() {
        let hex = "06ae6ab0636d720e8000b0d548016ce8";
        for form in [
            "06ae6ab0-636d-720e-8000-b0d548016ce8",
            "{06AE6AB0-636D-720E-8000-B0D548016CE8}",
            "urn:uuid:06ae6ab0-636d-720e-8000-b0d548016ce8",
            hex,
        ] {
            assert_eq!(parse_uuid(form).as_deref(), Some(hex), "{form}");
        }
        assert_eq!(parse_uuid("nope"), None);
        assert_eq!(parse_uuid("06ae6ab0636d720e8000b0d548016ce"), None);
    }

    #[test]
    fn timestamps_round_trip_like_pydantic() {
        assert_eq!(
            api_ts("2026-11-01 02:59:20.104157"),
            "2026-11-01T02:59:20.104157Z"
        );
        assert_eq!(api_ts("2026-11-01 02:59:20.000000"), "2026-11-01T02:59:20Z");
        assert_eq!(api_ts("2026-11-01 02:59:20"), "2026-11-01T02:59:20Z");
        assert_eq!(
            iso_naive("2026-11-01 02:59:20.000100"),
            "2026-11-01T02:59:20.000100"
        );
        assert_eq!(
            iso_naive("2026-11-01 02:59:20.000000"),
            "2026-11-01T02:59:20"
        );
        assert_eq!(now_db().len(), 26);
    }

    #[test]
    fn cursor_accepts_isoformat_variants() {
        let want = Some("2026-11-01 02:59:20.104157".to_owned());
        assert_eq!(cursor_ts("2026-11-01T02:59:20.104157Z"), want);
        assert_eq!(cursor_ts("2026-11-01T09:59:20.104157+07:00"), want);
        assert_eq!(cursor_ts("2026-11-01T02:59:20.104157"), want);
        assert_eq!(cursor_ts("2026-11-01 02:59:20.104157"), want);
        assert_eq!(
            cursor_ts("2026-11-01"),
            Some("2026-11-01 00:00:00.000000".to_owned())
        );
        assert_eq!(cursor_ts("yesterday"), None);
    }

    #[test]
    fn truthiness_follows_python() {
        for v in [
            json!(null),
            json!(false),
            json!(0),
            json!(""),
            json!([]),
            json!({}),
        ] {
            assert!(!truthy(&v), "{v}");
        }
        for v in [
            json!(true),
            json!(1),
            json!(0.5),
            json!("x"),
            json!([0]),
            json!({"a": 0}),
        ] {
            assert!(truthy(&v), "{v}");
        }
    }

    fn row(id: &str, role: &str, weight_text: usize) -> MessageRow {
        MessageRow {
            id: id.into(),
            session_id: "s".into(),
            role: role.into(),
            content: Some("x".repeat(weight_text)),
            ..MessageRow::default()
        }
    }

    #[test]
    fn bounded_page_keeps_min_rows_then_respects_budget() {
        assert_eq!(row_weight(&row("a", "user", 10)), 266);
        let mut extra = row("a", "assistant", 0);
        extra.extra = Some(json!({"k": "é"}));
        // json.dumps(..., ensure_ascii=False, separators=(",", ":")) in UTF-8
        assert_eq!(row_weight(&extra), 256 + r#"{"k":"é"}"#.len());
        let big: Vec<MessageRow> = (0..30)
            .map(|i| row(&i.to_string(), "user", 20_000))
            .collect();
        assert_eq!(bounded_page(&big).len(), HISTORY_MIN_ROWS);
        let small: Vec<MessageRow> = (0..200).map(|i| row(&i.to_string(), "user", 1)).collect();
        assert_eq!(bounded_page(&small).len(), HISTORY_MAX_ROWS);
        let exact: Vec<MessageRow> = (0..30)
            .map(|i| row(&i.to_string(), "user", HISTORY_TARGET_BYTES / 25 - 256))
            .collect();
        assert_eq!(bounded_page(&exact).len(), 25);
    }
}
