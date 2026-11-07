//! Chat transcripts: one SQLite file per session, `<agent dir>/transcripts/<chat id>.db`.
//!
//! Each file is written by exactly one process, the engine running that chat
//! (`evo-engine --session-db <file>`), through evo-harness's
//! `SqliteSessionRepo`. The desktop shell only reads them (search, fork) and
//! removes them with their chat. Keeping every chat's transcript in the shared
//! `evo.db` made all engines queue on that file's single write lock
//! (`docs/architecture/decisions/0007-one-transcript-file-per-chat.md`).
//!
//! This module owns the files' location, identity and life cycle:
//! - [`path_in`] maps a chat id to its file (ids are checked, never a path);
//! - [`prepare`] stamps a new file as an evo transcript before the harness
//!   creates its tables, and refuses any other SQLite file;
//! - [`fork`], [`remove`] and [`sweep`] are the shell's file operations;
//! - [`adopt_legacy`] moves transcripts that older builds kept in `evo.db`
//!   into their own files, once, before any engine starts.
//!
//! The session tables are evo-harness's; [`SESSION_SCHEMA`] repeats their DDL
//! so this crate (a leaf) can create a file the harness opens as its own. A
//! test in evo-engine, which links both, checks that the two stay identical.

use std::path::{Path, PathBuf};
use std::time::Duration;

use rusqlite::{params, Connection, OpenFlags, OptionalExtension, TransactionBehavior};

use crate::DbError;

/// `application_id` of a transcript file ("evoT"); `evo.db` is "evo1".
pub const APPLICATION_ID: i64 = 0x6576_6F54;

/// The folder under the agent directory that holds the transcript files.
pub const DIR_NAME: &str = "transcripts";

/// evo-harness's SQLite session tables
/// (`evo_harness::session::sqlite::SqliteSessionRepo`), byte for byte, so the
/// harness's `CREATE TABLE IF NOT EXISTS` finds them and leaves them alone.
pub const SESSION_SCHEMA: &str = "CREATE TABLE IF NOT EXISTS sessions (
                 id TEXT PRIMARY KEY,
                 created_at INTEGER NOT NULL,
                 parent_session_id TEXT,
                 state_json TEXT NOT NULL
             );
             CREATE TABLE IF NOT EXISTS progress_heads (
                 session_id TEXT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
                 sequence INTEGER NOT NULL
             );
             CREATE TABLE IF NOT EXISTS progress_frames (
                 session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                 sequence INTEGER NOT NULL, id TEXT NOT NULL, lane TEXT NOT NULL,
                 run_id TEXT NOT NULL, stream_index INTEGER NOT NULL, frame_json TEXT NOT NULL,
                 PRIMARY KEY(session_id, sequence), UNIQUE(session_id,id)
             );
             CREATE INDEX IF NOT EXISTS progress_run ON progress_frames(session_id,run_id,sequence);";

/// Suffix of a file being written by [`fork`] or [`adopt_legacy`]; renamed
/// into place when complete, removed by [`sweep`] when a crash left it.
const PARTIAL_SUFFIX: &str = ".partial";

/// Suffix of a file set aside by [`adopt_legacy`] because it disagreed with
/// the transcript kept in `evo.db`. Never removed automatically.
const CONFLICT_SUFFIX: &str = ".conflict";

/// `<agent dir>/transcripts`.
pub fn dir() -> Result<PathBuf, DbError> {
    Ok(crate::agent_dir()?.join(DIR_NAME))
}

/// The transcript file of chat `id` under the default folder.
pub fn path(id: &str) -> Result<PathBuf, DbError> {
    path_in(&dir()?, id)
}

/// The transcript file of chat `id` in `dir`. An id becomes a file name, so
/// only ASCII letters, digits, `-` and `_` are accepted (chat ids are UUIDs).
pub fn path_in(dir: &Path, id: &str) -> Result<PathBuf, DbError> {
    if !valid_id(id) {
        return Err(DbError::InvalidId(id.to_string()));
    }
    Ok(dir.join(format!("{id}.db")))
}

fn valid_id(id: &str) -> bool {
    !id.is_empty()
        && id.len() <= 128
        && id
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || byte == b'-' || byte == b'_')
}

fn io_error(path: &Path) -> impl FnOnce(std::io::Error) -> DbError + '_ {
    move |source| DbError::Io {
        path: path.to_path_buf(),
        source,
    }
}

