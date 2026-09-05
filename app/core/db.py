from __future__ import annotations

import hashlib
import time
from collections.abc import AsyncGenerator, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger
from sqlalchemy import event
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import AsyncAdaptedQueuePool
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.requests import Request

from app.core.config import settings
from app.core.metrics import (
    DB_POOL_CHECKED_OUT,
    DB_POOL_TIMEOUTS,
    DB_POOL_WAIT,
    DB_QUERY_DURATION,
    DB_TRANSACTION_DURATION,
)
from app.core.request_context import request_origin

if TYPE_CHECKING:
    from alembic.config import Config

_db_url = settings.DATABASE_URL.get_secret_value()
_is_sqlite = "sqlite" in _db_url
# Resolved on-disk DB path for SQLite, or "" otherwise. Used by
# ``run_migrations`` to take a sibling file lock so concurrent processes
# don't race on ``CREATE TABLE alembic_version``.
_db_path: str = ""

# SQLite cannot create the parent directory itself — without this, a
# fresh ``uv tool install`` install fails on first start with
# ``sqlite3.OperationalError: unable to open database file`` because
# ``~/.local/share/EvoFlux/`` doesn't exist yet. ``mkdir`` is cheap
# and idempotent; safer to do it unconditionally for SQLite URLs.
if _is_sqlite:
    # ``sqlite+aiosqlite:///<abs-path>`` → strip the scheme.
    _db_path = _db_url.split("///", 1)[-1]
    if _db_path and _db_path != ":memory:":
        Path(_db_path).expanduser().parent.mkdir(parents=True, exist_ok=True)


# SQLite is a single-writer database. Giving every concurrent writer its own
# pooled connection lets all of them occupy the pool while SQLite queues them
# on its file lock, starving otherwise-safe WAL readers. Keep the application
# writer lane at one connection and give HTTP reads an independent pool.
class _ObservedQueuePool(AsyncAdaptedQueuePool):
    """Measure the queueing time hidden before SQLAlchemy's checkout event."""

    lane = "unknown"

    def _do_get(self):  # noqa: ANN202 — SQLAlchemy's private hook is untyped
        started = time.perf_counter()
        _method, route = request_origin()
        try:
            return super()._do_get()
        except SQLAlchemyTimeoutError:
            DB_POOL_TIMEOUTS.labels(lane=self.lane, route=route).inc()
            raise
        finally:
            elapsed = time.perf_counter() - started
            DB_POOL_WAIT.labels(lane=self.lane, route=route).observe(elapsed)
            if elapsed >= 0.25:
                logger.warning(
                    "slow_db_pool_wait lane={} route={} duration_ms={}",
                    self.lane,
                    route,
                    round(elapsed * 1000),
                )


class _WriteQueuePool(_ObservedQueuePool):
    lane = "write"


class _ReadQueuePool(_ObservedQueuePool):
    lane = "read"


_write_pool_kwargs: dict = (
    {
        "poolclass": _WriteQueuePool,
        "pool_size": 1,
        "max_overflow": 0,
        "pool_timeout": 5,
    }
    if _is_sqlite
    else {"pool_size": 20, "max_overflow": 10, "pool_timeout": 10}
)

engine = create_async_engine(
    _db_url,
    echo=False,
    pool_pre_ping=True,
    pool_recycle=3600,
    **_write_pool_kwargs,
)

read_engine = (
    create_async_engine(
        _db_url,
        echo=False,
        pool_pre_ping=True,
        pool_recycle=3600,
        poolclass=_ReadQueuePool,
        pool_size=5,
        max_overflow=0,
        pool_timeout=5,
    )
    if _is_sqlite
    else engine
)

