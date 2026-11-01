"""Source fixtures for the ``/api/import`` contract.

Every builder writes a small export of one tool under the test's temp dir,
with fixed timestamps so previews (``created 2026-01-02``) stay stable.
"""

from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path
from typing import Any

import httpx
from normalize import normalize

UNAUTHORIZED_BODY = {"detail": "Unauthorized — EvoFlux access key required."}

CLAUDE_WEB_CONVERSATIONS = [
    {
        "uuid": "conv-1",
        "name": "Trip plan",
        "created_at": "2026-01-02T10:00:00Z",
        "updated_at": "2026-01-03T10:00:00Z",
        "chat_messages": [
            {
                "sender": "human",
                "text": "Plan a trip",
                "created_at": "2026-01-02T10:00:00Z",
            },
            {
                "sender": "assistant",
                "content": [
                    {"type": "text", "text": "Sure."},
                    {"type": "tool_use", "name": "search"},
                    {"type": "image"},
                ],
                "created_at": "2026-01-02T10:00:05Z",
            },
        ],
    }
]

CLAUDE_WEB_PROJECTS = [
    {
        "name": "Research Hub",
        "instructions": "Be thorough.",
        "documents": [
            {"name": "Notes One", "content": "# Notes\nbody"},
            {"name": "empty", "content": ""},
        ],
    }
]

CHATGPT_CONVERSATIONS = [
    {
        "id": "abc-123",
        "title": "Recipe ideas",
        "create_time": 1767348000.0,
        "update_time": 1767351600.0,
        "mapping": {
            "root": {"children": ["m1"]},
            "m1": {
                "message": {
                    "author": {"role": "user"},
                    "content": {"content_type": "text", "parts": ["Ideas?"]},
                    "create_time": 1767348000.0,
                },
                "children": ["m2"],
            },
            "m2": {
                "message": {
                    "author": {"role": "assistant"},
                    "content": {
                        "content_type": "code",
                        "language": "py",
                        "text": "print(1)",
                    },
                    "create_time": 1767348010.0,
                    "metadata": {"model_slug": "gpt-x"},
                },
                "children": [],
            },
        },
    },
    {"title": "Empty", "create_time": 1767348000.0, "mapping": {}},
]

SECRET = "sk-contract-secret-0000"


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def write_json(path: Path, data: Any) -> Path:
    return write(path, json.dumps(data))


def write_zip(path: Path, members: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data if isinstance(data, str) else json.dumps(data))
    return path


def jsonl(path: Path, rows: list[Any]) -> Path:
    return write(path, "\n".join(json.dumps(row) for row in rows) + "\n")


def mcp_config(server_key: str = "mcpServers") -> dict[str, Any]:
    return {
        server_key: {
            "files": {
                "command": "npx",
                "args": ["files-server"],
                "env": {"API_KEY": SECRET},
                "headers": {"Authorization": f"Bearer {SECRET}"},
                "accessToken": SECRET,
                "nested": {"clientSecret": SECRET, "keep": "yes"},
            },
            "broken": "not-a-dict",
        }
    }


def build_generic_dir(root: Path) -> Path:
    """A loose folder: agent, knowledge note, skill dir, mcp.json and a .env."""
    source = root / "generic-src"
    write(
        source / "agent.md",
        "---\nname: helper-bot\ndescription: Helps out\n---\nDo helpful things.\n",
    )
    write(source / "notes.md", "# Meeting Notes\nKnowledge body.\n")
    write(
        source / "pdf-tools" / "SKILL.md",
        "---\nname: PDF Tools\ndescription: Work with PDFs\n---\nUse pdftk.\n",
    )
    write_json(source / "mcp.json", mcp_config())
    write(source / "keys.env", f"OPENAI_API_KEY={SECRET}\nPLAIN=1\n")
    return source


