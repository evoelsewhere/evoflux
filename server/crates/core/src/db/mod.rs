//! SQLite access for every Rust lane: a `query_only` read pool, the concurrent
//! write lane (`BEGIN CONCURRENT`) and the exclusive FIFO write lane.
//!
//! Port of app/core/db.py and `documents/architecture/sqlite-concurrency.md`,
//! extended by design §3.3. The file stays readable by stock SQLite and v3:
//! `wal` journal mode only (never `wal2`), no DDL, no schema change.

mod checkpoint;
mod lanes;
mod metrics;
mod retry;
pub mod rowid;

use std::future::Future;
use std::io::Read as _;
use std::ops::Deref;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use rusqlite::{Connection, OpenFlags};

use checkpoint::WalKeeper;
use lanes::{ConcurrentWrites, Lane, Opener, WRITTEN_TABLES};
use metrics::Metrics;

/// Environment switch: only `on` enables the concurrent lane; anything else,
/// including unset, keeps every write on the exclusive FIFO lane (design §3.3).
pub const CONCURRENT_WRITES_ENV: &str = "EVOFLUX_DB_CONCURRENT_WRITES";

#[derive(Debug, thiserror::Error)]
pub enum DbError {
    /// No connection within the admission timeout, a lock wait that ran out,
    /// or a concurrent commit that kept conflicting. Renders as HTTP 503
    /// `database_busy`.
    #[error("database is busy")]
    Busy,
    /// The file uses `wal2`, which stock SQLite and v3 cannot open.
    #[error("database uses wal2 journal mode, which is not supported")]
    Wal2,
    /// `PRAGMA journal_mode=WAL` did not take effect.
    #[error("database journal mode is {0}, expected wal")]
    NotWal(String),
    #[error("no unused random rowid found")]
    RowidExhausted,
    #[error("database connection closed")]
    Closed,
    #[error("database closure panicked")]
    Panicked,
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    Sqlite(#[from] rusqlite::Error),
}

impl DbError {
    /// Lock and admission failures all surface as [`DbError::Busy`].
    fn normalize(self) -> DbError {
        match self {
            DbError::Sqlite(err) if retry::is_busy(&err) => DbError::Busy,
            other => other,
        }
    }
}

/// `_database_busy` in app/core/exception_handlers.py for [`DbError::Busy`];
/// anything else is Python's catch-all 500.
impl From<DbError> for crate::ApiError {
    fn from(err: DbError) -> Self {
        match err {
            DbError::Busy => crate::ApiError::database_busy(),
            _ => crate::ApiError::internal(),
        }
    }
}

#[derive(Clone, Debug)]
pub struct DbOptions {
    /// `query_only` read connections.
    pub readers: usize,
    /// `BEGIN CONCURRENT` writer connections.
    pub concurrent_writers: usize,
    /// Longest wait for a connection before [`DbError::Busy`].
    pub admission_timeout: Duration,
    /// Retries after a lost concurrent commit, one per backoff step
    /// (2/8/32/64/128 ms); the default 5 allows up to 6 attempts in total.
    pub max_retries: u32,
    /// `false` routes [`Db::write`] through the exclusive FIFO lane. Defaults
    /// to `false` unless `EVOFLUX_DB_CONCURRENT_WRITES=on`.
    pub concurrent_enabled: bool,
    /// WAL frames after a commit that trigger a `PASSIVE` checkpoint.
    pub wal_checkpoint_pages: u32,
    /// WAL frames after a commit that pause new write transactions until a
    /// `TRUNCATE` checkpoint has reset the WAL.
    pub wal_restart_pages: u32,
}

impl DbOptions {
    /// Concurrent writes are off by default everywhere (owner decision,
    /// design §3.3) until they are re-benchmarked; only `on` enables them.
    pub fn concurrent_writes_from_env(value: Option<&str>) -> bool {
        value.is_some_and(|v| v.trim().eq_ignore_ascii_case("on"))
    }
}

impl Default for DbOptions {
    fn default() -> Self {
        let switch = std::env::var(CONCURRENT_WRITES_ENV).ok();
        DbOptions {
            readers: 5,
            // Windows Phase 0 benchmark (bounded WAL): two writers led
            // cross-table work without exhausting the retry budget.
            concurrent_writers: 2,
            admission_timeout: Duration::from_secs(5),
            max_retries: 5,
            concurrent_enabled: DbOptions::concurrent_writes_from_env(switch.as_deref()),
            // SQLite's own autocheckpoint threshold, and four times that.
            wal_checkpoint_pages: 1000,
            wal_restart_pages: 4000,
        }
    }
}

/// An open write transaction. Dereferences to the connection; the lane owns
/// `BEGIN`, `COMMIT` and `ROLLBACK`.
///
/// rusqlite's `Transaction` cannot be started with `BEGIN CONCURRENT`, and a
/// `&Transaction` offers closures nothing beyond `&Connection`, so both write
/// lanes pass this type.
pub struct Tx<'a> {
    conn: &'a Connection,
}

