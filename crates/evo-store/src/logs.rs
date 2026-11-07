//! The run log kept on this machine for debugging.
//!
//! The desktop shell writes engine stderr, engine lifecycle (start, exit,
//! crash), its own events and UI errors here, tagged with the chat they belong
//! to. It is bounded: [`prune`] drops entries older than a retention window and
//! keeps the newest `max_rows`, so the log cannot grow without limit.

use rusqlite::{params, params_from_iter, Connection, Row};
use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::chats::now_ms;
use crate::DbError;

pub const LEVELS: [&str; 4] = ["debug", "info", "warn", "error"];

/// Default retention: two weeks or 50k entries, whichever is smaller.
pub const DEFAULT_MAX_AGE_MS: i64 = 14 * 24 * 60 * 60 * 1000;
pub const DEFAULT_MAX_ROWS: i64 = 50_000;

#[derive(Debug, Clone, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct LogEntry {
    pub id: i64,
    pub at_ms: i64,
    pub level: String,
    pub source: String,
    pub chat_id: Option<String>,
    pub message: String,
    pub data: Option<Value>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct NewLog {
    pub level: String,
    pub source: String,
    #[serde(default)]
    pub chat_id: Option<String>,
    pub message: String,
    #[serde(default)]
    pub data: Option<Value>,
    /// When it happened; now when absent.
    #[serde(default)]
    pub at_ms: Option<i64>,
}

impl NewLog {
    pub fn new(level: &str, source: &str, message: impl Into<String>) -> Self {
        Self {
            level: level.into(),
            source: source.into(),
            chat_id: None,
            message: message.into(),
            data: None,
            at_ms: None,
        }
    }

    pub fn chat(mut self, chat_id: Option<&str>) -> Self {
        self.chat_id = chat_id.map(str::to_owned);
        self
    }

    pub fn data(mut self, data: Value) -> Self {
        self.data = Some(data);
        self
    }
}

#[derive(Debug, Clone, Default, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LogQuery {
    /// Lowest level to include (`debug` includes everything).
    pub min_level: Option<String>,
    pub source: Option<String>,
    pub chat_id: Option<String>,
    /// Case-insensitive text in the message.
    pub search: Option<String>,
    /// Page backwards: only entries with a smaller id.
    pub before_id: Option<i64>,
    /// At most this many (default 500, max 5000).
    pub limit: Option<u32>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct LogStats {
    pub count: i64,
    pub oldest_ms: Option<i64>,
    pub newest_ms: Option<i64>,
    pub sources: Vec<String>,
}

fn rank(level: &str) -> usize {
    LEVELS.iter().position(|known| *known == level).unwrap_or(1)
}

fn normalize_level(level: &str) -> &'static str {
    match level.to_ascii_lowercase().as_str() {
        "trace" | "debug" => "debug",
        "warn" | "warning" => "warn",
        "error" | "fatal" | "panic" => "error",
        _ => "info",
    }
}

fn entry_row(row: &Row<'_>) -> rusqlite::Result<LogEntry> {
    let data: Option<String> = row.get(6)?;
    Ok(LogEntry {
        id: row.get(0)?,
        at_ms: row.get(1)?,
        level: row.get(2)?,
        source: row.get(3)?,
        chat_id: row.get(4)?,
        message: row.get(5)?,
        data: data.and_then(|text| serde_json::from_str(&text).ok()),
    })
}

/// Append entries in one transaction.
pub fn append(conn: &mut Connection, entries: &[NewLog]) -> Result<(), DbError> {
    if entries.is_empty() {
        return Ok(());
    }
    let tx = conn.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
    {
        let mut statement = tx.prepare_cached(
            "INSERT INTO app_logs (at_ms, level, source, chat_id, message, data_json) VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
        )?;
        let now = now_ms();
        for entry in entries {
            let data = entry.data.as_ref().map(Value::to_string);
            statement.execute(params![
                entry.at_ms.unwrap_or(now),
                normalize_level(&entry.level),
                entry.source,
                entry.chat_id,
                entry.message,
                data
            ])?;
        }
    }
    tx.commit()?;
    Ok(())
}

/// Matching entries, newest first.
pub fn query(conn: &Connection, query: &LogQuery) -> Result<Vec<LogEntry>, DbError> {
    let mut clauses = Vec::new();
    let mut values: Vec<rusqlite::types::Value> = Vec::new();
    if let Some(level) = &query.min_level {
        let allowed = &LEVELS[rank(normalize_level(level))..];
        clauses.push(format!(
            "level IN ({})",
            allowed
                .iter()
                .map(|l| format!("'{l}'"))
                .collect::<Vec<_>>()
                .join(", ")
        ));
    }
    if let Some(source) = query.source.as_ref().filter(|s| !s.is_empty()) {
        clauses.push("source = ?".into());
        values.push(source.clone().into());
    }
    if let Some(chat) = query.chat_id.as_ref().filter(|s| !s.is_empty()) {
        clauses.push("chat_id = ?".into());
        values.push(chat.clone().into());
    }
    if let Some(search) = query.search.as_ref().filter(|s| !s.is_empty()) {
        let escaped = search
            .replace('\\', "\\\\")
            .replace('%', "\\%")
            .replace('_', "\\_");
        clauses.push("(message LIKE ? ESCAPE '\\' OR data_json LIKE ? ESCAPE '\\')".into());
        values.push(format!("%{escaped}%").into());
        values.push(format!("%{escaped}%").into());
    }
    if let Some(before) = query.before_id {
        clauses.push("id < ?".into());
        values.push(before.into());
    }
    let filter = if clauses.is_empty() {
        String::new()
    } else {
        format!("WHERE {}", clauses.join(" AND "))
    };
    let limit = query.limit.unwrap_or(500).clamp(1, 5000);
    let mut statement = conn.prepare(&format!(
        "SELECT id, at_ms, level, source, chat_id, message, data_json FROM app_logs {filter} ORDER BY id DESC LIMIT {limit}"
    ))?;
    let rows = statement.query_map(params_from_iter(values), entry_row)?;
    Ok(rows.collect::<Result<_, _>>()?)
}