def build_claude_code_dir(home: Path) -> Path:
    claude = home / ".claude"
    project = claude / "projects" / "my-proj"
    write(project / "CLAUDE.md", "Project rules.")
    jsonl(
        project / "s1.jsonl",
        [
            {"type": "summary", "summary": "skip"},
            {
                "type": "user",
                "uuid": "u1",
                "timestamp": "2026-01-02T09:00:00Z",
                "message": {"role": "user", "content": "Fix the bug\nplease"},
            },
            {
                "type": "assistant",
                "uuid": "a1",
                "timestamp": "2026-01-02T09:00:05Z",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "Looking."},
                        {
                            "type": "tool_use",
                            "id": "t1",
                            "name": "Read",
                            "input": {"path": "a"},
                        },
                    ],
                },
            },
            {
                "type": "user",
                "uuid": "u2",
                "timestamp": "2026-01-02T09:00:06Z",
                "message": {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": "t1", "content": "ok"}
                    ],
                },
            },
        ],
    )
    write(claude / "projects" / "my-proj" / "sessions" / "bad.jsonl", "{oops\n")
    write(claude / "commands" / "review.md", "# Review code\nCheck it.")
    write(
        claude / "skills" / "deploy" / "SKILL.md",
        "---\nname: deploy\ndescription: Ship it\n---\nSteps.",
    )
    write(
        claude / "my-plugin" / "skills" / "deploy" / "SKILL.md",
        "---\nname: deploy\n---\nPlugin deploy.",
    )
    write_json(claude / "my-plugin" / "mcp.json", {"servers": {"plug": {"url": "x"}}})
    write_json(claude / ".mcp.json", mcp_config())
    write_json(claude / "settings.json", {"ANTHROPIC_API_KEY": SECRET})
    write(claude / "plans" / "p.md", "plan")
    return claude


def build_codex_dir(home: Path) -> Path:
    codex = home / ".codex"
    jsonl(
        codex / "sessions" / "2026" / "01" / "02" / "thread-a.jsonl",
        [
            {"type": "session_meta", "payload": {}},
            {
                "type": "response_item",
                "timestamp": "2026-01-02T08:00:00Z",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "Write tests"}],
                },
            },
            {
                "type": "response_item",
                "timestamp": "2026-01-02T08:00:01Z",
                "payload": {
                    "type": "function_call",
                    "call_id": "c1",
                    "name": "shell",
                    "arguments": {"cmd": ["ls"]},
                },
            },
            {
                "type": "response_item",
                "timestamp": "2026-01-02T08:00:02Z",
                "payload": {
                    "type": "function_call_output",
                    "call_id": "c1",
                    "output": "a.txt",
                },
            },
            {
                "type": "event_msg",
                "timestamp": "2026-01-02T08:00:03Z",
                "payload": {"type": "assistant_message", "message": "Done"},
            },
        ],
    )
    write(codex / "instructions.md", "Codex rules.")
    write_json(codex / "config.json", {"model": "o4"})
    write(
        home / ".agents" / "skills" / "lint" / "SKILL.md",
        "---\nname: lint\ndescription: Lint code\n---\nRun ruff.",
    )
    return codex


def build_cursor_dir(root: Path) -> Path:
    workspace = root / "cursor-ws"
    write(
        workspace / ".cursor" / "rules" / "style.mdc",
        "---\ndescription: Style guide\n---\nUse tabs.",
    )
    write(workspace / ".cursor" / "rules" / "plain.mdc", "# Plain rule\nBody")
    write_json(workspace / ".cursor" / "mcp.json", mcp_config("servers"))
    write_json(workspace / ".cursor" / "settings.json", {"theme": "dark"})
    write(workspace / ".cursorrules", "Workspace rules.")
    return workspace


_JOB_ID = re.compile(r"[0-9a-f]{32}")


def by_source_item(body: dict) -> dict:
    """Journal rows of one job share ``created_at`` and are ordered by a random
    id in Python, so their order carries no meaning."""
    return {**body, "items": sorted(body["items"], key=lambda i: i["source_item_id"])}


class Scrub:
    """Replace the run's temp path and import id so snapshots are stable."""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp = str(tmp_path)

    def __call__(self, value: Any, import_id: str | None = None) -> Any:
        def walk(node: Any) -> Any:
            if isinstance(node, dict):
                return {walk(k): walk(v) for k, v in node.items()}
            if isinstance(node, list):
                return [walk(v) for v in node]
            if isinstance(node, str):
                if import_id:
                    node = node.replace(import_id, "<import_id>")
                if _JOB_ID.fullmatch(node):
                    return "<job_id>"
                return node.replace(self.tmp, "<tmp>").replace("\\", "/")
            return node

        return normalize(walk(value))


def detect(client: httpx.Client, path: Path | str, source: str | None = None):
    body: dict[str, Any] = {"path": str(path)}
    if source is not None:
        body["source"] = source
    return client.post("/api/import/detect", json=body)


def detect_ok(client: httpx.Client, path: Path | str, source: str | None = None):
    response = detect(client, path, source)
    assert response.status_code == 200, response.text
    return response.json()
