//! evo's application database (`~/.evo/agent/evo.db`) and chat transcript
//! files, stored on this machine.
//!
//! `evo.db` holds what the desktop and the engine share: provider settings,
//! the models.dev cache, workspaces and chats, the chats' search text, shared
//! app settings, mail between sessions, usage and cost history and the run
//! log. Both the engine and
//! the desktop shell open it through this crate, so there is one schema and
//! one migration history (`docs/features/app-database/spec.md`).
//!
//! Each chat's transcript is a file of its own (`transcripts/<chat id>.db`,
//! [`transcripts`]), written only by that chat's engine, so engines never wait
//! on one another's write lock
//! (`docs/architecture/decisions/0007-one-transcript-file-per-chat.md`).
//! Older builds kept transcripts in `evo.db`; the shell moves them out at
//! startup ([`transcripts::adopt_legacy`]).
//!
//! # Migrations
//!
//! Schema changes are numbered SQL files under `migrations/`, embedded in the
//! binary and listed in [`MIGRATIONS`]. Opening the database applies every
//! pending migration, each in its own transaction, and records it in
//! `schema_migrations` with a checksum of its SQL; `PRAGMA user_version`
//! mirrors the newest applied version so external tools can read it cheaply.
//!
//! Rules (enforced at open):
//! - migrations are append-only: an applied migration whose SQL changed is an
//!   error rather than a silent divergence between installs (line endings do
//!   not count: a CRLF checkout of the same SQL is the same migration);
//! - a database written by a newer engine (a version this binary does not
//!   know) is refused instead of being written by older code;
//! - versions are contiguous from 1.
//!
//! The shell and every engine (one per open chat) share `evo.db`: it runs in
//! WAL mode with a busy timeout, every write transaction takes the write lock
//! up front (`BEGIN IMMEDIATE`), and migration does too, so two processes
//! starting at once apply each migration exactly once.

use std::path::{Path, PathBuf};
use std::time::Duration;

use rusqlite::{Connection, OpenFlags, TransactionBehavior};
use sha2::{Digest, Sha256};

/// One schema step.
pub struct Migration {
    pub version: i64,
    pub name: &'static str,
    pub sql: &'static str,
}

pub mod chats;
pub mod logs;
pub mod mail;
pub mod settings;
pub mod transcripts;
pub mod usage;

/// The SQLite binding this crate is built on, for callers that hold a connection.
pub use rusqlite;

/// Every migration, in order. Append only — never edit or reorder an entry
/// that has shipped; write a new migration instead.
pub const MIGRATIONS: &[Migration] = &[
    Migration {
        version: 1,
        name: "provider_settings",
        sql: include_str!("migrations/0001_provider_settings.sql"),
    },
    Migration {
        version: 2,
        name: "models_dev",
        sql: include_str!("migrations/0002_models_dev.sql"),
    },
    Migration {
        version: 3,
        name: "chats_sessions_logs",
        sql: include_str!("migrations/0003_chats_sessions_logs.sql"),
    },
    Migration {
        version: 4,
        name: "chat_parents",
        sql: include_str!("migrations/0004_chat_parents.sql"),
    },
    Migration {
        version: 5,
        name: "chat_worktrees",
        sql: include_str!("migrations/0005_chat_worktrees.sql"),
    },
    Migration {
        version: 6,
        name: "mail",
        sql: include_str!("migrations/0006_mail.sql"),
    },
    Migration {
        version: 7,
        name: "chat_search",
        sql: include_str!("migrations/0007_chat_search.sql"),
    },
    Migration {
        version: 8,
        name: "usage_events",
        sql: include_str!("migrations/0008_usage_events.sql"),
    },
    Migration {
        version: 9,
        name: "usage_durations",
        sql: include_str!("migrations/0009_usage_durations.sql"),
    },
];

/// `application_id` stamped on the file ("evo1"), so tools and evo itself can
/// tell an evo database from any other SQLite file.
const APPLICATION_ID: i64 = 0x6576_6F31;

