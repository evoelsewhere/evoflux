"""Per-repository lifecycle for the dependency-free incremental code index."""

from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import shutil
import sqlite3
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import astuple, dataclass
from pathlib import Path

from loguru import logger

from app.services.code_index.executor import run_index_work, submit_index_update
from app.services.code_index.file_matcher import SourceMetadata, walk_source_records
from app.services.code_index.languages import SEARCH_ONLY_LANGUAGES
from app.services.code_index.models import IndexStats
from app.services.code_index.parsers.registry import default_registry
from app.services.code_index.paths import RepositoryIndexPaths, paths_for_repository
from app.services.code_index.pipeline import (
    FileState,
    build_file_state,
    processing_identity,
)
from app.services.code_index.reconcile import plan_reconciliation
from app.services.code_index.settings import load_project_settings

_REQUIRED_SCHEMA: dict[str, frozenset[str]] = {
    "source_files": frozenset(
        {
            "file_path",
            "language",
            "fingerprint",
            "byte_size",
            "modified_ns",
            "changed_ns",
            "content",
            "processor",
            "graph_enabled",
        }
    ),
    "code_symbols": frozenset(
        {
            "id",
            "local_id",
            "file_path",
            "language",
            "kind",
            "name",
            "qualified_name",
            "line_start",
            "line_end",
            "signature",
            "docstring",
        }
    ),
    "source_chunks": frozenset(
        {
            "id",
            "file_path",
            "language",
            "line_start",
            "line_end",
            "content",
            "embedding",
            "symbol_id",
            "symbol_name",
        }
    ),
    "code_relations": frozenset(
        {
            "id",
            "src_id",
            "kind",
            "dst_id",
            "dst_name",
            "module_path",
            "local_name",
            "file_path",
            "line",
        }
    ),
    "index_errors": frozenset({"file_path", "error"}),
    "source_chunks_fts": frozenset({"content", "file_path", "language"}),
}

_RECOVERABLE_DATABASE_ERRORS: tuple[str, ...] = (
    "database disk image is malformed",
    "file is not a database",
    "no such column",
    "no such table",
    "not a database",
    "vtable constructor failed",
)

_REQUIRED_SCHEMA_OBJECTS: dict[str, str] = {
    "ix_code_symbols_name": "index",
    "ix_code_symbols_qualified": "index",
    "ix_code_symbols_file": "index",
    "ix_code_relations_src": "index",
    "ix_code_relations_dst": "index",
    "ix_code_relations_file": "index",
    "ix_source_chunks_file": "index",
    "source_chunks_fts_ai": "trigger",
    "source_chunks_fts_ad": "trigger",
    "source_chunks_fts_au": "trigger",
}


@dataclass(frozen=True, slots=True)
class IndexProgress:
    phase: str
    progress: float
    message: str


ProgressCallback = Callable[[IndexProgress], None]


