//! Usage and cost history: one row per model response.
//!
//! A chat's engine records each response's tokens, cost and duration as it
//! finishes ([`record`]); the cost is what the provider computed from the
//! model's models.dev price at that moment. The desktop reads totals, a time
//! series split by model (hour, day or week buckets) and breakdowns by model,
//! chat and source for its Usage page ([`summary`], [`events`]).
//! Design: `docs/features/usage-and-cost/sdd.md`.

use rusqlite::types::Value as SqlValue;
use rusqlite::{params, params_from_iter, Connection, Row};
use serde::{Deserialize, Serialize};

use crate::DbError;

/// Which part of a chat made the call.
pub const SOURCES: [&str; 4] = ["chat", "subagent", "plugin", "side"];

/// How many chats [`summary`] lists, most expensive first.
pub const TOP_CHATS: i64 = 50;

/// One response to record.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct NewUsage {
    pub at_ms: i64,
    pub chat_id: Option<String>,
    /// One of [`SOURCES`]; anything else is stored as `chat`.
    pub source: String,
    pub provider_id: String,
    pub model_id: String,
    pub input: i64,
    pub output: i64,
    pub cache_read: i64,
    pub cache_write: i64,
    pub reasoning: i64,
    pub cost_input: f64,
    pub cost_output: f64,
    pub cost_cache_read: f64,
    pub cost_cache_write: f64,
    pub cost_usd: f64,
    pub stop_reason: Option<String>,
    /// From the request going out to the last token.
    #[serde(default)]
    pub duration_ms: Option<i64>,
}

impl NewUsage {
    /// Whether the response used anything worth a row.
    pub fn is_empty(&self) -> bool {
        self.input == 0
            && self.output == 0
            && self.cache_read == 0
            && self.cache_write == 0
            && self.cost_usd == 0.0
    }
}

/// A recorded response, with its chat's title when the chat still exists.
#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct UsageEvent {
    pub id: i64,
    pub at_ms: i64,
    pub chat_id: Option<String>,
    pub chat_title: Option<String>,
    pub source: String,
    pub provider_id: String,
    pub model_id: String,
    pub input: i64,
    pub output: i64,
    pub cache_read: i64,
    pub cache_write: i64,
    pub reasoning: i64,
    pub cost_usd: f64,
    pub stop_reason: Option<String>,
    pub duration_ms: Option<i64>,
}

/// Which rows a query covers. Every field narrows; none means all.
#[derive(Debug, Clone, Default, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct UsageQuery {
    /// From this time (ms, inclusive).
    pub from_ms: Option<i64>,
    /// Up to this time (ms, exclusive).
    pub to_ms: Option<i64>,
    pub chat_id: Option<String>,
    pub provider_id: Option<String>,
    pub model_id: Option<String>,
    pub source: Option<String>,
    /// Time series bucket: `hour`, `day` (default) or `week`.
    pub bucket: Option<String>,
}

/// Sums over a set of rows.
#[derive(Debug, Clone, Default, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct UsageTotals {
    pub requests: i64,
    pub input: i64,
    pub output: i64,
    pub cache_read: i64,
    pub cache_write: i64,
    pub reasoning: i64,
    pub cost_input: f64,
    pub cost_output: f64,
    pub cost_cache_read: f64,
    pub cost_cache_write: f64,
    pub cost_usd: f64,
    /// Responses that ended in an error or were stopped, and what they cost.
    pub errors: i64,
    pub cost_errors: f64,
    /// Responses with a known duration, their summed duration and output.
    pub timed: i64,
    pub timed_ms: i64,
    pub timed_output: i64,
}

