"""``POST /api/team/search-app``: the command-palette search over application data."""

from __future__ import annotations

import pytest

from memory_helpers import (
    SEARCH_APP,
    uid,
    insert_message,
    insert_session,
    scrub,
)

KEYS = ["id", "kind", "label", "description", "session_id", "path", "metadata"]


def search(client, query: str, **body) -> list[dict]:
    response = client.post(SEARCH_APP, json={"query": query, **body})
    assert response.status_code == 200, response.text
    assert list(response.json()) == ["items"]
    return response.json()["items"]


def ids(items: list[dict]) -> list[str]:
    return [item["id"] for item in items]


def put_wiki(client, path: str, content: str) -> None:
    response = client.put("/api/wiki/file", json={"path": path, "content": content})
    assert response.status_code == 200, response.text


def mk_project(
    client, tmp_path, name: str, description: str | None = None, repo: str | None = None
) -> dict:
    folder = tmp_path / "projects" / (repo or f"repo-{name}")
    folder.mkdir(parents=True, exist_ok=True)
    body = {"name": name, "workspace_paths": [str(folder)]}
    if description is not None:
        body["description"] = description
    response = client.post("/api/team/projects", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def memory_ids(items: list[dict]) -> list[str]:
    return [i["id"] for i in items if i["kind"] == "memory"]


def norm(tmp_path, value: str | None) -> str | None:
    if value is None:
        return None
    return value.replace("\\", "/").replace(str(tmp_path).replace("\\", "/"), "<tmp>")


def test_request_validation(client) -> None:
    cases = [
        ({}, [("missing", ["body", "query"])]),
        ({"query": ""}, [("string_too_short", ["body", "query"])]),
        ({"query": "x" * 1001}, [("string_too_long", ["body", "query"])]),
        ({"query": "x", "limit": 0}, [("greater_than_equal", ["body", "limit"])]),
        ({"query": "x", "limit": 101}, [("less_than_equal", ["body", "limit"])]),
        ({"query": "x", "limit": "many"}, [("int_parsing", ["body", "limit"])]),
        ({"query": 5}, [("string_type", ["body", "query"])]),
        ({"query": None}, [("string_type", ["body", "query"])]),
    ]
    for body, expected in cases:
        response = client.post(SEARCH_APP, json=body)
        assert response.status_code == 422, body
        got = [(e["type"], e["loc"]) for e in response.json()["detail"]]
        assert got == expected, body
    no_body = client.post(SEARCH_APP)
    assert no_body.status_code == 422
    assert no_body.json()["detail"][0]["type"] == "missing"


def test_boundary_values_are_accepted(client) -> None:
    assert search(client, "x" * 1000) == []
    assert search(client, "qzx-nothing", limit=1) == []
    assert search(client, "qzx-nothing", limit=100) == []
    # a whitespace-only query passes validation and finds nothing
    assert search(client, "   \t ") == []


def test_unknown_methods(client) -> None:
    assert client.get(SEARCH_APP).status_code == 405
    assert client.put(SEARCH_APP, json={"query": "x"}).status_code == 405


def test_session_rows(client, tmp_path) -> None:
    ws = tmp_path / "projects" / "qzxrepo"
    ws.mkdir(parents=True)
    plain = insert_session(tmp_path, 1, "qzx plain chat")
    work = insert_session(
        tmp_path, 2, "qzx ranked", mode="work", workspace=str(ws), agent_name="builder"
    )
    insert_session(tmp_path, 3, None, agent_name="qzx-agent-only")
    insert_session(tmp_path, 4, "qzx child", parent_session_id=plain)
    insert_session(tmp_path, 5, "qzx side", session_type="side_chat")
    insert_session(tmp_path, 6, "other", scheduled_task_name="qzx-nightly")
    insert_session(tmp_path, 7, "workspace-only", workspace=str(ws))

    items = search(client, "qzx")
    sessions = {i["session_id"]: i for i in items if i["kind"] == "session"}
    assert set(sessions) == {uid(n) for n in (1, 2, 3, 6, 7)}
    by_n = {n: sessions[uid(n)] for n in (1, 2, 3, 6)}
    assert by_n[1]["id"] == f"session:{uid(1)}"
    assert list(by_n[1]) == KEYS
    assert by_n[1]["label"] == "qzx plain chat"
    assert by_n[1]["description"] == "work"
    assert by_n[1]["path"] is None
    assert by_n[1]["metadata"] == {
        "mode": "work",
        "workspace": None,
        "project_id": None,
        "updated_at": "2026-01-01T00:00:01+00:00",
    }
    assert by_n[2]["description"] == "work · qzxrepo · builder"
    assert by_n[2]["metadata"]["mode"] == "work"
    assert norm(tmp_path, by_n[2]["metadata"]["workspace"]) == "<tmp>/projects/qzxrepo"
    # no title: the label falls back, the agent name still matches
    assert by_n[3]["label"] == "Untitled chat"
    assert by_n[3]["description"] == "work · qzx-agent-only"
    assert by_n[6]["label"] == "other"
    assert by_n[6]["description"] == "work · scheduled · qzx-nightly"
    # newest update first within the group
    order = [i["session_id"] for i in items if i["kind"] == "session"]
    assert order == [uid(n) for n in (7, 6, 3, 2, 1)]
    # a workspace path match finds the session whose workspace contains the text
    by_path = search(client, "qzxrepo")
    assert {i["session_id"] for i in by_path if i["kind"] == "session"} == {
        uid(2),
        uid(7),
    }
    assert work and ws.is_dir()


def test_session_matching_folds_ascii_in_sql_and_non_ascii_only_for_the_query(
    client, tmp_path
) -> None:
    """SQLite ``LIKE`` folds ASCII only and the needle is casefolded in Python.

    A lowercase non-ASCII title is found by an upper-case query; an upper-case
    non-ASCII title is never found, because the SQL prefilter drops it.
    """
    insert_session(tmp_path, 1, "đi tới nơi ấy")
    insert_session(tmp_path, 2, "đi tới NƠI khác")
    insert_session(tmp_path, 3, "Ordinary")

    def sessions(query: str) -> list[str]:
        return [i["label"] for i in search(client, query) if i["kind"] == "session"]

    assert sessions("nơi") == ["đi tới nơi ấy"]
    assert sessions("NƠI") == ["đi tới nơi ấy"]

    assert sessions("ORDINARY") == ["Ordinary"]
    assert sessions("ordinary") == ["Ordinary"]


def test_like_wildcards_in_the_query_match_literally(client, tmp_path) -> None:
    insert_session(tmp_path, 1, "100% done")
    insert_session(tmp_path, 2, "100 percent")
    insert_session(tmp_path, 3, "snake_case")
    insert_session(tmp_path, 4, "snakeXcase")
    assert [i["label"] for i in search(client, "100%")] == ["100% done"]
    assert [i["label"] for i in search(client, "snake_")] == ["snake_case"]
    assert [i["label"] for i in search(client, "e_c")] == ["snake_case"]


def test_message_rows_one_per_conversation(client, tmp_path) -> None:
    lead = insert_session(tmp_path, 1, "Lead chat")
    member = insert_session(
        tmp_path, 2, "Member", parent_session_id=lead, agent_name="helper"
    )
    other = insert_session(tmp_path, 3, "Other chat")
    insert_message(tmp_path, 1, lead, "user", "first qzxterm mention")
    insert_message(
        tmp_path, 2, lead, "assistant", "second **qzxterm** with `code` and ## heading"
    )
    insert_message(tmp_path, 3, member, "assistant", "member says qzxterm too")
    insert_message(tmp_path, 4, lead, "tool", "qzxterm tool output")
    insert_message(tmp_path, 5, lead, "system", "qzxterm system")
    insert_message(tmp_path, 6, lead, "user", None)
    insert_message(tmp_path, 7, other, "user", "QZXTERM in a different chat")

    items = [i for i in search(client, "qzxterm") if i["kind"] == "message"]
    assert [i["label"] for i in items] == ["Other chat", "Lead chat"]
    other_row, lead_row = items
    assert other_row["id"] == f"message:{uid(1007)}"
    assert other_row["description"] == "QZXTERM in a different chat"
    assert other_row["session_id"] == uid(3)
    assert other_row["path"] is None
    assert other_row["metadata"] == {
        "mode": "work",
        "workspace": None,
        "project_id": None,
        "message_id": other_row["id"].removeprefix("message:"),
        "role": "user",
        "agent_name": None,
        "match_count": 1,
        "excerpt": "QZXTERM in a different chat",
        "created_at": "2026-01-01T00:01:07+00:00",
    }
    # the member's reply is grouped under the lead; the newest hit represents the group
    assert lead_row["session_id"] == uid(1)
    assert lead_row["metadata"]["match_count"] == 3
    assert lead_row["metadata"]["message_id"] == lead_row["id"].removeprefix("message:")
    assert lead_row["metadata"]["role"] == "assistant"
    assert lead_row["metadata"]["agent_name"] == "helper"
    assert lead_row["metadata"]["excerpt"] == "member says qzxterm too"
    assert lead_row["description"] == "3 matches · member says qzxterm too"
    assert member and lead_row["metadata"]["created_at"] == "2026-01-01T00:01:03+00:00"


def test_message_excerpt_window_and_markdown_stripping(client, tmp_path) -> None:
    chat = insert_session(tmp_path, 1, "Window chat")
    filler = "word " * 60
    insert_message(
        tmp_path,
        1,
        chat,
        "user",
        f"{filler}**needle-qzx** `ticks` {filler}",
    )
    insert_message(tmp_path, 2, chat, "assistant", "x")
    (row,) = [i for i in search(client, "needle-qzx") if i["kind"] == "message"]
    excerpt = row["metadata"]["excerpt"]
    assert excerpt.startswith("…") and excerpt.endswith("…")
    assert "needle-qzx ticks" in excerpt
    assert "**" not in excerpt and "`" not in excerpt
    assert row["description"] == excerpt
    assert len(excerpt) == 2 + len(excerpt.strip("…"))


def test_message_hit_is_dropped_when_the_chat_title_already_matches(
    client, tmp_path
) -> None:
    titled = insert_session(tmp_path, 1, "qzxtitle discussion")
    untitled = insert_session(tmp_path, 2, "plain")
    insert_message(tmp_path, 1, titled, "user", "qzxtitle body")
    insert_message(tmp_path, 2, untitled, "user", "qzxtitle body")
    items = search(client, "qzxtitle")
    assert [(i["kind"], i["label"]) for i in items] == [
        ("session", "qzxtitle discussion"),
        ("message", "plain"),
    ]


def test_project_row(client, tmp_path) -> None:
    project_id = mk_project(client, tmp_path, "Qzxproj", "about it", repo="repo-one")[
        "id"
    ]
    mk_project(client, tmp_path, "plain", "has qzxproj inside", repo="repo-two")
    items = [i for i in search(client, "QZXPROJ") if i["kind"] == "project"]
    assert len(items) == 2
    first = next(i for i in items if i["id"] == f"project:{project_id}")
    assert first == {
        "id": f"project:{project_id}",
        "kind": "project",
        "label": "Qzxproj",
        "description": "about it",
        "session_id": None,
        "path": None,
        "metadata": {"project_id": project_id},
    }
    second = next(i for i in items if i is not first)
    assert second["label"] == "plain"
    assert second["description"] == "has qzxproj inside"


def test_project_without_description_and_hidden_projects(client, tmp_path) -> None:
    created = mk_project(client, tmp_path, "qzxbare")
    (row,) = [i for i in search(client, "qzxbare") if i["kind"] == "project"]
    assert row["description"] == "Coding project"
    deleted = client.delete(f"/api/team/projects/{created['id']}")
    assert deleted.status_code in (200, 204)
    assert [i for i in search(client, "qzxbare") if i["kind"] == "project"] == []


def test_workspace_row_belongs_to_its_project(client, tmp_path) -> None:
    repo = tmp_path / "projects" / "qzxrepo-ws"
    repo.mkdir(parents=True)
    project = client.post(
        "/api/team/projects", json={"name": "owner", "workspace_paths": [str(repo)]}
    ).json()
    items = [i for i in search(client, "qzxrepo-ws") if i["kind"] == "workspace"]
    assert len(items) == 1
    row = items[0]
    workspace_id = project["workspaces"][0]["workspace_id"]
    assert row["id"] == f"workspace:{workspace_id}"
    assert row["label"] == "qzxrepo-ws"
    assert norm(tmp_path, row["description"]) == "<tmp>/projects/qzxrepo-ws"
    assert norm(tmp_path, row["path"]) == "<tmp>/projects/qzxrepo-ws"
    assert row["session_id"] is None
    assert row["metadata"]["kind"] == "repo"
    assert row["metadata"]["project_id"] == project["id"]
    assert norm(tmp_path, row["metadata"]["workspace"]) == "<tmp>/projects/qzxrepo-ws"


def test_scheduled_task_row(client) -> None:
    every = client.post(
        "/api/scheduler/tasks",
        json={
            "name": "qzx-every",
            "schedule_type": "every",
            "every_seconds": 90,
            "prompt": "p",
        },
    )
    cron = client.post(
        "/api/scheduler/tasks",
        json={
            "name": "other-name",
            "schedule_type": "cron",
            "cron_expression": "0 9 * * *",
            "prompt": "mentions qzx-prompt",
            "enabled": False,
        },
    )
    assert every.status_code == 201 and cron.status_code == 201
    rows = {
        i["label"]: i
        for i in search(client, "qzx-every")
        if i["kind"] == "scheduled_task"
    }
    assert set(rows) == {"qzx-every"}
    assert rows["qzx-every"]["id"] == f"scheduled-task:{every.json()['id']}"
    assert rows["qzx-every"]["description"] == "every 90s · pending"
    assert rows["qzx-every"]["metadata"] == {
        "task_id": every.json()["id"],
        "mode": "work",
    }
    # the prompt and the cron expression are searched too
    by_prompt = {
        i["label"]: i
        for i in search(client, "qzx-prompt")
        if i["kind"] == "scheduled_task"
    }
    assert set(by_prompt) == {"other-name"}
    assert by_prompt["other-name"]["description"] == "0 9 * * * · paused"
    by_cron = [i for i in search(client, "0 9 * * *") if i["kind"] == "scheduled_task"]
    assert [i["label"] for i in by_cron] == ["other-name"]


def test_memory_rows(client, tmp_path) -> None:
    put_wiki(
        client,
        "topics/qzxtopic.md",
        "---\ndescription: Qzx **topic** title\ntags: [animal]\n---\nQzxfact one has many details. "
        * 1,
    )
    put_wiki(client, "notes/2026-02-03.md", "raw qzxfact note body")
    put_wiki(client, "imports/qzximport.md", "imported qzxfact text")
    put_wiki(client, "entities/unrelated.md", "nothing here")
    items = [i for i in search(client, "qzxfact") if i["kind"] == "memory"]
    by_id = {i["id"]: i for i in items}
    assert set(by_id) == {
        "memory:topics/qzxtopic.md",
        "memory:notes/2026-02-03.md",
        "memory:imports/qzximport.md",
    }
    topic = by_id["memory:topics/qzxtopic.md"]
    assert topic["label"] == "Qzx topic title"
    assert topic["description"] == "Qzxfact one has many details."
    assert topic["path"] == "topics/qzxtopic.md"
    assert topic["session_id"] is None
    assert topic["metadata"] == {"source_ref": "topic:qzxtopic"}
    note = by_id["memory:notes/2026-02-03.md"]
    assert note["label"] == "notes/2026-02-03.md"
    assert note["metadata"] == {"source_ref": "note:2026-02-03.md"}
    assert by_id["memory:imports/qzximport.md"]["metadata"] == {
        "source_ref": "import:qzximport"
    }


def test_memory_weak_matches_abstain_and_stopwords_are_ignored(client) -> None:
    put_wiki(client, "topics/pairs.md", "alpha only here")
    # two meaningful tokens, one matched: coverage 0.5 and one piece of evidence is enough
    assert memory_ids(search(client, "alpha beta")) == ["memory:topics/pairs.md"]
    # three tokens, one matched: needs two pieces of evidence
    assert memory_ids(search(client, "alpha beta gamma")) == []
    # stop words do not count as query tokens
    assert memory_ids(search(client, "what is the alpha")) == ["memory:topics/pairs.md"]


def test_memory_inflections_and_user_file(client) -> None:
    put_wiki(client, "topics/run.md", "running planned stories")
    assert memory_ids(search(client, "runs")) == ["memory:topics/run.md"]
    assert memory_ids(search(client, "story")) == ["memory:topics/run.md"]
    user = [i for i in search(client, "preferences") if i["kind"] == "memory"]
    assert [(i["id"], i["label"], i["metadata"]) for i in user] == [
        ("memory:USER.md", "USER.md", {"source_ref": "memory:user"})
    ]


def test_memory_description_is_cut_to_200_characters(client) -> None:
    put_wiki(client, "topics/long.md", "qzxlong " + "word " * 200)
    (row,) = [i for i in search(client, "qzxlong") if i["kind"] == "memory"]
    assert len(row["description"]) == 200
    assert row["description"].startswith("qzxlong word word")


def test_memory_takes_at_most_eight_rows(client) -> None:
    for n in range(12):
        put_wiki(client, f"topics/page{n:02d}.md", f"qzxmany page {n}")
    rows = [i for i in search(client, "qzxmany") if i["kind"] == "memory"]
    assert len(rows) == 8


def test_agent_and_skill_rows(client, tmp_path) -> None:
    agent = client.post(
        "/api/agents",
        json={
            "name": "qzxagent",
            "content": "---\nname: qzxagent\nrole: member\ndescription:   Does   qzx things\n---\nbody text\n",
        },
    )
    assert agent.status_code in (200, 201), agent.text
    plain = client.post(
        "/api/agents",
        json={
            "name": "second",
            "content": "---\nname: second\nrole: member\n---\n\n## Heading line\nmentions qzxagent\n",
        },
    )
    assert plain.status_code in (200, 201), plain.text
    skill = client.post(
        "/api/skills",
        json={
            "name": "qzxskill",
            "content": "---\nname: qzxskill\ndescription: Skill   for qzx\n---\n\nbody\n",
        },
    )
    assert skill.status_code in (200, 201), skill.text

    rows = search(client, "qzxagent")
    agents = {i["label"]: i for i in rows if i["kind"] == "agent"}
    assert set(agents) == {"qzxagent", "second"}
    one = agents["qzxagent"]
    assert one["id"] == "agent:qzxagent"
    assert one["description"] == "Does qzx things"
    assert norm(tmp_path, one["path"]) == "<tmp>/config/agents/qzxagent.md"
    assert one["metadata"] == {"name": "qzxagent"}
    assert one["session_id"] is None
    # no frontmatter description: the first prose line of the body
    assert agents["second"]["description"] == "Heading line"

    skills = [i for i in search(client, "qzxskill") if i["kind"] == "skill"]
    assert len(skills) == 1
    assert skills[0]["id"] == "app-skill:qzxskill"
    assert skills[0]["label"] == "qzxskill"
    assert skills[0]["description"] == "Skill for qzx"
    assert norm(tmp_path, skills[0]["path"]).startswith("<tmp>/config/skills/qzxskill")
    assert skills[0]["metadata"]["name"] == "qzxskill"
    assert list(skills[0]) == KEYS


def test_group_order_is_round_robin(client, tmp_path) -> None:
    session = insert_session(tmp_path, 1, "qzxrr session one")
    insert_session(tmp_path, 2, "qzxrr session two")
    other = insert_session(tmp_path, 3, "plain chat")
    insert_message(tmp_path, 1, other, "user", "qzxrr in a message")
    mk_project(client, tmp_path, "qzxrr project")
    put_wiki(client, "topics/rr.md", "qzxrr memory text")
    items = search(client, "qzxrr")
    assert [i["kind"] for i in items] == [
        "session",
        "message",
        "project",
        "workspace",
        "memory",
        "session",
    ]
    assert session


def test_limit_caps_the_total_and_each_source(client, tmp_path) -> None:
    for n in range(1, 31):
        insert_session(tmp_path, n, f"qzxcap chat {n:02d}")
    assert len(search(client, "qzxcap", limit=100)) == 25
    assert len(search(client, "qzxcap")) == 25
    assert len(search(client, "qzxcap", limit=10)) == 10
    one = search(client, "qzxcap", limit=1)
    assert [i["label"] for i in one] == ["qzxcap chat 30"]


def test_search_is_read_only(client, tmp_path) -> None:
    insert_session(tmp_path, 1, "qzxro")

    def snapshot() -> list[str]:
        return sorted(
            p.name for p in (tmp_path / "wiki").rglob("*") if not p.name.startswith(".")
        )

    before = snapshot()
    search(client, "qzxro")
    assert snapshot() == before


@pytest.mark.parametrize(
    "query", ["qzx*", "qzx(", "[qzx", "qzx\\", "qzx'", 'qzx"', "qzx;--", "qzx\x00"]
)
def test_special_characters_in_the_query_are_literal(client, tmp_path, query) -> None:
    insert_session(tmp_path, 1, f"title {query} end")
    insert_session(tmp_path, 2, "title qzx end")
    rows = [i for i in search(client, query) if i["kind"] == "session"]
    assert [i["label"] for i in rows] == [f"title {query} end"]
    assert scrub(rows) is not None