impl Deref for Tx<'_> {
    type Target = Connection;

    fn deref(&self) -> &Connection {
        self.conn
    }
}

tokio::task_local! {
    static ROUTE: &'static str;
}

/// Runs `fut` with `route` as the `route` label of database metrics.
pub async fn with_route<F: Future>(route: &'static str, fut: F) -> F::Output {
    ROUTE.scope(route, fut).await
}

fn current_route() -> &'static str {
    ROUTE.try_with(|route| *route).unwrap_or("unknown")
}

pub struct Db {
    readers: Lane,
    writers: Option<Lane>,
    exclusive: Lane,
    concurrent: Arc<ConcurrentWrites>,
    metrics: Arc<Metrics>,
}

impl Db {
    /// Opens every connection on its own thread. Blocking: call it at startup
    /// or through `spawn_blocking`.
    pub fn open(path: &Path, opts: DbOptions) -> Result<Db, DbError> {
        refuse_wal2(path)?;
        let metrics = Arc::new(Metrics::default());
        let wal = Arc::new(WalKeeper::new(
            opts.wal_checkpoint_pages,
            opts.wal_restart_pages,
            metrics.clone(),
        ));
        let concurrent = Arc::new(ConcurrentWrites {
            commit_lock: Mutex::new(()),
            max_retries: opts.max_retries,
            metrics: metrics.clone(),
            inject_busy_snapshot: AtomicBool::new(false),
            wal: wal.clone(),
        });
        let timeout = opts.admission_timeout;
        // The exclusive connection opens first so it alone switches the file to WAL.
        let exclusive = Lane::start(
            "exclusive",
            1,
            timeout,
            metrics.clone(),
            opener(path, Role::Write, &wal),
        )?;
        let writers = if opts.concurrent_enabled {
            Some(Lane::start(
                "write",
                opts.concurrent_writers,
                timeout,
                metrics.clone(),
                opener(path, Role::Concurrent, &wal),
            )?)
        } else {
            None
        };
        let readers = Lane::start(
            "read",
            opts.readers,
            timeout,
            metrics.clone(),
            opener(path, Role::Read, &wal),
        )?;
        Ok(Db {
            readers,
            writers,
            exclusive,
            concurrent,
            metrics,
        })
    }

    /// Runs `f` on a `query_only` read connection.
    pub async fn read<T, F>(&self, f: F) -> Result<T, DbError>
    where
        T: Send + 'static,
        F: FnOnce(&Connection) -> Result<T, DbError> + Send + 'static,
    {
        self.readers.run(move |conn| f(conn)).await
    }