/// Open an existing file for reading. Read-write flags (without `CREATE`):
/// a read-only connection cannot always attach to a WAL file another process
/// is writing. `query_only` keeps this connection from changing anything.
fn open_for_reading(path: &Path) -> Result<Option<Connection>, DbError> {
    if !path.exists() {
        return Ok(None);
    }
    let connection = match Connection::open_with_flags(
        path,
        OpenFlags::SQLITE_OPEN_READ_WRITE | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    ) {
        Ok(connection) => connection,
        // Removed between the check and the open.
        Err(_) if !path.exists() => return Ok(None),
        Err(error) => return Err(error.into()),
    };
    connection.busy_timeout(Duration::from_secs(5))?;
    connection.pragma_update(None, "query_only", "ON")?;
    Ok(Some(connection))
}

fn has_tables(connection: &Connection) -> rusqlite::Result<bool> {
    connection.query_row(
        "SELECT EXISTS (SELECT 1 FROM sqlite_schema WHERE type = 'table')",
        [],
        |row| row.get(0),
    )
}

/// Make `path` ready for the engine's session repository: create its folder,
/// and stamp a new (empty) file as a transcript. An existing transcript is
/// left as it is; any other SQLite file — `evo.db` included — is refused.
pub fn prepare(path: &Path) -> Result<(), DbError> {
    if let Some(dir) = path.parent() {
        std::fs::create_dir_all(dir).map_err(|source| DbError::CreateDir {
            path: dir.to_path_buf(),
            source,
        })?;
    }
    let connection = Connection::open_with_flags(
        path,
        OpenFlags::SQLITE_OPEN_READ_WRITE
            | OpenFlags::SQLITE_OPEN_CREATE
            | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )?;
    connection.busy_timeout(Duration::from_secs(5))?;
    let app_id: i64 = connection.query_row("PRAGMA application_id", [], |row| row.get(0))?;
    match app_id {
        APPLICATION_ID => Ok(()),
        0 if !has_tables(&connection)? => {
            connection.pragma_update(None, "application_id", APPLICATION_ID)?;
            Ok(())
        }
        _ => Err(DbError::Foreign {
            path: path.to_path_buf(),
        }),
    }
}

/// What kind of file `path` is, read without changing it.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FileKind {
    /// No file, or an empty one.
    New,
    /// A transcript file (this module's [`APPLICATION_ID`]).
    Transcript,
    /// The application database, `evo.db`.
    AppDatabase,
    /// Any other SQLite file.
    Other,
}

/// Tell a transcript file from `evo.db` (which older builds passed to
/// `--session-db`) and from anything else.
pub fn kind(path: &Path) -> Result<FileKind, DbError> {
    let Some(connection) = open_for_reading(path)? else {
        return Ok(FileKind::New);
    };
    let app_id: i64 = connection.query_row("PRAGMA application_id", [], |row| row.get(0))?;
    Ok(match app_id {
        APPLICATION_ID => FileKind::Transcript,
        crate::APPLICATION_ID => FileKind::AppDatabase,
        0 if !has_tables(&connection)? => FileKind::New,
        _ => FileKind::Other,
    })
}

/// The reducer snapshot (`sessions.state_json`) of session `id` in its
/// transcript file, or `None` when there is no file or no such session.
pub fn read_state(path: &Path, id: &str) -> Result<Option<String>, DbError> {
    let Some(connection) = open_for_reading(path)? else {
        return Ok(None);
    };
    let found = connection
        .query_row(
            "SELECT state_json FROM sessions WHERE id = ?1",
            [id],
            |row| row.get(0),
        )
        .optional();
    match found {
        Ok(state) => Ok(state),
        // A file whose engine never created the tables.
        Err(rusqlite::Error::SqliteFailure(_, Some(message)))
            if message.contains("no such table") =>
        {
            Ok(None)
        }
        Err(error) => Err(error.into()),
    }
}

/// One session row to write into a new transcript file.
struct SessionRow {
    id: String,
    created_at: i64,
    parent_session_id: Option<String>,
    state_json: String,
}

/// Progress rows carried along with a session (`progress_heads`, `progress_frames`).
#[derive(Default)]
struct ProgressRows {
    head: Option<i64>,
    frames: Vec<(i64, String, String, String, i64, String)>,
}

