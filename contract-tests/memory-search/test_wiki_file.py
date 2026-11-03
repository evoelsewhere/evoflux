"""``GET/PUT/DELETE /api/wiki/file``: path rules, bytes on disk and error bodies."""

from __future__ import annotations

import os
import sys

import pytest

from memory_helpers import SECTIONS  # noqa: F401  (kept for parity with the tree tests)

EMPTY = {
    "description": "",
    "updated": None,
    "tags": [],
    "confidence": None,
    "sources": [],
}

#: (path as sent, 400 detail). The detail is the first rule the path breaks.
BAD_PATHS = [
    ("", "Wiki path must not be empty."),
    ("/abs.md", "Wiki path must be relative: /abs.md"),
    ("~/x.md", "Wiki path must be relative: ~/x.md"),
    ("~x.md", "Wiki path must be relative: ~x.md"),
    ("/x.txt", "Wiki path must be relative: /x.txt"),
    ("notes.txt", "Wiki files must be Markdown (.md): notes.txt"),
    ("topics/x.MD", "Wiki files must be Markdown (.md): topics/x.MD"),
    ("topics/x.md ", "Wiki files must be Markdown (.md): topics/x.md "),
    ("topics/.md", "Wiki files must be Markdown (.md): topics/.md"),
    ("../x.txt", "Wiki files must be Markdown (.md): ../x.txt"),
    ("../x.md", "Wiki path may not contain '..' or '.': ../x.md"),
    ("topics/../USER.md", "Wiki path may not contain '..' or '.': topics/../USER.md"),
    ("topics/./x.md", "Wiki path may not contain '..' or '.': topics/./x.md"),
    ("./USER.md", "Wiki path may not contain '..' or '.': ./USER.md"),
    (
        "FOO.md",
        "Only INDEX.md, LINT.md, LOG.md, USER.md are valid at wiki root level: FOO.md",
    ),
    (
        "user.md",
        "Only INDEX.md, LINT.md, LOG.md, USER.md are valid at wiki root level: user.md",
    ),
    (
        "bad/x.md",
        "Wiki subdir must be one of [comparisons, entities, imports, notes, sources, topics]:"
        " got 'bad'",
    ),
    (
        "TOPICS/x.md",
        "Wiki subdir must be one of [comparisons, entities, imports, notes, sources, topics]:"
        " got 'TOPICS'",
    ),
    ("topics/a/b.md", "Wiki path too deep (max 2 components): topics/a/b.md"),
    (
        "USER.md/x.md",
        "Wiki subdir must be one of [comparisons, entities, imports, notes, sources, topics]: got 'USER.md'",
    ),
]


def _put(client, path: str, content: str = "x"):
    return client.put("/api/wiki/file", json={"path": path, "content": content})


def test_bad_paths_are_400_with_the_first_broken_rule_on_every_verb(
    client, wiki
) -> None:
    mismatches = []
    for path, detail in BAD_PATHS:
        for name, response in (
            ("GET", client.get("/api/wiki/file", params={"path": path})),
            ("PUT", _put(client, path)),
            ("DELETE", client.delete("/api/wiki/file", params={"path": path})),
        ):
            got = (response.status_code, response.json())
            if got != (400, {"detail": detail}):
                mismatches.append((name, path, got))
    assert not mismatches
    # a rejected write leaves no file behind, not even outside the wiki
    assert not (wiki.parent / "x.md").exists()
    assert not (wiki / "x.txt").exists()


def test_get_returns_raw_content_and_parsed_metadata(client, wiki) -> None:
    text = "---\ndescription: Hi\ntags: [A]\nupdated: 2026-01-02\nconfidence: LOW\nsources: [s]\n---\nBody ü\n"
    (wiki / "topics" / "a.md").write_bytes(text.encode("utf-8"))
    response = client.get("/api/wiki/file", params={"path": "topics/a.md"})
    assert response.status_code == 200
    assert response.json() == {
        "path": "topics/a.md",
        "content": text,
        "description": "Hi",
        "updated": "2026-01-02",
        "tags": ["a"],
        "confidence": "low",
        "sources": ["s"],
    }
    assert list(response.json()) == [
        "path",
        "content",
        "description",
        "updated",
        "tags",
        "confidence",
        "sources",
    ]


def test_get_system_files_and_the_seeded_user_file(client) -> None:
    response = client.get("/api/wiki/file", params={"path": "USER.md"})
    assert response.status_code == 200
    assert response.json() == {
        "path": "USER.md",
        "content": "identity: {}\npreferences: []\nworking_style: []\nprojects: []\n",
        **EMPTY,
    }
    for name in ("INDEX.md", "LOG.md", "LINT.md"):
        missing = client.get("/api/wiki/file", params={"path": name})
        assert missing.status_code == 404
        assert missing.json() == {"detail": f"Wiki file not found: {name}"}