/// Drop entries older than `max_age_ms` and all but the newest `max_rows`.
/// Returns how many were removed.
pub fn prune(conn: &Connection, max_age_ms: i64, max_rows: i64) -> Result<usize, DbError> {
    let mut removed = conn.execute(
        "DELETE FROM app_logs WHERE at_ms < ?1",
        [now_ms() - max_age_ms],
    )?;
    removed += conn.execute(
        "DELETE FROM app_logs WHERE id <= (SELECT id FROM app_logs ORDER BY id DESC LIMIT 1 OFFSET ?1)",
        [max_rows],
    )?;
    Ok(removed)
}

pub fn clear(conn: &Connection) -> Result<usize, DbError> {
    Ok(conn.execute("DELETE FROM app_logs", [])?)
}

pub fn stats(conn: &Connection) -> Result<LogStats, DbError> {
    let (count, oldest_ms, newest_ms) = conn.query_row(
        "SELECT COUNT(*), MIN(at_ms), MAX(at_ms) FROM app_logs",
        [],
        |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
    )?;
    let mut statement = conn.prepare("SELECT DISTINCT source FROM app_logs ORDER BY source")?;
    let sources = statement
        .query_map([], |row| row.get(0))?
        .collect::<Result<_, _>>()?;
    Ok(LogStats {
        count,
        oldest_ms,
        newest_ms,
        sources,
    })
}

/// One line per entry, oldest first: `2026-11-05T10:00:00.000Z ERROR engine [chat] message {data}`.
pub fn export_text(conn: &Connection, filter: &LogQuery) -> Result<String, DbError> {
    let mut all = query(
        conn,
        &LogQuery {
            limit: Some(5000),
            ..filter.clone()
        },
    )?;
    all.reverse();
    let mut out = String::new();
    for entry in all {
        out.push_str(&format_time(entry.at_ms));
        out.push(' ');
        out.push_str(&entry.level.to_uppercase());
        out.push(' ');
        out.push_str(&entry.source);
        if let Some(chat) = &entry.chat_id {
            out.push_str(&format!(" [{chat}]"));
        }
        out.push(' ');
        out.push_str(&entry.message);
        if let Some(data) = &entry.data {
            out.push(' ');
            out.push_str(&data.to_string());
        }
        out.push('\n');
    }
    Ok(out)
}

/// RFC 3339 UTC with milliseconds, without a date library.
fn format_time(ms: i64) -> String {
    let secs = ms.div_euclid(1000);
    let millis = ms.rem_euclid(1000);
    let days = secs.div_euclid(86_400);
    let rem = secs.rem_euclid(86_400);
    // Civil from days (Howard Hinnant).
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = doy - (153 * mp + 2) / 5 + 1;
    let month = if mp < 10 { mp + 3 } else { mp - 9 };
    let year = yoe + era * 400 + i64::from(month <= 2);
    format!(
        "{year:04}-{month:02}-{day:02}T{:02}:{:02}:{:02}.{millis:03}Z",
        rem / 3600,
        (rem % 3600) / 60,
        rem % 60
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn append_query_prune() {
        let dir = tempfile::tempdir().unwrap();
        let mut conn = crate::open_at(&dir.path().join("evo.db")).unwrap();
        append(
            &mut conn,
            &[
                NewLog::new("debug", "engine", "spawned").chat(Some("c1")),
                NewLog::new("WARNING", "engine", "slow 100% load").chat(Some("c1")),
                NewLog::new("error", "ui", "boom").data(serde_json::json!({"stack": "x"})),
                NewLog {
                    at_ms: Some(0),
                    ..NewLog::new("info", "shell", "ancient")
                },
            ],
        )
        .unwrap();

        let warn_up = query(
            &conn,
            &LogQuery {
                min_level: Some("warn".into()),
                ..Default::default()
            },
        )
        .unwrap();
        assert_eq!(
            warn_up
                .iter()
                .map(|e| e.message.as_str())
                .collect::<Vec<_>>(),
            ["boom", "slow 100% load"]
        );
        assert_eq!(warn_up[1].level, "warn");
        assert_eq!(
            query(
                &conn,
                &LogQuery {
                    chat_id: Some("c1".into()),
                    ..Default::default()
                }
            )
            .unwrap()
            .len(),
            2
        );
        assert_eq!(
            query(
                &conn,
                &LogQuery {
                    search: Some("100%".into()),
                    ..Default::default()
                }
            )
            .unwrap()
            .len(),
            1
        );
        assert_eq!(
            query(
                &conn,
                &LogQuery {
                    search: Some("stack".into()),
                    ..Default::default()
                }
            )
            .unwrap()
            .len(),
            1
        );

        assert_eq!(prune(&conn, DEFAULT_MAX_AGE_MS, 2).unwrap(), 2);
        let left = query(&conn, &LogQuery::default()).unwrap();
        assert_eq!(left.len(), 2);
        assert_eq!(stats(&conn).unwrap().count, 2);
        assert!(export_text(&conn, &LogQuery::default())
            .unwrap()
            .contains("ERROR ui boom {\"stack\":\"x\"}"));
    }

    #[test]
    fn formats_utc() {
        assert_eq!(format_time(0), "1970-01-01T00:00:00.000Z");
        assert_eq!(format_time(1_793_000_000_123), "2026-10-26T07:33:20.123Z");
    }
}
