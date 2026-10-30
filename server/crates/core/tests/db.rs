//! Task 8: SQLite read, concurrent and exclusive write lanes (design §3.3).
// Test setup may block: these tests own their threads and temp files.
#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::indexing_slicing,
    clippy::disallowed_methods,
    clippy::panic
)]

use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU32, AtomicUsize, Ordering};
use std::sync::{Arc, Barrier};
use std::time::{Duration, Instant};

use evoflux_core::db::{rowid, Db, DbError, DbOptions};
use rusqlite::{params, ToSql};

fn temp_db() -> (tempfile::TempDir, PathBuf) {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("evoflux.db");
    (dir, path)
}

fn concurrent_options() -> DbOptions {
    DbOptions {
        concurrent_enabled: true,
        ..DbOptions::default()
    }
}

fn open(path: &Path, opts: DbOptions) -> Db {
    Db::open(path, opts).unwrap()
}

/// Tables are created with stock rusqlite calls: Rust never runs DDL in the app.
fn create_tables(path: &Path, tables: &[&str]) {
    let conn = rusqlite::Connection::open(path).unwrap();
    conn.pragma_update(None, "journal_mode", "WAL").unwrap();
    for table in tables {
        conn.execute_batch(&format!(
            "CREATE TABLE {table} (id TEXT PRIMARY KEY NOT NULL, n INTEGER NOT NULL)"
        ))
        .unwrap();
    }
}

fn count(db_path: &Path, table: &str) -> i64 {
    let conn = rusqlite::Connection::open(db_path).unwrap();
    conn.query_row(&format!("SELECT count(*) FROM {table}"), [], |r| r.get(0))
        .unwrap()
}

#[tokio::test(flavor = "multi_thread")]
async fn begin_concurrent_available() {
    let (_dir, path) = temp_db();
    create_tables(&path, &["t"]);
    let db = open(&path, concurrent_options());
    db.write(|tx| {
        tx.execute("INSERT INTO t (id, n) VALUES ('a', 1)", [])?;
        Ok(())
    })
    .await
    .unwrap();
    let version: String = db
        .read(|conn| Ok(conn.query_row("SELECT sqlite_version()", [], |r| r.get(0))?))
        .await
        .unwrap();
    assert!(!version.is_empty());
    // The pinned build must accept BEGIN CONCURRENT directly.
    let conn = rusqlite::Connection::open(&path).unwrap();
    conn.execute_batch("BEGIN CONCURRENT; INSERT INTO t (id, n) VALUES ('b', 2); COMMIT;")
        .unwrap();
    assert_eq!(count(&path, "t"), 2);
}

#[tokio::test(flavor = "multi_thread")]
async fn refuses_wal2() {
    let (_dir, path) = temp_db();
    create_tables(&path, &["t"]);
    // wal2 marks the header's file-format read/write versions (bytes 18 and 19) as 3.
    let mut bytes = std::fs::read(&path).unwrap();
    bytes[18] = 3;
    bytes[19] = 3;
    std::fs::write(&path, &bytes).unwrap();
    let err = Db::open(&path, concurrent_options()).err().unwrap();
    assert!(matches!(err, DbError::Wal2), "{err:?}");
}

#[tokio::test(flavor = "multi_thread")]
async fn admission_timeout_returns_busy() {
    let (_dir, path) = temp_db();
    create_tables(&path, &["t"]);
    let db = Arc::new(open(&path, concurrent_options()));
    let holder = {
        let db = db.clone();
        tokio::spawn(async move {
            db.write_exclusive(|_tx| {
                std::thread::sleep(Duration::from_secs(6));
                Ok(())
            })
            .await
        })
    };
    tokio::time::sleep(Duration::from_millis(200)).await;
    let started = Instant::now();
    let err = db.write_exclusive(|_tx| Ok(())).await.err().unwrap();
    let waited = started.elapsed();
    assert!(matches!(err, DbError::Busy), "{err:?}");
    assert!(waited >= Duration::from_millis(4800), "{waited:?}");
    assert!(waited < Duration::from_millis(5800), "{waited:?}");
    holder.await.unwrap().unwrap();
    assert!(db.metric("EVOFLUX_db_pool_timeouts_total", &[("lane", "exclusive")]) >= 1.0);
}

#[tokio::test(flavor = "multi_thread")]
async fn different_tables_commit_in_parallel() {
    let (_dir, path) = temp_db();
    let tables = ["t0", "t1", "t2", "t3"];
    create_tables(&path, &tables);
    let db = Arc::new(open(
        &path,
        DbOptions {
            concurrent_writers: 4,
            ..concurrent_options()
        },
    ));
    let mut tasks = Vec::new();
    for table in tables {
        let db = db.clone();
        tasks.push(tokio::spawn(async move {
            for i in 0..500_i64 {
                let id = format!("{table}-{i}");
                db.write(move |tx| {
                    rowid::insert(tx, table, &["id", "n"], &[&id as &dyn ToSql, &i])?;
                    Ok(())
                })
                .await
                .unwrap();
            }
        }));
    }
    for task in tasks {
        task.await.unwrap();
    }
    for table in tables {
        assert_eq!(count(&path, table), 500);
        assert_eq!(
            db.metric("EVOFLUX_db_concurrent_conflicts_total", &[("table", table)]),
            0.0
        );
    }
    assert_eq!(
        db.metric("EVOFLUX_db_concurrent_retries_total", &[("lane", "write")]),
        0.0
    );
}

