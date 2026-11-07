//! Waiting out other engines that hold the database's write lock.
//!
//! Every chat's engine (and the desktop shell) writes to the same SQLite file,
//! and SQLite lets one writer in at a time. A connection's busy timeout covers
//! short waits, but under a burst — dozens of engines starting or streaming at
//! once — SQLite's busy handler can still give up, and that "database is
//! locked" used to fail the whole turn. These helpers rerun such an operation
//! from the start after a growing, jittered pause, until [`BUSY_BUDGET`] has
//! passed; only then does the error surface.

use std::sync::Mutex;
use std::time::{Duration, Instant};

use rusqlite::Connection;

use crate::error::{SessionError, SessionResult};

/// How long one statement waits inside SQLite before it reports the database
/// busy. Short in unit tests, so they can hold the lock past it quickly.
#[cfg(not(test))]
pub(super) const BUSY_TIMEOUT: Duration = Duration::from_secs(5);
#[cfg(test)]
pub(super) const BUSY_TIMEOUT: Duration = Duration::from_millis(100);

/// How long an operation keeps retrying a busy database in total.
const BUSY_BUDGET: Duration = Duration::from_secs(60);

/// The longest pause between two attempts.
const MAX_PAUSE: Duration = Duration::from_millis(500);

/// Whether `error` means another connection holds the lock (worth retrying).
pub(super) fn is_busy(error: &rusqlite::Error) -> bool {
    matches!(
        error,
        rusqlite::Error::SqliteFailure(failure, _)
            if matches!(failure.code, rusqlite::ErrorCode::DatabaseBusy | rusqlite::ErrorCode::DatabaseLocked)
    )
}

/// The pauses of one operation's retries.
pub(super) struct Backoff {
    started: Instant,
    attempt: u32,
}

impl Backoff {
    pub(super) fn new() -> Self {
        Self {
            started: Instant::now(),
            attempt: 0,
        }
    }

    /// The pause before the next attempt, or `None` once the budget is spent.
    /// Pauses double from 10 ms up to [`MAX_PAUSE`]; each is drawn from
    /// [half, full] so engines that failed together retry apart.
    pub(super) fn next_pause(&mut self) -> Option<Duration> {
        if self.started.elapsed() >= BUSY_BUDGET {
            return None;
        }
        let full = Duration::from_millis(10u64 << self.attempt.min(6)).min(MAX_PAUSE);
        self.attempt += 1;
        let half = full / 2;
        let spread = half.as_micros().max(1);
        let jitter = (uuid::Uuid::new_v4().as_u128() % spread) as u64;
        Some(half + Duration::from_micros(jitter))
    }
}

/// Run `op` on the connection until it succeeds, fails with anything but a
/// busy database, or the budget is spent; errors read "`what`: cause". The
/// connection is released during pauses. `op` must leave nothing half-done
/// when it fails (one statement, or a transaction that rolls back on drop).
pub(super) async fn run<T>(
    db: &Mutex<Connection>,
    what: &str,
    mut op: impl FnMut(&Connection) -> rusqlite::Result<T>,
) -> SessionResult<T> {
    let mut backoff = Backoff::new();
    loop {
        let result = {
            let conn = db
                .lock()
                .map_err(|_| SessionError::storage("SQLite connection poisoned"))?;
            op(&conn)
        };
        match result {
            Ok(value) => return Ok(value),
            Err(error) if is_busy(&error) => match backoff.next_pause() {
                Some(pause) => tokio::time::sleep(pause).await,
                None => return Err(SessionError::storage(format!("{what}: {error}"))),
            },
            Err(error) => return Err(SessionError::storage(format!("{what}: {error}"))),
        }
    }
}

/// Like [`run`], for synchronous callers (opening the repository), on a
/// connection they own.
pub(super) fn retry_blocking<T>(
    mut op: impl FnMut() -> rusqlite::Result<T>,
) -> rusqlite::Result<T> {
    let mut backoff = Backoff::new();
    loop {
        match op() {
            Err(error) if is_busy(&error) => match backoff.next_pause() {
                Some(pause) => std::thread::sleep(pause),
                None => return Err(error),
            },
            result => return result,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn pauses_grow_to_the_cap_and_stay_within_half_to_full() {
        let mut backoff = Backoff::new();
        let mut fulls = Vec::new();
        for attempt in 0..10u32 {
            let full = Duration::from_millis(10u64 << attempt.min(6)).min(MAX_PAUSE);
            let pause = backoff.next_pause().unwrap();
            assert!(
                pause >= full / 2 && pause <= full,
                "attempt {attempt}: {pause:?} not in [{:?}, {full:?}]",
                full / 2
            );
            fulls.push(full);
        }
        assert_eq!(fulls.last(), Some(&MAX_PAUSE));
    }

    #[test]
    fn a_spent_budget_stops_retrying() {
        let mut backoff = Backoff {
            started: Instant::now() - BUSY_BUDGET,
            attempt: 0,
        };
        assert_eq!(backoff.next_pause(), None);
    }

    #[test]
    fn only_busy_and_locked_are_retryable() {
        let failure = |code| {
            rusqlite::Error::SqliteFailure(
                rusqlite::ffi::Error {
                    code,
                    extended_code: 0,
                },
                None,
            )
        };
        assert!(is_busy(&failure(rusqlite::ErrorCode::DatabaseBusy)));
        assert!(is_busy(&failure(rusqlite::ErrorCode::DatabaseLocked)));
        assert!(!is_busy(&failure(rusqlite::ErrorCode::ConstraintViolation)));
        assert!(!is_busy(&rusqlite::Error::QueryReturnedNoRows));
    }
}
