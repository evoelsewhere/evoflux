"""``/api/team/{sid}/document-versions``: history, checkpoint, undo/redo and restore."""

from __future__ import annotations

import io
import json
import os
import zipfile
from pathlib import Path

BASE = "/api/team"


def make_zip(marker: str) -> bytes:
    """The smallest complete archive; the service only needs a readable central directory."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", f"<Types>{marker}</Types>")
    return buffer.getvalue()


def url(sid: str) -> str:
    return f"{BASE}/{sid}/document-versions"


def history(client, sid: str, path: str = "a.docx") -> dict:
    response = client.get(url(sid), params={"path": path})
    assert response.status_code == 200, response.text
    return response.json()


def act(client, sid: str, action: str, path: str = "a.docx", **extra):
    return client.post(url(sid), json={"path": path, "action": action, **extra})


def test_history_of_a_document_records_the_baseline(client, session_workspace) -> None:
    sid, root = session_workspace
    data = make_zip("one")
    (root / "a.docx").write_bytes(data)
    body = history(client, sid)
    assert list(body) == ["path", "head", "can_undo", "can_redo", "versions"]
    assert body["path"] == "a.docx"
    assert body["can_undo"] is False and body["can_redo"] is False
    (version,) = body["versions"]
    assert body["head"] == version["id"]
    assert len(version["id"]) == 12
    assert version["size"] == len(data)
    assert version["label"] == ""
    assert version["source"] == "baseline"
    assert isinstance(version["created_at"], float)
    assert list(version) == ["id", "size", "created_at", "label", "source"]
    # asking again records nothing new
    assert history(client, sid) == body


def test_a_file_that_is_not_a_complete_archive_has_no_versions(client, session_workspace) -> None:
    sid, root = session_workspace
    (root / "a.docx").write_bytes(b"not a zip")
    body = history(client, sid)
    assert body == {"path": "a.docx", "head": None, "can_undo": False, "can_redo": False, "versions": []}
    for action in ("checkpoint",):
        assert act(client, sid, action).json()["versions"] == []


def test_changes_become_versions_and_undo_redo_walk_them(client, session_workspace) -> None:
    sid, root = session_workspace
    one, two, three = make_zip("one"), make_zip("two"), make_zip("three")
    (root / "a.docx").write_bytes(one)
    first = history(client, sid)["versions"][0]["id"]
    (root / "a.docx").write_bytes(two)
    second = history(client, sid)
    assert [v["source"] for v in second["versions"]] == ["baseline", "change"]
    assert second["can_undo"] is True and second["can_redo"] is False
    (root / "a.docx").write_bytes(three)
    history(client, sid)

    undone = act(client, sid, "undo")
    assert undone.status_code == 200
    body = undone.json()
    assert (root / "a.docx").read_bytes() == two
    assert body["head"] == second["versions"][1]["id"]
    assert body["can_undo"] is True and body["can_redo"] is True
    assert len(body["versions"]) == 3

    assert act(client, sid, "undo").status_code == 200
    assert (root / "a.docx").read_bytes() == one
    assert act(client, sid, "undo").status_code == 409
    assert act(client, sid, "undo").json() == {"detail": "Nothing to undo."}

    redone = act(client, sid, "redo")
    assert redone.status_code == 200 and (root / "a.docx").read_bytes() == two
    act(client, sid, "redo")
    assert (root / "a.docx").read_bytes() == three
    nothing = act(client, sid, "redo")
    assert nothing.status_code == 409
    assert nothing.json() == {"detail": "Nothing to redo."}
    assert first == body["versions"][0]["id"]


def test_a_new_change_after_undo_drops_the_redo_branch(client, session_workspace) -> None:
    sid, root = session_workspace
    (root / "a.docx").write_bytes(make_zip("one"))
    history(client, sid)
    (root / "a.docx").write_bytes(make_zip("two"))
    history(client, sid)
    act(client, sid, "undo")
    assert history(client, sid)["can_redo"] is True
    (root / "a.docx").write_bytes(make_zip("other"))
    body = history(client, sid)
    assert body["can_redo"] is False
    assert len(body["versions"]) == 2


def test_checkpoint_labels_the_next_change(client, session_workspace) -> None:
    sid, root = session_workspace
    (root / "a.docx").write_bytes(make_zip("one"))
    first = act(client, sid, "checkpoint", label="  before edit  ")
    assert first.status_code == 200
    assert [v["source"] for v in first.json()["versions"]] == ["baseline"]
    assert first.json()["versions"][0]["label"] == ""
    (root / "a.docx").write_bytes(make_zip("two"))
    after = history(client, sid)
    assert [v["label"] for v in after["versions"]] == ["", "before edit"]
    # the label is used once
    (root / "a.docx").write_bytes(make_zip("three"))
    assert history(client, sid)["versions"][-1]["label"] == ""


def test_checkpoint_of_unchanged_content_adds_nothing_and_label_is_cut(client, session_workspace) -> None:
    sid, root = session_workspace
    (root / "a.docx").write_bytes(make_zip("one"))
    act(client, sid, "checkpoint")
    again = act(client, sid, "checkpoint", label="x" * 500)
    assert len(again.json()["versions"]) == 1
    (root / "a.docx").write_bytes(make_zip("two"))
    body = history(client, sid)
    assert body["versions"][-1]["label"] == "x" * 200


def test_restore_writes_the_chosen_version_back(client, session_workspace) -> None:
    sid, root = session_workspace
    one, two = make_zip("one"), make_zip("two")
    (root / "a.docx").write_bytes(one)
    first = history(client, sid)["versions"][0]["id"]
    (root / "a.docx").write_bytes(two)
    history(client, sid)
    # unrecorded work is kept as a version before the restore
    unsaved = make_zip("unsaved")
    (root / "a.docx").write_bytes(unsaved)
    response = act(client, sid, "restore", version_id=first)
    assert response.status_code == 200
    body = response.json()
    assert body["head"] == first
    assert (root / "a.docx").read_bytes() == one
    assert len(body["versions"]) == 3
    assert body["can_redo"] is True
    restore_back = act(client, sid, "redo")
    assert restore_back.status_code == 200
    assert (root / "a.docx").read_bytes() == two


def test_restore_errors(client, session_workspace) -> None:
    sid, root = session_workspace
    (root / "a.docx").write_bytes(make_zip("one"))
    missing_id = act(client, sid, "restore")
    assert missing_id.status_code == 422
    assert missing_id.json() == {"detail": "version_id is required."}
    empty_id = act(client, sid, "restore", version_id="")
    assert empty_id.status_code == 422
    unknown = act(client, sid, "restore", version_id="nope")
    assert unknown.status_code == 409
    assert unknown.json() == {"detail": "That version no longer exists."}


def test_each_path_has_its_own_history_and_versions_are_stored_under_the_state_dir(
    client, session_workspace, tmp_path: Path
) -> None:
    sid, root = session_workspace
    (root / "sub").mkdir()
    (root / "a.docx").write_bytes(make_zip("a"))
    (root / "sub" / "b.xlsx").write_bytes(make_zip("b"))
    (root / "c.pptx").write_bytes(make_zip("c"))
    for name in ("a.docx", "sub/b.xlsx", "c.pptx"):
        assert history(client, sid, name)["path"] == name
    base = tmp_path / "state" / "document-versions" / sid
    directories = sorted(p for p in base.iterdir() if p.is_dir())
    assert len(directories) == 3
    for directory in directories:
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        assert len(manifest["versions"]) == 1
        assert (directory / "blobs" / manifest["versions"][0]["sha256"]).is_file()


def test_path_errors_and_versioned_suffixes(client, session_workspace) -> None:
    sid, root = session_workspace
    (root / "note.docm").write_bytes(make_zip("x"))
    (root / "dir.docx").mkdir()
    cases = [
        ("note.docm", 415, "Only Word, Excel and PowerPoint files keep versions."),
        ("A.DOCX", 404, "Document not found."),
        ("dir.docx", 404, "Document not found."),
        ("sub/../a.docx", 400, "Path must not traverse upward."),
        ("C:/abs/a.docx", 400, "Path must be relative."),
        # a rooted path without a drive is absolute on POSIX only
        (
            "/abs/a.docx",
            400,
            "Path escapes workspace root." if os.name == "nt" else "Path must be relative.",
        ),
    ]
    for path, status, detail in cases:
        for response in (
            client.get(url(sid), params={"path": path}),
            act(client, sid, "undo", path=path),
        ):
            assert (response.status_code, response.json()) == (status, {"detail": detail}), path


def test_invalid_session_id_is_400(client) -> None:
    response = client.get(f"{BASE}/not-a-uuid/document-versions", params={"path": "a.docx"})
    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid session id."}
    post = client.post(
        f"{BASE}/not-a-uuid/document-versions", json={"path": "a.docx", "action": "undo"}
    )
    assert post.status_code == 400
