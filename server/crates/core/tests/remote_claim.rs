#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::panic,
    clippy::indexing_slicing
)]
use evoflux_core::{
    db::{Db, DbOptions},
    remote_claim::{claim, ClaimError},
};
fn setup() -> (tempfile::TempDir, Db) {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("db.sqlite");
    let conn = rusqlite::Connection::open(&path).unwrap();
    conn.execute_batch("CREATE TABLE remote_use_sessions (id TEXT PRIMARY KEY NOT NULL, user_login TEXT NOT NULL, device_label TEXT, claimed_at DATETIME NOT NULL, last_seen_at DATETIME NOT NULL, released_at DATETIME, idle_expires_at DATETIME NOT NULL)").unwrap();
    drop(conn);
    let db = Db::open(&path, DbOptions::default()).unwrap();
    (dir, db)
}
#[tokio::test]
async fn claim_first_device_then_conflict() {
    let (_dir, db) = setup();
    claim(&db, "alice", Some("phone")).await.unwrap();
    assert!(matches!(
        claim(&db, "alice", Some("laptop")).await,
        Err(ClaimError::Conflict(_))
    ));
}
#[tokio::test]
async fn claim_same_device_idempotent() {
    let (_dir, db) = setup();
    claim(&db, "alice", Some("phone")).await.unwrap();
    claim(&db, "alice", Some("phone")).await.unwrap();
    let count: i64 = db
        .read(|c| Ok(c.query_row("SELECT count(*) FROM remote_use_sessions", [], |r| r.get(0))?))
        .await
        .unwrap();
    assert_eq!(count, 1);
}
#[tokio::test]
async fn conflict_timestamp_omits_zero_fraction() {
    let (_dir, db) = setup();
    db.write(|tx| { tx.execute("INSERT INTO remote_use_sessions VALUES ('holder', 'alice', 'phone', '2026-01-01 00:00:00.000000', '2026-01-01 00:00:00.000000', NULL, '9999-01-01 00:00:00.000000')", [])?; Ok(()) }).await.unwrap();
    let Err(ClaimError::Conflict(body)) = claim(&db, "bob", None).await else {
        panic!("expected conflict")
    };
    assert_eq!(body["current"]["claimed_at"], "2026-01-01T00:00:00+00:00");
}
#[test]
fn database_override_selects_the_same_sqlite_file() {
    let dir = tempfile::tempdir().unwrap();
    let mut vars = std::collections::HashMap::new();
    vars.insert(
        "DATABASE_URL".to_owned(),
        "sqlite+aiosqlite:///custom.db".to_owned(),
    );
    let settings =
        evoflux_core::config::Settings::from_vars(&vars, Some(dir.path()), dir.path()).unwrap();
    assert_eq!(
        settings.sqlite_database_path(),
        Some(std::path::PathBuf::from("custom.db"))
    );
    vars.insert(
        "DATABASE_URL".to_owned(),
        "postgresql://example/db".to_owned(),
    );
    let settings =
        evoflux_core::config::Settings::from_vars(&vars, Some(dir.path()), dir.path()).unwrap();
    assert_eq!(settings.sqlite_database_path(), None);
}
#[test]
fn unresolved_dotenv_paths_fail_closed() {
    let dir = tempfile::tempdir().unwrap();
    let mut vars = std::collections::HashMap::new();
    vars.insert(
        "DATABASE_URL".to_owned(),
        "sqlite+aiosqlite:///${DATA_ROOT}/db.sqlite".to_owned(),
    );
    let settings =
        evoflux_core::config::Settings::from_vars(&vars, Some(dir.path()), dir.path()).unwrap();
    assert_eq!(settings.sqlite_database_path(), None);
    vars.remove("DATABASE_URL");
    vars.insert("EVOFLUX_DATA_DIR".to_owned(), "${DATA_ROOT}".to_owned());
    let settings =
        evoflux_core::config::Settings::from_vars(&vars, Some(dir.path()), dir.path()).unwrap();
    assert_eq!(settings.sqlite_database_path(), None);
}
#[tokio::test]
async fn python_whitespace_is_trimmed_from_identity() {
    let (_dir, db) = setup();
    claim(&db, "\u{1c}alice\u{1f}", Some("\u{1c}phone\u{1f}"))
        .await
        .unwrap();
    claim(&db, "alice", Some("phone")).await.unwrap();
}
#[tokio::test]
async fn expired_holder_is_released_before_new_claim() {
    let (_dir, db) = setup();
    db.write(|tx| { tx.execute("INSERT INTO remote_use_sessions VALUES ('old', 'alice', 'phone', '2000-01-01 00:00:00.000000', '2000-01-01 00:00:00.000000', NULL, '2000-01-01 00:30:00.000000')", [])?; Ok(()) }).await.unwrap();
    claim(&db, "bob", Some("laptop")).await.unwrap();
    let (released, live): (i64, i64) = db.read(|c| Ok((c.query_row("SELECT count(*) FROM remote_use_sessions WHERE id='old' AND released_at IS NOT NULL", [], |r| r.get(0))?, c.query_row("SELECT count(*) FROM remote_use_sessions WHERE user_login='bob' AND released_at IS NULL", [], |r| r.get(0))?))).await.unwrap();
    assert_eq!((released, live), (1, 1));
}
#[tokio::test]
async fn repeat_claim_refreshes_last_seen_and_expiry() {
    let (_dir, db) = setup();
    claim(&db, "alice", Some("phone")).await.unwrap();
    db.write(|tx| { tx.execute("UPDATE remote_use_sessions SET last_seen_at='2000-01-01 00:00:00.000000', idle_expires_at='9999-01-01 00:00:00.000000'", [])?; Ok(()) }).await.unwrap();
    claim(&db, "alice", Some("phone")).await.unwrap();
    let (seen, expires): (String, String) = db
        .read(|c| {
            Ok(c.query_row(
                "SELECT last_seen_at, idle_expires_at FROM remote_use_sessions",
                [],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )?)
        })
        .await
        .unwrap();
    assert!(seen.as_str() > "2000-01-01 00:00:00.000000");
    assert!(expires.as_str() < "9999-01-01 00:00:00.000000");
}
