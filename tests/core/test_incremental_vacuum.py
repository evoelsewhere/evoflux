"""Regression test for SQLite free-page reclamation.

``PRAGMA incremental_vacuum`` frees one page per step of its statement and
declares no result columns, so SQLAlchemy closes the result after the first
step. Startup maintenance asked for 2048 pages and silently got one, which is
how a database accumulates hundreds of MiB of free pages that never come back.
"""

from __future__ import annotations

import pathlib

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.db import incremental_vacuum


async def _seed(connection) -> None:
    await connection.exec_driver_sql("PRAGMA auto_vacuum=INCREMENTAL")
    await connection.exec_driver_sql("PRAGMA journal_mode=WAL")
    await connection.exec_driver_sql(
        "CREATE TABLE t (id INTEGER PRIMARY KEY, blob TEXT)"
    )
    await connection.exec_driver_sql(
        "INSERT INTO t (blob) VALUES (hex(randomblob(400)))"
    )
    for _ in range(12):
        await connection.exec_driver_sql(
            "INSERT INTO t (blob) SELECT hex(randomblob(400)) FROM t"
        )
    await connection.exec_driver_sql("DELETE FROM t WHERE id % 4 != 0")


async def _free_pages(connection) -> int:
    return int(
        (await connection.exec_driver_sql("PRAGMA freelist_count")).scalar_one()
    )


@pytest.mark.asyncio
async def test_reclaims_every_free_page(tmp_path: pathlib.Path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'bloat.db'}")
    try:
        async with engine.connect() as connection:
            autocommit = await connection.execution_options(
                isolation_level="AUTOCOMMIT"
            )
            await _seed(autocommit)
            before = await _free_pages(autocommit)
            assert before > 100, "fixture did not produce a meaningful free list"

            freed = await incremental_vacuum(autocommit)

            assert freed == before
            assert await _free_pages(autocommit) == 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_page_budget_is_respected(tmp_path: pathlib.Path):
    """Startup maintenance bounds its work, and the bound has to be real."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'bounded.db'}")
    try:
        async with engine.connect() as connection:
            autocommit = await connection.execution_options(
                isolation_level="AUTOCOMMIT"
            )
            await _seed(autocommit)
            before = await _free_pages(autocommit)

            freed = await incremental_vacuum(autocommit, 64)

            # The old behaviour freed exactly one page whatever was asked for.
            assert freed == 64
            assert await _free_pages(autocommit) == before - 64
    finally:
        await engine.dispose()
