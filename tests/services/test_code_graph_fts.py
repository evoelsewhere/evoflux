"""The canonical FTS index covers source metadata and filters before limiting."""

from __future__ import annotations

from app.services.code_graph import fts_store


def _table_columns(database: str) -> tuple[str, ...]:
    import sqlite3

    with sqlite3.connect(database) as conn:
        return tuple(row[1] for row in conn.execute("PRAGMA table_info(code_node_fts)"))


def test_fts_searches_path_signature_and_docstring(tmp_path):
    database = str(tmp_path / "graph.sqlite")
    workspace = "00000000-0000-0000-0000-000000000001"
    rows: list[fts_store.FtsRow] = [
        (
            "00000000-0000-0000-0000-000000000010",
            "restore",
            "SessionService.restore",
            "app/services/session_restore.py",
            "restore(session_id: str) -> Session",
            "Reconnect a session and restore streamed messages.",
            "method",
            "python",
        ),
        (
            "00000000-0000-0000-0000-000000000011",
            "restore",
            "Fixture.restore",
            "tests/fixtures.py",
            "restore()",
            "test fixture",
            "function",
            "python",
        ),
    ]
    fts_store.rebuild_workspace_fts(database, workspace, rows)

    assert fts_store.search_fts(database, workspace, "session_restore") == [rows[0][0]]
    assert fts_store.search_fts(database, workspace, "streamed messages") == [
        rows[0][0]
    ]
    assert fts_store.search_fts(
        database, workspace, "restore", limit=1, kind="function"
    ) == [rows[1][0]]


def test_fts_expands_compound_identifiers_and_supports_broad_candidates(tmp_path):
    database = str(tmp_path / "graph.sqlite")
    workspace = "workspace"
    rows: list[fts_store.FtsRow] = [
        (
            "camel",
            "restoreRemoteSession",
            "SessionService.restoreRemoteSession",
            "src/sessionService.ts",
            "restoreRemoteSession(id: string)",
            "",
            "method",
            "typescript",
        ),
        (
            "noise",
            "render_panel",
            "Panel.render_panel",
            "src/render_panel.py",
            "render_panel()",
            "",
            "function",
            "python",
        ),
    ]
    fts_store.rebuild_workspace_fts(database, workspace, rows)

    assert fts_store.search_fts(database, workspace, "remote session") == ["camel"]
    assert fts_store.search_fts(
        database,
        workspace,
        "remote rendering",
        match_all=False,
    ) == ["camel"]
    assert fts_store.search_fts(database, workspace, "render panel") == ["noise"]


def test_fts_replaces_outdated_schema_in_place(tmp_path):
    import sqlite3

    database = str(tmp_path / "graph.sqlite")
    with sqlite3.connect(database) as conn:
        conn.execute(
            "CREATE VIRTUAL TABLE code_node_fts USING fts5("
            "node_id UNINDEXED, workspace_id UNINDEXED, name, qualified_name)"
        )
        conn.execute(
            "INSERT INTO code_node_fts VALUES (?, ?, ?, ?)",
            ("old", "workspace", "stale", "stale"),
        )
        conn.commit()

    fts_store.ensure_fts_table(database)

    assert _table_columns(database) == (
        "node_id",
        "workspace_id",
        "name",
        "qualified_name",
        "identifiers",
        "file_path",
        "signature",
        "docstring",
        "kind",
        "language",
    )
    assert fts_store.search_fts(database, "workspace", "stale") == []


def test_fts_indexes_unicode_identifiers(tmp_path):
    database = str(tmp_path / "graph.sqlite")
    rows: list[fts_store.FtsRow] = [
        (
            "unicode",
            "tínhTổng",
            "BáoCáo.tínhTổng",
            "src/báo_cáo.py",
            "def tínhTổng(values)",
            "",
            "method",
            "python",
        )
    ]
    fts_store.rebuild_workspace_fts(database, "workspace", rows)

    assert fts_store.search_fts(database, "workspace", "tính tổng") == ["unicode"]
