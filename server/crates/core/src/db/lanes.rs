//! Connection lanes: each connection lives on its own OS thread. Async callers
//! queue for a fair (FIFO) permit with the admission timeout, then hand the job
//! to a free connection thread over a bounded channel, so no rusqlite call ever
//! runs on a tokio worker.
//!
//! Port of the read/write lanes in app/core/db.py (5 s admission timeout →
//! `database_busy`), extended with the concurrent and exclusive write lanes of
//! design §3.3.

use std::collections::BTreeSet;
use std::panic::{catch_unwind, AssertUnwindSafe};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{self, Receiver, SyncSender};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use rusqlite::Connection;
use tokio::sync::{oneshot, OwnedSemaphorePermit, Semaphore};

use super::metrics::{Metrics, CONFLICTS, POOL_TIMEOUTS, RETRIES};
use super::{current_route, retry, DbError, Tx};

type Job = Box<dyn FnOnce(&mut Connection) + Send>;
type Queue = Arc<Mutex<Receiver<(Job, OwnedSemaphorePermit)>>>;

/// Opens and configures one connection on its lane thread.
pub(crate) type Opener = Arc<dyn Fn() -> Result<Connection, DbError> + Send + Sync>;

pub(crate) struct Lane {
    name: &'static str,
    permits: Arc<Semaphore>,
    jobs: SyncSender<(Job, OwnedSemaphorePermit)>,
    admission_timeout: Duration,
    metrics: Arc<Metrics>,
}

impl Lane {
    /// Starts `size` connection threads and waits until every connection is open.
    pub(crate) fn start(
        name: &'static str,
        size: usize,
        admission_timeout: Duration,
        metrics: Arc<Metrics>,
        open: Opener,
    ) -> Result<Lane, DbError> {
        let size = size.max(1);
        let (jobs, queue) = mpsc::sync_channel(size);
        let queue: Queue = Arc::new(Mutex::new(queue));
        let (ready_tx, ready_rx) = mpsc::channel();
        for i in 0..size {
            let queue = queue.clone();
            let open = open.clone();
            let ready = ready_tx.clone();
            std::thread::Builder::new()
                .name(format!("evoflux-db-{name}-{i}"))
                .spawn(move || match open() {
                    Ok(conn) => {
                        let _ = ready.send(Ok(()));
                        drop(ready);
                        serve(conn, &queue);
                    }
                    Err(err) => {
                        let _ = ready.send(Err(err));
                    }
                })
                .map_err(DbError::Io)?;
        }
        drop(ready_tx);
        for _ in 0..size {
            ready_rx.recv().map_err(|_| DbError::Closed)??;
        }
        Ok(Lane {
            name,
            permits: Arc::new(Semaphore::new(size)),
            jobs,
            admission_timeout,
            metrics,
        })
    }

    pub(crate) fn name(&self) -> &'static str {
        self.name
    }

    /// Runs `f` on a free connection of this lane.
    pub(crate) async fn run<T, F>(&self, f: F) -> Result<T, DbError>
    where
        T: Send + 'static,
        F: FnOnce(&mut Connection) -> Result<T, DbError> + Send + 'static,
    {
        let route = current_route();
        let started = Instant::now();
        let acquired =
            tokio::time::timeout(self.admission_timeout, self.permits.clone().acquire_owned())
                .await;
        self.metrics
            .observe_wait(self.name, route, started.elapsed());
        let permit = match acquired {
            Ok(Ok(permit)) => permit,
            Ok(Err(_)) => return Err(DbError::Closed),
            Err(_) => {
                self.metrics
                    .inc(POOL_TIMEOUTS, &[("lane", self.name), ("route", route)]);
                return Err(DbError::Busy);
            }
        };
        let (done_tx, done_rx) = oneshot::channel();
        let job: Job = Box::new(move |conn| {
            let result = catch_unwind(AssertUnwindSafe(|| f(conn))).unwrap_or_else(|_| {
                if !conn.is_autocommit() {
                    let _ = conn.execute_batch("ROLLBACK");
                }
                Err(DbError::Panicked)
            });
            let _ = done_tx.send(result);
        });
        // Permits never exceed the channel capacity, so this cannot be full.
        self.jobs
            .try_send((job, permit))
            .map_err(|_| DbError::Closed)?;
        done_rx
            .await
            .map_err(|_| DbError::Closed)?
            .map_err(DbError::normalize)
    }
}

