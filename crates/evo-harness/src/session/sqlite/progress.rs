use super::*;
use crate::session::types::{AssistantFrameOp, AssistantFrameRecord};

fn failure(error: impl std::fmt::Display) -> SessionError {
    SessionError::storage(format!("SQLite progress: {error}"))
}

/// Why one attempt to append progress did not commit.
enum Attempt {
    /// Another connection held the write lock past the busy timeout.
    Busy(rusqlite::Error),
    Failed(SessionError),
}

impl From<rusqlite::Error> for Attempt {
    fn from(error: rusqlite::Error) -> Self {
        if busy::is_busy(&error) {
            Self::Busy(error)
        } else {
            Self::Failed(failure(error))
        }
    }
}

impl From<SessionError> for Attempt {
    fn from(error: SessionError) -> Self {
        Self::Failed(error)
    }
}

impl SqliteSessionStorage {
    pub(super) async fn prune_completed_progress_sql(&self) -> SessionResult<usize> {
        let _gate = self.gate.lock().await;
        let id = self.inner.metadata().id;
        // One authoritative database statement: no stale Memory mirror, no
        // progress-row-times-history scan, and no state_json rewrite.
        busy::run(&self.db, "SQLite progress", |db| {
            db.execute(
                "WITH finished AS MATERIALIZED (
                    SELECT json_extract(r.value, '$.lane') AS lane,
                           json_extract(r.value, '$.runId') AS run_id
                    FROM sessions AS s, json_each(s.state_json, '$.records') AS r
                    WHERE s.id = ?1 AND json_extract(r.value, '$.type') = 'operation_finished'
                 )
                 DELETE FROM progress_frames WHERE session_id = ?1
                 AND (lane, run_id) IN (SELECT lane, run_id FROM finished)",
                params![id],
            )
        })
        .await
    }

    pub(super) async fn append_progress_sql(
        &self,
        records: Vec<AssistantFrameRecord>,
    ) -> SessionResult<Vec<AssistantFrameRecord>> {
        let _gate = self.gate.lock().await;
        // A busy database replays the whole transaction after a pause: the
        // failed attempt rolled back, so nothing of it was stored.
        let mut backoff = busy::Backoff::new();
        loop {
            match self.try_append_progress(&records) {
                Ok(stamped) => return Ok(stamped),
                Err(Attempt::Failed(error)) => return Err(error),
                Err(Attempt::Busy(error)) => match backoff.next_pause() {
                    Some(pause) => tokio::time::sleep(pause).await,
                    None => return Err(failure(error)),
                },
            }
        }
    }

    fn try_append_progress(
        &self,
        records: &[AssistantFrameRecord],
    ) -> Result<Vec<AssistantFrameRecord>, Attempt> {
        let mut db = self.db.lock().map_err(failure)?;
        // IMMEDIATE: take the write lock up front. A deferred transaction reads
        // first and then upgrades, and in WAL mode that upgrade fails at once
        // ("database is locked", no busy wait) whenever another engine wrote
        // meanwhile — two chats streaming into one database do so constantly.
        let transaction = db.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
        let session_id = self.inner.metadata().id;
        // Each lane is checked once: the check parses the whole session state
        // while every other engine waits for the write lock.
        let lanes: std::collections::BTreeSet<&str> = records
            .iter()
            .map(|record| record.base.lane.as_str())
            .collect();
        for lane in lanes {
            let found: bool = transaction.query_row("SELECT EXISTS(SELECT 1 FROM sessions, json_each(sessions.state_json, '$.lanes') WHERE sessions.id = ?1 AND json_each.key = ?2)",params![session_id,lane],|row| row.get(0))?;
            if !found {
                return Err(SessionError::invalid_payload("unknown progress lane/session").into());
            }
        }
        for record in records {
            let duplicate: bool = transaction.query_row(
                "SELECT EXISTS(SELECT 1 FROM progress_frames WHERE session_id=?1 AND id=?2)",
                params![session_id, record.base.id],
                |row| row.get(0),
            )?;
            if duplicate {
                return Err(SessionError::invalid_payload("duplicate progress id").into());
            }
        }
        transaction.execute(
            "INSERT OR IGNORE INTO progress_heads(session_id, sequence) VALUES (?1, 0)",
            params![session_id],
        )?;
        let sequence: u64 = transaction.query_row(
            "SELECT sequence FROM progress_heads WHERE session_id = ?1",
            params![session_id],
            |row| row.get(0),
        )?;
        let state = crate::session::progress::ProgressState::at_sequence(sequence);
        let stamped = state
            .prepare(records.to_vec(), || {
                crate::session::memory::Clock::now_ms(&SystemClock)
            })
            .map_err(SessionError::from)?;
        for record in &stamped {
            match record.op {
                AssistantFrameOp::Append => {
                    let json = serde_json::to_string(record).map_err(failure)?;
                    transaction.execute("INSERT INTO progress_frames(session_id, sequence, id, lane, run_id, stream_index, frame_json) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",params![session_id,record.base.seq,record.base.id,record.base.lane,record.run_id,record.stream_index as u64,json])?;
                }
                AssistantFrameOp::ClearStream => {
                    transaction.execute("DELETE FROM progress_frames WHERE session_id=?1 AND lane=?2 AND run_id=?3 AND stream_index=?4",params![session_id,record.base.lane,record.run_id,record.stream_index as u64])?;
                }
                AssistantFrameOp::ClearRun => {
                    transaction.execute(
                        "DELETE FROM progress_frames WHERE session_id=?1 AND lane=?2 AND run_id=?3",
                        params![session_id, record.base.lane, record.run_id],
                    )?;
                }
                AssistantFrameOp::CommitStream => unreachable!(),
            }
        }
        if let Some(last) = stamped.last() {
            transaction.execute(
                "UPDATE progress_heads SET sequence=?1 WHERE session_id=?2",
                params![last.base.seq, session_id],
            )?;
        }
        transaction.commit()?;
        Ok(stamped)
    }

    pub(super) async fn read_progress_sql(
        &self,
        run_id: &str,
    ) -> SessionResult<Vec<AssistantFrameRecord>> {
        let _gate = self.gate.lock().await;
        let id = self.inner.metadata().id;
        let rows: Vec<String> = busy::run(&self.db, "SQLite progress", |db| {
            let mut statement = db.prepare("SELECT frame_json FROM progress_frames WHERE session_id=?1 AND run_id=?2 ORDER BY sequence")?;
            let rows = statement.query_map(params![id, run_id], |row| row.get::<_, String>(0))?;
            rows.collect()
        })
        .await?;
        rows.iter()
            .map(|row| serde_json::from_str(row).map_err(failure))
            .collect()
    }
}
