from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Iterator
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings

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

_pool_kwargs: dict = (
    # Me SQLite with WAL: concurrent reads are safe; writes serialise at the DB level.
    # pool_size covers single-agent sessions; max_overflow handles burst from team members
    # (each member acquires a connection at startup + during turns).
    {"pool_size": 5, "max_overflow": 10}
    if _is_sqlite
    # Me size pool for concurrent async requests on Postgres/MySQL; defaults too small (5+10)
    else {"pool_size": 20, "max_overflow": 10}
)

engine = create_async_engine(
    _db_url,
    echo=False,
    pool_pre_ping=True,
    pool_recycle=3600,
    **_pool_kwargs,
)

# Me enable WAL mode for SQLite — 5-10x write throughput, concurrent reads during writes
if _is_sqlite:

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragmas(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        # WAL still serialises writers. Without this, a second application-DB
        # transaction can fail immediately instead of waiting for the lock.
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()


async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# Backs sqlite_write_guard() below. A single process-wide lock, not per
# workspace/project — busy_timeout alone isn't enough once a large application
# write legitimately holds the database longer than the timeout; another
# writer arriving mid-transaction still raises
# "database is locked" instead of waiting for the first to finish. This lock
# removes the race instead of racing the clock.
#
# Created lazily (not at module scope) and rebuilt if the running loop
# changes: an asyncio.Lock binds to whatever loop first awaits it, and a
# module-level instance would otherwise raise "bound to a different event
# loop" the moment it's reused under a new loop — every pytest-asyncio test
# gets its own, and a long-lived server could in principle recreate one too.
_sqlite_write_lock: asyncio.Lock | None = None
_sqlite_write_lock_loop: asyncio.AbstractEventLoop | None = None


def _get_sqlite_write_lock() -> asyncio.Lock:
    global _sqlite_write_lock, _sqlite_write_lock_loop
    loop = asyncio.get_running_loop()
    if _sqlite_write_lock is None or _sqlite_write_lock_loop is not loop:
        _sqlite_write_lock = asyncio.Lock()
        _sqlite_write_lock_loop = loop
    return _sqlite_write_lock


@asynccontextmanager
async def sqlite_write_guard() -> AsyncGenerator[None, None]:
    """Serialize the caller's DB writes against every other in-process
    SQLite writer.

    SQLite allows exactly one writer at a time. Wrap application-database
    spans that issue writes through the final ``commit()`` in this guard so
    they queue instead of colliding. Repository code indexes use independent
    managed SQLite targets and never enter this guard. No-op on Postgres/MySQL.
    """
    if not _is_sqlite:
        yield
        return
    async with _get_sqlite_write_lock():
        yield


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
    ``EvoFlux migrate`` step.  ``alembic.ini`` ships inside the ``app``
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


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise
