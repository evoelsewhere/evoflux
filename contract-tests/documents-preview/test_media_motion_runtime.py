"""Media proxy details, motion-review uploads and the Office runtime status."""

from __future__ import annotations

import uuid

import pytest

BASE = "/api/team"
JOB = "motion-" + "a" * 32
SAMPLE = {
    "sample_id": "s1",
    "frame_index": 0,
    "timestamp_ms": 0,
    "mime_type": "image/jpeg",
    "image_base64": "AAAA",
}


def body(**changes) -> dict:
    value = {
        "sample_request_id": "r1",
        "artifact_id": "art-1",
        "artifact_revision": 1,
        "samples": [SAMPLE],
    }
    value.update(changes)
    return value


def test_media_headers_ranges_and_content_types(client, session_workspace) -> None:
    sid, root = session_workspace
    (root / "p.png").write_bytes(b"\x89PNG\r\n")
    (root / "unknown.zzz").write_bytes(b"abc")
    response = client.get(f"{BASE}/{sid}/media/p.png")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.headers["content-disposition"] == 'inline; filename="p.png"'
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["etag"].startswith('"')
    assert response.headers["x-content-type-options"] == "nosniff"
    partial = client.get(f"{BASE}/{sid}/media/p.png", headers={"Range": "bytes=0-1"})
    assert partial.status_code == 206
    assert partial.content == b"\x89P"
    assert partial.headers["content-range"] == "bytes 0-1/6"
    bad_range = client.get(f"{BASE}/{sid}/media/p.png", headers={"Range": "bytes=50-60"})
    assert bad_range.status_code == 416
    other = client.get(f"{BASE}/{sid}/media/unknown.zzz")
    assert other.status_code == 200 and other.content == b"abc"


def test_media_path_errors(client, session_workspace) -> None:
    sid, root = session_workspace
    (root / "dir").mkdir()
    cases = [
        ("", 400, "Empty media path."),
        ("..%2Fx", 400, "Media path escapes session root."),
        ("dir", 404, "Media file not found."),
        ("nope.png", 404, "Media file not found."),
    ]
    for path, status, detail in cases:
        response = client.get(f"{BASE}/{sid}/media/{path}")
        assert (response.status_code, response.json()) == (status, {"detail": detail}), path


def test_media_of_an_unknown_session_falls_back_to_its_own_workspace_directory(
    client, tmp_path
) -> None:
    """A session id with no database row is not rejected: the per-session directory is used.

    Any well-formed UUID therefore addresses ``<workspace dir>/<uuid>`` (finding S1).
    """
    sid = str(uuid.UUID(int=99))
    folder = tmp_path / "workspace" / sid
    folder.mkdir(parents=True)
    (folder / "x.txt").write_bytes(b"data")
    response = client.get(f"{BASE}/{sid}/media/x.txt")
    assert response.status_code == 200 and response.content == b"data"


def test_document_preview_unsupported_and_corrupt_documents(client, session_workspace) -> None:
    sid, root = session_workspace
    (root / "a.docx").write_bytes(b"not an archive")
    (root / "b.xlsx").write_bytes(b"not an archive")
    for kind in ("document-preview", "office-preview"):
        for name in ("a.docx", "b.xlsx"):
            response = client.get(f"{BASE}/{sid}/{kind}/{name}")
            assert response.status_code == 415, (kind, name)
            assert response.json()["detail"].startswith(f"This file has a .{name.split('.')[1]} name")
    native = client.get(f"{BASE}/{sid}/document-preview/a.docx", params={"renderer": "native"})
    assert native.status_code == 415