#[tokio::test(flavor = "multi_thread")]
async fn same_table_conflict_retries_to_success() {
    let (_dir, path) = temp_db();
    create_tables(&path, &["t"]);
    let db = Arc::new(open(
        &path,
        DbOptions {
            concurrent_writers: 4,
            ..concurrent_options()
        },
    ));
    // Every writer reads and appends to the same last page, then all commit
    // together on the first attempt, so all but one must retry.
    let writers = 4;
    let barrier = Arc::new(Barrier::new(writers));
    let mut tasks = Vec::new();
    for w in 0..writers {
        let db = db.clone();
        let barrier = barrier.clone();
        tasks.push(tokio::spawn(async move {
            let mut first = true;
            db.write(move |tx| {
                let next: i64 =
                    tx.query_row("SELECT coalesce(max(n), 0) + 1 FROM t", [], |r| r.get(0))?;
                tx.execute(
                    "INSERT INTO t (id, n) VALUES (?1, ?2)",
                    params![format!("w{w}"), next],
                )?;
                if std::mem::take(&mut first) {
                    barrier.wait();
                }
                Ok(())
            })
            .await
        }));
    }
    for task in tasks {
        task.await.unwrap().unwrap();
    }
    assert_eq!(count(&path, "t"), writers as i64);
    assert!(db.metric("EVOFLUX_db_concurrent_retries_total", &[("lane", "write")]) > 0.0);
    assert!(db.metric("EVOFLUX_db_concurrent_conflicts_total", &[("table", "t")]) > 0.0);
}

async fn retry_scenario(inject: bool) -> (Vec<(String, i64)>, u32, usize) {
    let (_dir, path) = temp_db();
    create_tables(&path, &["t"]);
    let db = open(&path, concurrent_options());
    db.inject_busy_snapshot_on_first_commit(inject);
    let side_effects = AtomicUsize::new(0);
    let calls = Arc::new(AtomicU32::new(0));
    // Ids are generated before the closure; the closure holds database work only.
    let ids: Vec<String> = (0..3).map(|i| format!("row-{i}")).collect();
    {
        let calls = calls.clone();
        let ids = ids.clone();
        db.write(move |tx| {
            calls.fetch_add(1, Ordering::SeqCst);
            for (n, id) in ids.iter().enumerate() {
                let n = n as i64;
                rowid::insert(tx, "t", &["id", "n"], &[id as &dyn ToSql, &n])?;
            }
            tx.execute("UPDATE t SET n = n + 10 WHERE id = 'row-0'", [])?;
            Ok(())
        })
        .await
        .unwrap();
    }
    side_effects.fetch_add(1, Ordering::SeqCst);
    let rows = db
        .read(|conn| {
            let mut stmt = conn.prepare("SELECT id, n FROM t ORDER BY id")?;
            let rows = stmt
                .query_map([], |r| Ok((r.get(0)?, r.get(1)?)))?
                .collect::<Result<Vec<_>, _>>()?;
            Ok(rows)
        })
        .await
        .unwrap();
    (
        rows,
        calls.load(Ordering::SeqCst),
        side_effects.load(Ordering::SeqCst),
    )
}

#[tokio::test(flavor = "multi_thread")]
async fn retry_safety_closure_rerun_is_idempotent() {
    let (clean, clean_calls, _) = retry_scenario(false).await;
    let (retried, retried_calls, side_effects) = retry_scenario(true).await;
    assert_eq!(clean_calls, 1);
    assert_eq!(retried_calls, 2);
    assert_eq!(clean, retried);
    assert_eq!(side_effects, 1);
}

#[tokio::test(flavor = "multi_thread")]
async fn random_rowid_insert_never_sequential() {
    for _ in 0..1000 {
        let r = rowid::random_rowid();
        assert!((1..=1_i64 << 62).contains(&r));
    }
    let (_dir, path) = temp_db();
    create_tables(&path, &["t"]);
    let db = open(&path, concurrent_options());
    db.write(|tx| {
        for i in 0..1000_i64 {
            let id = format!("id-{i}");
            rowid::insert(tx, "t", &["id", "n"], &[&id as &dyn ToSql, &i])?;
        }
        Ok(())
    })
    .await
    .unwrap();
    let rowids: Vec<i64> = db
        .read(|conn| {
            let mut stmt = conn.prepare("SELECT rowid FROM t ORDER BY n")?;
            let rows = stmt
                .query_map([], |r| r.get(0))?
                .collect::<Result<Vec<_>, _>>()?;
            Ok(rows)
        })
        .await
        .unwrap();
    assert_eq!(rowids.len(), 1000);
    assert!(rowids.iter().all(|r| (1..=1_i64 << 62).contains(r)));
    assert!(
        !rowids.windows(2).all(|w| w[0] < w[1]),
        "rowids are monotonic"
    );
}