/// One bucket of the time series for one model.
#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SeriesPoint {
    /// Local time: `YYYY-MM-DD HH` (hour), `YYYY-MM-DD` (day, or the Monday
    /// that starts a week).
    pub bucket: String,
    pub provider_id: String,
    pub model_id: String,
    #[serde(flatten)]
    pub totals: UsageTotals,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ModelUsage {
    pub provider_id: String,
    pub model_id: String,
    pub last_ms: i64,
    #[serde(flatten)]
    pub totals: UsageTotals,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ChatUsage {
    pub chat_id: Option<String>,
    pub chat_title: Option<String>,
    pub last_ms: i64,
    #[serde(flatten)]
    pub totals: UsageTotals,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SourceUsage {
    pub source: String,
    #[serde(flatten)]
    pub totals: UsageTotals,
}

#[derive(Debug, Clone, Default, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct UsageSummary {
    pub totals: UsageTotals,
    /// The bucket the series uses (`hour`, `day` or `week`).
    pub bucket: String,
    /// Buckets with usage, oldest first, one point per model in each.
    pub series: Vec<SeriesPoint>,
    /// Most expensive first, then most tokens.
    pub by_model: Vec<ModelUsage>,
    /// The [`TOP_CHATS`] most expensive chats.
    pub by_chat: Vec<ChatUsage>,
    pub by_source: Vec<SourceUsage>,
    /// The oldest row in the whole history (not just this query).
    pub first_ms: Option<i64>,
}

const TOTALS: &str = "COUNT(*), COALESCE(SUM(u.input), 0), COALESCE(SUM(u.output), 0),
     COALESCE(SUM(u.cache_read), 0), COALESCE(SUM(u.cache_write), 0), COALESCE(SUM(u.reasoning), 0),
     COALESCE(SUM(u.cost_input), 0.0), COALESCE(SUM(u.cost_output), 0.0),
     COALESCE(SUM(u.cost_cache_read), 0.0), COALESCE(SUM(u.cost_cache_write), 0.0),
     COALESCE(SUM(u.cost_usd), 0.0),
     COALESCE(SUM(u.stop_reason IN ('error', 'aborted')), 0),
     COALESCE(SUM(CASE WHEN u.stop_reason IN ('error', 'aborted') THEN u.cost_usd END), 0.0),
     COALESCE(SUM(u.duration_ms > 0), 0),
     COALESCE(SUM(CASE WHEN u.duration_ms > 0 THEN u.duration_ms END), 0),
     COALESCE(SUM(CASE WHEN u.duration_ms > 0 THEN u.output END), 0)";

/// Read [`TOTALS`] starting at column `at`.
fn totals_at(row: &Row<'_>, at: usize) -> rusqlite::Result<UsageTotals> {
    Ok(UsageTotals {
        requests: row.get(at)?,
        input: row.get(at + 1)?,
        output: row.get(at + 2)?,
        cache_read: row.get(at + 3)?,
        cache_write: row.get(at + 4)?,
        reasoning: row.get(at + 5)?,
        cost_input: row.get(at + 6)?,
        cost_output: row.get(at + 7)?,
        cost_cache_read: row.get(at + 8)?,
        cost_cache_write: row.get(at + 9)?,
        cost_usd: row.get(at + 10)?,
        errors: row.get(at + 11)?,
        cost_errors: row.get(at + 12)?,
        timed: row.get(at + 13)?,
        timed_ms: row.get(at + 14)?,
        timed_output: row.get(at + 15)?,
    })
}

fn normalize_source(source: &str) -> &'static str {
    SOURCES
        .iter()
        .find(|known| known.eq_ignore_ascii_case(source))
        .copied()
        .unwrap_or("chat")
}

/// The series bucket and the SQL that names a row's bucket on the local clock.
fn bucket_of(bucket: Option<&str>) -> (&'static str, &'static str) {
    match bucket {
        Some("hour") => (
            "hour",
            "strftime('%Y-%m-%d %H', u.at_ms / 1000, 'unixepoch', 'localtime')",
        ),
        // The Monday on or before the day.
        Some("week") => (
            "week",
            "date(u.at_ms / 1000, 'unixepoch', 'localtime', '-6 days', 'weekday 1')",
        ),
        _ => ("day", "date(u.at_ms / 1000, 'unixepoch', 'localtime')"),
    }
}