def test_motion_review_validation_and_unknown_requests(client, session_workspace) -> None:
    sid, _ = session_workspace
    url = f"{BASE}/{sid}/motion-review/{JOB}"
    accepted_shape = client.post(url, json=body())
    assert accepted_shape.status_code == 409
    assert accepted_shape.json() == {"detail": "no matching pending motion review request"}

    invalid = client.post(
        url, json=body(artifact_id="Bad Id", artifact_revision=0, samples=[])
    )
    assert invalid.status_code == 422
    fields = {tuple(e["loc"]): e["type"] for e in invalid.json()["detail"]}
    assert fields == {
        ("artifact_id",): "string_pattern_mismatch",
        ("artifact_revision",): "greater_than_equal",
        ("samples",): "too_short",
    }
    too_many = client.post(url, json=body(samples=[SAMPLE] * 13))
    assert too_many.status_code == 422
    assert too_many.json()["detail"][0]["type"] == "too_long"
    bad_mime = client.post(url, json=body(samples=[{**SAMPLE, "mime_type": "image/png"}]))
    assert bad_mime.status_code == 422
    assert bad_mime.json()["detail"][0]["loc"] == ["samples", 0, "mime_type"]
    extra = client.post(url, json=body(unexpected=1))
    assert extra.status_code == 422
    assert extra.json()["detail"][0]["type"] == "extra_forbidden"
    not_json = client.post(url, content=b"{", headers={"content-type": "application/json"})
    # Python v3 answers 500 here: the 422 body carries the raw bytes in ``input``, which
    # FastAPI cannot serialise (NOTES finding B1). A port may answer the intended 422.
    assert not_json.status_code in (422, 500)
    if not_json.status_code == 422:
        assert not_json.json()["detail"][0]["type"] == "json_invalid"


def test_motion_review_size_limit_and_session_checks(client, session_workspace, tmp_path) -> None:
    sid, _ = session_workspace
    url = f"{BASE}/{sid}/motion-review/{JOB}"
    big = client.post(url, content=b"x" * 3_500_000, headers={"content-type": "application/json"})
    assert big.status_code == 413
    assert big.json() == {"detail": "Motion review request is too large."}
    missing = client.post(f"{BASE}/{uuid.UUID(int=5)}/motion-review/{JOB}", json=body())
    assert missing.status_code == 404
    assert missing.json() == {"detail": "Team session not found."}
    not_uuid = client.post(f"{BASE}/nope/motion-review/{JOB}", json=body())
    assert not_uuid.status_code == 422
    assert not_uuid.json()["detail"][0]["loc"] == ["path", "session_id"]
    bad_job = client.post(f"{BASE}/{sid}/motion-review/motion-xyz", json=body())
    assert bad_job.status_code == 422
    assert bad_job.json() == {"detail": "Invalid motion job id."}


def test_motion_review_of_a_child_session_is_refused(client, session_workspace, tmp_path) -> None:
    import sqlite3

    sid, _ = session_workspace
    child = uuid.UUID(int=7)
    with sqlite3.connect(tmp_path / "data" / "evoflux.db", timeout=30) as db:
        db.execute(
            "INSERT INTO chat_sessions (id, title, created_at, updated_at, parent_session_id) "
            "VALUES (?, 'child', '2026-01-01', '2026-01-01', ?)",
            (child.hex, uuid.UUID(sid).hex),
        )
    response = client.post(f"{BASE}/{child}/motion-review/{JOB}", json=body())
    assert response.status_code == 404
    assert response.json() == {"detail": "Team session not found."}


def test_office_runtime_status_and_install_without_a_published_runtime(client) -> None:
    status = client.get(f"{BASE}/office-runtime/status")
    assert status.status_code == 200
    assert status.json() == {
        "available": False,
        "platform": None,
        "version": None,
        "download_bytes": None,
        "install_bytes": None,
        "installed_version": None,
        "job": None,
    }
    install = client.post(f"{BASE}/office-runtime/install")
    assert install.status_code == 409
    assert install.json() == {
        "detail": "No verified LibreOffice runtime is published for this platform."
    }
    cancel = client.post(f"{BASE}/office-runtime/install/cancel")
    assert cancel.status_code == 200 and cancel.json()["job"] is None
    assert client.post(f"{BASE}/office-runtime/install/dismiss").status_code == 204
    assert client.delete(f"{BASE}/office-runtime").status_code == 204


@pytest.mark.parametrize(
    ("method", "path"),
    [("PUT", "/office-runtime/status"), ("GET", "/office-runtime/install"), ("POST", "/office-runtime")],
)
def test_runtime_wrong_methods(client, method, path) -> None:
    assert client.request(method, BASE + path).status_code == 405


def test_media_symlink_pointing_outside_the_workspace_is_refused(
    client, session_workspace, tmp_path
) -> None:
    sid, root = session_workspace
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"secret")
    try:
        (root / "link.txt").symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks need privileges on this platform")
    for kind in ("media", "document-preview"):
        response = client.get(f"{BASE}/{sid}/{kind}/link.txt")
        assert response.status_code == 400, kind
        assert response.json() == {"detail": "Media path escapes session root."}
