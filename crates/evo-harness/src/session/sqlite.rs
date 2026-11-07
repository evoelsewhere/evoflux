//! SQLite-backed session repository.
//!
//! The reducer remains the source of truth for session invariants. SQLite
//! stores one metadata row and a serialized reducer snapshot per session,
//! giving callers a durable, queryable repository without duplicating the
//! JSONL reducer logic. Writes are serialized per connection and committed
//! atomically after the in-memory mutation succeeds.

use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};

use async_trait::async_trait;
use rusqlite::{params, Connection, OptionalExtension};

use crate::error::{SessionError, SessionResult};
use crate::session::memory::{Clock, InMemorySessionStorage, SystemClock};
use crate::session::state::SessionState;
use crate::session::types::{
    BranchBounds, Entry, EntryQuery, ForkOptions, IdGenerator, LanePointer, LaneRecord, LogItem,
    LogOptions, OperationStartedRecord, ProvisionedEntry, RecordQuery, SessionCreateOptions,
    SessionLaneBranch, SessionMetadata, SessionRepo, SessionStats, SessionStorage,
};

#[derive(Clone)]
pub struct SqliteSessionStorage {
    db: Arc<Mutex<Connection>>,
    inner: InMemorySessionStorage,
    gate: Arc<tokio::sync::Mutex<()>>,
}

impl SqliteSessionStorage {
    fn new(
        db: Arc<Mutex<Connection>>,
        metadata: SessionMetadata,
        state: SessionState,
        clock: Arc<dyn Clock>,
        ids: Arc<dyn IdGenerator>,
        gate: Arc<tokio::sync::Mutex<()>>,
    ) -> Self {
        Self {
            db,
            inner: InMemorySessionStorage::from_state(metadata, state, clock, ids),
            gate,
        }
    }

    fn conn(&self) -> SessionResult<std::sync::MutexGuard<'_, Connection>> {
        self.db
            .lock()
            .map_err(|_| SessionError::storage("SQLite connection poisoned"))
    }

    /// Write the reduced state if the row still holds `previous`.
    fn persist_cas(&self, previous: &str) -> SessionResult<Cas> {
        let metadata = self.inner.metadata();
        let state = serde_json::to_string(&self.inner.snapshot_state())
            .map_err(|e| SessionError::storage(format!("serialize SQLite session: {e}")))?;
        let result = self.conn()?.execute(
            "UPDATE sessions SET state_json = ?1 WHERE id = ?2 AND state_json = ?3",
            params![state, metadata.id, previous],
        );
        match result {
            Ok(1) => Ok(Cas::Written),
            Ok(_) => Ok(Cas::Conflict),
            Err(error) if busy::is_busy(&error) => Ok(Cas::Busy(error)),
            Err(error) => Err(SessionError::storage(format!(
                "persist SQLite session: {error}"
            ))),
        }
    }

    async fn write_retry<T, F, Fut>(&self, op: F) -> SessionResult<T>
    where
        F: Fn(InMemorySessionStorage) -> Fut,
        Fut: std::future::Future<Output = SessionResult<T>>,
    {
        // Refresh, reduce, and CAS the exact snapshot that was refreshed. A
        // concurrent connection either wins the CAS or causes this operation
        // to replay against the newer state; its successful return is durable.
        // A busy database (other engines holding the write lock) replays the
        // same way after a pause instead of failing the caller.
        let _gate = self.gate.lock().await;
        let mut conflicts = 0;
        let mut backoff = busy::Backoff::new();
        loop {
            let previous = self.refresh_unlocked().await?;
            let value = match op(self.inner.clone()).await {
                Ok(value) => value,
                Err(error) => {
                    self.restore_snapshot(&previous)?;
                    return Err(error);
                }
            };
            match self.persist_cas(&previous) {
                Ok(Cas::Written) => return Ok(value),
                Ok(Cas::Conflict) => {
                    conflicts += 1;
                    if conflicts >= 16 {
                        return Err(SessionError::storage(
                            "SQLite write conflicted too many times",
                        ));
                    }
                }
                Ok(Cas::Busy(error)) => {
                    self.restore_snapshot(&previous)?;
                    match backoff.next_pause() {
                        Some(pause) => tokio::time::sleep(pause).await,
                        None => {
                            return Err(SessionError::storage(format!(
                                "persist SQLite session: {error}"
                            )))
                        }
                    }
                }
                Err(error) => {
                    self.restore_snapshot(&previous)?;
                    return Err(error);
                }
            }
        }
    }

    fn restore_snapshot(&self, state_json: &str) -> SessionResult<()> {
        let state = serde_json::from_str(state_json)
            .map_err(|e| SessionError::storage(format!("decode SQLite session: {e}")))?;
        self.inner.replace_state(state);
        Ok(())
    }

    async fn refresh_unlocked(&self) -> SessionResult<String> {
        let id = self.inner.metadata().id;
        let state_json: String = busy::run(&self.db, "refresh SQLite session", |conn| {
            conn.query_row(
                "SELECT state_json FROM sessions WHERE id = ?1",
                params![id],
                |row| row.get(0),
            )
        })
        .await?;
        let state = serde_json::from_str(&state_json)
            .map_err(|e| SessionError::storage(format!("decode SQLite session: {e}")))?;
        self.inner.replace_state(state);
        Ok(state_json)
    }

    async fn refresh_read(&self) -> SessionResult<tokio::sync::OwnedMutexGuard<()>> {
        let gate = self.gate.clone().lock_owned().await;
        self.refresh_unlocked().await?;
        Ok(gate)
    }
}

