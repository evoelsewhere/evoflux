"""``GET /api/wiki/tree``: sections, ordering and frontmatter metadata."""

from __future__ import annotations

import shutil
import sqlite3
from contextlib import closing

import pytest

from memory_helpers import INFO_KEYS, SECTIONS, db_path

DEFAULT_USER = "identity: {}\npreferences: []\nworking_style: []\nprojects: []\n"


def _info(path: str, **fields) -> dict:
    return {
        "path": path,
        "description": "",
        "updated": None,
        "tags": [],
        "confidence": None,
        "sources": [],
        **fields,
    }


def test_fresh_wiki_has_only_the_seeded_user_file(client, wiki) -> None:
    response = client.get("/api/wiki/tree")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {
        "system": [_info("USER.md")],
        "notes": [],
        "topics": [],
        "entities": [],
        "sources": [],
        "comparisons": [],
        "imports": [],
    }
    assert list(response.json()) == list(SECTIONS)
    assert (wiki / "USER.md").read_text(encoding="utf-8") == DEFAULT_USER
    for section in ("topics", "entities", "sources", "comparisons", "notes", "imports"):
        assert (wiki / section).is_dir()


def test_sections_order_and_filtering(client, wiki) -> None:
    for name in ("LINT.md", "LOG.md", "INDEX.md", "OTHER.md", "readme.txt"):
        (wiki / name).write_text("# t\n", encoding="utf-8")
    (wiki / "topics" / "b.md").write_text("b", encoding="utf-8")
    (wiki / "topics" / "a.md").write_text("a", encoding="utf-8")
    (wiki / "topics" / "c-last.md").write_text("Z", encoding="utf-8")
    (wiki / "topics" / "skip.txt").write_text("x", encoding="utf-8")
    (wiki / "topics" / "UPPER.MD").write_text("x", encoding="utf-8")
    (wiki / "topics" / "nested").mkdir()
    (wiki / "topics" / "nested" / "deep.md").write_text("x", encoding="utf-8")
    (wiki / "topics" / "dir.md").mkdir()
    (wiki / "entities" / "e.md").write_text("e", encoding="utf-8")
    (wiki / "sources" / "s.md").write_text("s", encoding="utf-8")
    (wiki / "comparisons" / "c.md").write_text("c", encoding="utf-8")
    (wiki / "imports" / "i.md").write_text("i", encoding="utf-8")
    (wiki / "notes" / "2026-01-02.md").write_text("n2", encoding="utf-8")
    (wiki / "notes" / "2026-01-01.md").write_text("n1", encoding="utf-8")
    (wiki / "stray").mkdir()
    (wiki / "stray" / "x.md").write_text("x", encoding="utf-8")

    tree = client.get("/api/wiki/tree").json()
    paths = {name: [row["path"] for row in tree[name]] for name in SECTIONS}
    upper = [p for p in paths["topics"] if p.lower().endswith("upper.md")]
    # On a case-insensitive suffix check this would list UPPER.MD; Python compares
    # the suffix exactly, so it is skipped everywhere.
    assert upper == []
    assert paths == {
        "system": ["USER.md", "INDEX.md", "LOG.md", "LINT.md"],
        "notes": ["notes/2026-01-01.md", "notes/2026-01-02.md"],
        # sorted by name; .MD, .txt and folders skipped (mixed case order differs by OS)
        "topics": ["topics/a.md", "topics/b.md", "topics/c-last.md"],
        "entities": ["entities/e.md"],
        "sources": ["sources/s.md"],
        "comparisons": ["comparisons/c.md"],
        "imports": ["imports/i.md"],
    }
    for name in SECTIONS:
        for row in tree[name]:
            assert set(row) == INFO_KEYS


FRONTMATTER_CASES = [
    # (id, file content, expected fields)
    ("none", "# Title\nbody\n", {}),
    (
        "full",
        "---\ndescription:  Hello  \ntags: [Alpha, ' beta ', '', 3]\nupdated: 2026-03-04\n"
        "confidence: High\nsources: [ a , '', b ]\n---\nbody\n",
        {
            "description": "Hello",
            "tags": ["alpha", "beta", "3"],
            "updated": "2026-03-04",
            "confidence": "high",
            "sources": ["a", "b"],
        },
    ),
    ("updated_string", "---\nupdated: ' later '\n---\nx", {"updated": "later"}),
    ("updated_blank", "---\nupdated: '  '\n---\nx", {}),
    ("updated_number", "---\nupdated: 5\n---\nx", {}),
    (
        "updated_datetime",
        "---\nupdated: 2026-03-04 05:06:07\n---\nx",
        {"updated": "2026-03-04T05:06:07"},
    ),
    ("confidence_invalid", "---\nconfidence: certain\n---\nx", {}),
    ("confidence_not_string", "---\nconfidence: 3\n---\nx", {}),
    ("tags_not_list", "---\ntags: solo\n---\nx", {}),
    ("sources_not_list", "---\nsources: solo\n---\nx", {}),
    ("description_number", "---\ndescription: 12\n---\nx", {"description": "12"}),
    ("description_null", "---\ndescription:\n---\nx", {"description": "None"}),
    ("not_a_mapping", "---\n- a\n- b\n---\nx", {}),
    ("bad_yaml", "---\n: : [\n---\nx", {}),
    ("empty_block", "---\n\n---\nx", {}),
    (
        "crlf",
        "---\r\ndescription: crlf\r\ntags: [t]\r\n---\r\nbody",
        {"description": "crlf", "tags": ["t"]},
    ),
    ("leading_blank_line", "\n---\ndescription: lead\n---\nx", {"description": "lead"}),
    ("unterminated", "---\ndescription: open\nbody", {}),
]