# Me enable WAL mode for SQLite — 5-10x write throughput, concurrent reads during writes
if _is_sqlite:

    def _set_sqlite_pragmas(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        # Fresh databases opt into bounded, explicit page reclamation. Existing
        # databases adopt it after the one-time maintenance VACUUM.
        cursor.execute("PRAGMA auto_vacuum=INCREMENTAL")
        # In-process writers queue in the one-connection writer lane. This
        # shorter timeout only covers a second process touching the same file
        # and prevents a local UI request from appearing frozen for 30 seconds.
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    def _set_sqlite_read_pragmas(dbapi_conn, connection_record):
        _set_sqlite_pragmas(dbapi_conn, connection_record)
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA query_only=ON")
        cursor.close()

    event.listen(engine.sync_engine, "connect", _set_sqlite_pragmas)
    event.listen(read_engine.sync_engine, "connect", _set_sqlite_read_pragmas)


def _sql_operation(statement: str) -> str:
    head = statement.lstrip().split(None, 1)
    return head[0].upper() if head else "UNKNOWN"


def _instrument_engine(target_engine, lane: str) -> None:
    @event.listens_for(target_engine.sync_engine, "checkout")
    def _checkout(dbapi_conn, connection_record, connection_proxy):
        DB_POOL_CHECKED_OUT.labels(lane=lane).inc()

    @event.listens_for(target_engine.sync_engine, "checkin")
    def _checkin(dbapi_conn, connection_record):
        DB_POOL_CHECKED_OUT.labels(lane=lane).dec()

    @event.listens_for(target_engine.sync_engine, "before_cursor_execute")
    def _before_cursor_execute(
        conn, cursor, statement, parameters, context, executemany
    ):
        context._evoflux_query_started = time.perf_counter()

    @event.listens_for(target_engine.sync_engine, "after_cursor_execute")
    def _after_cursor_execute(
        conn, cursor, statement, parameters, context, executemany
    ):
        started = getattr(context, "_evoflux_query_started", None)
        if started is None:
            return
        elapsed = time.perf_counter() - started
        operation = _sql_operation(statement)
        DB_QUERY_DURATION.labels(lane=lane, operation=operation).observe(elapsed)
        if elapsed >= 0.25:
            method, route = request_origin()
            normalized = " ".join(statement.split())
            fingerprint = hashlib.sha256(normalized.encode()).hexdigest()[:12]
            logger.warning(
                "slow_db_query lane={} operation={} fingerprint={} method={} "
                "route={} duration_ms={} statement={!r}",
                lane,
                operation,
                fingerprint,
                method,
                route,
                round(elapsed * 1000),
                normalized[:500],
            )

    @event.listens_for(target_engine.sync_engine, "begin")
    def _begin(conn):
        conn.info["evoflux_transaction_started"] = time.perf_counter()

    def _finish_transaction(conn, outcome: str) -> None:
        started = conn.info.pop("evoflux_transaction_started", None)
        if started is None:
            return
        DB_TRANSACTION_DURATION.labels(lane=lane, outcome=outcome).observe(
            time.perf_counter() - started
        )

    @event.listens_for(target_engine.sync_engine, "commit")
    def _commit(conn):
        _finish_transaction(conn, "commit")

    @event.listens_for(target_engine.sync_engine, "rollback")
    def _rollback(conn):
        _finish_transaction(conn, "rollback")


_instrument_engine(engine, "write")
if read_engine is not engine:
    _instrument_engine(read_engine, "read")


async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

read_session_factory = async_sessionmaker(
    read_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# Type alias for a session factory callable.
# async_sessionmaker[AsyncSession] satisfies this; so do @asynccontextmanager
# helpers used in tests — both are callable async context managers.
DbFactory = async_sessionmaker[AsyncSession]


def current_sqlite_path() -> str | None:
    """Return the on-disk path of the active SQLite database, or ``None``.

    Reads the *live* module-level ``engine`` (tests rebind it to a temp file).
    Returns ``None`` for non-SQLite engines or in-memory databases.
    """
    if engine.url.get_backend_name() != "sqlite":
        return None
    database = engine.url.database
    if not database or database == ":memory:":
        return None
    return database


def resolve_db_factory(factory: DbFactory | None) -> DbFactory:
    """Return *factory* if not ``None``, else the module-level default.

    Centralises the ``factory or async_session_factory`` fallback that
    was repeated across team-member, team, scheduler-tool, and loader
    call sites.  Production code generally passes a factory explicitly;
    tests sometimes pass ``None`` and expect to get the real one.
    """
    return factory if factory is not None else async_session_factory


def run_migrations() -> None:
    """Run pending Alembic migrations (upgrade head).

    Called once during server startup so users never need a separate
    ``evoflux migrate`` step.  ``alembic.ini`` ships inside the ``app``
    package so it is reachable from both source checkouts and installed
    wheels.

    Concurrent invocations on SQLite are serialised with an advisory file
    lock alongside the database file. Without this, two processes (e.g.
    a daemon wrapper and the actual uvicorn worker) can race on
    ``CREATE TABLE alembic_version`` and one ends up logging a noisy
    ``OperationalError: table … already exists`` even though both end up
    in the correct state. Postgres/MySQL serialise DDL themselves, so we
    skip the lock there.
    """
    from alembic.config import Config

    # Locate alembic.ini — packaged inside app/ so wheel installs find it.
    ini_path = Path(__file__).resolve().parent.parent / "alembic.ini"
    if not ini_path.is_file():
        # Treat as a hard error — silently skipping leaves users with an
        # empty DB and a confusing 500 on the first chat message.
        raise RuntimeError(
            f"alembic.ini not found at {ini_path}. "
            "The package is broken — reinstall EvoFlux."
        )

    cfg = Config(str(ini_path))
    # Override the DB URL so it always matches the runtime settings,
    # regardless of what alembic.ini has hardcoded.
    cfg.set_main_option("sqlalchemy.url", settings.DATABASE_URL.get_secret_value())

    if _is_sqlite and _db_path and _db_path != ":memory:":
        with _sqlite_migration_lock(Path(_db_path).expanduser()):
            _run_alembic_upgrade(cfg)
    else:
        _run_alembic_upgrade(cfg)


def _run_alembic_upgrade(cfg: Config) -> None:
    """Invoke ``alembic upgrade head`` and log the outcome.

    SQLite raises ``OperationalError: table alembic_version already exists``
    when two processes race on the very first migration (e.g. a daemon wrapper
    and the uvicorn worker both hit startup before the lock serialises them).
    That race means the schema is already in the correct state, so we treat it
    as a no-op rather than an error.
    """
    from alembic import command
    from sqlalchemy.exc import OperationalError

    try:
        command.upgrade(cfg, "head")
        logger.info("auto_migrate_complete")
    except OperationalError as exc:
        msg = str(exc).lower()
        if "already exists" in msg:
            # Schema was created by a concurrent process — we are at head.
            logger.debug("auto_migrate_skipped reason=already_exists")
        else:
            logger.error("auto_migrate_failed error={}", exc)
            raise
    except Exception as exc:
        logger.error("auto_migrate_failed error={}", exc)
        raise


@contextmanager
def _sqlite_migration_lock(db_path: Path) -> Iterator[None]:
    """Serialise concurrent ``run_migrations`` calls on the same SQLite DB.

    Uses ``fcntl.flock`` (POSIX) on a sibling ``.migrate.lock`` file. The
    lock file lives alongside the DB so it shares the DB's filesystem —
    important because ``flock`` is a no-op across NFS on some platforms.
    On Windows ``fcntl`` is unavailable; we fall back to no-op which is
    fine because Windows isn't a supported deployment target today.
    """
    try:
        import fcntl
    except ImportError:  # pragma: no cover — Windows
        yield
        return

    lock_path = db_path.parent / f"{db_path.name}.migrate.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


async def get_session(
    request: Request,
) -> AsyncGenerator[AsyncSession, None]:
    """Yield the read or write lane according to the HTTP method."""
    is_read_request = request.method in {
        "GET",
        "HEAD",
        "OPTIONS",
    }
    factory = read_session_factory if is_read_request else async_session_factory
    async with factory() as session:
        try:
            yield session
            if is_read_request:
                await session.rollback()
            else:
                await session.commit()
        except BaseException:
            await session.rollback()
            raise


async def get_write_session() -> AsyncGenerator[AsyncSession, None]:
    """Force the writer lane for GET-shaped transports such as durable SSE."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise


async def get_read_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield a request-scoped read session on SQLite's dedicated read lane.

    Read transactions are always rolled back at teardown. This closes the
    snapshot without turning every GET into a commit boundary and guarantees
    that accidental ORM mutations in a read route are not persisted.
    """
    async with read_session_factory() as session:
        try:
            yield session
        finally:
            await session.rollback()


#: ``PRAGMA auto_vacuum`` reporting INCREMENTAL.
AUTO_VACUUM_INCREMENTAL = 2


async def incremental_vacuum(connection, pages: int | None = None) -> int:
    """Reclaim free pages, and actually reclaim them. Returns pages freed.

    ``PRAGMA incremental_vacuum`` does its work one page per step of the
    statement, and it declares no result columns. SQLAlchemy sees a result
    that returns no rows and closes it after the first step, so
    ``exec_driver_sql("PRAGMA incremental_vacuum(2048)")`` frees exactly one
    page — measured on a 105 MiB fixture: 19,661 free pages went to 19,660.
    Stepping the cursor to exhaustion frees all of them and shrinks the file
    to 26 MiB.

    ``pages`` bounds the work; ``None`` reclaims everything.
    """
    if not _is_sqlite:
        return 0
    before = int(
        (await connection.exec_driver_sql("PRAGMA freelist_count")).scalar_one()
    )
    statement = (
        "PRAGMA incremental_vacuum"
        if pages is None
        else f"PRAGMA incremental_vacuum({int(pages)})"
    )
    # The aiosqlite cursor is the only way to step the pragma; SQLAlchemy's
    # own result object is closed before the work happens.
    raw = await connection.get_raw_connection()
    cursor = await raw.driver_connection.execute(statement)
    try:
        await cursor.fetchall()
    finally:
        await cursor.close()
    after = int(
        (await connection.exec_driver_sql("PRAGMA freelist_count")).scalar_one()
    )
    return max(0, before - after)


async def optimize_sqlite() -> None:
    """Refresh SQLite planner statistics opportunistically at startup."""
    if not _is_sqlite:
        return
    async with engine.begin() as connection:
        await connection.exec_driver_sql("PRAGMA optimize")
        auto_vacuum = (
            await connection.exec_driver_sql("PRAGMA auto_vacuum")
        ).scalar_one()
        if int(auto_vacuum) == AUTO_VACUUM_INCREMENTAL:
            # Reclaim at most 8 MiB (with the default 4 KiB page size) per
            # startup so maintenance never turns into an unbounded pause.
            freed = await incremental_vacuum(connection, 2048)
            if freed:
                logger.debug("sqlite_incremental_vacuum pages={}", freed)


async def dispose_engines() -> None:
    """Dispose both lanes without double-disposing a shared server engine."""
    if read_engine is not engine:
        await read_engine.dispose()
    await engine.dispose()