#[derive(Debug, thiserror::Error)]
pub enum DbError {
    #[error("could not locate the evo config directory: {0}")]
    Config(String),
    #[error("could not create {path}: {source}")]
    CreateDir {
        path: PathBuf,
        #[source]
        source: std::io::Error,
    },
    #[error("database error: {0}")]
    Sqlite(#[from] rusqlite::Error),
    #[error("{path} is not an evo database")]
    Foreign { path: PathBuf },
    #[error(
        "{path} was written by a newer evo (schema {found}, this build knows {known}); update evo"
    )]
    TooNew {
        path: PathBuf,
        found: i64,
        known: i64,
    },
    #[error(
        "migration {version} ({name}) changed after it was applied; add a new migration instead"
    )]
    Tampered { version: i64, name: String },
    #[error("{0:?} is not a valid chat id")]
    InvalidId(String),
    #[error("{path} already exists")]
    Exists { path: PathBuf },
    #[error("{path}: {source}")]
    Io {
        path: PathBuf,
        #[source]
        source: std::io::Error,
    },
}

/// `EVO_CODING_AGENT_DIR` (absolute), else `~/.evo/agent` — the engine's
/// agent directory, so engine and desktop open the same file.
pub fn agent_dir() -> Result<PathBuf, DbError> {
    if let Some(value) = std::env::var_os("EVO_CODING_AGENT_DIR") {
        let path = PathBuf::from(&value);
        if !path.is_absolute() {
            return Err(DbError::Config(format!(
                "EVO_CODING_AGENT_DIR={} is not an absolute path",
                path.display()
            )));
        }
        return Ok(path);
    }
    dirs::home_dir()
        .map(|home| home.join(".evo").join("agent"))
        .ok_or_else(|| DbError::Config("no home directory".into()))
}

pub fn db_path() -> Result<PathBuf, DbError> {
    Ok(agent_dir()?.join("evo.db"))
}

/// Unix seconds.
pub fn now() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0)
}

/// Open (creating and migrating as needed) the application database.
pub fn open() -> Result<Connection, DbError> {
    open_at(&db_path()?)
}

pub fn open_at(path: &Path) -> Result<Connection, DbError> {
    if let Some(dir) = path.parent() {
        std::fs::create_dir_all(dir).map_err(|source| DbError::CreateDir {
            path: dir.to_path_buf(),
            source,
        })?;
    }
    let mut connection = Connection::open_with_flags(
        path,
        OpenFlags::SQLITE_OPEN_READ_WRITE
            | OpenFlags::SQLITE_OPEN_CREATE
            | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )?;
    connection.busy_timeout(Duration::from_secs(5))?;
    enable_wal(&connection)?;
    connection.pragma_update(None, "foreign_keys", "ON")?;
    connection.pragma_update(None, "synchronous", "NORMAL")?;
    migrate(&mut connection, path, MIGRATIONS)?;
    Ok(connection)
}

/// Switch to WAL unless the database already uses it. Changing the journal
/// mode ignores the busy timeout, so a connection opened while another
/// process (the app, a chat's engine) holds the database retries for a while.
fn enable_wal(connection: &Connection) -> rusqlite::Result<()> {
    let mut attempt = 0;
    loop {
        let result = connection
            .query_row("PRAGMA journal_mode", [], |row| row.get::<_, String>(0))
            .and_then(|mode| {
                if mode.eq_ignore_ascii_case("wal") {
                    Ok(mode)
                } else {
                    connection.query_row("PRAGMA journal_mode = WAL", [], |row| {
                        row.get::<_, String>(0)
                    })
                }
            });
        match result {
            Ok(_) => return Ok(()),
            Err(rusqlite::Error::SqliteFailure(error, _))
                if matches!(
                    error.code,
                    rusqlite::ErrorCode::DatabaseBusy | rusqlite::ErrorCode::DatabaseLocked
                ) && attempt < 100 =>
            {
                attempt += 1;
                std::thread::sleep(Duration::from_millis(50));
            }
            Err(error) => return Err(error),
        }
    }
}

