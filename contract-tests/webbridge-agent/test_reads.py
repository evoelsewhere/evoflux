"""Transcript, queue, composer, media, question and permission routes of a paired session."""

from __future__ import annotations

import httpx
import pytest

from wa_helpers import T

MID = "22222222-2222-2222-2222-222222222222"


def _assign(client, pairing, sid: str) -> None:
    assert client.put(f"{T}/pairings/{pairing.id}/sessions/{sid}").status_code == 200


def test_history_of_an_empty_session(paired, panel) -> None:
    response = paired.get(f"{T}/sessions/{panel}/history")
    assert response.status_code == 200
    assert response.json() == {
        "session_id": panel,
        "messages": [],
        "has_more": False,
        "next_cursor": None,
        "revert": None,
    }


def test_history_projects_visible_messages_only(paired, panel, insert_message) -> None:
    insert_message(panel, "user", "first", created="2026-01-01 00:00:01.000000")
    insert_message(panel, "assistant", "second", created="2026-01-01 00:00:02.000000")
    insert_message(
        panel, "tool", "hidden tool output", created="2026-01-01 00:00:03.000000"
    )
    insert_message(
        panel, "system", "hidden system", created="2026-01-01 00:00:04.000000"
    )
    insert_message(panel, "user", "third", created="2026-01-01 00:00:05.000000")
    history = paired.get(f"{T}/sessions/{panel}/history").json()
    assert [(m["role"], m["content"]) for m in history["messages"]] == [
        ("user", "first"),
        ("assistant", "second"),
        ("user", "third"),
    ]
    assistant = history["messages"][1]
    assert assistant["agent"] is None
    assert assistant["attachments"] == []
    assert assistant["is_summary"] is False
    assert assistant["created_at"].startswith("2026-01-01T00:00:02")


def test_history_cursor_must_parse(paired, panel) -> None:
    bad = paired.get(f"{T}/sessions/{panel}/history", params={"before": "zzz"})
    assert bad.status_code == 422
    assert bad.json() == {"detail": "Invalid before cursor: zzz"}


def test_history_pages_with_a_cursor(paired, panel, insert_message) -> None:
    for index in range(60):
        insert_message(
            panel,
            "user" if index % 2 == 0 else "assistant",
            f"m{index:02d}",
            created=f"2026-01-01 00:00:{index:02d}.000000",
        )
    first = paired.get(f"{T}/sessions/{panel}/history").json()
    if first["has_more"]:
        assert first["next_cursor"]
        second = paired.get(
            f"{T}/sessions/{panel}/history", params={"before": first["next_cursor"]}
        ).json()
        contents = [m["content"] for m in second["messages"]] + [
            m["content"] for m in first["messages"]
        ]
        assert contents == sorted(contents)
        assert len(set(contents)) == len(contents)
    else:
        assert first["next_cursor"] is None
        assert len(first["messages"]) == 60


def test_queued_messages_can_be_listed_edited_and_cancelled(
    paired, panel, insert_message
) -> None:
    queued = insert_message(
        panel,
        "user",
        "queued text",
        extra={"queue_status": "queued", "model": "m", "service_tier": "fast"},
        exclude=True,
    )
    insert_message(
        panel, "user", "not queued", exclude=True, extra={"queue_status": "done"}
    )
    insert_message(panel, "user", "visible", extra={"queue_status": "queued"})
    listed = paired.get(f"{T}/sessions/{panel}/queued-messages")
    assert listed.status_code == 200
    (message,) = listed.json()["messages"]
    assert list(message) == [
        "id",
        "content",
        "created_at",
        "model",
        "thinking_level",
        "fast_mode",
    ]
    assert message["id"] == queued
    assert message["content"] == "queued text"
    assert (message["model"], message["thinking_level"], message["fast_mode"]) == (
        "m",
        None,
        True,
    )
    path = f"{T}/sessions/{panel}/queued-messages/{queued}"
    edited = paired.patch(path, json={"content": "  new text  "})
    assert edited.status_code == 200
    assert edited.json()["content"] == "new text"
    assert (
        paired.get(f"{T}/sessions/{panel}/queued-messages").json()["messages"][0][
            "content"
        ]
        == "new text"
    )
    for body in [
        {},
        {"content": ""},
        {"content": "   "},
        {"content": "x" * 100_001},
        {"content": "a", "x": 1},
    ]:
        assert paired.patch(path, json=body).status_code == 422, body
    missing = paired.patch(
        f"{T}/sessions/{panel}/queued-messages/{MID}", json={"content": "x"}
    )
    assert (missing.status_code, missing.json()) == (
        404,
        {"detail": "Queued message not found."},
    )
    cancelled = paired.delete(path)
    assert cancelled.status_code == 204
    assert cancelled.content == b""
    assert paired.get(f"{T}/sessions/{panel}/queued-messages").json() == {
        "messages": []
    }
    again = paired.delete(path)
    assert (again.status_code, again.json()) == (
        404,
        {"detail": "Queued message not found."},
    )


