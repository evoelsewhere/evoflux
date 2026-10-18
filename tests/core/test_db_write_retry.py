from __future__ import annotations

import pytest
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError

from app.core import db as db_module


@pytest.mark.asyncio
async def test_retry_on_db_timeout_retries_then_returns(monkeypatch):
    attempts = 0

    async def no_sleep(_delay: float) -> None:
        return None

    async def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise SQLAlchemyTimeoutError("writer lane busy")
        return "saved"

    monkeypatch.setattr(db_module.asyncio, "sleep", no_sleep)

    result = await db_module.retry_on_db_timeout(
        operation,
        operation_name="test.write",
        attempts=3,
    )

    assert result == "saved"
    assert attempts == 2


@pytest.mark.asyncio
async def test_retry_on_db_timeout_stops_after_attempt_limit(monkeypatch):
    attempts = 0

    async def no_sleep(_delay: float) -> None:
        return None

    async def operation() -> None:
        nonlocal attempts
        attempts += 1
        raise SQLAlchemyTimeoutError("writer lane busy")

    monkeypatch.setattr(db_module.asyncio, "sleep", no_sleep)

    with pytest.raises(SQLAlchemyTimeoutError, match="writer lane busy"):
        await db_module.retry_on_db_timeout(
            operation,
            operation_name="test.write",
            attempts=2,
        )

    assert attempts == 2
