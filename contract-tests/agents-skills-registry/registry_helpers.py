"""Shared builders for the ``/api/agents`` and ``/api/skills`` contract.

Every path the API returns lives under the test's temp dir, so ``Scrub`` turns
it into ``<tmp>`` (with ``/`` separators) before anything is compared.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

UNAUTHORIZED_BODY = {"detail": "Unauthorized — EvoFlux access key required."}

SKILL_BODY = "Follow the steps.\n"

#: Every route of the unit as (method, path, JSON body). The bodies are valid,
#: so a 401 proves authentication runs before anything else.
ROUTES: list[tuple[str, str, object]] = [
    ("GET", "/api/agents", None),
    ("GET", "/api/agents/registry", None),
    ("GET", "/api/agents/explorer", None),
    ("GET", "/api/agents/coding/coder", None),
    ("POST", "/api/agents", {"name": "x", "content": "---\nname: x\n---\nx"}),
    ("PUT", "/api/agents/x", {"name": "x", "content": "---\nname: x\n---\nx"}),
    ("DELETE", "/api/agents/x", None),
    ("PATCH", "/api/agents/model", {"names": ["x"], "model": "a:b"}),
    ("PATCH", "/api/agents/runtime-model/x", {"model": None}),
    ("PATCH", "/api/agents/runtime-settings/x", {}),
    ("GET", "/api/skills", None),
    ("GET", "/api/skills/x", None),
    ("POST", "/api/skills", {"name": "x", "content": "x"}),
    ("PUT", "/api/skills/x", {"content": "x"}),
    ("PATCH", "/api/skills/x", {"enabled": False}),
    ("DELETE", "/api/skills/x", None),
]


def skill_md(
    name: str,
    description: str = "Does a thing.",
    body: str = SKILL_BODY,
    extra: str = "",
) -> str:
    return f"---\nname: {name}\ndescription: {description}\n{extra}---\n\n{body}"


def agent_md(name: str, *, role: str = "member", extra: str = "", body: str = "x\n") -> str:
    return f"---\nname: {name}\nrole: {role}\n{extra}---\n{body}"


def write_skill(root: Path, name: str, text: str | None = None, **files: str) -> Path:
    """Create ``<root>/<name>/SKILL.md`` (and bundle files) the way a user would."""
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "SKILL.md").write_text(
        skill_md(name) if text is None else text, encoding="utf-8", newline=""
    )
    for relative, content in files.items():
        target = directory / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="")
    return directory


def tree(root: Path) -> dict[str, bytes | None]:
    """Every file (bytes) and directory (``None``) below ``root``, POSIX keys."""
    found: dict[str, bytes | None] = {}
    if not root.exists():
        return found
    for path in sorted(root.rglob("*")):
        key = path.relative_to(root).as_posix()
        found[key] = path.read_bytes() if path.is_file() else None
    return found


def lf(data: bytes) -> bytes:
    """The bytes Python writes on POSIX.

    ``agent_fs._atomic_write``, ``skill_settings._atomic_write`` and
    ``agent_settings._atomic_write`` open the temp file in text mode without
    ``newline=""``, so on Windows ``\n`` is written as ``\r\n``. Folding
    ``\r\n`` back to ``\n`` gives the POSIX bytes (``\r\r\n`` from CRLF input
    folds to the input's own ``\r\n``).
    """
    return data.replace(b"\r\n", b"\n") if os.name == "nt" else data


def agent_settings_id(project_id: str, resource_id: str, agent: str) -> str:
    material = f"{project_id}\0{resource_id}\0{agent}".encode("utf-8")
    return f"agent_{hashlib.sha256(material).hexdigest()[:32]}"


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
        return value

    def __call__(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, list):
            return [self(item) for item in value]
        if isinstance(value, dict):
            return {key: self(item) for key, item in value.items()}
        return value


def managed_state(
    state_dir: Path,
    config_dir: Path,
    *,
    agent_targets: list[str] = (),  # type: ignore[assignment]
    skills: list[str] = (),  # type: ignore[assignment]
) -> None:
    """Make Conductor own ``agent_targets`` (one team) and ``skills`` (one each).

    Provenance is read from ``settings.yaml`` (``conductor.project_id``) and
    ``<state>/conductor/managed-resources-v2.json`` on every request.
    """
    settings = config_dir / "settings.yaml"
    settings.write_text(
        settings.read_text(encoding="utf-8")
        + "\nconductor:\n  project_id: proj-1\n  project_name: Acme\n",
        encoding="utf-8",
    )
    stamp = "2026-01-01T00:00:00Z"
    resources: list[dict[str, Any]] = []
    if agent_targets:
        resources.append(
            {
                "project_id": "proj-1",
                "resource_id": "res-team",
                "kind": "agent_team",
                "slug": "team",
                "observed_state": "applied",
                "observed_at": stamp,
                "local_agent_targets": list(agent_targets),
                "version": "1.0.0",
                "version_id": "v1",
            }
        )
    for index, name in enumerate(skills):
        resources.append(
            {
                "project_id": "proj-1",
                "resource_id": f"res-skill-{index}",
                "kind": "skill",
                "slug": name,
                "observed_state": "applied",
                "observed_at": stamp,
            }
        )
    target = state_dir / "conductor"
    target.mkdir(parents=True, exist_ok=True)
    (target / "managed-resources-v2.json").write_text(
        json.dumps({"project_id": "proj-1", "resources": resources}), encoding="utf-8"
    )