def test_editing_a_queued_message_keeps_the_browser_context_prefix(
    paired, panel, insert_message
) -> None:
    queued = insert_message(
        panel,
        "user",
        "[context]\n\nUser request:\nold",
        exclude=True,
        extra={
            "queue_status": "queued",
            "webbridge_side_panel": {"user_content": "old"},
        },
    )
    path = f"{T}/sessions/{panel}/queued-messages/{queued}"
    listed = paired.get(f"{T}/sessions/{panel}/queued-messages").json()["messages"][0]
    assert listed["content"] == "old"
    assert paired.patch(path, json={"content": "new"}).json()["content"] == "new"
    other = insert_message(
        panel,
        "user",
        "unrelated text",
        exclude=True,
        extra={
            "queue_status": "queued",
            "webbridge_side_panel": {"user_content": "zzz"},
        },
    )
    conflict = paired.patch(
        f"{T}/sessions/{panel}/queued-messages/{other}", json={"content": "x"}
    )
    assert conflict.status_code == 409
    assert conflict.json() == {
        "detail": "Queued browser context could not be edited safely."
    }


def test_composer_catalog_without_a_workspace(paired, panel) -> None:
    catalog = paired.get(f"{T}/sessions/{panel}/composer-catalog")
    assert catalog.status_code == 200
    body = catalog.json()
    assert list(body) == [
        "session_id",
        "mode",
        "workspace",
        "supports_shell",
        "commands",
        "snippets",
        "references",
        "references_truncated",
    ]
    assert (
        body["session_id"],
        body["mode"],
        body["workspace"],
        body["supports_shell"],
    ) == (
        panel,
        "work",
        None,
        True,
    )
    builtin = [c for c in body["commands"] if c["category"] == "builtin"]
    assert [c["id"] for c in builtin] == [
        "stop",
        "continue",
        "compact",
        "shell",
        "undo",
        "redo",
        "new",
        "init",
        "btw",
        "goal",
        "goal:budget",
        "goal:pause",
        "goal:resume",
        "goal:stop",
    ]
    shell = next(c for c in builtin if c["id"] == "shell")
    assert shell == {
        "id": "shell",
        "label": "Shell",
        "description": "Run a shell command",
        "category": "builtin",
        "insert_text": "! ",
        "keep_input_open": True,
        "source": None,
    }
    assert body["snippets"] == []
    assert body["references"] == []
    assert body["references_truncated"] is False


