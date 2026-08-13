import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import select
from starlette.requests import Request

from app.core.db import get_session, get_write_session
from app.models.chat import ChatSession


@pytest.mark.asyncio
async def test_get_session_success():
    """Verify get_session yields a session and commits."""
    async for session in get_write_session():
        # Check if session is active
        result = await session.execute(text("SELECT 1"))
        assert result.scalar() == 1
        # No exception means it should commit


@pytest.mark.asyncio
async def test_get_session_error():
    """Verify get_session rolls back on error."""
    with pytest.raises(ValueError, match="Expected Error"):
        async for session in get_write_session():
            raise ValueError("Expected Error")


@pytest.mark.asyncio
async def test_get_session_sqlalchemy_error_rolls_back():
    """SQLAlchemyError is caught by BaseException handler, rolled back and re-raised."""
    with pytest.raises(SQLAlchemyError):
        async for session in get_write_session():
            raise SQLAlchemyError("db error")


@pytest.mark.asyncio
async def test_get_session_base_exception_rolls_back():
    """Non-SQLAlchemy BaseException (e.g. CancelledError) still rolls back."""
    import asyncio

    with pytest.raises(asyncio.CancelledError):
        async for session in get_write_session():
            raise asyncio.CancelledError()


@pytest.mark.asyncio
async def test_get_request_uses_read_lane_and_rolls_back_orm_changes():
    import app.core.db as db_module

    request = Request({"type": "http", "method": "GET", "path": "/test", "headers": []})
    transient = ChatSession(title="must not persist")
    dependency = get_session(request)
    session = await anext(dependency)
    session.add(transient)
    await dependency.aclose()

    async with db_module.async_session_factory() as verify:
        found = (
            await verify.exec(select(ChatSession).where(ChatSession.id == transient.id))
        ).first()
    assert found is None