class ManagedDatabase:
    """Small connection boundary used by indexing and concurrent readers."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._write_lock = threading.RLock()

    def _connect(self, *, readonly: bool = False) -> sqlite3.Connection:
        if readonly:
            connection = sqlite3.connect(
                f"{self.path.resolve().as_uri()}?mode=ro",
                uri=True,
                timeout=30,
            )
        else:
            connection = sqlite3.connect(self.path, timeout=30)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        if not readonly:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = NORMAL")
        return connection

    @contextmanager
    def readonly(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect(readonly=True)
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._write_lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
            finally:
                connection.close()

    def close(self) -> None:
        """Connections are operation scoped; kept for the registry protocol."""


class RepositoryIndex:
    """A regeneratable desired-state index isolated to one repository."""

    def __init__(
        self,
        *,
        root: Path,
        paths: RepositoryIndexPaths,
        database: ManagedDatabase,
    ) -> None:
        self.root = root
        self.paths = paths
        self.database = database
        self._update_lock = threading.RLock()
        self._dispatch_lock = threading.RLock()
        self._update_future: concurrent.futures.Future[IndexStats] | None = None
        self._update_future_full = False
        self._stats_lock = threading.RLock()
        self._stats_cache: (
            tuple[tuple[tuple[int, int] | None, ...], IndexStats] | None
        ) = None

    @classmethod
    async def create(cls, root: Path) -> RepositoryIndex:
        canonical = root.expanduser().resolve()
        if not canonical.is_dir():
            raise ValueError(
                f"Repository does not exist or is not a directory: {canonical}"
            )
        paths = paths_for_repository(canonical)
        paths.directory.mkdir(parents=True, exist_ok=True)
        database = ManagedDatabase(paths.target_db)
        try:
            await run_index_work(_ensure_schema, database)
        except sqlite3.DatabaseError as exc:
            if not _is_recoverable_database_error(exc):
                raise
            logger.warning("code_index_cache_rebuild root={} error={}", canonical, exc)
            await run_index_work(_rebuild_database, database)
        return cls(root=canonical, paths=paths, database=database)

    async def update(
        self,
        *,
        full: bool = False,
        progress: ProgressCallback | None = None,
    ) -> IndexStats:
        while True:
            with self._dispatch_lock:
                pending = self._update_future
                if pending is None or pending.done():
                    if progress:
                        progress(
                            IndexProgress(
                                "snapshot",
                                0.02,
                                "Scanning keyed source snapshot",
                            )
                        )
                    pending = submit_index_update(
                        self._update_locked,
                        (full, progress),
                        process_function=_update_repository_process,
                        process_args=(str(self.root), str(self.database.path), full),
                    )
                    self._update_future = pending
                    self._update_future_full = full
                covers_full_refresh = self._update_future_full
            result = await asyncio.shield(asyncio.wrap_future(pending))
            self._remember_stats(result)
            if not full or covers_full_refresh:
                return result

    def _update_locked(
        self,
        full: bool,
        progress: ProgressCallback | None,
    ) -> IndexStats:
        with self._update_lock:
            self._clear_stats_cache()
            try:
                stats = self._update_sync(full, progress)
            except sqlite3.DatabaseError as exc:
                if not _is_recoverable_database_error(exc):
                    raise
                logger.warning(
                    "code_index_cache_rebuild root={} error={}", self.root, exc
                )
                if progress:
                    progress(
                        IndexProgress(
                            "repair", 0.03, "Rebuilding invalid repository cache"
                        )
                    )
                _rebuild_database(self.database)
                stats = self._update_sync(True, progress)
            if progress:
                progress(IndexProgress("ready", 1.0, "Repository target synchronized"))
            return stats

    def _update_sync(
        self,
        full: bool,
        progress: ProgressCallback | None,
    ) -> IndexStats:
        registry = default_registry()
        project_settings = load_project_settings(self.root)
        override_extensions = {
            f".{item.ext}" for item in project_settings.language_overrides
        }

        def processor_for(path: str) -> tuple[str, str | None]:
            override = project_settings.language_for(path)
            identity = processing_identity(path, override)
            return f"{identity}:{project_settings.digest}", override

        with self.database.readonly() as connection:
            previous_rows = connection.execute(
                "SELECT file_path, fingerprint, byte_size, processor, "
                "modified_ns, changed_ns FROM source_files"
            ).fetchall()
            previous_errors = {
                str(row[0])
                for row in connection.execute(
                    "SELECT file_path FROM index_errors"
                ).fetchall()
            }
        known_sources = {
            str(path): SourceMetadata(
                fingerprint=str(fingerprint),
                byte_size=int(byte_size),
                processor=str(processor),
                modified_ns=int(modified_ns),
                changed_ns=int(changed_ns),
            )
            for path, fingerprint, byte_size, processor, modified_ns, changed_ns in previous_rows
        }
        records = {
            record.key: record
            for record in walk_source_records(
                self.root,
                extensions=registry.supported_extensions()
                | frozenset(SEARCH_ONLY_LANGUAGES)
                | frozenset(override_extensions),
                max_bytes=project_settings.max_file_size or 1_500_000,
                include=project_settings.includes,
                processor_for=processor_for,
                known_sources=known_sources,
                force_read=full,
            )
        }
        previous = {
            path: metadata.fingerprint for path, metadata in known_sources.items()
        }
        plan = plan_reconciliation(
            {key: record.fingerprint for key, record in records.items()},
            previous,
            force=full,
        )
        stale_errors = previous_errors - records.keys()
        if plan.is_noop and not stale_errors:
            return self.stats()

        states: dict[str, FileState] = {}
        errors: dict[str, str] = {}
        work = plan.reprocess
        for ordinal, key in enumerate(work, start=1):
            if progress:
                progress(
                    IndexProgress(
                        "transform",
                        0.05 + 0.75 * ordinal / max(1, len(work)),
                        f"Parsing {ordinal}/{len(work)} source components",
                    )
                )
            try:
                states[key] = build_file_state(records[key])
            except (OSError, UnicodeDecodeError, ValueError) as exc:
                errors[key] = str(exc)
            except Exception as exc:  # parser isolation: preserve last good target
                errors[key] = f"{type(exc).__name__}: {exc}"
                logger.warning("code_context_parse_failed path={} error={}", key, exc)

        if progress:
            progress(IndexProgress("commit", 0.85, "Reconciling target rows"))
        with self.database.transaction() as connection:
            if plan.is_noop:
                connection.executemany(
                    "DELETE FROM index_errors WHERE file_path = ?",
                    ((key,) for key in sorted(stale_errors)),
                )
            else:
                for key in plan.deletes:
                    _delete_component(connection, key)
                for key in work:
                    state = states.get(key)
                    if state is None:
                        continue
                    _delete_component(connection, key)
                    _insert_state(connection, state)
                connection.execute("DELETE FROM index_errors")
                connection.executemany(
                    "INSERT INTO index_errors(file_path, error) VALUES (?, ?)",
                    sorted(errors.items()),
                )
        return self.stats()

    async def ensure_ready(self, *, refresh: bool = True) -> IndexStats:
        # ``refresh=False`` is the latency-sensitive committed-index contract
        # used by UI autocomplete. A process restart creates a fresh
        # RepositoryIndex object, but an existing target database is already a
        # valid snapshot and must not trigger a full repository scan.
        if refresh or not self.paths.target_db.exists():
            return await self.update()
        return await run_index_work(self.stats)

    async def purge(self) -> None:
        """Wait for active work, then remove this regeneratable cache."""
        with self._dispatch_lock:
            pending = self._update_future
        if pending is not None:
            try:
                await asyncio.shield(asyncio.wrap_future(pending))
            except Exception:
                # A failed refresh must not prevent deleting its broken cache.
                pass
        await run_index_work(self._purge_locked)

    def _purge_locked(self) -> None:
        with self._update_lock:
            self._clear_stats_cache()
            self.database.close()
            shutil.rmtree(self.paths.directory, ignore_errors=True)

    def stats(self) -> IndexStats:
        signature_before = self._database_signature()
        with self._stats_lock:
            cached = self._stats_cache
            if cached is not None and cached[0] == signature_before:
                return cached[1]
        try:
            with self.database.readonly() as connection:
                files = _count(connection, "source_files")
                chunks = _count(connection, "source_chunks")
                symbols = _count(connection, "code_symbols")
                relations = _count(connection, "code_relations")
                language_rows = connection.execute(
                    "SELECT DISTINCT language FROM source_files ORDER BY language"
                ).fetchall()
                graph_language_rows = connection.execute(
                    "SELECT DISTINCT language FROM source_files "
                    "WHERE graph_enabled = 1 ORDER BY language"
                ).fetchall()
                error_rows = connection.execute(
                    "SELECT file_path, error FROM index_errors ORDER BY file_path"
                ).fetchall()
                fingerprint_rows = connection.execute(
                    "SELECT file_path, fingerprint FROM source_files ORDER BY file_path"
                ).fetchall()
        except sqlite3.DatabaseError as exc:
            return IndexStats(errors=(("<index>", f"{type(exc).__name__}: {exc}"),))
        digest = hashlib.sha256()
        for file_path, fingerprint in fingerprint_rows:
            digest.update(str(file_path).encode("utf-8", "replace"))
            digest.update(str(fingerprint).encode("ascii", "replace"))
        result = IndexStats(
            files=files,
            chunks=chunks,
            symbols=symbols,
            relations=relations,
            languages=tuple(str(row[0]) for row in language_rows),
            graph_languages=tuple(str(row[0]) for row in graph_language_rows),
            errors=tuple((str(row[0]), str(row[1])) for row in error_rows),
            version=digest.hexdigest()[:12] if fingerprint_rows else None,
        )
        signature_after = self._database_signature()
        if signature_before == signature_after:
            with self._stats_lock:
                self._stats_cache = (signature_after, result)
        return result

    def _database_signature(self) -> tuple[tuple[int, int] | None, ...]:
        def signature(path: Path) -> tuple[int, int] | None:
            try:
                stat = path.stat()
            except OSError:
                return None
            return stat.st_mtime_ns, stat.st_size

        return (
            signature(self.database.path),
            signature(Path(f"{self.database.path}-wal")),
        )

    def _remember_stats(self, value: IndexStats) -> None:
        with self._stats_lock:
            self._stats_cache = (self._database_signature(), value)

    def _clear_stats_cache(self) -> None:
        with self._stats_lock:
            self._stats_cache = None

    def rebuild_lexical_index(self) -> None:
        """Repair derived FTS state without rebuilding parsed source and graph rows."""
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO source_chunks_fts(source_chunks_fts) VALUES ('rebuild')"
            )

    def close(self) -> None:
        self.database.close()


def _update_repository_process(
    root: str,
    database_path: str,
    full: bool,
) -> IndexStats:
    """Reconstruct and update one index wholly inside the worker process."""

    canonical = Path(root).expanduser().resolve()
    target = Path(database_path).expanduser().resolve()
    paths = RepositoryIndexPaths(
        root=canonical,
        directory=target.parent,
        target_db=target,
    )
    database = ManagedDatabase(target)
    _ensure_schema(database)
    index = RepositoryIndex(root=canonical, paths=paths, database=database)
    return index._update_locked(full, None)


def _ensure_schema(database: ManagedDatabase) -> None:
    with database.transaction() as connection:
        schema_is_current = _schema_is_current(connection)
        if schema_is_current:
            return
        _execute_sql_script(
            connection,
            """
            DROP TRIGGER IF EXISTS source_chunks_fts_ai;
            DROP TRIGGER IF EXISTS source_chunks_fts_ad;
            DROP TRIGGER IF EXISTS source_chunks_fts_au;
            DROP TABLE IF EXISTS source_chunks_fts;
            DROP TABLE IF EXISTS code_relations;
            DROP TABLE IF EXISTS source_chunks;
            DROP TABLE IF EXISTS code_symbols;
            DROP TABLE IF EXISTS source_files;
            DROP TABLE IF EXISTS index_errors;
            """,
        )
        _execute_sql_script(
            connection,
            """
            CREATE TABLE IF NOT EXISTS source_files (
              file_path TEXT PRIMARY KEY,
              language TEXT NOT NULL,
              fingerprint TEXT NOT NULL,
              byte_size INTEGER NOT NULL,
              modified_ns INTEGER NOT NULL,
              changed_ns INTEGER NOT NULL,
              content TEXT NOT NULL,
              processor TEXT NOT NULL,
              graph_enabled INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS code_symbols (
              id TEXT PRIMARY KEY,
              local_id TEXT NOT NULL,
              file_path TEXT NOT NULL REFERENCES source_files(file_path) ON DELETE CASCADE,
              language TEXT NOT NULL,
              kind TEXT NOT NULL,
              name TEXT NOT NULL,
              qualified_name TEXT NOT NULL,
              line_start INTEGER NOT NULL,
              line_end INTEGER NOT NULL,
              signature TEXT,
              docstring TEXT
            );
            CREATE TABLE IF NOT EXISTS source_chunks (
              id TEXT PRIMARY KEY,
              file_path TEXT NOT NULL REFERENCES source_files(file_path) ON DELETE CASCADE,
              language TEXT NOT NULL,
              line_start INTEGER NOT NULL,
              line_end INTEGER NOT NULL,
              content TEXT NOT NULL,
              embedding BLOB NOT NULL,
              symbol_id TEXT,
              symbol_name TEXT
            );
            CREATE TABLE IF NOT EXISTS code_relations (
              id TEXT PRIMARY KEY,
              src_id TEXT NOT NULL,
              kind TEXT NOT NULL,
              dst_id TEXT,
              dst_name TEXT,
              module_path TEXT,
              local_name TEXT,
              file_path TEXT NOT NULL REFERENCES source_files(file_path) ON DELETE CASCADE,
              line INTEGER
            );
            CREATE TABLE IF NOT EXISTS index_errors (
              file_path TEXT PRIMARY KEY,
              error TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_code_symbols_name ON code_symbols(name);
            CREATE INDEX IF NOT EXISTS ix_code_symbols_qualified ON code_symbols(qualified_name);
            CREATE INDEX IF NOT EXISTS ix_code_symbols_file ON code_symbols(file_path);
            CREATE INDEX IF NOT EXISTS ix_code_relations_src ON code_relations(src_id, kind);
            CREATE INDEX IF NOT EXISTS ix_code_relations_dst ON code_relations(dst_id, dst_name, kind);
            CREATE INDEX IF NOT EXISTS ix_code_relations_file ON code_relations(file_path);
            CREATE INDEX IF NOT EXISTS ix_source_chunks_file ON source_chunks(file_path);
            CREATE VIRTUAL TABLE IF NOT EXISTS source_chunks_fts USING fts5(
              content, file_path, language,
              content='source_chunks', content_rowid='rowid', tokenize='unicode61'
            );
            CREATE TRIGGER IF NOT EXISTS source_chunks_fts_ai AFTER INSERT ON source_chunks BEGIN
              INSERT INTO source_chunks_fts(rowid, content, file_path, language)
              VALUES (new.rowid, new.content, new.file_path, new.language);
            END;
            CREATE TRIGGER IF NOT EXISTS source_chunks_fts_ad AFTER DELETE ON source_chunks BEGIN
              INSERT INTO source_chunks_fts(source_chunks_fts, rowid, content, file_path, language)
              VALUES ('delete', old.rowid, old.content, old.file_path, old.language);
            END;
            CREATE TRIGGER IF NOT EXISTS source_chunks_fts_au AFTER UPDATE ON source_chunks BEGIN
              INSERT INTO source_chunks_fts(source_chunks_fts, rowid, content, file_path, language)
              VALUES ('delete', old.rowid, old.content, old.file_path, old.language);
              INSERT INTO source_chunks_fts(rowid, content, file_path, language)
              VALUES (new.rowid, new.content, new.file_path, new.language);
            END;
            """,
        )
        try:
            connection.execute(
                "INSERT INTO source_chunks_fts(source_chunks_fts, rank) "
                "VALUES ('integrity-check', 1)"
            )
        except sqlite3.DatabaseError:
            # FTS is derived state. Repair it without discarding parsed rows.
            connection.execute(
                "INSERT INTO source_chunks_fts(source_chunks_fts) VALUES ('rebuild')"
            )


def _execute_sql_script(connection: sqlite3.Connection, script: str) -> None:
    """Execute complete SQL statements without ``executescript`` auto-commits."""
    statement = ""
    for line in script.splitlines(keepends=True):
        statement += line
        if sqlite3.complete_statement(statement):
            connection.execute(statement)
            statement = ""
    if statement.strip():
        raise sqlite3.OperationalError("Incomplete code-index schema statement")


def _is_recoverable_database_error(error: sqlite3.DatabaseError) -> bool:
    message = str(error).casefold()
    return any(value in message for value in _RECOVERABLE_DATABASE_ERRORS)


def _rebuild_database(database: ManagedDatabase) -> None:
    """Replace only regeneratable cache state after a verified SQLite failure."""
    for suffix in ("-wal", "-shm"):
        Path(f"{database.path}{suffix}").unlink(missing_ok=True)
    backup = database.path.with_suffix(f"{database.path.suffix}.corrupt")
    if database.path.exists():
        database.path.replace(backup)
    _ensure_schema(database)


def _schema_is_current(connection: sqlite3.Connection) -> bool:
    """Accept only the canonical schema shape; stale targets are regeneratable."""
    for table, required_columns in _REQUIRED_SCHEMA.items():
        columns = {
            str(row[1])
            for row in connection.execute(f'PRAGMA table_info("{table}")').fetchall()
        }
        if not required_columns.issubset(columns):
            return False
    object_rows = connection.execute(
        "SELECT name, type FROM sqlite_master WHERE name IN ("
        + ",".join("?" for _ in _REQUIRED_SCHEMA_OBJECTS)
        + ")",
        tuple(_REQUIRED_SCHEMA_OBJECTS),
    ).fetchall()
    objects = {str(name): str(kind) for name, kind in object_rows}
    if any(
        objects.get(name) != kind for name, kind in _REQUIRED_SCHEMA_OBJECTS.items()
    ):
        return False
    return True


def _delete_component(connection: sqlite3.Connection, file_path: str) -> None:
    connection.execute("DELETE FROM source_files WHERE file_path = ?", (file_path,))


def _insert_state(connection: sqlite3.Connection, state: FileState) -> None:
    connection.execute(
        "INSERT INTO source_files(file_path, language, fingerprint, byte_size, "
        "modified_ns, changed_ns, content, processor, graph_enabled) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        astuple(state.source),
    )
    connection.executemany(
        "INSERT INTO code_symbols(id, local_id, file_path, language, kind, name, "
        "qualified_name, line_start, line_end, signature, docstring) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (astuple(row) for row in state.symbols),
    )
    connection.executemany(
        "INSERT INTO source_chunks(id, file_path, language, line_start, line_end, "
        "content, embedding, symbol_id, symbol_name) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (astuple(row) for row in state.chunks),
    )
    connection.executemany(
        "INSERT INTO code_relations(id, src_id, kind, dst_id, dst_name, module_path, "
        "local_name, file_path, line) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (astuple(row) for row in state.relations),
    )


def _count(connection: sqlite3.Connection, table: str) -> int:
    return int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])


class RepositoryIndexRegistry:
    def __init__(self) -> None:
        self._indexes: dict[Path, RepositoryIndex] = {}
        self._creating: dict[Path, concurrent.futures.Future[RepositoryIndex]] = {}
        self._lock = threading.RLock()

    async def get(self, root: Path) -> RepositoryIndex:
        canonical = root.expanduser().resolve()
        owner = False
        with self._lock:
            cached = self._indexes.get(canonical)
            if cached is not None:
                return cached
            pending = self._creating.get(canonical)
            if pending is None:
                pending = concurrent.futures.Future()
                self._creating[canonical] = pending
                owner = True
        if not owner:
            return await asyncio.shield(asyncio.wrap_future(pending))
        try:
            created = await RepositoryIndex.create(canonical)
        except BaseException as exc:
            with self._lock:
                self._creating.pop(canonical, None)
                pending.set_exception(exc)
            raise
        with self._lock:
            self._indexes[canonical] = created
            self._creating.pop(canonical, None)
            pending.set_result(created)
        return created

    def close_all(self) -> None:
        with self._lock:
            indexes = list(self._indexes.values())
            self._indexes.clear()
        for index in indexes:
            try:
                index.close()
            except Exception as exc:  # pragma: no cover - shutdown best effort
                logger.warning(
                    "code_index_close_failed root={} error={}", index.root, exc
                )

    async def purge(self, root: Path) -> None:
        """Evict one repository index and delete its on-disk graph/cache."""
        canonical = root.expanduser().resolve()
        with self._lock:
            pending = self._creating.get(canonical)
        if pending is not None:
            try:
                await asyncio.shield(asyncio.wrap_future(pending))
            except Exception:
                pass
        with self._lock:
            index = self._indexes.pop(canonical, None)
        if index is not None:
            await index.purge()
            return
        paths = paths_for_repository(canonical)
        await asyncio.to_thread(shutil.rmtree, paths.directory, ignore_errors=True)


repository_indexes = RepositoryIndexRegistry()


__all__ = [
    "IndexProgress",
    "ManagedDatabase",
    "ProgressCallback",
    "RepositoryIndex",
    "RepositoryIndexRegistry",
    "repository_indexes",
]