/// Write a complete transcript file at `target`: build it beside the target
/// under a partial name, flush it to disk, then rename it into place. A crash
/// leaves either no file or a partial one that [`sweep`] removes; never a
/// half-written transcript under the real name. Fails if `target` exists.
fn write_new(target: &Path, row: &SessionRow, progress: &ProgressRows) -> Result<(), DbError> {
    if let Some(dir) = target.parent() {
        std::fs::create_dir_all(dir).map_err(|source| DbError::CreateDir {
            path: dir.to_path_buf(),
            source,
        })?;
    }
    if target.exists() {
        return Err(DbError::Exists {
            path: target.to_path_buf(),
        });
    }
    let partial = with_suffix(target, PARTIAL_SUFFIX);
    remove(&partial)?;
    let written = (|| -> Result<(), DbError> {
        let mut connection = Connection::open(&partial)?;
        // A rollback journal while building, so closing leaves one complete
        // file to rename (the engine switches it to WAL when it opens it).
        connection.pragma_update(None, "journal_mode", "DELETE")?;
        connection.pragma_update(None, "synchronous", "FULL")?;
        connection.pragma_update(None, "foreign_keys", "ON")?;
        connection.pragma_update(None, "application_id", APPLICATION_ID)?;
        let tx = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        tx.execute_batch(SESSION_SCHEMA)?;
        tx.execute(
            "INSERT INTO sessions (id, created_at, parent_session_id, state_json) VALUES (?1, ?2, ?3, ?4)",
            params![row.id, row.created_at, row.parent_session_id, row.state_json],
        )?;
        if let Some(sequence) = progress.head {
            tx.execute(
                "INSERT INTO progress_heads (session_id, sequence) VALUES (?1, ?2)",
                params![row.id, sequence],
            )?;
        }
        for (sequence, id, lane, run_id, stream_index, frame_json) in &progress.frames {
            tx.execute(
                "INSERT INTO progress_frames (session_id, sequence, id, lane, run_id, stream_index, frame_json)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
                params![row.id, sequence, id, lane, run_id, stream_index, frame_json],
            )?;
        }
        tx.commit()?;
        connection
            .close()
            .map_err(|(_, error)| DbError::Sqlite(error))?;
        Ok(())
    })();
    if let Err(error) = written {
        let _ = remove(&partial);
        return Err(error);
    }
    if target.exists() {
        let _ = remove(&partial);
        return Err(DbError::Exists {
            path: target.to_path_buf(),
        });
    }
    std::fs::rename(&partial, target).map_err(io_error(target))
}

fn with_suffix(path: &Path, suffix: &str) -> PathBuf {
    let mut name = path.as_os_str().to_os_string();
    name.push(suffix);
    PathBuf::from(name)
}

/// Copy chat `source`'s transcript as chat `id`'s: the same history, a new
/// session id whose parent is `source`, created `now_ms`. Progress of a turn
/// still streaming is not copied (a fork starts idle). `Ok(false)` when
/// `source` has no transcript yet (a chat that never got a prompt).
///
/// The source may be in use by its engine; the copy is a consistent snapshot
/// of what it had committed.
pub fn fork(dir: &Path, source: &str, id: &str, now_ms: i64) -> Result<bool, DbError> {
    let from = path_in(dir, source)?;
    let to = path_in(dir, id)?;
    let Some(state_json) = read_state(&from, source)? else {
        return Ok(false);
    };
    write_new(
        &to,
        &SessionRow {
            id: id.to_string(),
            created_at: now_ms,
            parent_session_id: Some(source.to_string()),
            state_json,
        },
        &ProgressRows::default(),
    )?;
    Ok(true)
}

/// Delete a transcript file with its WAL and shared-memory files. A missing
/// file is not an error. Fails while another process has the file open on
/// Windows: stop the chat's engine first; [`sweep`] retries at next startup.
pub fn remove(path: &Path) -> Result<(), DbError> {
    for file in [
        path.to_path_buf(),
        with_suffix(path, "-wal"),
        with_suffix(path, "-shm"),
        with_suffix(path, "-journal"),
    ] {
        match std::fs::remove_file(&file) {
            Ok(()) => {}
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
            Err(error) => {
                return Err(DbError::Io {
                    path: file,
                    source: error,
                })
            }
        }
    }
    Ok(())
}

/// The chat ids that have a transcript file in `dir`.
pub fn ids_in(dir: &Path) -> Result<Vec<String>, DbError> {
    let entries = match std::fs::read_dir(dir) {
        Ok(entries) => entries,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(Vec::new()),
        Err(error) => return Err(io_error(dir)(error)),
    };
    let mut ids = Vec::new();
    for entry in entries {
        let entry = entry.map_err(io_error(dir))?;
        let name = entry.file_name();
        let Some(name) = name.to_str() else { continue };
        if let Some(id) = name.strip_suffix(".db").filter(|id| valid_id(id)) {
            ids.push(id.to_string());
        }
    }
    ids.sort();
    Ok(ids)
}