fn sha256_hex(text: &str) -> String {
    let digest = Sha256::digest(text.as_bytes());
    digest.iter().map(|byte| format!("{byte:02x}")).collect()
}

/// The checksum recorded for a migration: SHA-256 of its SQL with CRLF line
/// endings turned into LF. `include_str!` embeds the file as checked out, and
/// Git on Windows (`core.autocrlf`) may check it out with CRLF; the same SQL
/// must not read as "changed after it was applied" because of that.
fn checksum(sql: &str) -> String {
    sha256_hex(&sql.replace("\r\n", "\n"))
}

/// Whether `recorded` is the checksum of `sql`. Builds before line endings
/// were normalized recorded the file's raw bytes, LF or CRLF; both still
/// match, so no existing database needs repairing.
fn checksum_matches(recorded: &str, sql: &str) -> bool {
    let lf = sql.replace("\r\n", "\n");
    recorded == sha256_hex(&lf) || recorded == sha256_hex(&lf.replace('\n', "\r\n"))
}

/// Whether the database is evo's and has exactly `migrations` applied, with
/// matching checksums — read only, no write lock. Anything else (a new file,
/// a pending, newer or changed migration, an error) is `false` and left to
/// [`migrate`]'s locked path, which reports it.
fn up_to_date(connection: &Connection, migrations: &[Migration]) -> bool {
    let check = || -> rusqlite::Result<bool> {
        let app_id: i64 = connection.query_row("PRAGMA application_id", [], |row| row.get(0))?;
        if app_id != APPLICATION_ID {
            return Ok(false);
        }
        let mut statement = connection
            .prepare("SELECT version, checksum FROM schema_migrations ORDER BY version")?;
        let applied = statement
            .query_map([], |row| {
                Ok((row.get::<_, i64>(0)?, row.get::<_, String>(1)?))
            })?
            .collect::<Result<Vec<_>, _>>()?;
        Ok(applied.len() == migrations.len()
            && applied
                .iter()
                .zip(migrations)
                .all(|((version, sum), migration)| {
                    *version == migration.version && checksum_matches(sum, migration.sql)
                }))
    };
    check().unwrap_or(false)
}

