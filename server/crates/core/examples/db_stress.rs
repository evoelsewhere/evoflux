//! Stress the real v3 schema through the core database lanes.
use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

use evoflux_core::db::{rowid, Db, DbError, DbOptions, Tx};
use rusqlite::ToSql;

#[derive(Clone)]
struct Options {
    db: PathBuf,
    seconds: u64,
    writers: usize,
    concurrent: bool,
    pattern: Pattern,
}

#[derive(Clone, Copy, PartialEq)]
enum Pattern {
    SameTable,
    CrossTable,
    /// A chat turn: user and assistant messages (with usage) and the
    /// session's `updated_at`, in one transaction.
    Message,
}

/// Largest WAL the run may reach: twice the lanes' restart size of 4000
/// frames of 4096 + 24 bytes.
const WAL_BOUND_BYTES: u64 = 2 * 4000 * (4096 + 24);

fn arguments() -> Result<Options, String> {
    let mut args = std::env::args().skip(1);
    let mut path = None;
    let mut seconds = 60;
    let mut writers = 4;
    let mut concurrent = true;
    let mut pattern = Pattern::CrossTable;
    while let Some(key) = args.next() {
        let value = args
            .next()
            .ok_or_else(|| format!("missing value for {key}"))?;
        match key.as_str() {
            "--db" => path = Some(PathBuf::from(value)),
            "--seconds" => seconds = value.parse().map_err(|_| "bad seconds")?,
            "--writers" => writers = value.parse().map_err(|_| "bad writers")?,
            "--report" if value == "json" => {}
            "--mode" if value == "fifo" => concurrent = false,
            "--mode" if value == "concurrent" => concurrent = true,
            "--pattern" if value == "same-table" => pattern = Pattern::SameTable,
            "--pattern" if value == "cross-table" => pattern = Pattern::CrossTable,
            "--pattern" if value == "message" => pattern = Pattern::Message,
            _ => return Err(format!("invalid argument {key}={value}")),
        }
    }
    if seconds == 0 || writers == 0 {
        return Err("seconds and writers must be positive".into());
    }
    Ok(Options {
        db: path.ok_or("--db is required")?,
        seconds,
        writers,
        concurrent,
        pattern,
    })
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let opts = arguments().map_err(std::io::Error::other)?;
    if !opts.db.is_file() {
        return Err("--db must name an existing disposable database".into());
    }
    let config = DbOptions {
        concurrent_enabled: opts.concurrent,
        concurrent_writers: opts.writers,
        ..DbOptions::default()
    };
    let db = Arc::new(Db::open(&opts.db, config)?);
    let runtime = tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()?;
    let wal = PathBuf::from(format!("{}-wal", opts.db.display()));
    let result = runtime.block_on(run(db, opts, wal))?;
    println!("{}", serde_json::to_string(&result)?);
    let wal_max = result
        .get("wal_max_bytes")
        .and_then(serde_json::Value::as_u64)
        .unwrap_or(0);
    if wal_max > WAL_BOUND_BYTES {
        return Err(format!("WAL reached {wal_max} bytes, bound {WAL_BOUND_BYTES}").into());
    }
    Ok(())
}