def test_get_missing_and_directory_are_404(client, wiki) -> None:
    (wiki / "topics" / "dir.md").mkdir()
    for path in ("topics/none.md", "topics/dir.md", "notes/2026-01-01.md"):
        response = client.get("/api/wiki/file", params={"path": path})
        assert response.status_code == 404
        assert response.json() == {"detail": f"Wiki file not found: {path}"}


def test_get_echoes_the_path_as_sent_and_accepts_an_empty_segment(client, wiki) -> None:
    (wiki / "topics" / "a.md").write_text("a", encoding="utf-8")
    response = client.get("/api/wiki/file", params={"path": "topics//a.md"})
    assert response.status_code == 200
    assert response.json()["path"] == "topics//a.md"
    assert response.json()["content"] == "a"


def test_get_translates_crlf_to_lf_but_put_keeps_bytes(client, wiki) -> None:
    (wiki / "topics" / "crlf.md").write_bytes(b"a\r\nb\r\n")
    got = client.get("/api/wiki/file", params={"path": "topics/crlf.md"}).json()
    assert got["content"] == "a\nb\n"
    put = _put(client, "topics/crlf2.md", "a\r\nb\r\n")
    assert put.status_code == 200
    assert put.json()["content"] == "a\r\nb\r\n"
    assert (wiki / "topics" / "crlf2.md").read_bytes() == b"a\r\nb\r\n"


def test_get_non_utf8_file_is_a_server_error(client, wiki) -> None:
    (wiki / "topics" / "bin.md").write_bytes(b"\xff\xfe\x00")
    response = client.get("/api/wiki/file", params={"path": "topics/bin.md"})
    assert response.status_code == 500
    assert response.text == "Internal Server Error"


def test_get_requires_the_path_query(client) -> None:
    response = client.get("/api/wiki/file")
    assert response.status_code == 422
    assert response.json() == {
        "detail": [
            {
                "type": "missing",
                "loc": ["query", "path"],
                "msg": "Field required",
                "input": None,
            }
        ]
    }


def test_put_creates_and_overwrites_with_parsed_metadata(client, wiki) -> None:
    content = "---\ndescription: First\ntags: [One, two]\n---\nbody\n"
    created = _put(client, "topics/new.md", content)
    assert created.status_code == 200
    assert created.json() == {
        "path": "topics/new.md",
        "content": content,
        "description": "First",
        "updated": None,
        "tags": ["one", "two"],
        "confidence": None,
        "sources": [],
    }
    assert (wiki / "topics" / "new.md").read_bytes() == content.encode("utf-8")
    replaced = _put(client, "topics/new.md", "plain")
    assert replaced.status_code == 200
    assert replaced.json() == {"path": "topics/new.md", "content": "plain", **EMPTY}
    assert (wiki / "topics" / "new.md").read_bytes() == b"plain"
    again = client.get("/api/wiki/file", params={"path": "topics/new.md"})
    assert again.json() == replaced.json()


def test_put_writes_each_section_root_files_and_unicode_exactly(client, wiki) -> None:
    for path in (
        "USER.md",
        "INDEX.md",
        "LOG.md",
        "LINT.md",
        "topics/t.md",
        "entities/e.md",
        "sources/s.md",
        "comparisons/c.md",
        "notes/n.md",
        "imports/i.md",
        "topics/ünï-文.md",
    ):
        payload = f"# {path} — ünï 文字 \U0001f600\n\n\ttab\n"
        response = _put(client, path, payload)
        assert response.status_code == 200, path
        assert (wiki / path).read_bytes() == payload.encode("utf-8"), path
    tree = client.get("/api/wiki/tree").json()
    assert [r["path"] for r in tree["system"]] == [
        "USER.md",
        "INDEX.md",
        "LOG.md",
        "LINT.md",
    ]


def test_put_empty_content_and_missing_directory(client, wiki) -> None:
    import shutil

    shutil.rmtree(wiki / "entities")
    response = _put(client, "entities/empty.md", "")
    assert response.status_code == 200
    assert response.json() == {"path": "entities/empty.md", "content": "", **EMPTY}
    assert (wiki / "entities" / "empty.md").read_bytes() == b""