/// Apply every pending migration in `migrations`.
pub(crate) fn migrate(
    connection: &mut Connection,
    path: &Path,
    migrations: &[Migration],
) -> Result<(), DbError> {
    debug_assert!(migrations
        .iter()
        .enumerate()
        .all(|(index, migration)| migration.version == index as i64 + 1));
    let known = migrations.last().map_or(0, |migration| migration.version);

    // Every engine opens this file several times while it runs. When it is
    // already ours and fully migrated, a read settles that without taking
    // the write lock, which every other engine may be waiting for.
    if up_to_date(connection, migrations) {
        return Ok(());
    }

    // The write lock serializes concurrent first opens across processes.
    let tx = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
    let app_id: i64 = tx.query_row("PRAGMA application_id", [], |row| row.get(0))?;
    let has_tables: bool = tx.query_row(
        "SELECT EXISTS (SELECT 1 FROM sqlite_schema WHERE type = 'table')",
        [],
        |row| row.get(0),
    )?;
    if app_id == 0 && has_tables {
        return Err(DbError::Foreign {
            path: path.to_path_buf(),
        });
    }
    if app_id != 0 && app_id != APPLICATION_ID {
        return Err(DbError::Foreign {
            path: path.to_path_buf(),
        });
    }
    tx.execute_batch(&format!(
        "PRAGMA application_id = {APPLICATION_ID};
         CREATE TABLE IF NOT EXISTS schema_migrations (
             version    INTEGER PRIMARY KEY NOT NULL,
             name       TEXT NOT NULL,
             checksum   TEXT NOT NULL,
             applied_at INTEGER NOT NULL
         ) STRICT;"
    ))?;

    let applied: Vec<(i64, String, String)> = {
        let mut statement =
            tx.prepare("SELECT version, name, checksum FROM schema_migrations ORDER BY version")?;
        let rows = statement.query_map([], |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)))?;
        rows.collect::<Result<_, _>>()?
    };
    if let Some((found, _, _)) = applied.iter().find(|(version, _, _)| *version > known) {
        return Err(DbError::TooNew {
            path: path.to_path_buf(),
            found: *found,
            known,
        });
    }
    for (version, name, sum) in &applied {
        let migration = &migrations[(*version - 1) as usize];
        if !checksum_matches(sum, migration.sql) {
            return Err(DbError::Tampered {
                version: *version,
                name: name.clone(),
            });
        }
    }
    tx.commit()?;

    for migration in migrations.iter().skip(applied.len()) {
        let tx = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        // Another process may have applied it while we waited for the lock.
        let done: bool = tx.query_row(
            "SELECT EXISTS (SELECT 1 FROM schema_migrations WHERE version = ?1)",
            [migration.version],
            |row| row.get(0),
        )?;
        if !done {
            tx.execute_batch(migration.sql)?;
            tx.execute(
                "INSERT INTO schema_migrations (version, name, checksum, applied_at) VALUES (?1, ?2, ?3, ?4)",
                rusqlite::params![migration.version, migration.name, checksum(migration.sql), now()],
            )?;
            tx.pragma_update(None, "user_version", migration.version)?;
        }
        tx.commit()?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn version(connection: &Connection) -> i64 {
        connection
            .query_row("PRAGMA user_version", [], |row| row.get(0))
            .unwrap()
    }

    #[test]
    fn reopening_a_migrated_database_takes_no_write_lock() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("evo.db");
        drop(open_at(&path).unwrap());
        // Another engine holds the write lock while this one opens the file.
        let (locked, wait) = std::sync::mpsc::channel();
        let holder_path = path.clone();
        let holder = std::thread::spawn(move || {
            let other = Connection::open(&holder_path).unwrap();
            other.execute_batch("BEGIN IMMEDIATE").unwrap();
            locked.send(()).unwrap();
            std::thread::sleep(Duration::from_secs(2));
            other.execute_batch("COMMIT").unwrap();
        });
        wait.recv().unwrap();
        let started = std::time::Instant::now();
        let connection = open_at(&path).unwrap();
        let waited = started.elapsed();
        holder.join().unwrap();
        assert!(
            waited < Duration::from_secs(1),
            "open waited {waited:?} for the write lock"
        );
        assert_eq!(version(&connection), MIGRATIONS.len() as i64);
    }

    #[test]
    fn anything_but_a_current_database_takes_the_locked_path() {
        let dir = tempfile::tempdir().unwrap();
        let fresh = Connection::open(dir.path().join("fresh.db")).unwrap();
        assert!(
            !up_to_date(&fresh, MIGRATIONS),
            "a new file needs migrating"
        );

        let path = dir.path().join("evo.db");
        let mut connection = open_at(&path).unwrap();
        assert!(up_to_date(&connection, MIGRATIONS));
        let older_build = &MIGRATIONS[..MIGRATIONS.len() - 1];
        assert!(
            !up_to_date(&connection, older_build),
            "a newer database is reported as too new"
        );
        assert!(matches!(
            migrate(&mut connection, &path, older_build),
            Err(DbError::TooNew { .. })
        ));

        connection
            .execute(
                "UPDATE schema_migrations SET checksum = 'changed' WHERE version = 1",
                [],
            )
            .unwrap();
        assert!(!up_to_date(&connection, MIGRATIONS));
        assert!(matches!(
            migrate(&mut connection, &path, MIGRATIONS),
            Err(DbError::Tampered { version: 1, .. })
        ));
    }

    #[test]
    fn creates_and_reopens_idempotently() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("evo.db");
        let connection = open_at(&path).unwrap();
        assert_eq!(version(&connection), MIGRATIONS.len() as i64);
        drop(connection);
        let connection = open_at(&path).unwrap();
        let count: i64 = connection
            .query_row("SELECT COUNT(*) FROM schema_migrations", [], |row| {
                row.get(0)
            })
            .unwrap();
        assert_eq!(count, MIGRATIONS.len() as i64);
    }

    #[test]
    fn applies_only_pending_migrations() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("evo.db");
        let mut connection = Connection::open(&path).unwrap();
        let first = [Migration {
            version: 1,
            name: "a",
            sql: "CREATE TABLE a (x INTEGER) STRICT;",
        }];
        migrate(&mut connection, &path, &first).unwrap();
        let both = [
            Migration {
                version: 1,
                name: "a",
                sql: "CREATE TABLE a (x INTEGER) STRICT;",
            },
            Migration {
                version: 2,
                name: "b",
                sql: "ALTER TABLE a ADD COLUMN y TEXT;",
            },
        ];
        migrate(&mut connection, &path, &both).unwrap();
        assert_eq!(version(&connection), 2);
        connection
            .execute("INSERT INTO a (x, y) VALUES (1, 'ok')", [])
            .unwrap();
    }

    #[test]
    fn rejects_edited_and_newer_schemas() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("evo.db");
        let mut connection = Connection::open(&path).unwrap();
        let original = [Migration {
            version: 1,
            name: "a",
            sql: "CREATE TABLE a (x INTEGER);",
        }];
        migrate(&mut connection, &path, &original).unwrap();
        let edited = [Migration {
            version: 1,
            name: "a",
            sql: "CREATE TABLE a (x TEXT);",
        }];
        assert!(matches!(
            migrate(&mut connection, &path, &edited),
            Err(DbError::Tampered { version: 1, .. })
        ));
        assert!(matches!(
            migrate(&mut connection, &path, &[]),
            Err(DbError::TooNew {
                found: 1,
                known: 0,
                ..
            })
        ));
    }

    #[test]
    fn line_endings_do_not_change_a_migration() {
        let lf = "CREATE TABLE a (\n    x INTEGER\n);\n";
        let crlf = "CREATE TABLE a (\r\n    x INTEGER\r\n);\r\n";
        assert_eq!(checksum(lf), checksum(crlf));
        let dir = tempfile::tempdir().unwrap();
        // A database recorded by an LF build, opened by a CRLF build, and the
        // other way round (older builds recorded the raw bytes of either).
        for (recorded_by, opened_by, file) in [(lf, crlf, "lf.db"), (crlf, lf, "crlf.db")] {
            let path = dir.path().join(file);
            let mut connection = Connection::open(&path).unwrap();
            let recorded = [Migration {
                version: 1,
                name: "a",
                sql: recorded_by,
            }];
            migrate(&mut connection, &path, &recorded).unwrap();
            connection
                .execute(
                    "UPDATE schema_migrations SET checksum = ?1",
                    [sha256_hex(recorded_by)],
                )
                .unwrap();
            let opened = [Migration {
                version: 1,
                name: "a",
                sql: opened_by,
            }];
            assert!(up_to_date(&connection, &opened), "{file}: read check");
            migrate(&mut connection, &path, &opened).unwrap();
        }
        // A real change is still refused, whatever its line endings.
        let path = dir.path().join("lf.db");
        let mut connection = Connection::open(&path).unwrap();
        let edited = [Migration {
            version: 1,
            name: "a",
            sql: "CREATE TABLE a (\r\n    x TEXT\r\n);\r\n",
        }];
        assert!(!up_to_date(&connection, &edited));
        assert!(matches!(
            migrate(&mut connection, &path, &edited),
            Err(DbError::Tampered { version: 1, .. })
        ));
    }

    #[test]
    fn chat_search_arrives_without_touching_legacy_transcripts() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("evo.db");
        let mut connection = Connection::open(&path).unwrap();
        connection
            .pragma_update(None, "foreign_keys", "ON")
            .unwrap();
        migrate(&mut connection, &path, &MIGRATIONS[..6]).unwrap();
        connection
            .execute_batch(
                "INSERT INTO chats (id, title, created_at, updated_at) VALUES ('c', 'C', 0, 0);
                 INSERT INTO sessions (id, created_at, state_json) VALUES ('c', 0, '{}');",
            )
            .unwrap();
        drop(connection);
        let connection = open_at(&path).unwrap();
        assert_eq!(version(&connection), MIGRATIONS.len() as i64);
        let (chats, sessions, search): (i64, i64, i64) = connection
            .query_row(
                "SELECT (SELECT COUNT(*) FROM chats), (SELECT COUNT(*) FROM sessions), (SELECT COUNT(*) FROM chat_search)",
                [],
                |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
            )
            .unwrap();
        assert_eq!(
            (chats, sessions, search),
            (1, 1, 0),
            "the shell moves transcripts, not the migration"
        );
        connection
            .execute(
                "INSERT INTO chat_search (chat_id, stamp, body) VALUES ('c', 's', 'text')",
                [],
            )
            .unwrap();
        connection
            .execute("DELETE FROM chats WHERE id = 'c'", [])
            .unwrap();
        let left: i64 = connection
            .query_row("SELECT COUNT(*) FROM chat_search", [], |row| row.get(0))
            .unwrap();
        assert_eq!(left, 0, "search text goes with its chat");
    }

    #[test]
    fn refuses_a_foreign_database() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("other.db");
        Connection::open(&path)
            .unwrap()
            .execute_batch("CREATE TABLE unrelated (x);")
            .unwrap();
        assert!(matches!(open_at(&path), Err(DbError::Foreign { .. })));
    }

    #[test]
    fn cascade_removes_a_providers_models() {
        let dir = tempfile::tempdir().unwrap();
        let connection = open_at(&dir.path().join("evo.db")).unwrap();
        connection
            .execute_batch(
                "INSERT INTO provider_settings (provider_id, enabled, created_at, updated_at) VALUES ('x', 1, 0, 0);
                 INSERT INTO provider_models (provider_id, model_id, source, seen_at) VALUES ('x', 'm', 'discovered', 0);
                 DELETE FROM provider_settings WHERE provider_id = 'x';",
            )
            .unwrap();
        let left: i64 = connection
            .query_row("SELECT COUNT(*) FROM provider_models", [], |row| row.get(0))
            .unwrap();
        assert_eq!(left, 0);
    }

    #[test]
    fn usage_events_arrive_empty_and_keep_existing_chats() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("evo.db");
        let mut connection = Connection::open(&path).unwrap();
        connection
            .pragma_update(None, "foreign_keys", "ON")
            .unwrap();
        migrate(&mut connection, &path, &MIGRATIONS[..7]).unwrap();
        connection
            .execute(
                "INSERT INTO chats (id, title, created_at, updated_at, cost_usd) VALUES ('c', 'C', 0, 0, 1.5)",
                [],
            )
            .unwrap();
        drop(connection);
        let connection = open_at(&path).unwrap();
        assert_eq!(version(&connection), MIGRATIONS.len() as i64);
        let (cost, events): (f64, i64) = connection
            .query_row(
                "SELECT (SELECT cost_usd FROM chats WHERE id = 'c'), (SELECT COUNT(*) FROM usage_events)",
                [],
                |row| Ok((row.get(0)?, row.get(1)?)),
            )
            .unwrap();
        assert_eq!(
            (cost, events),
            (1.5, 0),
            "history starts empty; chat totals stay"
        );
        let refused = connection.execute(
            "INSERT INTO usage_events (at_ms, source, provider_id, model_id) VALUES (0, 'elsewhere', 'p', 'm')",
            [],
        );
        assert!(refused.is_err(), "unknown sources are refused");
    }
}
