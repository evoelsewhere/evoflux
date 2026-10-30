"""Build the v3.x upgrade fixtures under ``fixtures/upgrade/<tag>/``.

For every tag: ``git worktree add`` outside the repository, ``uv sync``, start
that tag's ``serve`` with the contract harness, seed it through its public HTTP
API, stop it, checkpoint the WAL and copy the database and config directory.

    uv run python contract-tests/fixtures/build_upgrade_fixtures.py [--tag v3.1.1 ...]

With no ``--tag`` it builds only v3.0.0, the one committed fixture (the oldest
schema, so it exercises the full migration path). Any of the 13 tags can be built.

Messages are seeded with the user shell command (``shell=true`` chat), which
runs no model, so no provider or network is involved. Secrets are dummy values.
"""

from __future__ import annotations

import argparse
from contextlib import closing
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from backends import REPO_ROOT, start_backend  # noqa: E402

TAGS = [f"v3.0.{n}" for n in range(11)] + ["v3.1.0", "v3.1.1"]
DEFAULT_TAGS = ["v3.0.0"]
FIXTURE_DIR = HERE / "upgrade"
WORKTREE_ROOT = Path(r"D:\evoelsewhere\.tmp-upgrade-tags")
MAX_DB_BYTES = 2 * 1024 * 1024
DUMMY_API_KEY = "sk-dummy-upgrade-fixture-0000"
MESSAGE_TIMEOUT_S = 60.0


def _venv_python(tree: Path) -> str:
    sub = "Scripts/python.exe" if sys.platform == "win32" else "bin/python"
    return str(tree / ".venv" / sub)


def _prepare_worktree(tag: str) -> Path:
    tree = WORKTREE_ROOT / tag
    if not tree.exists():
        WORKTREE_ROOT.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "worktree", "add", "--detach", str(tree), tag],
            cwd=REPO_ROOT,
            check=True,
        )
    subprocess.run(["uv", "sync"], cwd=tree, check=True)
    return tree


def _remove_worktree(tag: str) -> None:
    tree = WORKTREE_ROOT / tag
    if tree.exists():
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(tree)],
            cwd=REPO_ROOT,
            check=False,
        )


def _shell_session(
    client: httpx.Client, command: str, expected_output: str, **fields: str
) -> str:
    """Send a user shell command and wait until its output is in the history."""
    data = {"message": command, "shell": "true", **fields}
    response = client.post("/api/team/chat", data=data)
    response.raise_for_status()
    session_id = response.json()["session_id"]
    deadline = time.monotonic() + MESSAGE_TIMEOUT_S
    while time.monotonic() < deadline:
        history = client.get(f"/api/team/{session_id}/history")
        if history.status_code == 200 and expected_output in history.text:
            return session_id
        time.sleep(0.5)
    raise RuntimeError(f"no shell output for session {session_id}: {history.text}")


def _seed(client: httpx.Client, workspace: Path) -> dict:
    created: dict = {"sessions": [], "coding_sessions": []}
    for n in (1, 2):
        marker = f"fixture-work-{n}"
        created["sessions"].append(
            _shell_session(client, f"echo {marker}", marker, mode="work")
        )

    project = client.post(
        "/api/team/projects",
        json={"name": "Fixture project", "workspace_paths": [str(workspace)]},
    )
    project.raise_for_status()
    project_id = project.json()["id"]
    created["project"] = project_id
    created["coding_sessions"].append(
        _shell_session(
            client,
            "echo fixture-coding-1",
            "fixture-coding-1",
            mode="coding",
            project_id=project_id,
        )
    )

    task = client.post(
        "/api/scheduler/tasks",
        json={
            "name": "fixture-task",
            "prompt": "Summarise the fixture workspace.",
            "schedule_type": "every",
            "every_seconds": 86400,
            "enabled": False,
        },
    )
    task.raise_for_status()
    created["scheduler_task"] = task.json().get("id") or task.json().get("name")

    for path, body in (
        (
            "topics/fixture-wiki.md",
            "# Fixture wiki page\n\nSeeded for upgrade tests.\n",
        ),
        ("notes/fixture-memory.md", "# Fixture memory\n\nRemember the fixture.\n"),
    ):
        client.put(
            "/api/wiki/file", json={"path": path, "content": body}
        ).raise_for_status()
    created["wiki"] = ["topics/fixture-wiki.md", "notes/fixture-memory.md"]

    skills = client.get("/api/skills")
    skills.raise_for_status()
    items = skills.json()
    items = items.get("skills", items) if isinstance(items, dict) else items
    skill = items[0]["name"]
    client.patch(f"/api/skills/{skill}", json={"enabled": False}).raise_for_status()
    created["skill_disabled"] = skill

    secret = client.put(
        "/api/settings/providers/openai", json={"api_key": DUMMY_API_KEY}
    )
    created["dummy_provider_key_saved"] = secret.status_code < 300
    return created