def test_frontmatter_metadata_in_the_tree(client, wiki) -> None:
    expected: dict[str, dict] = {}
    for case_id, content, fields in FRONTMATTER_CASES:
        name = f"topics/{case_id}.md"
        (wiki / name).write_bytes(content.encode("utf-8"))
        expected[name] = _info(name, **fields)
    rows = {row["path"]: row for row in client.get("/api/wiki/tree").json()["topics"]}
    mismatches = {
        name: (rows.get(name), want)
        for name, want in expected.items()
        if rows.get(name) != want
    }
    assert not mismatches


def test_frontmatter_in_system_notes_and_imports_files(client, wiki) -> None:
    (wiki / "USER.md").write_text(
        "---\ndescription: me\ntags: [P]\n---\nx", encoding="utf-8"
    )
    (wiki / "notes" / "n.md").write_text(
        "---\nconfidence: low\n---\nx", encoding="utf-8"
    )
    (wiki / "imports" / "i.md").write_text(
        "---\nsources: [s]\n---\nx", encoding="utf-8"
    )
    tree = client.get("/api/wiki/tree").json()
    assert tree["system"] == [_info("USER.md", description="me", tags=["p"])]
    assert tree["notes"] == [_info("notes/n.md", confidence="low")]
    assert tree["imports"] == [_info("imports/i.md", sources=["s"])]


def test_unreadable_file_is_listed_with_empty_metadata(client, wiki) -> None:
    (wiki / "topics" / "bad.md").write_bytes(
        b"---\ndescription: x\n---\n\xff\xfe broken"
    )
    (wiki / "topics" / "good.md").write_text(
        "---\ndescription: ok\n---\nx", encoding="utf-8"
    )
    (wiki / "LOG.md").write_bytes(b"\xff\xfe")
    response = client.get("/api/wiki/tree")
    assert response.status_code == 200
    tree = response.json()
    assert tree["topics"] == [
        _info("topics/bad.md"),
        _info("topics/good.md", description="ok"),
    ]
    # a root file that cannot be decoded is still listed, as if it were empty
    assert [row["path"] for row in tree["system"]] == ["USER.md", "LOG.md"]
    assert tree["system"][1] == _info("LOG.md")


def test_unprocessed_only_filters_notes_by_dream_log(client, wiki, tmp_path) -> None:
    for name in ("new.md", "done.md", "stale.md"):
        (wiki / "notes" / name).write_text(name, encoding="utf-8")
    (wiki / "topics" / "t.md").write_text("t", encoding="utf-8")
    with closing(sqlite3.connect(db_path(tmp_path), timeout=30)) as conn, conn:
        for name, stamp in (
            ("done.md", "2099-01-01 00:00:00.000000"),
            ("stale.md", "2000-01-01 00:00:00.000000"),
            ("gone.md", "2000-01-01 00:00:00.000000"),
        ):
            conn.execute(
                "INSERT INTO dream_notes_log (filename, processed_at) VALUES (?, ?)",
                (name, stamp),
            )
    everything = client.get("/api/wiki/tree").json()
    assert [r["path"] for r in everything["notes"]] == [
        "notes/done.md",
        "notes/new.md",
        "notes/stale.md",
    ]
    filtered = client.get("/api/wiki/tree", params={"unprocessed_only": "true"}).json()
    # processed after the file was modified: dropped; modified after processing: kept
    assert [r["path"] for r in filtered["notes"]] == ["notes/new.md", "notes/stale.md"]
    # only notes/ is filtered
    assert filtered["topics"] == everything["topics"]
    assert filtered["system"] == everything["system"]
    explicit_false = client.get(
        "/api/wiki/tree", params={"unprocessed_only": "false"}
    ).json()
    assert explicit_false == everything


def test_unprocessed_only_with_no_notes_directory(client, wiki) -> None:
    shutil.rmtree(wiki / "notes")
    for query in ({}, {"unprocessed_only": "true"}):
        tree = client.get("/api/wiki/tree", params=query).json()
        assert tree["notes"] == []


def test_unprocessed_only_rejects_a_non_boolean(client) -> None:
    response = client.get("/api/wiki/tree", params={"unprocessed_only": "maybe"})
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail[0]["loc"] == ["query", "unprocessed_only"]
    assert detail[0]["type"] == "bool_parsing"


@pytest.mark.parametrize("flag", ["1", "yes", "on", "TRUE"])
def test_unprocessed_only_accepts_pydantic_booleans(client, wiki, flag) -> None:
    (wiki / "notes" / "n.md").write_text("n", encoding="utf-8")
    response = client.get("/api/wiki/tree", params={"unprocessed_only": flag})
    assert response.status_code == 200
    assert [r["path"] for r in response.json()["notes"]] == ["notes/n.md"]


def test_missing_wiki_directory_is_recreated_empty(client, wiki) -> None:
    shutil.rmtree(wiki)
    response = client.get("/api/wiki/tree")
    assert response.status_code == 200
    body = response.json()
    assert all(body[name] == [] for name in SECTIONS)
    assert wiki.is_dir()


def test_unknown_methods_and_paths(client) -> None:
    assert client.post("/api/wiki/tree").status_code == 405
    assert client.get("/api/wiki/missing").status_code == 404