    /// Ordinary write on the concurrent lane (`BEGIN CONCURRENT`) when enabled;
    /// otherwise use the exclusive FIFO lane. `f` may run more than once:
    /// database work only, no I/O or events inside it.
    pub async fn write<T, F>(&self, f: F) -> Result<T, DbError>
    where
        T: Send + 'static,
        F: FnMut(&Tx<'_>) -> Result<T, DbError> + Send + 'static,
    {
        let Some(writers) = &self.writers else {
            return self.write_exclusive(f).await;
        };
        let shared = self.concurrent.clone();
        let mut f = f;
        writers
            .run(move |conn| lanes::run_concurrent(conn, &shared, &mut f))
            .await
    }

    /// Write on the single FIFO connection (`BEGIN IMMEDIATE`): migrations,
    /// bulk purge/import and wide multi-table changes.
    pub async fn write_exclusive<T, F>(&self, f: F) -> Result<T, DbError>
    where
        T: Send + 'static,
        F: FnMut(&Tx<'_>) -> Result<T, DbError> + Send + 'static,
    {
        let mut f = f;
        let wal = self.concurrent.wal.clone();
        self.exclusive
            .run(move |conn| lanes::run_exclusive(conn, &wal, &mut f))
            .await
    }

    /// Lane that [`Db::write`] uses: `write` (concurrent) or `exclusive`.
    pub fn write_lane(&self) -> &'static str {
        self.writers.as_ref().unwrap_or(&self.exclusive).name()
    }

    /// Sum of the series of metric `name` whose labels include `labels`.
    pub fn metric(&self, name: &str, labels: &[(&str, &str)]) -> f64 {
        self.metrics.value(name, labels)
    }

    /// Prometheus text exposition of the database metrics.
    pub fn render_metrics(&self) -> String {
        self.metrics.render()
    }

    /// Test hook for the retry-safety test: every first concurrent `COMMIT`
    /// fails with `SQLITE_BUSY_SNAPSHOT`.
    #[doc(hidden)]
    pub fn inject_busy_snapshot_on_first_commit(&self, on: bool) {
        self.concurrent
            .inject_busy_snapshot
            .store(on, Ordering::SeqCst);
    }
}

#[derive(Clone, Copy)]
enum Role {
    Read,
    Write,
    Concurrent,
}

fn opener(path: &Path, role: Role, wal: &Arc<WalKeeper>) -> Opener {
    let path: PathBuf = path.to_path_buf();
    let wal = wal.clone();
    Arc::new(move || open_connection(&path, role, &wal))
}

fn open_connection(path: &Path, role: Role, wal: &Arc<WalKeeper>) -> Result<Connection, DbError> {
    let flags = OpenFlags::SQLITE_OPEN_READ_WRITE
        | OpenFlags::SQLITE_OPEN_CREATE
        | OpenFlags::SQLITE_OPEN_URI
        | OpenFlags::SQLITE_OPEN_NO_MUTEX;
    let mut conn = Connection::open_with_flags(path, flags)?;
    conn.busy_timeout(Duration::from_secs(5))?;
    let mode: String = conn.query_row("PRAGMA journal_mode=WAL", [], |r| r.get(0))?;
    if !mode.eq_ignore_ascii_case("wal") {
        return Err(DbError::NotWal(mode));
    }
    conn.pragma_update(None, "foreign_keys", "ON")?;
    conn.pragma_update(None, "synchronous", "NORMAL")?;
    match role {
        Role::Read => conn.pragma_update(None, "query_only", "ON")?,
        Role::Write => wal.attach(&mut conn)?,
        Role::Concurrent => {
            wal.attach(&mut conn)?;
            let written = WRITTEN_TABLES.with(Arc::clone);
            conn.update_hook(Some(move |_action, _db: &str, table: &str, _rowid| {
                if let Ok(mut tables) = written.lock() {
                    if !tables.contains(table) {
                        tables.insert(table.to_owned());
                    }
                }
            }))?;
        }
    }
    Ok(conn)
}

/// `wal2` sets the header's file-format write/read versions (bytes 18 and 19)
/// to 3. Stock SQLite cannot open such a file, so neither do we.
fn refuse_wal2(path: &Path) -> Result<(), DbError> {
    let mut header = [0_u8; 100];
    let read = match std::fs::OpenOptions::new().read(true).open(path) {
        Ok(mut file) => file.read(&mut header)?,
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => return Ok(()),
        Err(err) => return Err(err.into()),
    };
    let is_sqlite = header.starts_with(b"SQLite format 3\0");
    if read >= 20 && is_sqlite && (header.get(18) == Some(&3) || header.get(19) == Some(&3)) {
        return Err(DbError::Wal2);
    }
    Ok(())
}