def _checkpoint(db: Path) -> None:
    """Fold the WAL into the database; retry while the stopped backend lets go."""
    for attempt in range(15):
        try:
            with closing(sqlite3.connect(db)) as conn:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            return
        except sqlite3.OperationalError:
            if attempt == 14:
                raise
            time.sleep(1.0)


def _scrub_paths(db: Path, root: Path) -> None:
    """Replace the machine-specific temp root with ``/fixture`` in every text column."""
    variants = {
        str(root),
        str(root).replace("\\", "\\\\"),
        root.as_posix(),
        str(root).replace("\\", "/"),
    }
    with closing(sqlite3.connect(db)) as conn:
        for (table,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall():
            columns = [
                c[1]
                for c in conn.execute(f'PRAGMA table_info("{table}")')
                if "CHAR" in c[2].upper()
                or "TEXT" in c[2].upper()
                or "JSON" in c[2].upper()
            ]
            for column in columns:
                for variant in sorted(variants, key=len, reverse=True):
                    conn.execute(
                        f'UPDATE "{table}" SET "{column}" = replace("{column}", ?, ?) '
                        f'WHERE "{column}" LIKE ?',
                        (variant, "/fixture", f"%{variant}%"),
                    )
        conn.commit()
        conn.execute("VACUUM")  # drops the old paths from free pages
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("integrity_check failed after path scrub")


def _row_counts(db: Path) -> tuple[dict[str, int], str]:
    with closing(sqlite3.connect(db)) as conn:
        tables = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        counts = {
            t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            for t in sorted(tables)
            if t != "alembic_version"
        }
        revision = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    return counts, revision


def build_tag(tag: str, *, keep_worktree: bool = False) -> Path:
    tree = _prepare_worktree(tag)
    out = FIXTURE_DIR / tag
    try:
        with tempfile.TemporaryDirectory(prefix=f"evoflux-fixture-{tag}-") as tmp:
            tmp_path = Path(tmp)
            workspace = tmp_path / "project-repo"
            workspace.mkdir()
            backend = start_backend(
                "python",
                tmp_path,
                source_root=tree,
                python=_venv_python(tree),
            )
            try:
                with httpx.Client(
                    base_url=backend.base_url,
                    headers={"Authorization": f"Bearer {backend.token}"},
                    timeout=30.0,
                ) as client:
                    created = _seed(client, workspace)
                    listed = client.get("/api/team/sessions").json()
                    text = json.dumps(listed)
                    missing = [
                        s
                        for s in created["sessions"] + created["coding_sessions"]
                        if s not in text
                    ]
                    if missing:
                        raise RuntimeError(f"{tag}: sessions not listed: {missing}")
            finally:
                backend.stop()
            db = tmp_path / "data" / "evoflux.db"
            _checkpoint(db)
            _scrub_paths(db, tmp_path)
            counts, revision = _row_counts(db)
            leaked = (tmp_path.name.encode(), Path.home().name.encode())
            if any(item in db.read_bytes() for item in leaked):
                raise RuntimeError(f"{tag}: machine-specific path left in evoflux.db")
            if db.stat().st_size > MAX_DB_BYTES:
                raise RuntimeError(f"{tag}: evoflux.db is {db.stat().st_size} bytes")
            if out.exists():
                shutil.rmtree(out)
            out.mkdir(parents=True)
            shutil.copyfile(db, out / "evoflux.db")
            config = tmp_path / "config"
            shutil.copytree(
                config, out / "config", ignore=shutil.ignore_patterns("*.lock")
            )
            wiki = tmp_path / "wiki"
            if wiki.exists():
                shutil.copytree(
                    wiki, out / "wiki", ignore=shutil.ignore_patterns("*.lock")
                )
            manifest = {
                "tag": tag,
                "alembic_revision": revision,
                "row_counts": counts,
                "created_ids": created,
            }
            (out / "MANIFEST.json").write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
                newline="\n",
            )
    finally:
        if not keep_worktree:
            _remove_worktree(tag)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", action="append", choices=TAGS)
    parser.add_argument("--keep-worktrees", action="store_true")
    args = parser.parse_args()
    for tag in args.tag or DEFAULT_TAGS:
        print(f"== {tag}", flush=True)
        build_tag(tag, keep_worktree=args.keep_worktrees)


if __name__ == "__main__":
    main()
