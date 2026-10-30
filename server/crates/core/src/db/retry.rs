//! Retry policy for the concurrent write lane (design §3.3).

use std::time::Duration;

use rusqlite::ffi;

/// Backoff before retry `n` (1-based), before jitter.
const BACKOFF_MS: [u64; 5] = [2, 8, 32, 64, 128];

/// `COMMIT` of a `BEGIN CONCURRENT` transaction lost to another commit.
pub(crate) fn is_busy_snapshot(err: &rusqlite::Error) -> bool {
    matches!(err, rusqlite::Error::SqliteFailure(e, _) if e.extended_code == ffi::SQLITE_BUSY_SNAPSHOT)
}

/// SQLite gave up waiting for a lock (after `busy_timeout`).
pub(crate) fn is_busy(err: &rusqlite::Error) -> bool {
    matches!(
        err.sqlite_error_code(),
        Some(ffi::ErrorCode::DatabaseBusy | ffi::ErrorCode::DatabaseLocked)
    )
}

/// The error a lost `COMMIT` returns; used by the retry-safety test hook.
pub(crate) fn busy_snapshot_error() -> rusqlite::Error {
    rusqlite::Error::SqliteFailure(ffi::Error::new(ffi::SQLITE_BUSY_SNAPSHOT), None)
}

/// Jittered delay for retry `n` (1-based): uniform in [base/2, base*3/2].
pub(crate) fn backoff(retry: u32) -> Duration {
    let index = usize::try_from(retry.saturating_sub(1)).unwrap_or(usize::MAX);
    let base = BACKOFF_MS
        .get(index)
        .or(BACKOFF_MS.last())
        .copied()
        .unwrap_or(128)
        * 1000;
    Duration::from_micros(base / 2 + fastrand::u64(0..=base))
}

/// Sleep before a retry. Runs only on the lane's dedicated OS thread, never on
/// a tokio worker.
pub(crate) fn sleep_before_retry(retry: u32) {
    #[allow(clippy::disallowed_methods)]
    std::thread::sleep(backoff(retry));
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn backoff_is_jittered_around_schedule() {
        for (retry, base) in [
            (1, 2_000),
            (2, 8_000),
            (3, 32_000),
            (4, 64_000),
            (5, 128_000),
        ] {
            for _ in 0..100 {
                let d = backoff(retry).as_micros();
                assert!(d >= base / 2 && d <= base * 3 / 2, "{retry}: {d}");
            }
        }
    }

    #[test]
    fn classifies_busy_snapshot() {
        let err = busy_snapshot_error();
        assert!(is_busy_snapshot(&err));
        assert!(is_busy(&err));
    }
}