#[tokio::test(flavor = "multi_thread")]
async fn off_switch_uses_fifo() {
    let (_dir, path) = temp_db();
    create_tables(&path, &["t"]);
    let opts = DbOptions {
        concurrent_enabled: false,
        ..concurrent_options()
    };
    let db = open(&path, opts);
    db.write(|tx| {
        tx.execute("INSERT INTO t (id, n) VALUES ('a', 1)", [])?;
        Ok(())
    })
    .await
    .unwrap();
    let wait = "EVOFLUX_db_pool_wait_seconds_count";
    assert_eq!(db.metric(wait, &[("lane", "exclusive")]), 1.0);
    assert_eq!(db.metric(wait, &[("lane", "write")]), 0.0);
    assert!(!DbOptions::concurrent_writes_from_env(Some("off")));
    assert!(DbOptions::concurrent_writes_from_env(Some("on")));
    assert!(!DbOptions::concurrent_writes_from_env(None));
}

#[test]
fn busy_maps_to_database_busy() {
    let busy = evoflux_core::ApiError::from(DbError::Busy);
    let expected = evoflux_core::ApiError::database_busy();
    assert_eq!(busy.status, expected.status);
    assert_eq!(busy.headers, expected.headers);
    assert_eq!(busy.body_bytes(), expected.body_bytes());
    let other = evoflux_core::ApiError::from(DbError::Closed);
    assert_eq!(other.status, evoflux_core::ApiError::internal().status);
}

#[tokio::test(flavor = "multi_thread")]
async fn rowid_alias_primary_key_keeps_sqlite_ids() {
    let (_dir, path) = temp_db();
    // Shaped like v3.1.1 `dream_log`: `id` is an INTEGER PRIMARY KEY, so it is
    // the rowid and the API-visible id.
    let conn = rusqlite::Connection::open(&path).unwrap();
    conn.pragma_update(None, "journal_mode", "WAL").unwrap();
    conn.execute_batch(
        "CREATE TABLE dream_log (id INTEGER NOT NULL, session_id CHAR(32) NOT NULL, \
         processed_at DATETIME NOT NULL, PRIMARY KEY (id))",
    )
    .unwrap();
    drop(conn);
    let db = open(&path, concurrent_options());
    db.write(|tx| {
        for i in 0..5 {
            let session = format!("s{i}");
            rowid::insert(
                tx,
                "dream_log",
                &["session_id", "processed_at"],
                &[&session as &dyn ToSql, &"2026-10-30 00:00:00"],
            )?;
        }
        Ok(())
    })
    .await
    .unwrap();
    let ids: Vec<i64> = db
        .read(|conn| {
            let mut stmt = conn.prepare("SELECT id FROM dream_log ORDER BY session_id")?;
            let rows = stmt
                .query_map([], |r| r.get(0))?
                .collect::<Result<Vec<_>, _>>()?;
            Ok(rows)
        })
        .await
        .unwrap();
    assert_eq!(ids, vec![1, 2, 3, 4, 5]);
}

#[tokio::test(flavor = "multi_thread")]
async fn read_lane_is_query_only() {
    let (_dir, path) = temp_db();
    create_tables(&path, &["t"]);
    let db = open(&path, concurrent_options());
    let query_only: i64 = db
        .read(|conn| Ok(conn.query_row("PRAGMA query_only", [], |r| r.get(0))?))
        .await
        .unwrap();
    assert_eq!(query_only, 1);
    let err = db
        .read(|conn| Ok(conn.execute("INSERT INTO t (id, n) VALUES ('x', 1)", [])?))
        .await
        .err()
        .unwrap();
    let DbError::Sqlite(err) = err else {
        panic!("{err:?}");
    };
    assert_eq!(err.sqlite_error_code(), Some(rusqlite::ErrorCode::ReadOnly));
    assert_eq!(count(&path, "t"), 0);
}

/// The bundled bindings were generated for a newer header than the pinned
/// amalgamation; the library that actually links must be the pinned one.
#[test]
fn linked_sqlite_is_the_pinned_build() {
    let pin = include_str!("../../../vendor/SQLITE_BRANCH.toml");
    let release = pin
        .lines()
        .find_map(|l| l.strip_prefix("based_on_release = "))
        .unwrap()
        .trim()
        .trim_matches('"');
    assert_eq!(rusqlite::version(), release);
}
