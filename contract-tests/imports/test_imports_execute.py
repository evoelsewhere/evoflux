"""``/api/import`` contract: execute, history, history detail and undo."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import httpx

from import_sources import (
    CHATGPT_CONVERSATIONS,
    SECRET,
    build_generic_dir,
    by_source_item,
    detect_ok,
    write,
    write_json,
)

EMPTY_UNDO = {"undone": 0, "skipped": 0, "items": []}


def _execute(client, import_id: str, body=None) -> dict:
    response = client.post(f"/api/import/execute/{import_id}", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def _text(path: Path) -> str:
    """File text with the platform newline folded, for cross-OS snapshots."""
    return path.read_bytes().decode("utf-8").replace("\r\n", "\n")


def _history(client) -> list[dict]:
    response = client.get("/api/import/history")
    assert response.status_code == 200
    return response.json()["imports"]


# ── execute ────────────────────────────────────────────────────────────────


def test_execute_unknown_import_is_404(client) -> None:
    response = client.post("/api/import/execute/nope")
    assert response.status_code == 404
    assert response.json() == {"detail": "Import not found"}


def test_execute_rejects_unknown_origin(client, tmp_path, snapshot) -> None:
    body = detect_ok(client, write(tmp_path / "n.md", "# N\nx"), "generic")
    response = client.post(
        f"/api/import/execute/{body['import_id']}", json={"origin": "cron"}
    )
    assert response.status_code == 422
    snapshot.check("execute_bad_origin.json", response.json())
    # The preview is still there.
    assert client.get(f"/api/import/preview/{body['import_id']}").status_code == 200


def test_execute_generic_writes_every_target(
    client, tmp_path, config_dir, wiki_dir, scrub, snapshot
) -> None:
    detected = detect_ok(client, build_generic_dir(tmp_path), "generic")
    result = _execute(client, detected["import_id"])
    job_id = result["import_id"]
    assert len(job_id) == 32 and int(job_id, 16) >= 0
    snapshot.check("execute_generic.json", scrub(result, job_id))
    assert client.get(f"/api/import/preview/{detected['import_id']}").status_code == 404

    agent = config_dir / "agents" / "helper-bot.md"
    skill = config_dir / "skills" / "pdf-tools" / "SKILL.md"
    knowledge = wiki_dir / "sources" / "notes.md"
    mcp = config_dir / "mcp.json"
    files = {
        "agent": _text(agent),
        "skill": _text(skill),
        "knowledge": _text(knowledge),
        "mcp": json.loads(mcp.read_text(encoding="utf-8")),
    }
    snapshot.check("execute_generic_files.json", scrub(files))
    # Text-mode writes: the platform newline on disk.
    assert (b"\r\n" in agent.read_bytes()) == (os.name == "nt")
    assert SECRET not in mcp.read_text(encoding="utf-8")

    history = _history(client)
    assert [row["import_id"] for row in history] == [job_id]
    snapshot.check("history_generic.json", scrub(history, job_id))
    detail = client.get(f"/api/import/history/{job_id}")
    assert detail.status_code == 200
    snapshot.check(
        "history_detail_generic.json", scrub(by_source_item(detail.json()), job_id)
    )
    assert SECRET not in detail.text


def test_execute_origin_auto_sync_is_recorded(client, tmp_path) -> None:
    body = detect_ok(client, write(tmp_path / "n.md", "# N\nx"), "generic")
    result = _execute(client, body["import_id"], {"origin": "auto_sync"})
    assert result["imported"] == {"knowledge": 1}
    assert _history(client)[0]["origin"] == "auto_sync"


def test_execute_skips_existing_targets_detected_at_execute_time(
    client, tmp_path, config_dir
) -> None:
    detected = detect_ok(client, build_generic_dir(tmp_path), "generic")
    write(config_dir / "agents" / "helper-bot.md", "MINE")
    result = _execute(client, detected["import_id"])
    assert result["skipped"]["agent"] == 1
    assert "agent" not in result["imported"]
    assert (config_dir / "agents" / "helper-bot.md").read_bytes() == b"MINE"


def test_execute_all_skipped_has_no_undo(client, tmp_path, snapshot) -> None:
    detected = detect_ok(client, write(tmp_path / "n.md", "# N\nx"), "generic")
    client.patch(
        f"/api/import/preview/{detected['import_id']}/items/0", json={"action": "skip"}
    )
    result = _execute(client, detected["import_id"])
    assert result["imported"] == {} and result["skipped"] == {"knowledge": 1}
    row = _history(client)[0]
    assert row["undo_state"] == "unavailable" and row["undo_available"] is False
    undo = client.post(f"/api/import/history/{result['import_id']}/undo")
    assert undo.json() == {
        "import_id": result["import_id"],
        "state": "unavailable",
        **EMPTY_UNDO,
    }


def test_concurrent_execute_of_one_import_writes_once(
    client, backend, tmp_path, config_dir
) -> None:
    detected = detect_ok(client, build_generic_dir(tmp_path), "generic")
    url = f"{backend.base_url}/api/import/execute/{detected['import_id']}"
    headers = {"Authorization": f"Bearer {backend.token}"}
    barrier = threading.Barrier(4)
    responses: list[httpx.Response] = []

    def run() -> None:
        barrier.wait()
        responses.append(httpx.post(url, headers=headers, timeout=60.0))

    threads = [threading.Thread(target=run) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    # One request imports every item. Python lets the others race on the same
    # preview: they answer 200 with everything skipped, or 500.
    assert {r.status_code for r in responses} <= {200, 404, 500}
    ok = [r.json() for r in responses if r.status_code == 200]
    importing = [body for body in ok if body["imported"]]
    assert len(importing) == 1
    assert importing[0]["imported"] == {
        "agent": 1,
        "skill": 1,
        "knowledge": 1,
        "mcp_server": 1,
    }
    assert (config_dir / "agents" / "helper-bot.md").is_file()
    assert client.get(f"/api/import/preview/{detected['import_id']}").status_code == 404


# ── sessions: import, re-import, undo ──────────────────────────────────────


def test_session_import_reimport_and_undo(client, tmp_path, scrub, snapshot) -> None:
    source = write_json(tmp_path / "src" / "chatgpt.json", CHATGPT_CONVERSATIONS)
    first = _execute(client, detect_ok(client, source)["import_id"])
    assert first["imported"] == {"session": 1}

    again = detect_ok(client, source)
    assert again["items"][0]["conflicts"] == ["Already imported"]
    assert again["items"][0]["action"] == "skip"
    assert again["summary"]["already_imported"] == 1
    response = client.patch(
        f"/api/import/preview/{again['import_id']}/items",
        json={"indexes": [0], "action": "reimport"},
    )
    assert response.json() == {"status": "ok", "updated": 1}
    second = _execute(client, again["import_id"])
    assert second["imported"] == {"session": 1}

    detail = client.get(f"/api/import/history/{second['import_id']}").json()
    assert detail["items"][0]["operation"] == "reimported"

    undo_second = client.post(f"/api/import/history/{second['import_id']}/undo")
    assert undo_second.status_code == 200
    undo_first = client.post(f"/api/import/history/{first['import_id']}/undo")
    repeat = client.post(f"/api/import/history/{first['import_id']}/undo")
    snapshot.check(
        "session_undo.json",
        scrub(
            {
                "second": undo_second.json(),
                "first": undo_first.json(),
                "repeat": repeat.json(),
                "history": _history(client),
            }
        ),
    )
    assert repeat.json() == {
        "import_id": first["import_id"],
        "state": "undone",
        **EMPTY_UNDO,
    }
    # The session is gone, so a fresh detect is new again.
    assert detect_ok(client, source)["items"][0]["conflicts"] == []


# ── undo of file targets ───────────────────────────────────────────────────


def test_undo_created_files_removes_them(
    client, tmp_path, config_dir, wiki_dir, scrub, snapshot
) -> None:
    seeded_mcp = (config_dir / "mcp.json").read_bytes()
    result = _execute(
        client, detect_ok(client, build_generic_dir(tmp_path), "generic")["import_id"]
    )
    response = client.post(f"/api/import/history/{result['import_id']}/undo")
    assert response.status_code == 200
    snapshot.check(
        "undo_generic.json", scrub(by_source_item(response.json()), result["import_id"])
    )
    assert not (config_dir / "agents" / "helper-bot.md").exists()
    assert not (config_dir / "skills" / "pdf-tools").exists()
    assert not (wiki_dir / "sources" / "notes.md").exists()
    # mcp.json existed (seeded), so undo writes it back instead of unlinking.
    assert (config_dir / "mcp.json").read_bytes() == seeded_mcp
    row = _history(client)[0]
    assert row["undo_state"] == "undone" and row["undone_count"] == 4


def test_reimport_of_existing_file_target_is_skipped(
    client, tmp_path, config_dir, wiki_dir
) -> None:
    """Python's execute-time conflict check forces ``skip`` on every existing file
    target, so a chosen Re-import of an agent, skill or knowledge file never runs."""
    agent = config_dir / "agents" / "helper-bot.md"
    write(agent, "")
    agent.write_bytes(b"---\r\nname: helper-bot\r\n---\nold body \xc3\xa9")
    note = write(wiki_dir / "sources" / "notes.md", "ORIGINAL")
    before = {agent: agent.read_bytes(), note: note.read_bytes()}
    write(
        tmp_path / "src" / "agent.md",
        "---\nname: helper-bot\ndescription: New\n---\nnew body\n",
    )
    write(tmp_path / "src" / "notes.md", "# New")
    detected = detect_ok(client, tmp_path / "src", "generic")
    assert [item["conflicts"] for item in detected["items"]] == [
        ["Agent already exists"],
        ["Knowledge file already exists"],
    ]
    response = client.patch(
        f"/api/import/preview/{detected['import_id']}/items",
        json={"indexes": [0, 1], "action": "reimport"},
    )
    assert response.json() == {"status": "ok", "updated": 2}
    result = _execute(client, detected["import_id"])
    assert result["imported"] == {}
    assert result["skipped"] == {"agent": 1, "knowledge": 1}
    assert result["errors"] == []
    for path, data in before.items():
        assert path.read_bytes() == data
    detail = client.get(f"/api/import/history/{result['import_id']}").json()
    assert [item["reason"] for item in detail["items"]] == [
        "Skipped by user or conflict detection"
    ] * 2


def test_undo_restores_mcp_config_byte_for_byte(client, tmp_path, config_dir) -> None:
    mcp = config_dir / "mcp.json"
    local = {
        "servers": {
            "files": {"command": "old", "env": {"API_KEY": "local-only-value"}},
            "other": {"url": "http://x"},
        },
        "extra": True,
    }
    mcp.write_bytes((json.dumps(local, indent=2) + "\n").encode("utf-8"))
    before = mcp.read_bytes()
    source = write_json(
        tmp_path / "src" / "mcp.json",
        {
            "mcpServers": {
                "files": {"command": "npx"},
                "fresh": {
                    "command": "npx",
                    "env": {"API_KEY": SECRET},
                    "headers": {"X-Api-Key": SECRET},
                    "args": [{"password": SECRET, "keep": 1}],
                },
            }
        },
    )
    detected = detect_ok(client, source, "generic")
    assert [item["conflicts"] for item in detected["items"]] == [
        ["MCP server already exists"],
        [],
    ]
    # Re-import of the existing server is forced back to skip at execute time.
    client.patch(
        f"/api/import/preview/{detected['import_id']}/items/0",
        json={"action": "reimport"},
    )
    result = _execute(client, detected["import_id"])
    assert result["imported"] == {"mcp_server": 1}
    assert result["skipped"] == {"mcp_server": 1}
    merged = json.loads(mcp.read_text(encoding="utf-8"))
    assert merged == {
        **local,
        "servers": {
            **local["servers"],
            "fresh": {"command": "npx", "args": [{"keep": 1}]},
        },
    }
    assert mcp.read_text(encoding="utf-8").endswith("}\n")
    detail = client.get(f"/api/import/history/{result['import_id']}").text
    assert SECRET not in detail and "local-only-value" not in detail

    undo = client.post(f"/api/import/history/{result['import_id']}/undo").json()
    assert undo["state"] == "undone" and undo["undone"] == 1
    # Python rewrites the file in text mode: the platform newline on disk.
    assert mcp.read_bytes() == before.replace(b"\n", os.linesep.encode())


def test_undo_leaves_changed_files_alone(client, tmp_path, config_dir, snapshot):
    result = _execute(
        client, detect_ok(client, build_generic_dir(tmp_path), "generic")["import_id"]
    )
    skill = config_dir / "skills" / "pdf-tools" / "SKILL.md"
    skill.write_bytes(b"edited by user")
    (config_dir / "agents" / "helper-bot.md").unlink()
    response = client.post(f"/api/import/history/{result['import_id']}/undo")
    body = response.json()
    assert body["state"] == "partially_undone"
    assert body["undone"] == 2 and body["skipped"] == 2
    snapshot.check(
        "undo_partial.json",
        sorted(
            [item["kind"], item["outcome"], item["reason"]] for item in body["items"]
        ),
    )
    assert skill.read_bytes() == b"edited by user"
    again = client.post(f"/api/import/history/{result['import_id']}/undo").json()
    assert again["state"] == "partially_undone"
    assert again["undone"] == 2 and again["skipped"] == 2
    assert len(again["items"]) == 2
    row = _history(client)[0]
    assert row["undo_state"] == "partially_undone"
    assert row["undo_available"] is False
    assert (row["undoable_count"], row["undone_count"], row["undo_skipped_count"]) == (
        0,
        2,
        2,
    )


# ── MCP credentials ────────────────────────────────────────────────────────


def test_mcp_new_server_without_config_creates_then_undo_unlinks(
    client, tmp_path, config_dir
) -> None:
    mcp = config_dir / "mcp.json"
    mcp.unlink()
    source = write_json(
        tmp_path / "src" / "x.mcp.json", {"servers": {"s": {"url": "u"}}}
    )
    result = _execute(client, detect_ok(client, source, "generic")["import_id"])
    assert json.loads(mcp.read_text(encoding="utf-8")) == {
        "servers": {"s": {"url": "u"}}
    }
    client.post(f"/api/import/history/{result['import_id']}/undo")
    assert not mcp.exists()


# ── history ────────────────────────────────────────────────────────────────


def test_history_empty(client) -> None:
    assert client.get("/api/import/history").json() == {"imports": []}


def test_history_detail_and_undo_unknown_job_are_404(client) -> None:
    for response in (
        client.get("/api/import/history/nope"),
        client.post("/api/import/history/nope/undo"),
    ):
        assert response.status_code == 404
        assert response.json() == {"detail": "Import history item not found"}


def test_history_is_newest_first_and_capped_at_50(client, tmp_path) -> None:
    job_ids = []
    for index in range(51):
        note = write(tmp_path / "notes" / f"n{index}.md", f"# N{index}")
        job_ids.append(
            _execute(client, detect_ok(client, note, "generic")["import_id"])[
                "import_id"
            ]
        )
    history = _history(client)
    assert len(history) == 50
    assert [row["import_id"] for row in history] == list(reversed(job_ids))[:50]