/// Append responses in one transaction. Empty ones are skipped.
pub fn record(conn: &mut Connection, rows: &[NewUsage]) -> Result<usize, DbError> {
    let rows: Vec<&NewUsage> = rows.iter().filter(|row| !row.is_empty()).collect();
    if rows.is_empty() {
        return Ok(0);
    }
    let tx = conn.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
    {
        let mut statement = tx.prepare_cached(
            "INSERT INTO usage_events (at_ms, chat_id, source, provider_id, model_id,
                 input, output, cache_read, cache_write, reasoning,
                 cost_input, cost_output, cost_cache_read, cost_cache_write, cost_usd, stop_reason,
                 duration_ms)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, ?15, ?16, ?17)",
        )?;
        for row in &rows {
            statement.execute(params![
                row.at_ms,
                row.chat_id,
                normalize_source(&row.source),
                row.provider_id,
                row.model_id,
                row.input.max(0),
                row.output.max(0),
                row.cache_read.max(0),
                row.cache_write.max(0),
                row.reasoning.max(0),
                finite(row.cost_input),
                finite(row.cost_output),
                finite(row.cost_cache_read),
                finite(row.cost_cache_write),
                finite(row.cost_usd),
                row.stop_reason,
                row.duration_ms.filter(|ms| *ms > 0),
            ])?;
        }
    }
    tx.commit()?;
    Ok(rows.len())
}

/// A provider that reported a NaN or negative cost must not poison the sums.
fn finite(value: f64) -> f64 {
    if value.is_finite() && value > 0.0 {
        value
    } else {
        0.0
    }
}

/// `WHERE …` for a query over `usage_events` aliased `u`, and its values.
fn filter(query: &UsageQuery) -> (String, Vec<SqlValue>) {
    let mut clauses = Vec::new();
    let mut values = Vec::new();
    if let Some(from) = query.from_ms {
        clauses.push("u.at_ms >= ?");
        values.push(SqlValue::Integer(from));
    }
    if let Some(to) = query.to_ms {
        clauses.push("u.at_ms < ?");
        values.push(SqlValue::Integer(to));
    }
    for (column, value) in [
        ("u.chat_id = ?", &query.chat_id),
        ("u.provider_id = ?", &query.provider_id),
        ("u.model_id = ?", &query.model_id),
        ("u.source = ?", &query.source),
    ] {
        if let Some(value) = value.as_deref().filter(|value| !value.is_empty()) {
            clauses.push(column);
            values.push(SqlValue::Text(value.to_owned()));
        }
    }
    let sql = if clauses.is_empty() {
        String::new()
    } else {
        format!("WHERE {}", clauses.join(" AND "))
    };
    (sql, values)
}

