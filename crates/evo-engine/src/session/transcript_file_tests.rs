//! `--session-db` with one transcript file per chat (ADR 0007): the files
//! evo-store makes (fork, moved from `evo.db`) and the ones the harness makes
//! must be the same thing.

use super::*;
use evo_harness::session::types::{EntryQuery, ProvisionedEntry, ProvisionedKind};

fn schema(path: &Path) -> Vec<(String, String)> {
    let conn = rusqlite::Connection::open(path).unwrap();
    let mut statement = conn
        .prepare("SELECT name, sql FROM sqlite_schema WHERE sql IS NOT NULL ORDER BY name")
        .unwrap();
    let rows = statement
        .query_map([], |row| {
            Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?))
        })
        .unwrap();
    rows.map(|row| {
        let (name, sql) = row.unwrap();
        (name, sql.split_whitespace().collect::<Vec<_>>().join(" "))
    })
    .collect()
}

fn app_id(path: &Path) -> i64 {
    rusqlite::Connection::open(path)
        .unwrap()
        .query_row("PRAGMA application_id", [], |row| row.get(0))
        .unwrap()
}

async fn open(path: &Path, id: &str) -> Session {
    match database_session(path, id).await {
        Ok(session) => session,
        Err(error) => panic!("open {}: {error}", path.display()),
    }
}

async fn say(session: &Session, id: &str, text: &str) {
    session
        .storage()
        .append_entry(
            ProvisionedEntry {
                id: id.into(),
                kind: ProvisionedKind::Message {
                    message: evo_agent::message::AgentMessage::from(
                        evo_ai::types::UserMessage::new(text, 1),
                    ),
                    terminate: None,
                },
            },
            "main",
        )
        .await
        .unwrap();
}

async fn entries(session: &Session) -> usize {
    session
        .storage()
        .find_entries(&EntryQuery::default())
        .await
        .unwrap()
        .len()
}

#[test]
fn evo_store_writes_the_harness_session_schema() {
    let dir = tempfile::tempdir().unwrap();
    let harness = dir.path().join("harness.db");
    drop(evo_harness::session::sqlite::SqliteSessionRepo::open(&harness).unwrap());
    let store = dir.path().join("store.db");
    rusqlite::Connection::open(&store)
        .unwrap()
        .execute_batch(evo_store::transcripts::SESSION_SCHEMA)
        .unwrap();
    assert_eq!(schema(&store), schema(&harness));
    assert!(!schema(&harness).is_empty());
}

#[tokio::test]
async fn a_new_transcript_file_holds_only_the_session() {
    let dir = tempfile::tempdir().unwrap();
    let path = evo_store::transcripts::path_in(&dir.path().join("transcripts"), "chat-1").unwrap();
    let session = open(&path, "chat-1").await;
    say(&session, "m1", "hello").await;
    assert_eq!(app_id(&path), evo_store::transcripts::APPLICATION_ID);
    let tables: Vec<String> = schema(&path)
        .into_iter()
        .map(|(name, _)| name)
        .filter(|name| !name.starts_with("sqlite_"))
        .collect();
    assert_eq!(
        tables,
        [
            "progress_frames",
            "progress_heads",
            "progress_run",
            "sessions"
        ],
        "no app tables in a transcript file"
    );
    drop(session);

    // Reopening continues the same session.
    let again = open(&path, "chat-1").await;
    assert_eq!(entries(&again).await, 1);
}

#[tokio::test]
async fn files_evo_store_makes_open_as_sessions() {
    let dir = tempfile::tempdir().unwrap();
    let files = dir.path().join("transcripts");
    let source = open(
        &evo_store::transcripts::path_in(&files, "src").unwrap(),
        "src",
    )
    .await;
    say(&source, "m1", "one").await;
    say(&source, "m2", "two").await;

    // A fork, taken while the source engine still has its file open.
    assert!(evo_store::transcripts::fork(&files, "src", "copy", 5).unwrap());
    let copy = open(
        &evo_store::transcripts::path_in(&files, "copy").unwrap(),
        "copy",
    )
    .await;
    assert_eq!(entries(&copy).await, 2);
    assert_eq!(
        copy.storage().metadata().parent_session_id.as_deref(),
        Some("src")
    );
    say(&copy, "m3", "three").await;
    assert_eq!(entries(&copy).await, 3);
    assert_eq!(entries(&source).await, 2, "the source is untouched");

    // A transcript an older build kept in evo.db, moved into its own file.
    let app = dir.path().join("evo.db");
    let mut conn = evo_store::open_at(&app).unwrap();
    let legacy = open(&app, "old").await;
    say(&legacy, "m1", "from evo.db").await;
    drop(legacy);
    evo_store::chats::create_chat(
        &conn,
        &evo_store::chats::NewChat {
            id: "old".into(),
            title: "Old".into(),
            ..Default::default()
        },
    )
    .unwrap();
    let adopted = evo_store::transcripts::adopt_legacy(&mut conn, &files).unwrap();
    assert_eq!(adopted.moved, vec!["old".to_string()]);
    let moved = open(
        &evo_store::transcripts::path_in(&files, "old").unwrap(),
        "old",
    )
    .await;
    assert_eq!(entries(&moved).await, 1);
}

#[tokio::test]
async fn other_sqlite_files_are_refused() {
    let dir = tempfile::tempdir().unwrap();
    let other = dir.path().join("other.db");
    rusqlite::Connection::open(&other)
        .unwrap()
        .execute_batch("CREATE TABLE notes (x);")
        .unwrap();
    let error = match database_session(&other, "x").await {
        Ok(_) => panic!("a foreign file must be refused"),
        Err(error) => error.to_string(),
    };
    assert!(error.contains("not an evo transcript"), "{error}");
}

/// Two chats write at once, each into its own file: neither waits on the
/// other's write lock (the reason for ADR 0007).
#[tokio::test]
async fn chats_in_separate_files_do_not_share_a_lock() {
    let dir = tempfile::tempdir().unwrap();
    let files = dir.path().join("transcripts");
    let a_path = evo_store::transcripts::path_in(&files, "a").unwrap();
    let a = open(&a_path, "a").await;
    let b = open(&evo_store::transcripts::path_in(&files, "b").unwrap(), "b").await;
    // Another process holds chat a's write lock for a while.
    let holder = rusqlite::Connection::open(&a_path).unwrap();
    holder.execute_batch("BEGIN IMMEDIATE").unwrap();
    let started = std::time::Instant::now();
    say(&b, "m1", "not blocked").await;
    assert!(
        started.elapsed() < std::time::Duration::from_secs(1),
        "chat b waited {:?} on chat a's lock",
        started.elapsed()
    );
    holder.execute_batch("COMMIT").unwrap();
    say(&a, "m1", "after the lock").await;
    assert_eq!(entries(&a).await, 1);
    assert_eq!(entries(&b).await, 1);
}