fn serve(mut conn: Connection, queue: &Queue) {
    loop {
        let next = match queue.lock() {
            Ok(rx) => rx.recv(),
            Err(_) => return,
        };
        let Ok((job, permit)) = next else {
            return;
        };
        job(&mut conn);
        drop(permit);
    }
}

/// Shared state for the concurrent lane's connections.
pub(crate) struct ConcurrentWrites {
    /// Commits are serialized in-process rather than by SQLite's busy handler,
    /// as the begin-concurrent document recommends.
    pub(crate) commit_lock: Mutex<()>,
    pub(crate) max_retries: u32,
    pub(crate) metrics: Arc<Metrics>,
    /// Test hook: every first `COMMIT` fails with `SQLITE_BUSY_SNAPSHOT`.
    pub(crate) inject_busy_snapshot: AtomicBool,
}

thread_local! {
    /// Tables written by this thread's open transaction, recorded by the
    /// connection's update hook so a conflict can be counted per table. Each
    /// connection has its own thread, so this is per connection.
    pub(crate) static WRITTEN_TABLES: Arc<Mutex<BTreeSet<String>>> = Arc::default();
}

/// `BEGIN CONCURRENT` transaction, rerunning `f` after a lost commit.
pub(crate) fn run_concurrent<T, F>(
    conn: &Connection,
    shared: &ConcurrentWrites,
    f: &mut F,
) -> Result<T, DbError>
where
    F: FnMut(&Tx<'_>) -> Result<T, DbError>,
{
    let written = WRITTEN_TABLES.with(Arc::clone);
    let mut retries = 0;
    loop {
        if let Ok(mut tables) = written.lock() {
            tables.clear();
        }
        conn.execute_batch("BEGIN CONCURRENT")?;
        let value = match f(&Tx { conn }) {
            Ok(value) => value,
            Err(err) => {
                rollback(conn);
                return Err(err);
            }
        };
        let committed = {
            let _guard = shared.commit_lock.lock().map_err(|_| DbError::Closed)?;
            if retries == 0 && shared.inject_busy_snapshot.load(Ordering::SeqCst) {
                Err(retry::busy_snapshot_error())
            } else {
                conn.execute_batch("COMMIT")
            }
        };
        match committed {
            Ok(()) => return Ok(value),
            Err(err) if retry::is_busy_snapshot(&err) => {
                rollback(conn);
                if let Ok(tables) = written.lock() {
                    for table in tables.iter() {
                        shared.metrics.inc(CONFLICTS, &[("table", table)]);
                    }
                }
                if retries >= shared.max_retries {
                    return Err(DbError::Busy);
                }
                retries += 1;
                shared.metrics.inc(RETRIES, &[("lane", "write")]);
                retry::sleep_before_retry(retries);
            }
            Err(err) => {
                rollback(conn);
                return Err(err.into());
            }
        }
    }
}

/// `BEGIN IMMEDIATE` transaction on the single FIFO connection.
pub(crate) fn run_exclusive<T, F>(conn: &Connection, f: &mut F) -> Result<T, DbError>
where
    F: FnMut(&Tx<'_>) -> Result<T, DbError>,
{
    conn.execute_batch("BEGIN IMMEDIATE")?;
    let result = f(&Tx { conn }).and_then(|value| {
        conn.execute_batch("COMMIT")?;
        Ok(value)
    });
    if result.is_err() {
        rollback(conn);
    }
    result
}

fn rollback(conn: &Connection) {
    if !conn.is_autocommit() {
        let _ = conn.execute_batch("ROLLBACK");
    }
}