/// Total size in bytes and number of the transcript files in `dir`.
pub fn usage(dir: &Path) -> (u64, usize) {
    let Ok(entries) = std::fs::read_dir(dir) else {
        return (0, 0);
    };
    let mut bytes = 0;
    let mut files = 0;
    for entry in entries.flatten() {
        let name = entry.file_name();
        let name = name.to_string_lossy();
        if let Ok(metadata) = entry.metadata() {
            if metadata.is_file() {
                bytes += metadata.len();
                if name.ends_with(".db") {
                    files += 1;
                }
            }
        }
    }
    (bytes, files)
}

/// What [`sweep`] removed.
#[derive(Debug, Default, PartialEq, Eq)]
pub struct Swept {
    /// Transcripts whose chat no longer exists.
    pub orphans: Vec<String>,
    /// Files that could not be removed (still open somewhere); retried next time.
    pub failed: Vec<String>,
}

/// Remove the transcripts of chats that no longer exist in `evo.db` (drafts
/// that never got a prompt, chats deleted while their file was in use) and the
/// partial files a crash left. Call only while no engine runs.
pub fn sweep(conn: &Connection, dir: &Path) -> Result<Swept, DbError> {
    let mut swept = Swept::default();
    let entries = match std::fs::read_dir(dir) {
        Ok(entries) => entries,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(swept),
        Err(error) => return Err(io_error(dir)(error)),
    };
    let mut statement = conn.prepare("SELECT EXISTS (SELECT 1 FROM chats WHERE id = ?1)")?;
    for entry in entries.flatten() {
        let name = entry.file_name();
        let Some(name) = name.to_str() else { continue };
        if let Some(stem) = name.strip_suffix(PARTIAL_SUFFIX) {
            if stem.ends_with(".db") {
                let _ = std::fs::remove_file(entry.path());
                let _ = std::fs::remove_file(with_suffix(&entry.path(), "-journal"));
            }
            continue;
        }
        let Some(id) = name.strip_suffix(".db").filter(|id| valid_id(id)) else {
            continue;
        };
        let exists: bool = statement.query_row([id], |row| row.get(0))?;
        if exists {
            continue;
        }
        match remove(&entry.path()) {
            Ok(()) => swept.orphans.push(id.to_string()),
            Err(_) => swept.failed.push(id.to_string()),
        }
    }
    swept.orphans.sort();
    swept.failed.sort();
    Ok(swept)
}

/// What [`adopt_legacy`] did.
#[derive(Debug, Default, PartialEq, Eq)]
pub struct Adopted {
    /// Chats whose transcript moved from `evo.db` into its own file.
    pub moved: Vec<String>,
    /// Chats whose file already held the same transcript (a crash after the
    /// copy, before the `evo.db` row was removed).
    pub already: Vec<String>,
    /// Chats whose existing file disagreed with `evo.db`; the file was set
    /// aside as `<id>.db.conflict-<ms>` and `evo.db`'s transcript adopted.
    pub conflicts: Vec<String>,
    /// `evo.db` transcripts without a chat (drafts), dropped as before.
    pub dropped: usize,
}

/// Whether `evo.db` still holds chat `id`'s transcript (an older build wrote
/// it there and [`adopt_legacy`] has not moved it yet).
pub fn has_legacy(conn: &Connection, id: &str) -> Result<bool, DbError> {
    let found = conn.query_row(
        "SELECT EXISTS (SELECT 1 FROM sessions WHERE id = ?1)",
        [id],
        |row| row.get(0),
    );
    match found {
        Ok(found) => Ok(found),
        Err(rusqlite::Error::SqliteFailure(_, Some(message)))
            if message.contains("no such table") =>
        {
            Ok(false)
        }
        Err(error) => Err(error.into()),
    }
}