def test_composer_catalog_lists_workspace_commands_snippets_and_files(
    client, pairing, paired, make_session, tmp_path
) -> None:
    workspace = tmp_path / "project"
    (workspace / ".evoflux" / "commands" / "team").mkdir(parents=True)
    (workspace / ".evoflux" / "commands" / "review.md").write_text(
        "---\ndescription: Review the diff\n---\nReview $ARGUMENTS now\n",
        encoding="utf-8",
    )
    (workspace / ".evoflux" / "commands" / "team" / "plan.md").write_text(
        "Plan it\n", encoding="utf-8"
    )
    (workspace / ".evoflux" / "snippets").mkdir()
    (workspace / ".evoflux" / "snippets" / "hello.md").write_text(
        "---\ndescription: Greeting\n---\nHello there\n", encoding="utf-8"
    )
    (workspace / "src").mkdir()
    (workspace / "src" / "main.py").write_text("print()\n", encoding="utf-8")
    (workspace / "README.md").write_text("# hi\n", encoding="utf-8")
    sid = make_session(workspace=workspace, mode="coding")
    _assign(client, pairing, sid)
    body = paired.get(f"{T}/sessions/{sid}/composer-catalog").json()
    assert body["mode"] == "coding"
    assert body["workspace"] == str(workspace.resolve())
    custom = {c["id"]: c for c in body["commands"] if c["category"] == "command"}
    assert custom["review"] == {
        "id": "review",
        "label": "review",
        "description": "Review the diff",
        "category": "command",
        "insert_text": "review",
        "keep_input_open": True,
        "source": "project-EvoFlux",
    }
    assert custom["team/plan"]["label"] == "team:plan"
    assert custom["team/plan"]["insert_text"] == "team:plan"
    assert custom["team/plan"]["description"] == "Custom command (project-EvoFlux)"
    assert body["snippets"] == [
        {
            "id": "hello",
            "label": "hello",
            "description": "Greeting",
            "source": "project-EvoFlux",
        }
    ]
    refs = {(r["path"], r["type"]) for r in body["references"]}
    assert ("README.md", "file") in refs
    assert ("src/main.py", "file") in refs
    assert ("src", "directory") in refs
    render = paired.post(
        f"{T}/sessions/{sid}/composer/commands/review/render",
        json={"arguments": " the PR "},
    )
    assert (render.status_code, render.json()) == (
        200,
        {"name": "review", "content": "Review the PR now"},
    )
    nested = paired.post(
        f"{T}/sessions/{sid}/composer/commands/team/plan/render",
        json={"arguments": "x"},
    )
    assert nested.status_code == 200
    assert nested.json()["name"] == "team/plan"
    snippet = paired.post(f"{T}/sessions/{sid}/composer/snippets/hello/render")
    assert (snippet.status_code, snippet.json()) == (
        200,
        {"name": "hello", "content": "Hello there"},
    )
    missing = paired.post(f"{T}/sessions/{sid}/composer/snippets/nope/render")
    assert (missing.status_code, missing.json()) == (
        404,
        {"detail": "Snippet 'nope' not found."},
    )


def test_composer_workspace_must_exist(
    client, pairing, paired, make_session, tmp_path
) -> None:
    sid = make_session(workspace=tmp_path / "does-not-exist")
    _assign(client, pairing, sid)
    response = paired.get(f"{T}/sessions/{sid}/composer-catalog")
    assert response.status_code == 422
    assert response.json()["detail"].startswith(
        "Workspace does not exist or is not a directory: "
    )


def test_render_errors(paired, panel) -> None:
    missing = paired.post(
        f"{T}/sessions/{panel}/composer/commands/ghost/render", json={}
    )
    assert (missing.status_code, missing.json()) == (
        404,
        {"detail": "Command 'ghost' not found."},
    )
    snippet = paired.post(f"{T}/sessions/{panel}/composer/snippets/x/render")
    assert (snippet.status_code, snippet.json()) == (
        404,
        {"detail": "Snippet 'x' not found."},
    )
    bad = paired.post(
        f"{T}/sessions/{panel}/composer/commands/x/render", json={"arguments": 5}
    )
    assert bad.status_code == 422


def test_markdown_media_is_served_only_when_an_assistant_message_references_it(
    client, pairing, paired, make_session, insert_message, tmp_path
) -> None:
    workspace = tmp_path / "ws"
    (workspace / "sub").mkdir(parents=True)
    (workspace / "pic.png").write_bytes(b"\x89PNG-pic")
    (workspace / "secret.txt").write_text("secret", encoding="utf-8")
    (workspace / "sub" / "inner.png").write_bytes(b"inner")
    sid = make_session(workspace=workspace)
    _assign(client, pairing, sid)
    insert_message(
        sid,
        "assistant",
        "look ![a](pic.png) and ![b](./sub/inner.png) ![c](https://x.test/r.png)",
    )
    insert_message(
        sid, "user", "user text ![u](secret.txt)", created="2026-01-01 00:00:02.000000"
    )
    path = f"{T}/sessions/{sid}/media"
    served = paired.get(f"{path}/pic.png")
    assert served.status_code == 200
    assert served.content == b"\x89PNG-pic"
    assert served.headers["content-type"] == "image/png"
    assert served.headers["content-disposition"].startswith("inline")
    assert paired.get(f"{path}/sub/inner.png").content == b"inner"
    for unreferenced in ["secret.txt", "other.png", "r.png", "sub"]:
        response = paired.get(f"{path}/{unreferenced}")
        assert (response.status_code, response.json()) == (
            404,
            {"detail": "Media not found."},
        ), unreferenced