def test_put_leaves_a_lock_file_and_no_temporary_files(client, wiki) -> None:
    _put(client, "topics/a.md", "a")
    _put(client, "topics/a.md", "b")
    assert (wiki / ".memory-write.lock").is_file()
    assert sorted(p.name for p in (wiki / "topics").iterdir()) == ["a.md"]
    # start-up also leaves a `.scoped-memory-*` marker (and briefly its temp file)
    names = sorted(p.name for p in wiki.iterdir() if ".scoped-memory" not in p.name)
    assert names == [
        ".memory-write.lock",
        "USER.md",
        "comparisons",
        "entities",
        "imports",
        "notes",
        "sources",
        "topics",
    ], names
    # the lock file is not a wiki page
    tree = client.get("/api/wiki/tree").json()
    assert [r["path"] for r in tree["system"]] == ["USER.md"]


def test_put_body_validation_is_422_and_runs_before_the_path_check(
    client, wiki
) -> None:
    cases = [
        ({}, [("missing", ["body", "path"]), ("missing", ["body", "content"])]),
        ({"path": "topics/x.md"}, [("missing", ["body", "content"])]),
        ({"content": "x"}, [("missing", ["body", "path"])]),
        ({"path": 1, "content": "x"}, [("string_type", ["body", "path"])]),
        (
            {"path": "topics/x.md", "content": None},
            [("string_type", ["body", "content"])],
        ),
        ({"path": "../bad", "content": 5}, [("string_type", ["body", "content"])]),
    ]
    for body, expected in cases:
        response = client.put("/api/wiki/file", json=body)
        assert response.status_code == 422, body
        got = [(e["type"], e["loc"]) for e in response.json()["detail"]]
        assert got == expected, body
    invalid_json = client.put(
        "/api/wiki/file", content=b"{nope", headers={"Content-Type": "application/json"}
    )
    assert invalid_json.status_code == 422
    assert invalid_json.json()["detail"][0]["type"] == "json_invalid"
    assert not (wiki / "topics" / "x.md").exists()


def test_put_ignores_unknown_body_fields(client, wiki) -> None:
    response = client.put(
        "/api/wiki/file",
        json={"path": "topics/x.md", "content": "x", "extra": [1], "tags": ["t"]},
    )
    assert response.status_code == 200
    assert response.json() == {"path": "topics/x.md", "content": "x", **EMPTY}


def test_delete_removes_the_file_and_echoes_the_path(client, wiki) -> None:
    (wiki / "topics" / "gone.md").write_text("x", encoding="utf-8")
    (wiki / "notes" / "n.md").write_text("x", encoding="utf-8")
    (wiki / "LINT.md").write_text("x", encoding="utf-8")
    for path in ("topics/gone.md", "notes/n.md", "LINT.md"):
        response = client.delete("/api/wiki/file", params={"path": path})
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "path": path}
        assert not (wiki / path).exists()
    # the folder stays
    assert (wiki / "topics").is_dir()
    assert (
        client.get("/api/wiki/file", params={"path": "topics/gone.md"}).status_code
        == 404
    )


def test_delete_missing_file_is_404(client) -> None:
    for path in ("topics/none.md", "LINT.md"):
        response = client.delete("/api/wiki/file", params={"path": path})
        assert response.status_code == 404
        assert response.json() == {"detail": f"Wiki file not found: {path}"}


def test_delete_refuses_user_index_and_log_even_when_absent(client, wiki) -> None:
    for name in ("USER.md", "INDEX.md", "LOG.md"):
        response = client.delete("/api/wiki/file", params={"path": name})
        assert response.status_code == 400
        assert response.json() == {
            "detail": f"Refusing to delete protected wiki file: {name}. "
            "Overwrite the contents instead."
        }
    assert (wiki / "USER.md").is_file()
    assert not (wiki / "INDEX.md").exists()


def test_delete_requires_the_path_query(client) -> None:
    response = client.delete("/api/wiki/file")
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["query", "path"]


def test_other_methods_on_the_file_route_are_405(client) -> None:
    assert (
        client.post(
            "/api/wiki/file", json={"path": "topics/x.md", "content": "x"}
        ).status_code
        == 405
    )
    assert client.patch("/api/wiki/file", json={}).status_code == 405


@pytest.mark.skipif(
    sys.platform == "win32", reason="symlinks need privileges on Windows"
)
def test_symlink_out_of_the_wiki_is_refused(client, wiki, tmp_path) -> None:
    outside = tmp_path / "outside.md"
    outside.write_text("secret", encoding="utf-8")
    os.symlink(outside, wiki / "topics" / "link.md")
    expected = {"detail": "Wiki path escapes root: topics/link.md"}
    get = client.get("/api/wiki/file", params={"path": "topics/link.md"})
    put = _put(client, "topics/link.md", "overwritten")
    delete = client.delete("/api/wiki/file", params={"path": "topics/link.md"})
    for response in (get, put, delete):
        assert response.status_code == 400
        assert response.json() == expected
    assert outside.read_text(encoding="utf-8") == "secret"
    assert (wiki / "topics" / "link.md").is_symlink()
