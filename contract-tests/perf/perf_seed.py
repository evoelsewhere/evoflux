"""Build the database every perf test starts from.

The schema comes from a real backend start (so Alembic stays the only DDL
author); this module only inserts rows. Ids are fixed so scenarios can address
them. Rows are written through ``sqlite3`` with columns taken from the schema,
which keeps the harness independent of ``app`` imports.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

BIG_SESSION_ID = "00000000-0000-7000-8000-00000000b16b"
MCP_SESSION_ID = "00000000-0000-7000-8000-0000000000c1"
MCP_TOOL_CALL_ID = "call_perf_mcp_app"
MCP_SERVER_NAME = "perf-slow"
BIG_SESSION_MESSAGES = 5000
SMALL_SESSIONS = 40

_BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _hex(value: str) -> str:
    return value.replace("-", "")


def _ts(offset_ms: int) -> str:
    stamp = _BASE + timedelta(milliseconds=offset_ms)
    return stamp.strftime("%Y-%m-%d %H:%M:%S.%f")


def _message_id(session: int, index: int) -> str:
    return f"{session:08x}{index:024x}"


def seed_database(db_path: Path) -> None:
    connection = sqlite3.connect(db_path)
    try:
        with connection:
            _insert_sessions(connection)
            _insert_big_history(connection)
            _insert_mcp_tool_message(connection)
    finally:
        connection.close()


def _insert_sessions(connection: sqlite3.Connection) -> None:
    rows = [(_hex(BIG_SESSION_ID), "Large history", _ts(0), _ts(10_000_000))]
    rows.append((_hex(MCP_SESSION_ID), "MCP app session", _ts(1), _ts(2)))
    for index in range(SMALL_SESSIONS):
        rows.append((f"{index + 1:032x}", f"Session {index}", _ts(index), _ts(index)))
    connection.executemany(
        "INSERT INTO chat_sessions (id, title, created_at, updated_at) VALUES (?,?,?,?)",
        rows,
    )


def _insert_big_history(connection: sqlite3.Connection) -> None:
    body = "The quick brown fox jumps over the lazy dog. " * 90  # ~4 KB
    tool_result = json.dumps({"output": "line of tool output\n" * 150})
    rows = []
    for index in range(BIG_SESSION_MESSAGES):
        role = ("user", "assistant", "tool")[index % 3]
        content = tool_result if role == "tool" else f"{index}: {body}"
        rows.append(
            (
                _message_id(1, index),
                _hex(BIG_SESSION_ID),
                role,
                content,
                f"call_{index}" if role == "tool" else None,
                _ts(index * 1000),
            )
        )
    connection.executemany(
        "INSERT INTO session_messages (id, session_id, role, content, tool_call_id, created_at)"
        " VALUES (?,?,?,?,?,?)",
        rows,
    )


def _insert_mcp_tool_message(connection: sqlite3.Connection) -> None:
    extra = json.dumps({"mcp_app": {"server": MCP_SERVER_NAME}})
    connection.execute(
        "INSERT INTO session_messages"
        " (id, session_id, role, content, tool_call_id, extra, created_at)"
        " VALUES (?,?,?,?,?,?,?)",
        (
            _message_id(2, 0),
            _hex(MCP_SESSION_ID),
            "tool",
            "{}",
            MCP_TOOL_CALL_ID,
            extra,
            _ts(3),
        ),
    )