/// How a compare-and-swap write of the session state ended.
enum Cas {
    Written,
    /// Another connection changed the row since it was read.
    Conflict,
    /// Another connection held the write lock past the busy timeout.
    Busy(rusqlite::Error),
}

/// Switch to WAL unless the database already uses it. Changing the journal
/// mode ignores the busy timeout, so a connection opened while another engine
/// holds the database retries for a while instead of failing.
fn enable_wal(conn: &Connection) -> SessionResult<()> {
    let mode = |conn: &Connection| {
        conn.query_row("PRAGMA journal_mode", [], |row| row.get::<_, String>(0))
    };
    let mut attempt = 0;
    loop {
        let result = mode(conn).and_then(|current| {
            if current.eq_ignore_ascii_case("wal") {
                Ok(current)
            } else {
                conn.query_row("PRAGMA journal_mode = WAL", [], |row| {
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
                std::thread::sleep(std::time::Duration::from_millis(50));
            }
            Err(error) => {
                return Err(SessionError::storage(format!(
                    "initialize SQLite database: {error}"
                )))
            }
        }
    }
}

mod busy;
mod progress;

#[async_trait]
impl SessionStorage for SqliteSessionStorage {
    async fn prune_completed_progress(&self) -> SessionResult<usize> {
        self.prune_completed_progress_sql().await
    }

    async fn append_progress(
        &self,
        records: Vec<crate::session::types::AssistantFrameRecord>,
    ) -> SessionResult<Vec<crate::session::types::AssistantFrameRecord>> {
        self.append_progress_sql(records).await
    }
    async fn read_progress(
        &self,
        run_id: &str,
    ) -> SessionResult<Vec<crate::session::types::AssistantFrameRecord>> {
        self.read_progress_sql(run_id).await
    }
    fn metadata(&self) -> SessionMetadata {
        self.inner.metadata()
    }
    async fn get_lanes(&self) -> SessionResult<Vec<LanePointer>> {
        let _gate = self.refresh_read().await?;
        self.inner.get_lanes().await
    }
    async fn lane_branch(&self, lane: &str) -> SessionResult<SessionLaneBranch> {
        let _gate = self.refresh_read().await?;
        self.inner.lane_branch(lane).await
    }
    async fn create_lane(&self, lane: &str, at: Option<&str>) -> SessionResult<()> {
        let lane = lane.to_string();
        let at = at.map(str::to_string);
        self.write_retry(move |inner| {
            let lane = lane.clone();
            let at = at.clone();
            async move { inner.create_lane(&lane, at.as_deref()).await }
        })
        .await
    }
    async fn move_lane(&self, lane: &str, to: Option<&str>) -> SessionResult<()> {
        let lane = lane.to_string();
        let to = to.map(str::to_string);
        self.write_retry(move |inner| {
            let lane = lane.clone();
            let to = to.clone();
            async move { inner.move_lane(&lane, to.as_deref()).await }
        })
        .await
    }
    async fn append_queue_cancellations(
        &self,
        records: Vec<LaneRecord>,
    ) -> SessionResult<Vec<LaneRecord>> {
        self.write_retry(move |inner| {
            let records = records.clone();
            async move { inner.append_queue_cancellations(records).await }
        })
        .await
    }

    async fn history_revision(&self) -> SessionResult<u64> {
        let _gate = self.refresh_read().await?;
        self.inner.history_revision().await
    }

    async fn append_entry_if_revision(
        &self,
        entry: ProvisionedEntry,
        lane: &str,
        expected: u64,
    ) -> SessionResult<Entry> {
        let lane = lane.to_owned();
        self.write_retry(move |inner| {
            let entry = entry.clone();
            let lane = lane.clone();
            async move { inner.append_entry_if_revision(entry, &lane, expected).await }
        })
        .await
    }

    async fn append_record_if_revision(
        &self,
        record: LaneRecord,
        expected: u64,
    ) -> SessionResult<LaneRecord> {
        self.write_retry(move |inner| {
            let record = record.clone();
            async move { inner.append_record_if_revision(record, expected).await }
        })
        .await
    }

    async fn append_entry(&self, entry: ProvisionedEntry, lane: &str) -> SessionResult<Entry> {
        let lane = lane.to_string();
        self.write_retry(move |inner| {
            let entry = entry.clone();
            let lane = lane.clone();
            async move { inner.append_entry(entry, &lane).await }
        })
        .await
    }
    async fn append_record(&self, record: LaneRecord) -> SessionResult<LaneRecord> {
        self.write_retry(move |inner| {
            let record = record.clone();
            async move { inner.append_record(record).await }
        })
        .await
    }
    async fn message_summaries(
        &self,
        lane: &str,
        query: &crate::session::types::MessageSummaryQuery,
    ) -> SessionResult<crate::session::types::MessageSummaryPage> {
        let _gate = self.refresh_read().await?;
        self.inner.message_summaries(lane, query).await
    }
    async fn message_window(
        &self,
        lane: &str,
        query: &crate::session::types::MessageWindowQuery,
    ) -> SessionResult<crate::session::types::MessageWindowPage> {
        let _gate = self.refresh_read().await?;
        self.inner.message_window(lane, query).await
    }
    async fn get_entry(&self, id: &str) -> SessionResult<Option<Entry>> {
        let _gate = self.refresh_read().await?;
        self.inner.get_entry(id).await
    }
    async fn find_entries(&self, query: &EntryQuery) -> SessionResult<Vec<Entry>> {
        let _gate = self.refresh_read().await?;
        self.inner.find_entries(query).await
    }
    async fn find_entries_on_branch(
        &self,
        query: &EntryQuery,
        bounds: &BranchBounds,
        start: &str,
    ) -> SessionResult<Vec<Entry>> {
        let _gate = self.refresh_read().await?;
        self.inner
            .find_entries_on_branch(query, bounds, start)
            .await
    }
    async fn branch_ancestry(
        &self,
        bounds: &BranchBounds,
        start: &str,
    ) -> SessionResult<Vec<crate::session::types::EntryAncestry>> {
        // SQLite's existing snapshot refresh eagerly deserializes state_json.
        // Only the subsequent ancestry walk is metadata-only in this backend.
        let _gate = self.refresh_read().await?;
        self.inner.branch_ancestry(bounds, start).await
    }

    async fn context_on_branch(
        &self,
        bounds: &BranchBounds,
        start: &str,
    ) -> SessionResult<crate::session::context::SessionContext> {
        let _gate = self.refresh_read().await?;
        SessionStorage::context_on_branch(&self.inner, bounds, start).await
    }

    async fn find_records(&self, query: &RecordQuery) -> SessionResult<Vec<LaneRecord>> {
        let _gate = self.refresh_read().await?;
        self.inner.find_records(query).await
    }
    async fn record_page(
        &self,
        query: &crate::session::types::RecordPageQuery,
    ) -> SessionResult<crate::session::types::RecordPage> {
        let _gate = self.refresh_read().await?;
        self.inner.record_page(query).await
    }
    async fn find_open_operations(
        &self,
        lane: &str,
        limit: Option<usize>,
    ) -> SessionResult<Vec<OperationStartedRecord>> {
        let _gate = self.refresh_read().await?;
        self.inner.find_open_operations(lane, limit).await
    }
    async fn get_log(&self, options: &LogOptions) -> SessionResult<Vec<LogItem>> {
        let _gate = self.refresh_read().await?;
        self.inner.get_log(options).await
    }
    async fn get_name(&self) -> SessionResult<Option<String>> {
        let _gate = self.refresh_read().await?;
        self.inner.get_name().await
    }
    async fn set_name(&self, name: Option<&str>) -> SessionResult<()> {
        let name = name.map(str::to_string);
        self.write_retry(move |inner| {
            let name = name.clone();
            async move { inner.set_name(name.as_deref()).await }
        })
        .await
    }
    async fn get_label(&self, id: &str) -> SessionResult<Option<String>> {
        let _gate = self.refresh_read().await?;
        self.inner.get_label(id).await
    }
    async fn set_label(&self, id: &str, label: Option<&str>) -> SessionResult<()> {
        let id = id.to_string();
        let label = label.map(str::to_string);
        self.write_retry(move |inner| {
            let id = id.clone();
            let label = label.clone();
            async move { inner.set_label(&id, label.as_deref()).await }
        })
        .await
    }
    async fn get_stats(&self) -> SessionResult<SessionStats> {
        let _gate = self.refresh_read().await?;
        self.inner.get_stats().await
    }
}

pub struct SqliteSessionRepo {
    path: PathBuf,
    db: Arc<Mutex<Connection>>,
    clock: Arc<dyn Clock>,
    ids: Arc<dyn IdGenerator>,
    gate: Arc<tokio::sync::Mutex<()>>,
}

impl SqliteSessionRepo {
    pub fn open(path: impl AsRef<Path>) -> SessionResult<Self> {
        Self::with_clock_ids(
            path,
            Arc::new(SystemClock),
            Arc::new(crate::session::DefaultIdGenerator::new()),
        )
    }

    pub fn with_clock_ids(
        path: impl AsRef<Path>,
        clock: Arc<dyn Clock>,
        ids: Arc<dyn IdGenerator>,
    ) -> SessionResult<Self> {
        let path = path.as_ref().to_path_buf();
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)
                .map_err(|e| SessionError::storage(format!("create SQLite parent: {e}")))?;
        }
        let conn = Connection::open(&path)
            .map_err(|e| SessionError::storage(format!("open SQLite database: {e}")))?;
        conn.busy_timeout(busy::BUSY_TIMEOUT)
            .map_err(|e| SessionError::storage(format!("configure SQLite busy timeout: {e}")))?;
        // Reject native experimental artifacts BEFORE WAL/schema initialization.
        // Compiled unconditionally: feature-off legacy writers must reject too.
        let application_id: i64 =
            busy::retry_blocking(|| conn.query_row("PRAGMA application_id", [], |row| row.get(0)))
                .map_err(|e| SessionError::storage(format!("read SQLite format identity: {e}")))?;
        if matches!(application_id, 0x5250494e | 0x5250494f | 0x52504951) {
            return Err(SessionError::storage(
                "experimental native artifact cannot be opened by the legacy SQLite writer",
            ));
        }
        enable_wal(&conn)?;
        // WAL + NORMAL: commits stop fsyncing while they hold the database's
        // single write lock (FULL fsyncs every commit, which serialized every
        // engine sharing evo.db behind the disk). A process crash loses
        // nothing; a power cut can lose the last commits but never corrupts
        // the file. evo-store opens the same file with the same setting.
        conn.pragma_update(None, "synchronous", "NORMAL")
            .map_err(|e| SessionError::storage(format!("configure SQLite synchronous: {e}")))?;
        busy::retry_blocking(|| {
            conn.execute_batch(
                "CREATE TABLE IF NOT EXISTS sessions (
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
             CREATE INDEX IF NOT EXISTS progress_run ON progress_frames(session_id,run_id,sequence);
             PRAGMA foreign_keys = ON;",
            )
        })
        .map_err(|e| SessionError::storage(format!("initialize SQLite database: {e}")))?;
        Ok(Self {
            path,
            db: Arc::new(Mutex::new(conn)),
            clock,
            ids,
            gate: Arc::new(tokio::sync::Mutex::new(())),
        })
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    async fn insert(&self, metadata: &SessionMetadata, state: &SessionState) -> SessionResult<()> {
        let state = serde_json::to_string(state)
            .map_err(|e| SessionError::storage(format!("serialize SQLite state: {e}")))?;
        let inserted = busy::run(&self.db, "insert SQLite session", |conn| {
            match conn.execute(
                "INSERT INTO sessions (id, created_at, parent_session_id, state_json) VALUES (?1, ?2, ?3, ?4)",
                params![metadata.id, metadata.created_at, metadata.parent_session_id, state],
            ) {
                Ok(_) => Ok(true),
                Err(rusqlite::Error::SqliteFailure(err, _))
                    if err.code == rusqlite::ErrorCode::ConstraintViolation =>
                {
                    Ok(false)
                }
                Err(other) => Err(other),
            }
        })
        .await?;
        if !inserted {
            return Err(SessionError::already_exists(format!(
                "Session already exists: {}",
                metadata.id
            )));
        }
        Ok(())
    }

    async fn load_row(&self, id: &str) -> SessionResult<Option<(SessionMetadata, SessionState)>> {
        busy::run(&self.db, "read SQLite session", |conn| {
            conn.query_row(
                "SELECT id, created_at, parent_session_id, state_json FROM sessions WHERE id = ?1",
                params![id],
                |row| {
                    let metadata = SessionMetadata {
                        id: row.get(0)?,
                        created_at: row.get(1)?,
                        parent_session_id: row.get(2)?,
                    };
                    let state_json: String = row.get(3)?;
                    let state = serde_json::from_str(&state_json).map_err(|e| {
                        rusqlite::Error::FromSqlConversionFailure(
                            3,
                            rusqlite::types::Type::Text,
                            Box::new(e),
                        )
                    })?;
                    Ok((metadata, state))
                },
            )
            .optional()
        })
        .await
    }
}

#[async_trait]
impl SessionRepo for SqliteSessionRepo {
    type Storage = SqliteSessionStorage;

    async fn create(&self, options: &SessionCreateOptions) -> SessionResult<Self::Storage> {
        let metadata = SessionMetadata {
            id: options.id.clone().unwrap_or_else(|| self.ids.next()),
            created_at: self.clock.now_ms(),
            parent_session_id: options.parent_session_id.clone(),
        };
        let state = SessionState::new();
        self.insert(&metadata, &state).await?;
        Ok(SqliteSessionStorage::new(
            self.db.clone(),
            metadata,
            state,
            self.clock.clone(),
            self.ids.clone(),
            self.gate.clone(),
        ))
    }

    async fn open(&self, metadata: &SessionMetadata) -> SessionResult<Self::Storage> {
        let (metadata, state) = self.load_row(&metadata.id).await?.ok_or_else(|| {
            SessionError::not_found(format!("Session not found: {}", metadata.id))
        })?;
        Ok(SqliteSessionStorage::new(
            self.db.clone(),
            metadata,
            state,
            self.clock.clone(),
            self.ids.clone(),
            self.gate.clone(),
        ))
    }

    async fn list(&self) -> SessionResult<Vec<SessionMetadata>> {
        let db = self
            .db
            .lock()
            .map_err(|_| SessionError::storage("SQLite connection poisoned"))?;
        let mut stmt = db
            .prepare(
                "SELECT id, created_at, parent_session_id FROM sessions ORDER BY created_at DESC",
            )
            .map_err(|e| SessionError::storage(format!("list SQLite sessions: {e}")))?;
        let rows = stmt
            .query_map([], |row| {
                Ok(SessionMetadata {
                    id: row.get(0)?,
                    created_at: row.get(1)?,
                    parent_session_id: row.get(2)?,
                })
            })
            .map_err(|e| SessionError::storage(format!("list SQLite sessions: {e}")))?;
        rows.map(|row| row.map_err(|e| SessionError::storage(format!("read SQLite metadata: {e}"))))
            .collect()
    }

    async fn delete(&self, metadata: &SessionMetadata) -> SessionResult<()> {
        busy::run(&self.db, "delete SQLite session", |conn| {
            conn.execute("DELETE FROM sessions WHERE id = ?1", params![metadata.id])
        })
        .await?;
        Ok(())
    }

    async fn fork(
        &self,
        source: &SessionMetadata,
        options: &SessionCreateOptions,
        fork: &ForkOptions,
    ) -> SessionResult<Self::Storage> {
        let source_storage = self.open(source).await?;
        let id = options.id.clone().unwrap_or_else(|| self.ids.next());
        let metadata = SessionMetadata {
            id,
            created_at: self.clock.now_ms(),
            parent_session_id: Some(source.id.clone()),
        };
        let forked = source_storage.inner.fork_from(
            metadata.clone(),
            fork,
            self.clock.clone(),
            self.ids.clone(),
        )?;
        let state = forked.snapshot_state();
        self.insert(&metadata, &state).await?;
        Ok(SqliteSessionStorage::new(
            self.db.clone(),
            metadata,
            state,
            self.clock.clone(),
            self.ids.clone(),
            self.gate.clone(),
        ))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::session::memory::{CounterIdGenerator, FakeClock};
    use crate::session::types::{EntryOrder, EntryQuery, ForkOptions, ProvisionedKind};
    use evo_agent::message::AgentMessage;

    fn repo() -> (SqliteSessionRepo, tempfile::TempDir) {
        let dir = tempfile::tempdir().unwrap();
        let repo = SqliteSessionRepo::with_clock_ids(
            dir.path().join("sessions.db"),
            Arc::new(FakeClock::new()),
            Arc::new(CounterIdGenerator::new()),
        )
        .unwrap();
        (repo, dir)
    }

    #[tokio::test]
    async fn context_projection_refreshes_and_matches_branch_query() {
        let (repo, _dir) = repo();
        let first = repo
            .create(&SessionCreateOptions {
                id: Some("context".into()),
                parent_session_id: None,
                metadata: None,
            })
            .await
            .unwrap();
        first
            .append_entry(
                ProvisionedEntry {
                    id: "m1".into(),
                    kind: ProvisionedKind::Message {
                        message: AgentMessage::from(evo_ai::types::UserMessage::new("one", 1)),
                        terminate: None,
                    },
                },
                "main",
            )
            .await
            .unwrap();
        let second = repo.open(&first.metadata()).await.unwrap();
        second
            .append_entry(
                ProvisionedEntry {
                    id: "m2".into(),
                    kind: ProvisionedKind::Message {
                        message: AgentMessage::from(evo_ai::types::UserMessage::new("two", 2)),
                        terminate: None,
                    },
                },
                "main",
            )
            .await
            .unwrap();
        let actual = first
            .context_on_branch(&BranchBounds::default(), "m2")
            .await
            .unwrap();
        let path = first
            .find_entries_on_branch(
                &EntryQuery {
                    order: Some(EntryOrder::OldestFirst),
                    ..Default::default()
                },
                &BranchBounds::default(),
                "m2",
            )
            .await
            .unwrap();
        let expected = crate::session::context::build_session_context(&path, &Default::default());
        assert_eq!(actual.messages, expected.messages);
        assert_eq!(actual.messages.len(), 2);
    }

    #[tokio::test]
    async fn round_trip_append_and_fork() {
        let (repo, _dir) = repo();
        let session = repo
            .create(&SessionCreateOptions {
                id: Some("root".into()),
                parent_session_id: None,
                metadata: None,
            })
            .await
            .unwrap();
        session
            .append_entry(
                ProvisionedEntry {
                    id: "m1".into(),
                    kind: ProvisionedKind::Message {
                        message: AgentMessage::from(evo_ai::types::UserMessage::new("hello", 1)),
                        terminate: None,
                    },
                },
                "main",
            )
            .await
            .unwrap();
        let reopened = repo.open(&session.metadata()).await.unwrap();
        assert_eq!(
            reopened
                .find_entries(&EntryQuery::default())
                .await
                .unwrap()
                .len(),
            1
        );
        let second_handle = repo.open(&session.metadata()).await.unwrap();
        second_handle
            .append_entry(
                ProvisionedEntry {
                    id: "m2".into(),
                    kind: ProvisionedKind::Message {
                        message: AgentMessage::from(evo_ai::types::UserMessage::new("world", 2)),
                        terminate: None,
                    },
                },
                "main",
            )
            .await
            .unwrap();
        assert_eq!(
            session
                .find_entries(&EntryQuery::default())
                .await
                .unwrap()
                .len(),
            2
        );
        let fork = repo
            .fork(
                &session.metadata(),
                &SessionCreateOptions {
                    id: Some("child".into()),
                    parent_session_id: None,
                    metadata: None,
                },
                &ForkOptions::default(),
            )
            .await
            .unwrap();
        assert_eq!(fork.metadata().parent_session_id.as_deref(), Some("root"));
        assert_eq!(repo.list().await.unwrap().len(), 2);
    }

    #[tokio::test]
    async fn duplicate_id_is_already_exists_and_delete_works() {
        let (repo, _dir) = repo();
        repo.create(&SessionCreateOptions {
            id: Some("same".into()),
            parent_session_id: None,
            metadata: None,
        })
        .await
        .unwrap();
        let err = match repo
            .create(&SessionCreateOptions {
                id: Some("same".into()),
                parent_session_id: None,
                metadata: None,
            })
            .await
        {
            Ok(_) => panic!("expected duplicate"),
            Err(e) => e,
        };
        assert_eq!(err.code, crate::error::SessionErrorCode::AlreadyExists);
        repo.delete(&SessionMetadata {
            id: "same".into(),
            created_at: 0,
            parent_session_id: None,
        })
        .await
        .unwrap();
        assert!(repo.list().await.unwrap().is_empty());
    }

    #[derive(Default)]
    struct ReviewGatedClock {
        armed: std::sync::atomic::AtomicBool,
        reached: std::sync::Mutex<usize>,
        changed: std::sync::Condvar,
    }
    impl Clock for ReviewGatedClock {
        fn now_ms(&self) -> i64 {
            if self.armed.load(std::sync::atomic::Ordering::SeqCst) {
                let mut reached = self.reached.lock().unwrap();
                *reached += 1;
                self.changed.notify_all();
                if *reached < 2 {
                    // A serialized implementation may hold its transaction while
                    // stamping, so bound this gate instead of deadlocking it.
                    let _ = self
                        .changed
                        .wait_timeout_while(reached, std::time::Duration::from_secs(2), |count| {
                            *count < 2
                        })
                        .unwrap();
                }
            }
            1
        }
    }

    #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
    async fn review_sqlite_two_handles_must_preserve_both_successful_appends() {
        let dir = tempfile::tempdir().unwrap();
        let clock = Arc::new(ReviewGatedClock::default());
        let repo = SqliteSessionRepo::with_clock_ids(
            dir.path().join("review.sqlite"),
            clock.clone(),
            Arc::new(CounterIdGenerator::new()),
        )
        .unwrap();
        let first = repo
            .create(&SessionCreateOptions {
                id: Some("review".into()),
                parent_session_id: None,
                metadata: None,
            })
            .await
            .unwrap();
        let second = repo.open(&first.metadata()).await.unwrap();
        let metadata = first.metadata();
        clock.armed.store(true, std::sync::atomic::Ordering::SeqCst);
        let append = |storage: SqliteSessionStorage, id: &'static str| {
            tokio::spawn(async move {
                storage
                    .append_entry(
                        ProvisionedEntry {
                            id: id.into(),
                            kind: ProvisionedKind::Message {
                                message: AgentMessage::from(evo_ai::types::UserMessage::new(id, 0)),
                                terminate: None,
                            },
                        },
                        "main",
                    )
                    .await
                    .unwrap()
            })
        };
        let left = append(first, "writer-one");
        let right = append(second, "writer-two");
        let (a, b) = tokio::join!(left, right);
        let (a, b) = (a.unwrap(), b.unwrap());
        clock
            .armed
            .store(false, std::sync::atomic::Ordering::SeqCst);
        let reloaded = repo.open(&metadata).await.unwrap();
        let all = reloaded.find_entries(&EntryQuery::default()).await.unwrap();
        eprintln!(
            "review SQLite concurrent handles: successful_seqs=({}, {}), reopened_entry_ids={:?}",
            a.seq(),
            b.seq(),
            all.iter().map(Entry::id).collect::<Vec<_>>()
        );
        assert_eq!(
            all.len(),
            2,
            "both appends returned success, but one whole-state snapshot overwrote the other"
        );
    }

    /// Another process (a second chat's engine) holds the database's write
    /// lock for `hold`, well past the busy timeout. Returns once it has the
    /// lock; the lock is released when `hold` has passed.
    fn hold_write_lock(path: &Path, hold: std::time::Duration) -> std::thread::JoinHandle<()> {
        let path = path.to_path_buf();
        let (locked, wait) = std::sync::mpsc::channel();
        let holder = std::thread::spawn(move || {
            let other = Connection::open(&path).unwrap();
            other.execute_batch("BEGIN IMMEDIATE").unwrap();
            locked.send(()).unwrap();
            std::thread::sleep(hold);
            other.execute_batch("COMMIT").unwrap();
        });
        wait.recv().unwrap();
        holder
    }

    fn message(id: &str) -> ProvisionedEntry {
        ProvisionedEntry {
            id: id.into(),
            kind: ProvisionedKind::Message {
                message: AgentMessage::from(evo_ai::types::UserMessage::new(id, 1)),
                terminate: None,
            },
        }
    }

    #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
    async fn writes_wait_out_another_engine_holding_the_write_lock() {
        let (repo, _dir) = repo();
        let hold = busy::BUSY_TIMEOUT * 6;
        let session = repo
            .create(&SessionCreateOptions {
                id: Some("busy".into()),
                parent_session_id: None,
                metadata: None,
            })
            .await
            .unwrap();
        session.append_entry(message("m1"), "main").await.unwrap();

        // An entry (whole-state compare-and-swap) while the lock is held.
        let holder = hold_write_lock(repo.path(), hold);
        let started = std::time::Instant::now();
        session.append_entry(message("m2"), "main").await.unwrap();
        assert!(
            started.elapsed() >= busy::BUSY_TIMEOUT,
            "the write did not wait for the lock"
        );
        holder.join().unwrap();

        // Streamed progress (an IMMEDIATE transaction) while the lock is held.
        let holder = hold_write_lock(repo.path(), hold);
        let stamped = session
            .append_progress(vec![crate::session::types::AssistantFrameRecord {
                base: crate::session::types::RecordBase {
                    id: "frame-1".into(),
                    seq: 0,
                    lane: "main".into(),
                    timestamp: 0,
                },
                run_id: "run-1".into(),
                stream_index: 0,
                op: crate::session::types::AssistantFrameOp::Append,
                frame: Some(serde_json::json!({ "text": "partial" })),
            }])
            .await
            .unwrap();
        holder.join().unwrap();
        assert_eq!(stamped.len(), 1);
        assert_eq!(session.read_progress("run-1").await.unwrap().len(), 1);

        // Opening a session while the lock is held.
        let holder = hold_write_lock(repo.path(), hold);
        let created = repo
            .create(&SessionCreateOptions {
                id: Some("busy-2".into()),
                parent_session_id: None,
                metadata: None,
            })
            .await;
        holder.join().unwrap();
        assert!(created.is_ok(), "{:?}", created.err());

        let reopened = repo.open(&session.metadata()).await.unwrap();
        let ids: Vec<_> = reopened
            .find_entries(&EntryQuery {
                order: Some(EntryOrder::OldestFirst),
                ..Default::default()
            })
            .await
            .unwrap()
            .iter()
            .map(|entry| entry.id().to_string())
            .collect();
        assert_eq!(ids, ["m1", "m2"]);
    }

    #[tokio::test]
    async fn review_sqlite_failed_persist_rolls_back_memory_and_disk() {
        let (repo, _dir) = repo();
        let session = repo
            .create(&SessionCreateOptions {
                id: Some("rollback".into()),
                parent_session_id: None,
                metadata: None,
            })
            .await
            .unwrap();
        session
            .db
            .lock()
            .unwrap()
            .execute_batch("CREATE TRIGGER reject_session_update BEFORE UPDATE ON sessions BEGIN SELECT RAISE(ABORT, 'review rejection'); END;")
            .unwrap();
        let result = session
            .append_entry(
                ProvisionedEntry {
                    id: "rejected".into(),
                    kind: ProvisionedKind::Message {
                        message: AgentMessage::from(evo_ai::types::UserMessage::new("rejected", 1)),
                        terminate: None,
                    },
                },
                "main",
            )
            .await;
        assert!(result.is_err());
        assert!(session.get_entry("rejected").await.unwrap().is_none());
        let reopened = repo.open(&session.metadata()).await.unwrap();
        assert!(reopened.get_entry("rejected").await.unwrap().is_none());
    }
}