/// Totals, the time series and the breakdowns for `query`.
pub fn summary(conn: &Connection, query: &UsageQuery) -> Result<UsageSummary, DbError> {
    let (filter, values) = filter(query);
    let (bucket, bucket_sql) = bucket_of(query.bucket.as_deref());

    let totals = conn.query_row(
        &format!("SELECT {TOTALS} FROM usage_events u {filter}"),
        params_from_iter(values.iter()),
        |row| totals_at(row, 0),
    )?;

    // Local buckets: the person reads "today" on their own clock.
    let series = conn
        .prepare(&format!(
            "SELECT {bucket_sql} AS bucket, u.provider_id, u.model_id, {TOTALS}
             FROM usage_events u {filter}
             GROUP BY bucket, u.provider_id, u.model_id ORDER BY bucket"
        ))?
        .query_map(params_from_iter(values.iter()), |row| {
            Ok(SeriesPoint {
                bucket: row.get(0)?,
                provider_id: row.get(1)?,
                model_id: row.get(2)?,
                totals: totals_at(row, 3)?,
            })
        })?
        .collect::<Result<Vec<_>, _>>()?;

    let by_model = conn
        .prepare(&format!(
            "SELECT u.provider_id, u.model_id, MAX(u.at_ms), {TOTALS}
             FROM usage_events u {filter}
             GROUP BY u.provider_id, u.model_id
             ORDER BY SUM(u.cost_usd) DESC, SUM(u.input + u.output + u.cache_read + u.cache_write) DESC"
        ))?
        .query_map(params_from_iter(values.iter()), |row| {
            Ok(ModelUsage {
                provider_id: row.get(0)?,
                model_id: row.get(1)?,
                last_ms: row.get(2)?,
                totals: totals_at(row, 3)?,
            })
        })?
        .collect::<Result<Vec<_>, _>>()?;

    let by_chat = conn
        .prepare(&format!(
            "SELECT u.chat_id, (SELECT title FROM chats c WHERE c.id = u.chat_id), MAX(u.at_ms), {TOTALS}
             FROM usage_events u {filter}
             GROUP BY u.chat_id
             ORDER BY SUM(u.cost_usd) DESC, SUM(u.input + u.output + u.cache_read + u.cache_write) DESC
             LIMIT {TOP_CHATS}"
        ))?
        .query_map(params_from_iter(values.iter()), |row| {
            Ok(ChatUsage {
                chat_id: row.get(0)?,
                chat_title: row.get(1)?,
                last_ms: row.get(2)?,
                totals: totals_at(row, 3)?,
            })
        })?
        .collect::<Result<Vec<_>, _>>()?;

    let by_source = conn
        .prepare(&format!(
            "SELECT u.source, {TOTALS} FROM usage_events u {filter}
             GROUP BY u.source ORDER BY SUM(u.cost_usd) DESC"
        ))?
        .query_map(params_from_iter(values.iter()), |row| {
            Ok(SourceUsage {
                source: row.get(0)?,
                totals: totals_at(row, 1)?,
            })
        })?
        .collect::<Result<Vec<_>, _>>()?;

    let first_ms = conn.query_row("SELECT MIN(at_ms) FROM usage_events", [], |row| row.get(0))?;

    Ok(UsageSummary {
        totals,
        bucket: bucket.into(),
        series,
        by_model,
        by_chat,
        by_source,
        first_ms,
    })
}

/// The newest responses matching `query`, paging backwards from `before_id`.
pub fn events(
    conn: &Connection,
    query: &UsageQuery,
    before_id: Option<i64>,
    limit: u32,
) -> Result<Vec<UsageEvent>, DbError> {
    let (mut filter, mut values) = self::filter(query);
    if let Some(before) = before_id {
        filter = if filter.is_empty() {
            "WHERE u.id < ?".into()
        } else {
            format!("{filter} AND u.id < ?")
        };
        values.push(SqlValue::Integer(before));
    }
    values.push(SqlValue::Integer(i64::from(limit.clamp(1, 2000))));
    let rows = conn
        .prepare(&format!(
            "SELECT u.id, u.at_ms, u.chat_id, (SELECT title FROM chats c WHERE c.id = u.chat_id),
                    u.source, u.provider_id, u.model_id, u.input, u.output, u.cache_read,
                    u.cache_write, u.reasoning, u.cost_usd, u.stop_reason, u.duration_ms
             FROM usage_events u {filter} ORDER BY u.id DESC LIMIT ?"
        ))?
        .query_map(params_from_iter(values.iter()), |row| {
            Ok(UsageEvent {
                id: row.get(0)?,
                at_ms: row.get(1)?,
                chat_id: row.get(2)?,
                chat_title: row.get(3)?,
                source: row.get(4)?,
                provider_id: row.get(5)?,
                model_id: row.get(6)?,
                input: row.get(7)?,
                output: row.get(8)?,
                cache_read: row.get(9)?,
                cache_write: row.get(10)?,
                reasoning: row.get(11)?,
                cost_usd: row.get(12)?,
                stop_reason: row.get(13)?,
                duration_ms: row.get(14)?,
            })
        })?
        .collect::<Result<Vec<_>, _>>()?;
    Ok(rows)
}

