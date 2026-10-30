//! Lane-managed WAL checkpoints.
//!
//! SQLite resets the WAL only when no connection still reads an older
//! snapshot. With two or more `BEGIN CONCURRENT` writers one transaction is
//! nearly always open, so the autocheckpoint never resets the WAL: it grows
//! without bound and every commit pays for another checkpoint attempt. The
//! write lanes therefore turn the autocheckpoint off and checkpoint here:
//!
//! - after a commit that adds `wal_checkpoint_pages` frames, a `PASSIVE`
//!   checkpoint (in the concurrent lane, still under the commit mutex);
//! - once the WAL holds `wal_restart_pages` frames, new write transactions
//!   wait at the gate until open ones finish, then a `TRUNCATE` checkpoint
//!   resets the WAL.

use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::{Arc, Condvar, Mutex, PoisonError};

use rusqlite::Connection;

use super::metrics::{Metrics, CHECKPOINTS};
use super::DbError;

pub(crate) struct WalKeeper {
    /// Frames in the WAL after the last lane commit, from the WAL hook.
    frames: AtomicU32,
    /// Frame count at the last `PASSIVE` checkpoint.
    checkpointed_at: AtomicU32,
    checkpoint_pages: u32,
    restart_pages: u32,
    gate: Mutex<Gate>,
    changed: Condvar,
    metrics: Arc<Metrics>,
}

#[derive(Default)]
struct Gate {
    /// Write transactions open on lane connections.
    open: usize,
    /// A `TRUNCATE` checkpoint is waiting or running.
    draining: bool,
}

/// Held for the life of one write transaction.
pub(crate) struct Entered<'a>(&'a WalKeeper);

impl Drop for Entered<'_> {
    fn drop(&mut self) {
        let mut gate = self.0.gate.lock().unwrap_or_else(PoisonError::into_inner);
        gate.open = gate.open.saturating_sub(1);
        drop(gate);
        self.0.changed.notify_all();
    }
}

impl WalKeeper {
    pub(crate) fn new(checkpoint_pages: u32, restart_pages: u32, metrics: Arc<Metrics>) -> Self {
        WalKeeper {
            frames: AtomicU32::new(0),
            checkpointed_at: AtomicU32::new(0),
            checkpoint_pages: checkpoint_pages.max(1),
            restart_pages: restart_pages.max(1),
            gate: Mutex::new(Gate::default()),
            changed: Condvar::new(),
            metrics,
        }
    }

    /// Turns off the autocheckpoint of a write connection and reports its
    /// commits' WAL size here instead.
    pub(crate) fn attach(self: &Arc<Self>, conn: &mut Connection) -> Result<(), DbError> {
        conn.pragma_update(None, "wal_autocheckpoint", 0)?;
        let keeper = self.clone();
        conn.wal_hook(Some(move |_: &mut rusqlite::hooks::Wal, frames| {
            keeper
                .frames
                .store(u32::try_from(frames).unwrap_or(0), Ordering::SeqCst);
            Ok(())
        }))?;
        Ok(())
    }

    /// Waits while the WAL is being reset, then counts a transaction as open.
    pub(crate) fn enter(&self) -> Result<Entered<'_>, DbError> {
        let gate = self.gate.lock().map_err(|_| DbError::Closed)?;
        let mut gate = self
            .changed
            .wait_while(gate, |g| g.draining)
            .map_err(|_| DbError::Closed)?;
        gate.open += 1;
        Ok(Entered(self))
    }

    /// `PASSIVE` checkpoint once enough frames were added since the last one.
    /// Call right after a successful `COMMIT`.
    pub(crate) fn after_commit(&self, conn: &Connection) {
        let frames = self.frames.load(Ordering::SeqCst);
        let mut last = self.checkpointed_at.load(Ordering::SeqCst);
        if frames < last {
            // The WAL was reset since.
            last = 0;
        }
        if frames.saturating_sub(last) >= self.checkpoint_pages {
            self.checkpointed_at.store(frames, Ordering::SeqCst);
            checkpoint(conn, "PASSIVE", &self.metrics);
        }
    }

    /// Resets the WAL once it is over the restart size. Call after the
    /// transaction's [`Entered`] guard is dropped and outside the commit
    /// mutex, so open transactions can finish.
    pub(crate) fn restart_if_due(&self, conn: &Connection) {
        if self.frames.load(Ordering::SeqCst) < self.restart_pages {
            return;
        }
        let mut gate = self.gate.lock().unwrap_or_else(PoisonError::into_inner);
        if gate.draining {
            return;
        }
        gate.draining = true;
        let mut gate = self
            .changed
            .wait_while(gate, |g| g.open > 0)
            .unwrap_or_else(PoisonError::into_inner);
        // With no lane transaction open, only short reads can hold an old
        // snapshot; `TRUNCATE` waits for those through the busy handler.
        checkpoint(conn, "TRUNCATE", &self.metrics);
        self.frames.store(0, Ordering::SeqCst);
        self.checkpointed_at.store(0, Ordering::SeqCst);
        gate.draining = false;
        drop(gate);
        self.changed.notify_all();
    }
}

fn checkpoint(conn: &Connection, mode: &'static str, metrics: &Metrics) {
    // Best effort: a checkpoint that cannot finish leaves the WAL for the next one.
    let done = conn.query_row(&format!("PRAGMA wal_checkpoint({mode})"), [], |r| {
        r.get::<_, i64>(0)
    });
    let outcome = match done {
        Ok(0) => "ok",
        Ok(_) => "busy",
        Err(_) => "error",
    };
    metrics.inc(CHECKPOINTS, &[("mode", mode), ("outcome", outcome)]);
}
