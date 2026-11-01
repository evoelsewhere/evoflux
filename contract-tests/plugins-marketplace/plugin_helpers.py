"""Builders and constants for the ``/api/plugins`` contract."""

from __future__ import annotations

import io
import json
import re
import shutil
import sys
import time
import zipfile
from pathlib import Path
from typing import Any

UNAUTHORIZED_BODY = {"detail": "Unauthorized — EvoFlux access key required."}
PLUGIN_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
MCP_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"
HERE = Path(__file__).parent
FAKE_SERVER = HERE / "fake_mcp_server.py"
PYTHON_NAME = Path(sys.executable).name
ID = "0" * 32
PREVIEW = "a" * 32
SOURCE = "b" * 16


def skill_md(name: str, description: str = "Does a thing.") -> str:
    return f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n\nSteps.\n"


def write_plugin(
    root: Path,
    name: str = "demo",
    *,
    version: str | None = "1.0.0",
    skills: tuple[str, ...] = (),
    mcp: dict[str, Any] | None = None,
    manifest_extra: dict[str, Any] | None = None,
    files: dict[str, str | bytes] | None = None,
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {"$schema": PLUGIN_SCHEMA, "name": name}
    if version:
        manifest["version"] = version
    manifest["description"] = f"The {name} plugin."
    manifest.update(manifest_extra or {})
    (root / "plugin.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    for skill in skills:
        directory = root / "skills" / skill
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "SKILL.md").write_text(
            skill_md(skill), encoding="utf-8", newline=""
        )
    if mcp is not None:
        (root / "mcp.json").write_text(
            json.dumps({"$schema": MCP_SCHEMA, "mcpServers": mcp}, indent=2) + "\n",
            encoding="utf-8",
        )
    for relative, content in (files or {}).items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content, encoding="utf-8", newline="")
    return root


def stdio_server(**extra: Any) -> dict[str, Any]:
    """An ``mcp.json`` stdio entry that runs the fake server copied into the plugin."""
    return {
        "type": "stdio",
        "command": PYTHON_NAME,
        "args": ["fake_mcp_server.py"],
        **extra,
    }


def write_mcp_plugin(root: Path, name: str = "mcpdemo", **server: Any) -> Path:
    write_plugin(root, name, mcp={"fake": stdio_server(**server)})
    shutil.copyfile(FAKE_SERVER, root / "fake_mcp_server.py")
    return root


def zip_dir(source: Path, target: Path, *, prefix: str = "") -> Path:
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                archive.write(path, prefix + path.relative_to(source).as_posix())
    return target


def zip_bytes(entries: dict[str, str | bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def tree(root: Path) -> dict[str, bytes | None]:
    found: dict[str, bytes | None] = {}
    if not root.exists():
        return found
    for path in sorted(root.rglob("*")):
        found[path.relative_to(root).as_posix()] = (
            path.read_bytes() if path.is_file() else None
        )
    return found


class Scrub:
    """Replace the temp dir in JSON-able values and fold path separators."""

    def __init__(self, tmp: Path) -> None:
        self._roots = {str(tmp), str(tmp.resolve())}

    def text(self, value: str) -> str:
        for root in self._roots:
            pattern = re.escape(root) + r"[^\s'\"<>|?*:]*"
            value = re.sub(
                pattern,
                lambda m: m.group(0).replace(root, "<tmp>").replace("\\", "/"),
                value,
            )
        return re.sub(r"\b[0-9a-f]{32}\b", "<id32>", value)

    def __call__(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, list):
            return [self(item) for item in value]
        if isinstance(value, dict):
            return {key: self(item) for key, item in value.items()}
        return value


def wait_for(predicate, timeout: float = 30.0, interval: float = 0.25):
    deadline = time.monotonic() + timeout
    value = predicate()
    while not value and time.monotonic() < deadline:
        time.sleep(interval)
        value = predicate()
    return value


def install(
    client, path: Path, *, mode: str = "install", enabled: bool = False
) -> dict:
    response = client.post(
        "/api/plugins/install",
        json={"path": str(path), "mode": mode, "enabled": enabled},
    )
    assert response.status_code == 201, response.text
    return response.json()


def servers(client) -> dict[str, dict]:
    response = client.get("/api/plugins")
    assert response.status_code == 200, response.text
    return {item["server_name"]: item for item in response.json()["mcp_servers"]}