def test_media_never_escapes_the_workspace(
    client, pairing, paired, make_session, insert_message, tmp_path
) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (tmp_path / "outside.png").write_bytes(b"outside")
    sid = make_session(workspace=workspace)
    _assign(client, pairing, sid)
    insert_message(
        sid, "assistant", "![x](../outside.png) ![y](/etc/hosts) ![z](pic.png)"
    )
    for name in ["../outside.png", "outside.png", "%2e%2e/outside.png"]:
        assert paired.get(f"{T}/sessions/{sid}/media/{name}").status_code == 404


def test_questions_and_permissions_without_pending_requests(paired, panel) -> None:
    assert paired.get(f"{T}/sessions/{panel}/questions/pending").json() == {
        "questions": []
    }
    reply = paired.post(
        f"{T}/sessions/{panel}/questions/r1/reply",
        json={"request_session_id": panel, "answers": ["a"]},
    )
    assert (reply.status_code, reply.json()) == (
        404,
        {"detail": "Question request not found."},
    )
    for body in [
        {},
        {"request_session_id": panel},
        {"request_session_id": panel, "answers": []},
        {"request_session_id": panel, "answers": ["a"] * 21},
        {"request_session_id": panel, "answers": ["x" * 20_001]},
        {"request_session_id": "nope", "answers": ["a"]},
        {"request_session_id": panel, "answers": ["a"], "x": 1},
    ]:
        assert (
            paired.post(
                f"{T}/sessions/{panel}/questions/r1/reply", json=body
            ).status_code
            == 422
        ), body
    permission = paired.post(
        f"{T}/sessions/{panel}/permissions/r1/reply", json={"reply": "once"}
    )
    assert permission.status_code == 404
    assert permission.json() == {
        "detail": "Permission request 'r1' not found or already resolved."
    }
    bad = paired.post(
        f"{T}/sessions/{panel}/permissions/r1/reply", json={"reply": "maybe"}
    )
    assert bad.status_code == 422
    assert bad.json() == {
        "detail": "Invalid reply 'maybe'. Must be one of: ['always', 'once', 'reject']"
    }
    assert (
        paired.post(f"{T}/sessions/{panel}/permissions/r1/reply", json={}).status_code
        == 422
    )


def test_interrupt_an_idle_session(paired, panel) -> None:
    response = paired.post(f"{T}/sessions/{panel}/interrupt")
    assert response.status_code == 200
    assert response.json() == {
        "status": "interrupted",
        "session_id": panel,
        "cancelled": [],
    }


def test_stream_is_server_sent_events_and_ends_when_the_pairing_is_revoked(
    backend, client, pairing, panel
) -> None:
    with httpx.Client(
        base_url=backend.base_url, headers=pairing.bearer, timeout=30.0
    ) as http:
        with http.stream("GET", f"{T}/sessions/{panel}/stream") as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            assert client.delete(f"{T}/pairings/{pairing.id}").status_code == 204
            # the generator notices the revocation and the stream ends instead of hanging
            assert isinstance(b"".join(response.iter_bytes()), bytes)


@pytest.mark.parametrize("bad", ["nope", "123"])
def test_session_ids_must_be_uuids(paired, bad) -> None:
    for suffix in [
        "history",
        "queued-messages",
        "composer-catalog",
        "questions/pending",
    ]:
        response = paired.get(f"{T}/sessions/{bad}/{suffix}")
        assert response.status_code == 422, suffix
        assert response.json()["detail"][0]["loc"] == ["path", "session_id"]