/// Forget the whole history. Returns how many rows went.
pub fn clear(conn: &Connection) -> Result<usize, DbError> {
    Ok(conn.execute("DELETE FROM usage_events", [])?)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::chats::{self, NewChat};

    fn db() -> (tempfile::TempDir, Connection) {
        let dir = tempfile::tempdir().unwrap();
        let conn = crate::open_at(&dir.path().join("evo.db")).unwrap();
        (dir, conn)
    }

    fn usage(at_ms: i64, chat: &str, model: &str, cost: f64) -> NewUsage {
        NewUsage {
            at_ms,
            chat_id: Some(chat.into()),
            source: "chat".into(),
            provider_id: "anthropic".into(),
            model_id: model.into(),
            input: 1000,
            output: 200,
            cache_read: 50,
            cache_write: 10,
            reasoning: 5,
            cost_input: cost * 0.6,
            cost_output: cost * 0.4,
            cost_usd: cost,
            stop_reason: Some("stop".into()),
            ..Default::default()
        }
    }

    #[test]
    fn records_and_sums_by_model_chat_and_source() {
        let (_dir, mut conn) = db();
        let rows = [
            usage(1_000, "a", "big", 0.5),
            usage(2_000, "a", "small", 0.1),
            NewUsage {
                source: "subagent".into(),
                ..usage(3_000, "b", "big", 0.25)
            },
            NewUsage {
                source: "nonsense".into(),
                ..usage(4_000, "b", "small", 0.05)
            },
            // Nothing used: skipped.
            NewUsage {
                input: 0,
                output: 0,
                cache_read: 0,
                cache_write: 0,
                cost_usd: 0.0,
                ..usage(5_000, "c", "big", 0.0)
            },
        ];
        assert_eq!(record(&mut conn, &rows).unwrap(), 4);

        let all = summary(&conn, &UsageQuery::default()).unwrap();
        assert_eq!(all.totals.requests, 4);
        assert_eq!(all.totals.input, 4000);
        assert!((all.totals.cost_usd - 0.9).abs() < 1e-9);
        assert_eq!(all.first_ms, Some(1_000));
        assert_eq!(all.by_model[0].model_id, "big");
        assert!((all.by_model[0].totals.cost_usd - 0.75).abs() < 1e-9);
        assert_eq!(all.by_model[0].last_ms, 3_000);
        assert_eq!(all.by_chat[0].chat_id.as_deref(), Some("a"));
        let sources: Vec<_> = all.by_source.iter().map(|s| s.source.as_str()).collect();
        assert_eq!(
            sources,
            ["chat", "subagent"],
            "unknown sources are stored as chat"
        );

        let ranged = summary(
            &conn,
            &UsageQuery {
                from_ms: Some(2_000),
                to_ms: Some(4_000),
                ..Default::default()
            },
        )
        .unwrap();
        assert_eq!(ranged.totals.requests, 2);
        assert_eq!(
            ranged.first_ms,
            Some(1_000),
            "the history's start ignores the range"
        );

        let one_model = summary(
            &conn,
            &UsageQuery {
                model_id: Some("small".into()),
                ..Default::default()
            },
        )
        .unwrap();
        assert_eq!(one_model.totals.requests, 2);
        assert_eq!(one_model.series.len(), 1);
    }

    #[test]
    fn the_series_splits_buckets_by_model() {
        let (_dir, mut conn) = db();
        // Around noon UTC on two days, an hour apart on the first.
        let day = 86_400_000;
        let base = 20 * 365 * day + day / 2;
        record(
            &mut conn,
            &[
                usage(base, "a", "big", 0.5),
                usage(base + 3_600_000, "a", "small", 0.1),
                usage(base + day, "a", "big", 0.2),
            ],
        )
        .unwrap();

        let by_day = summary(&conn, &UsageQuery::default()).unwrap();
        assert_eq!(by_day.bucket, "day");
        let buckets: Vec<_> = by_day.series.iter().map(|p| p.bucket.as_str()).collect();
        assert_eq!(buckets.len(), 3, "{buckets:?}");
        assert_eq!(buckets[0], buckets[1], "two models on the first day");
        assert_ne!(buckets[1], buckets[2]);

        let by_hour = summary(
            &conn,
            &UsageQuery {
                bucket: Some("hour".into()),
                ..Default::default()
            },
        )
        .unwrap();
        assert_eq!(by_hour.bucket, "hour");
        assert_eq!(by_hour.series.len(), 3);
        assert_eq!(by_hour.series[0].bucket.len(), "YYYY-MM-DD HH".len());
        assert_ne!(by_hour.series[0].bucket, by_hour.series[1].bucket);

        let by_week = summary(
            &conn,
            &UsageQuery {
                bucket: Some("week".into()),
                ..Default::default()
            },
        )
        .unwrap();
        assert_eq!(by_week.bucket, "week");
        assert!(by_week.series.len() <= 3);
    }

    #[test]
    fn errors_and_speed_are_counted() {
        let (_dir, mut conn) = db();
        record(
            &mut conn,
            &[
                NewUsage {
                    duration_ms: Some(2_000),
                    ..usage(1, "a", "m", 0.1)
                },
                NewUsage {
                    stop_reason: Some("error".into()),
                    duration_ms: Some(0),
                    ..usage(2, "a", "m", 0.3)
                },
                NewUsage {
                    stop_reason: Some("aborted".into()),
                    ..usage(3, "a", "m", 0.2)
                },
            ],
        )
        .unwrap();
        let all = summary(&conn, &UsageQuery::default()).unwrap();
        assert_eq!(all.totals.errors, 2);
        assert!((all.totals.cost_errors - 0.5).abs() < 1e-9);
        assert_eq!(
            (
                all.totals.timed,
                all.totals.timed_ms,
                all.totals.timed_output
            ),
            (1, 2_000, 200),
            "a zero duration is unknown"
        );
        let latest = events(&conn, &UsageQuery::default(), None, 3).unwrap();
        assert_eq!(latest[2].duration_ms, Some(2_000));
        assert_eq!(latest[1].duration_ms, None);
    }

    #[test]
    fn events_page_backwards_and_show_chat_titles() {
        let (_dir, mut conn) = db();
        chats::create_chat(
            &conn,
            &NewChat {
                id: "a".into(),
                workspace_id: None,
                title: "Fix the build".into(),
                provider: None,
                model: None,
                parent_chat_id: None,
                origin: None,
                worktree_path: None,
            },
        )
        .unwrap();
        let rows: Vec<_> = (0..5)
            .map(|i| usage(1_000 + i, if i % 2 == 0 { "a" } else { "gone" }, "m", 0.01))
            .collect();
        record(&mut conn, &rows).unwrap();

        let first = events(&conn, &UsageQuery::default(), None, 3).unwrap();
        assert_eq!(first.len(), 3);
        assert!(first[0].id > first[1].id);
        assert_eq!(first[0].chat_title.as_deref(), Some("Fix the build"));
        assert_eq!(first[1].chat_title, None, "a deleted chat keeps its spend");
        let rest = events(&conn, &UsageQuery::default(), Some(first[2].id), 3).unwrap();
        assert_eq!(rest.len(), 2);

        let only_a = events(
            &conn,
            &UsageQuery {
                chat_id: Some("a".into()),
                ..Default::default()
            },
            None,
            10,
        )
        .unwrap();
        assert_eq!(only_a.len(), 3);

        assert_eq!(clear(&conn).unwrap(), 5);
        assert!(events(&conn, &UsageQuery::default(), None, 10)
            .unwrap()
            .is_empty());
    }

    #[test]
    fn bad_costs_are_stored_as_zero() {
        let (_dir, mut conn) = db();
        record(
            &mut conn,
            &[NewUsage {
                cost_usd: f64::NAN,
                cost_input: -1.0,
                ..usage(1, "a", "m", 0.0)
            }],
        )
        .unwrap();
        let all = summary(&conn, &UsageQuery::default()).unwrap();
        assert_eq!(all.totals.cost_usd, 0.0);
        assert_eq!(all.totals.cost_input, 0.0);
    }
}
