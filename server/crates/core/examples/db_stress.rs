//! Stress the real v3 schema through the core database lanes.
use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

use evoflux_core::db::{rowid, Db, DbError, DbOptions};
use rusqlite::ToSql;

#[derive(Clone)]
struct Options {
    db: PathBuf,
    seconds: u64,
    writers: usize,
    concurrent: bool,
    same_table: bool,
}

fn arguments() -> Result<Options, String> {
    let mut args = std::env::args().skip(1);
    let mut path = None;
    let mut seconds = 60;
    let mut writers = 4;
    let mut concurrent = true;
    let mut same_table = false;
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
            "--pattern" if value == "same-table" => same_table = true,
            "--pattern" if value == "cross-table" => same_table = false,
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
        same_table,
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
    let result = runtime.block_on(run(db, opts));
    println!("{}", serde_json::to_string(&result?)?);
    Ok(())
}

async fn run(db: Arc<Db>, opts: Options) -> Result<serde_json::Value, DbError> {
    let started = Instant::now();
    let deadline = started + Duration::from_secs(opts.seconds);
    let attempted_busy = Arc::new(AtomicU64::new(0));
    let mut tasks = Vec::new();
    for worker in 0..opts.writers {
        let db = db.clone();
        let busy = attempted_busy.clone();
        let same_table = opts.same_table;
        tasks.push(tokio::spawn(async move {
            let mut timings = Vec::new();
            let mut counts = [0_u64; 3];
            while Instant::now() < deadline {
                let table = if same_table { 0 } else { worker % 3 };
                let id = format!("{:016x}{:016x}", fastrand::u64(..), fastrand::u64(..));
                let start = Instant::now();
                loop {
                    let key = id.clone();
                    let result = db
                        .write(move |tx| {
                            let now = "2026-10-30 00:00:00";
                            match table {
                                0 => rowid::insert(
                                    tx,
                                    "chat_sessions",
                                    &["id", "title", "created_at", "updated_at"],
                                    &[&key as &dyn ToSql, &"stress", &now, &now],
                                ),
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
        serde_json::json!({"acknowledged": timings.len(), "elapsed_seconds": started.elapsed().as_secs_f64(), "failed": 0, "busy_retries": attempted_busy.load(Ordering::Relaxed), "conflicts": db.metric("EVOFLUX_db_concurrent_conflicts_total", &[]), "transaction_retries": db.metric("EVOFLUX_db_concurrent_retries_total", &[]), "p99_ms": timings.get(index).copied().unwrap_or(0.0), "counts": {"chat_sessions": counts.first().copied().unwrap_or(0), "session_folders": counts.get(1).copied().unwrap_or(0), "memory_facts": counts.get(2).copied().unwrap_or(0)}}),
    )
}