async fn run(db: Arc<Db>, opts: Options, wal: PathBuf) -> Result<serde_json::Value, DbError> {
    let started = Instant::now();
    let deadline = started + Duration::from_secs(opts.seconds);
    let attempted_busy = Arc::new(AtomicU64::new(0));
    let wal_max = Arc::new(AtomicU64::new(0));
    let mut tasks = Vec::new();
    for worker in 0..opts.writers {
        let db = db.clone();
        let busy = attempted_busy.clone();
        let wal = wal.clone();
        let wal_max = wal_max.clone();
        let pattern = opts.pattern;
        tasks.push(tokio::spawn(async move {
            let mut timings = Vec::new();
            let mut counts = [0_u64; 3];
            // The message pattern appends to one chat session per writer.
            let session = random_id();
            if pattern == Pattern::Message {
                let key = session.clone();
                db.write(move |tx| insert_session(tx, &key)).await?;
            }
            while Instant::now() < deadline {
                let table = match pattern {
                    Pattern::SameTable => 0,
                    Pattern::CrossTable => worker % 3,
                    Pattern::Message => 3,
                };
                let id = random_id();
                let start = Instant::now();
                loop {
                    let key = id.clone();
                    let session = session.clone();
                    let result = db
                        .write(move |tx| {
                            let now = "2026-10-30 00:00:00";
                            match table {
                                0 => insert_session(tx, &key),
                                3 => chat_turn(tx, &session, &key),
                                1 => rowid::insert(
                                    tx,
                                    "session_folders",
                                    &["id", "name", "created_at", "updated_at"],
                                    &[&key as &dyn ToSql, &"stress", &now, &now],
                                ),
                                _ => rowid::insert(
                                    tx,
                                    "memory_facts",
                                    &[
                                        "id",
                                        "scope_type",
                                        "scope_id",
                                        "kind",
                                        "content",
                                        "content_hash",
                                        "created_at",
                                        "updated_at",
                                        "last_seen_at",
                                    ],
                                    &[
                                        &key as &dyn ToSql,
                                        &"user",
                                        &"stress",
                                        &"fact",
                                        &key,
                                        &key,
                                        &now,
                                        &now,
                                        &now,
                                    ],
                                ),
                            }
                        })
                        .await;
                    match result {
                        Ok(()) => break,
                        Err(DbError::Busy) if Instant::now() < deadline => {
                            busy.fetch_add(1, Ordering::Relaxed);
                            tokio::time::sleep(Duration::from_millis(10)).await;
                        }
                        Err(e) => return Err(e),
                    }
                }
                if let Some(count) = counts.get_mut(table) {
                    *count += 1;
                }
                timings.push(start.elapsed().as_secs_f64() * 1000.0);
                let size = std::fs::metadata(&wal).map_or(0, |m| m.len());
                wal_max.fetch_max(size, Ordering::Relaxed);
            }
            Ok::<_, DbError>((counts, timings))
        }));
    }
    let mut counts = [0_u64; 3];
    let mut timings = Vec::new();
    for task in tasks {
        let (worker_counts, worker_timings) = task.await.map_err(|_| DbError::Closed)??;
        for (total, count) in counts.iter_mut().zip(worker_counts) {
            *total += count;
        }
        timings.extend(worker_timings);
    }
    timings.sort_by(f64::total_cmp);
    let index = timings
        .len()
        .saturating_mul(99)
        .div_ceil(100)
        .saturating_sub(1);
    Ok(
        serde_json::json!({"acknowledged": timings.len(), "elapsed_seconds": started.elapsed().as_secs_f64(), "failed": 0, "busy_retries": attempted_busy.load(Ordering::Relaxed), "conflicts": db.metric("EVOFLUX_db_concurrent_conflicts_total", &[]), "transaction_retries": db.metric("EVOFLUX_db_concurrent_retries_total", &[]), "p99_ms": timings.get(index).copied().unwrap_or(0.0), "wal_max_bytes": wal_max.load(Ordering::Relaxed), "checkpoints": db.metric("EVOFLUX_db_wal_checkpoints_total", &[]), "counts": {"chat_sessions": counts.first().copied().unwrap_or(0), "session_folders": counts.get(1).copied().unwrap_or(0), "memory_facts": counts.get(2).copied().unwrap_or(0)}}),
    )
}

fn random_id() -> String {
    format!("{:016x}{:016x}", fastrand::u64(..), fastrand::u64(..))
}

fn insert_session(tx: &Tx<'_>, id: &str) -> Result<(), DbError> {
    let now = "2026-10-30 00:00:00";
    rowid::insert(
        tx,
        "chat_sessions",
        &["id", "title", "created_at", "updated_at"],
        &[&id as &dyn ToSql, &"stress", &now, &now],
    )
}

/// User message, assistant message carrying usage, and the session touch.
fn chat_turn(tx: &Tx<'_>, session: &str, id: &str) -> Result<(), DbError> {
    let now = "2026-10-30 00:00:00";
    let columns = ["id", "session_id", "role", "content", "extra", "created_at"];
    let user = format!("{id}u");
    rowid::insert(
        tx,
        "session_messages",
        &columns,
        &[
            &user as &dyn ToSql,
            &session,
            &"user",
            &"hello",
            &None::<String>,
            &now,
        ],
    )?;
    let usage = r#"{"usage": {"input_tokens": 1200, "output_tokens": 300}}"#;
    let answer = "a".repeat(400);
    let assistant = format!("{id}a");
    rowid::insert(
        tx,
        "session_messages",
        &columns,
        &[
            &assistant as &dyn ToSql,
            &session,
            &"assistant",
            &answer,
            &usage,
            &now,
        ],
    )?;
    tx.execute(
        "UPDATE chat_sessions SET updated_at = ?1 WHERE id = ?2",
        (now, session),
    )?;
    Ok(())
}