/// Move every transcript that older builds kept in `evo.db` (the `sessions`,
/// `progress_heads` and `progress_frames` rows) into its own file in `dir`,
/// then delete the rows. Each chat is copied, flushed and renamed into place
/// before its rows go, so a crash at any point loses nothing and the next run
/// finishes the job. Transcripts with no chat are dropped (as the startup
/// cleanup always did). Call before any engine starts.
pub fn adopt_legacy(conn: &mut Connection, dir: &Path) -> Result<Adopted, DbError> {
    let mut adopted = Adopted::default();
    let dropped = conn.execute(
        "DELETE FROM sessions WHERE id NOT IN (SELECT id FROM chats)",
        [],
    )?;
    adopted.dropped = dropped;
    let ids: Vec<String> = {
        let mut statement = conn.prepare("SELECT id FROM sessions ORDER BY id")?;
        let rows = statement.query_map([], |row| row.get(0))?;
        rows.collect::<Result<_, _>>()?
    };
    for id in ids {
        let row: SessionRow = conn.query_row(
            "SELECT id, created_at, parent_session_id, state_json FROM sessions WHERE id = ?1",
            [&id],
            |row| {
                Ok(SessionRow {
                    id: row.get(0)?,
                    created_at: row.get(1)?,
                    parent_session_id: row.get(2)?,
                    state_json: row.get(3)?,
                })
            },
        )?;
        let target = match path_in(dir, &id) {
            Ok(target) => target,
            // Not a file name: leave the row where it is, as it was.
            Err(_) => continue,
        };
        if target.exists() {
            match read_state(&target, &id) {
                Ok(Some(state)) if state == row.state_json => {
                    conn.execute("DELETE FROM sessions WHERE id = ?1", [&id])?;
                    adopted.already.push(id);
                    continue;
                }
                _ => {
                    let aside = with_suffix(
                        &target,
                        &format!("{CONFLICT_SUFFIX}-{}", crate::chats::now_ms()),
                    );
                    std::fs::rename(&target, &aside).map_err(io_error(&target))?;
                    for suffix in ["-wal", "-shm"] {
                        let _ = std::fs::rename(
                            with_suffix(&target, suffix),
                            with_suffix(&aside, suffix),
                        );
                    }
                    adopted.conflicts.push(id.clone());
                }
            }
        }
        let mut progress = ProgressRows {
            head: conn
                .query_row(
                    "SELECT sequence FROM progress_heads WHERE session_id = ?1",
                    [&id],
                    |row| row.get(0),
                )
                .optional()?,
            frames: Vec::new(),
        };
        {
            let mut statement = conn.prepare(
                "SELECT sequence, id, lane, run_id, stream_index, frame_json FROM progress_frames
                 WHERE session_id = ?1 ORDER BY sequence",
            )?;
            let rows = statement.query_map([&id], |row| {
                Ok((
                    row.get(0)?,
                    row.get(1)?,
                    row.get(2)?,
                    row.get(3)?,
                    row.get(4)?,
                    row.get(5)?,
                ))
            })?;
            progress.frames = rows.collect::<Result<_, _>>()?;
        }
        write_new(&target, &row, &progress)?;
        let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
        tx.execute("DELETE FROM progress_frames WHERE session_id = ?1", [&id])?;
        tx.execute("DELETE FROM progress_heads WHERE session_id = ?1", [&id])?;
        tx.execute("DELETE FROM sessions WHERE id = ?1", [&id])?;
        tx.commit()?;
        if !adopted.conflicts.contains(&id) {
            adopted.moved.push(id);
        }
    }
    Ok(adopted)
}

/// A cheap fingerprint of a transcript's files (size and modification time
/// of the file and its WAL), to tell whether it changed since it was last
/// read. `None` when there is no file.
pub fn stamp(path: &Path) -> Option<String> {
    let part = |path: &Path| {
        std::fs::metadata(path).ok().map(|metadata| {
            let modified = metadata
                .modified()
                .ok()
                .and_then(|time| time.duration_since(std::time::UNIX_EPOCH).ok())
                .map_or(0, |since| since.as_nanos());
            format!("{}:{modified}", metadata.len())
        })
    };
    let main = part(path)?;
    let wal = part(&with_suffix(path, "-wal")).unwrap_or_default();
    Some(format!("{main};{wal}"))
}

