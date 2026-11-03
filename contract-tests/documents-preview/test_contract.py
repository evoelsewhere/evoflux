"""Black-box checks against the real sidecar, never invoking a converter."""

import uuid

import pytest

SID = str(uuid.UUID(int=1))
JOB = "motion-" + "a" * 32
BASE = "/api/team"
ROUTES = [
    ("GET", f"/{SID}/media/x"),
    ("GET", f"/{SID}/document-preview/x"),
    ("GET", f"/{SID}/office-preview/x"),
    ("GET", f"/{SID}/document-versions"),
    ("POST", f"/{SID}/document-versions"),
    ("POST", f"/{SID}/motion-review/{JOB}"),
    ("GET", "/office-runtime/status"),
    ("POST", "/office-runtime/install"),
    ("POST", "/office-runtime/install/cancel"),
    ("POST", "/office-runtime/install/dismiss"),
    ("DELETE", "/office-runtime"),
]


@pytest.mark.parametrize(("method", "path"), ROUTES)
@pytest.mark.parametrize("token", [None, "wrong"])
def test_auth_before_validation(client, method, path, token):
    client.headers.pop("Authorization")
    if token:
        client.headers["Authorization"] = f"Bearer {token}"
    response = client.request(method, BASE + path, json={})
    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized — EvoFlux access key required."}


@pytest.mark.parametrize("kind", ["media", "document-preview", "office-preview"])
def test_missing_file(client, session_workspace, kind):
    sid, _ = session_workspace
    r = client.get(f"{BASE}/{sid}/{kind}/missing.docx")
    assert r.status_code == 404
    assert r.json() == {"detail": "Media file not found."}


@pytest.mark.parametrize("kind", ["media", "document-preview", "office-preview"])
def test_invalid_session(client, kind):
    r = client.get(f"{BASE}/bad/{kind}/missing.docx")
    assert r.status_code == 400
    assert r.json() == {"detail": "Invalid session id."}


@pytest.mark.parametrize("kind", ["media", "document-preview", "office-preview"])
def test_absolute_path_rejected(client, session_workspace, kind):
    sid, _ = session_workspace
    r = client.get(f"{BASE}/{sid}/{kind}/C:%5Coutside.docx")
    assert r.status_code == 400


@pytest.mark.parametrize("kind", ["document-preview", "office-preview"])
def test_unsupported_preview(client, session_workspace, kind):
    sid, root = session_workspace
    (root / "note.txt").write_text("hello", encoding="utf-8")
    r = client.get(f"{BASE}/{sid}/{kind}/note.txt")
    assert r.status_code == 415
    assert r.json() == {"detail": ".txt is not supported for document preview."}


def test_media_bytes_and_disposition(client, session_workspace):
    sid, root = session_workspace
    content = b"\x00hello\xff\r\n"
    (root / "file.bin").write_bytes(content)
    url = f"{BASE}/{sid}/media/file.bin"
    r = client.get(url)
    assert r.status_code == 200 and r.content == content
    assert r.headers["content-disposition"].startswith("inline;")
    assert "etag" in r.headers and "last-modified" in r.headers
    r = client.get(url, params={"download": "true"})
    assert r.content == content
    assert r.headers["content-disposition"].startswith("attachment;")


@pytest.mark.parametrize("query", ["download=maybe", "download=2"])
def test_media_invalid_download(client, query):
    assert client.get(f"{BASE}/{SID}/media/x?{query}").status_code == 422


@pytest.mark.parametrize("kind", ["document-preview", "office-preview"])
def test_renderer_validation(client, kind):
    assert client.get(f"{BASE}/{SID}/{kind}/x?renderer=other").status_code == 422


@pytest.mark.parametrize("params", [{}, {"path": ""}])
def test_versions_query_validation(client, params):
    assert (
        client.get(f"{BASE}/{SID}/document-versions", params=params).status_code == 422
    )


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"path": "a.docx"},
        {"path": "a.docx", "action": "bad"},
        {"path": "", "action": "undo"},
    ],
)
def test_versions_body_validation(client, body):
    assert client.post(f"{BASE}/{SID}/document-versions", json=body).status_code == 422


@pytest.mark.parametrize(
    ("path", "status", "detail"),
    [
        ("x.txt", 415, "Only Word, Excel and PowerPoint files keep versions."),
        ("missing.docx", 404, "Document not found."),
        ("../escape.docx", 400, "Path must not traverse upward."),
        ("C:\\escape.docx", 400, "Path must be relative."),
    ],
)
def test_versions_path_errors(client, session_workspace, path, status, detail):
    sid, _ = session_workspace
    r = client.get(f"{BASE}/{sid}/document-versions", params={"path": path})
    assert r.status_code == status and r.json() == {"detail": detail}


def test_motion_bad_job(client, session_workspace):
    sid, _ = session_workspace
    r = client.post(f"{BASE}/{sid}/motion-review/bad", json={})
    assert r.status_code == 422 and r.json() == {"detail": "Invalid motion job id."}


def test_motion_missing_session(client):
    r = client.post(f"{BASE}/{SID}/motion-review/{JOB}", json={})
    assert r.status_code == 404 and r.json() == {"detail": "Team session not found."}


@pytest.mark.parametrize("body", [{}, {"sample_request_id": "x"}, {"unexpected": True}])
def test_motion_body_validation(client, session_workspace, body):
    sid, _ = session_workspace
    assert (
        client.post(f"{BASE}/{sid}/motion-review/{JOB}", json=body).status_code == 422
    )


def test_runtime_idle(client):
    url = f"{BASE}/office-runtime"
    r = client.get(url + "/status")
    assert r.status_code == 200
    assert r.json()["installed_version"] is None and r.json()["job"] is None
    assert client.post(url + "/install/cancel").status_code == 200
    assert client.post(url + "/install/dismiss").status_code == 204
    assert client.delete(url).status_code == 204