/// The text a person might search a transcript for: every string in the
/// reducer snapshot except identifiers, type tags, image data and signatures,
/// one per line.
pub fn searchable_text(state_json: &str) -> String {
    fn skip(key: &str) -> bool {
        matches!(key, "id" | "type" | "role" | "data" | "mimeType" | "api")
            || key.ends_with("Id")
            || key.to_ascii_lowercase().contains("signature")
    }
    fn walk(value: &serde_json::Value, out: &mut String) {
        match value {
            serde_json::Value::String(text) if !text.is_empty() => {
                out.push_str(text);
                out.push('\n');
            }
            serde_json::Value::Array(items) => items.iter().for_each(|item| walk(item, out)),
            serde_json::Value::Object(map) => {
                for (key, value) in map {
                    if !skip(key) {
                        walk(value, out);
                    }
                }
            }
            _ => {}
        }
    }
    match serde_json::from_str::<serde_json::Value>(state_json) {
        Ok(value) => {
            let mut out = String::new();
            walk(&value, &mut out);
            out
        }
        // Not JSON (never written by the harness): search the raw text.
        Err(_) => state_json.to_string(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn app_db(dir: &Path) -> Connection {
        crate::open_at(&dir.join("evo.db")).unwrap()
    }

    fn chat(conn: &Connection, id: &str) {
        crate::chats::create_chat(
            conn,
            &crate::chats::NewChat {
                id: id.into(),
                title: id.into(),
                ..Default::default()
            },
        )
        .unwrap();
    }

    /// A transcript file as the engine leaves it: prepared, then the
    /// harness's tables and one session row.
    fn transcript(dir: &Path, id: &str, state: &str) -> PathBuf {
        let path = path_in(dir, id).unwrap();
        prepare(&path).unwrap();
        let conn = Connection::open(&path).unwrap();
        conn.pragma_update(None, "journal_mode", "WAL").unwrap();
        conn.execute_batch(SESSION_SCHEMA).unwrap();
        conn.execute(
            "INSERT INTO sessions (id, created_at, parent_session_id, state_json) VALUES (?1, 1, NULL, ?2)",
            params![id, state],
        )
        .unwrap();
        path
    }

    fn legacy(conn: &Connection, id: &str, state: &str) {
        conn.execute(
            "INSERT INTO sessions (id, created_at, parent_session_id, state_json) VALUES (?1, 7, 'p', ?2)",
            params![id, state],
        )
        .unwrap();
    }

    #[test]
    fn ids_become_file_names_only_when_safe() {
        let dir = Path::new("/t");
        assert_eq!(
            path_in(dir, "0b7e4c2a-9f1d-4e6b-8a3c-2d5f6e7a8b9c").unwrap(),
            dir.join("0b7e4c2a-9f1d-4e6b-8a3c-2d5f6e7a8b9c.db")
        );
        assert!(path_in(dir, "chat_1").is_ok());
        for bad in [
            "",
            "..",
            "../evo",
            "a/b",
            "a\\b",
            "a.db",
            "c:x",
            "é",
            &"x".repeat(129),
        ] {
            assert!(
                matches!(path_in(dir, bad), Err(DbError::InvalidId(_))),
                "{bad:?} must be refused"
            );
        }
    }

    #[test]
    fn prepare_stamps_new_files_and_refuses_others() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("nested").join("a.db");
        prepare(&path).unwrap();
        assert_eq!(kind(&path).unwrap(), FileKind::Transcript);
        // Idempotent.
        prepare(&path).unwrap();

        let app = dir.path().join("evo.db");
        drop(crate::open_at(&app).unwrap());
        assert_eq!(kind(&app).unwrap(), FileKind::AppDatabase);
        assert!(matches!(prepare(&app), Err(DbError::Foreign { .. })));

        let other = dir.path().join("other.db");
        Connection::open(&other)
            .unwrap()
            .execute_batch("CREATE TABLE t (x);")
            .unwrap();
        assert_eq!(kind(&other).unwrap(), FileKind::Other);
        assert!(matches!(prepare(&other), Err(DbError::Foreign { .. })));

        assert_eq!(kind(&dir.path().join("missing.db")).unwrap(), FileKind::New);
        assert!(
            !dir.path().join("missing.db").exists(),
            "kind never creates a file"
        );
    }

    #[test]
    fn fork_copies_the_committed_history_under_a_new_id() {
        let dir = tempfile::tempdir().unwrap();
        let source = transcript(dir.path(), "src", r#"{"records":["hello"]}"#);
        // The source stays open and in use while it is copied.
        let writer = Connection::open(&source).unwrap();
        writer
            .execute(
                "UPDATE sessions SET state_json = ?1",
                [r#"{"records":["hello","world"]}"#],
            )
            .unwrap();
        assert!(fork(dir.path(), "src", "copy", 42).unwrap());
        let copy = path_in(dir.path(), "copy").unwrap();
        assert_eq!(kind(&copy).unwrap(), FileKind::Transcript);
        let conn = Connection::open(&copy).unwrap();
        let (created, parent, state): (i64, Option<String>, String) = conn
            .query_row(
                "SELECT created_at, parent_session_id, state_json FROM sessions WHERE id = 'copy'",
                [],
                |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
            )
            .unwrap();
        assert_eq!(
            (created, parent.as_deref(), state.as_str()),
            (42, Some("src"), r#"{"records":["hello","world"]}"#)
        );
        assert!(!with_suffix(&copy, PARTIAL_SUFFIX).exists());

        // A chat that never got a prompt has nothing to copy.
        assert!(!fork(dir.path(), "never", "copy2", 1).unwrap());
        assert!(!path_in(dir.path(), "copy2").unwrap().exists());
        // A fork never overwrites a transcript.
        assert!(matches!(
            fork(dir.path(), "src", "copy", 43),
            Err(DbError::Exists { .. })
        ));
    }

    #[test]
    fn remove_deletes_the_file_and_its_companions() {
        let dir = tempfile::tempdir().unwrap();
        let path = transcript(dir.path(), "a", "{}");
        std::fs::write(with_suffix(&path, "-shm"), b"x").unwrap();
        remove(&path).unwrap();
        for suffix in ["", "-wal", "-shm", "-journal"] {
            assert!(!with_suffix(&path, suffix).exists(), "{suffix}");
        }
        // Missing is fine.
        remove(&path).unwrap();
    }

    #[test]
    fn sweep_removes_orphans_and_partials_only() {
        let dir = tempfile::tempdir().unwrap();
        let conn = app_db(dir.path());
        let files = dir.path().join(DIR_NAME);
        chat(&conn, "kept");
        transcript(&files, "kept", "{}");
        transcript(&files, "orphan", "{}");
        std::fs::write(files.join("half.db.partial"), b"x").unwrap();
        std::fs::write(files.join("x.db.conflict-1"), b"x").unwrap();
        std::fs::write(files.join("notes.txt"), b"x").unwrap();
        let swept = sweep(&conn, &files).unwrap();
        assert_eq!(
            swept,
            Swept {
                orphans: vec!["orphan".into()],
                failed: vec![]
            }
        );
        assert!(files.join("kept.db").exists());
        assert!(!files.join("orphan.db").exists());
        assert!(!files.join("half.db.partial").exists());
        assert!(
            files.join("x.db.conflict-1").exists(),
            "conflicts are kept for the person"
        );
        assert!(files.join("notes.txt").exists());
        assert_eq!(ids_in(&files).unwrap(), vec!["kept".to_string()]);
        // A missing folder is nothing to sweep.
        assert_eq!(
            sweep(&conn, &dir.path().join("none")).unwrap(),
            Swept::default()
        );
    }

    /// Windows refuses to delete a file another handle has open: the sweep
    /// reports it and keeps going instead of failing the startup.
    #[cfg(windows)]
    #[test]
    fn sweep_reports_a_file_still_in_use() {
        let dir = tempfile::tempdir().unwrap();
        let conn = app_db(dir.path());
        let files = dir.path().join(DIR_NAME);
        let busy = transcript(&files, "busy", "{}");
        transcript(&files, "gone", "{}");
        let holder = Connection::open(&busy).unwrap();
        holder
            .query_row("SELECT COUNT(*) FROM sessions", [], |row| {
                row.get::<_, i64>(0)
            })
            .unwrap();
        let swept = sweep(&conn, &files).unwrap();
        assert_eq!(swept.orphans, vec!["gone".to_string()]);
        assert_eq!(swept.failed, vec!["busy".to_string()]);
        drop(holder);
        assert_eq!(
            sweep(&conn, &files).unwrap().orphans,
            vec!["busy".to_string()]
        );
    }

    #[test]
    fn adopt_moves_legacy_transcripts_with_their_progress() {
        let dir = tempfile::tempdir().unwrap();
        let mut conn = app_db(dir.path());
        let files = dir.path().join(DIR_NAME);
        chat(&conn, "a");
        chat(&conn, "b");
        legacy(&conn, "a", r#"{"records":["a"]}"#);
        legacy(&conn, "b", r#"{"records":["b"]}"#);
        legacy(&conn, "draft", "{}");
        conn.execute_batch(
            "INSERT INTO progress_heads (session_id, sequence) VALUES ('a', 2);
             INSERT INTO progress_frames (session_id, sequence, id, lane, run_id, stream_index, frame_json)
             VALUES ('a', 1, 'f1', 'main', 'r', 0, '{}'), ('a', 2, 'f2', 'main', 'r', 1, '{}');",
        )
        .unwrap();
        assert!(has_legacy(&conn, "a").unwrap());

        let adopted = adopt_legacy(&mut conn, &files).unwrap();
        assert_eq!(adopted.moved, vec!["a".to_string(), "b".to_string()]);
        assert_eq!(adopted.dropped, 1);
        assert!(!has_legacy(&conn, "a").unwrap());
        let left: i64 = conn
            .query_row(
                "SELECT (SELECT COUNT(*) FROM sessions) + (SELECT COUNT(*) FROM progress_heads) + (SELECT COUNT(*) FROM progress_frames)",
                [],
                |row| row.get(0),
            )
            .unwrap();
        assert_eq!(left, 0);

        let a = path_in(&files, "a").unwrap();
        assert_eq!(kind(&a).unwrap(), FileKind::Transcript);
        assert_eq!(
            read_state(&a, "a").unwrap().as_deref(),
            Some(r#"{"records":["a"]}"#)
        );
        let file = Connection::open(&a).unwrap();
        let (created, parent, head, frames): (i64, String, i64, i64) = file
            .query_row(
                "SELECT s.created_at, s.parent_session_id, h.sequence, (SELECT COUNT(*) FROM progress_frames)
                 FROM sessions s JOIN progress_heads h ON h.session_id = s.id",
                [],
                |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?, row.get(3)?)),
            )
            .unwrap();
        assert_eq!((created, parent.as_str(), head, frames), (7, "p", 2, 2));

        // Nothing left to do on the next start.
        assert_eq!(adopt_legacy(&mut conn, &files).unwrap(), Adopted::default());
    }

    #[test]
    fn adopt_finishes_after_a_crash_and_keeps_disagreeing_files() {
        let dir = tempfile::tempdir().unwrap();
        let mut conn = app_db(dir.path());
        let files = dir.path().join(DIR_NAME);
        chat(&conn, "done");
        chat(&conn, "clash");
        // A crash after the copy: the file matches, the row is still there.
        legacy(&conn, "done", r#"{"v":1}"#);
        transcript(&files, "done", r#"{"v":1}"#);
        // A file that does not hold evo.db's transcript.
        legacy(&conn, "clash", r#"{"v":"legacy"}"#);
        transcript(&files, "clash", r#"{"v":"other"}"#);
        // A partial copy from the crash.
        std::fs::write(files.join("done.db.partial"), b"half").unwrap();

        let adopted = adopt_legacy(&mut conn, &files).unwrap();
        assert_eq!(adopted.already, vec!["done".to_string()]);
        assert_eq!(adopted.conflicts, vec!["clash".to_string()]);
        assert!(adopted.moved.is_empty());
        assert_eq!(
            read_state(&path_in(&files, "clash").unwrap(), "clash")
                .unwrap()
                .as_deref(),
            Some(r#"{"v":"legacy"}"#)
        );
        let aside: Vec<_> = std::fs::read_dir(&files)
            .unwrap()
            .flatten()
            .map(|entry| entry.file_name().to_string_lossy().into_owned())
            .filter(|name| {
                name.starts_with("clash.db.conflict-")
                    && !name.ends_with("-wal")
                    && !name.ends_with("-shm")
            })
            .collect();
        assert_eq!(aside.len(), 1, "the other file is kept aside");
        assert!(!has_legacy(&conn, "done").unwrap());
        assert!(!has_legacy(&conn, "clash").unwrap());
    }

    #[test]
    fn stamp_changes_when_the_transcript_is_written() {
        let dir = tempfile::tempdir().unwrap();
        assert_eq!(stamp(&dir.path().join("none.db")), None);
        let path = transcript(dir.path(), "a", "{}");
        let before = stamp(&path).unwrap();
        std::thread::sleep(Duration::from_millis(20));
        let conn = Connection::open(&path).unwrap();
        conn.execute(
            "UPDATE sessions SET state_json = ?1",
            [r#"{"x":"a longer state"}"#],
        )
        .unwrap();
        assert_ne!(stamp(&path).unwrap(), before);
    }

    #[test]
    fn searchable_text_keeps_words_not_identifiers_or_data() {
        let state = r#"{"records":[{"type":"message","id":"e1","parentId":"e0",
            "message":{"role":"user","content":[{"type":"text","text":"Fix the parser"},
            {"type":"image","data":"iVBORw0KGgo","mimeType":"image/png"}]}},
            {"type":"message","message":{"role":"assistant","content":[
            {"type":"thinking","thinking":"look at lexer","thinkingSignature":"c2ln"},
            {"type":"toolCall","id":"t1","name":"read","arguments":{"path":"src/lexer.rs"}}]}}]}"#;
        let text = searchable_text(state);
        for word in ["Fix the parser", "look at lexer", "read", "src/lexer.rs"] {
            assert!(text.contains(word), "{word} missing from {text:?}");
        }
        for noise in [
            "iVBORw0KGgo",
            "c2ln",
            "e1",
            "e0",
            "t1",
            "image/png",
            "toolCall",
        ] {
            assert!(!text.contains(noise), "{noise} should not be indexed");
        }
        assert_eq!(searchable_text("not json"), "not json");
    }
}
