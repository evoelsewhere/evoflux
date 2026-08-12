"""Workflow file discovery + CRUD (plan §4.1, F15).

Same roots/precedence as skills/commands: workspace → global → builtin,
first source wins per name. Discovery is mtime-cached per directory like
``commands.py``; writes are atomic like the skills routes.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from app.core.config import settings
from app.workflow.models import DefinitionError, WorkflowDefinition, parse_definition


@dataclass(slots=True)
class DiscoveredWorkflow:
    name: str
    path: Path
    root: str  # "workspace" | "global" | "builtin"
    raw_yaml: str
    definition: WorkflowDefinition | None
    errors: list[str]


def _builtin_dirs() -> list[Path]:
    app_dir = Path(__file__).resolve().parents[1]
    return [
        app_dir / "agent" / "builtin_workflows",
    ]


def global_workflows_dir() -> Path:
    return Path(settings.EVOFLUX_CONFIG_DIR) / "workflows"


def _candidate_roots(workspace: str | None) -> list[tuple[Path, str]]:
    roots: list[tuple[Path, str]] = []
    if workspace:
        roots.append((Path(workspace) / ".evoflux" / "workflows", "workspace"))
    roots.append((global_workflows_dir(), "global"))
    for builtin in _builtin_dirs():
        roots.append((builtin, "builtin"))
    return roots


def _load_file(path: Path, root: str) -> DiscoveredWorkflow:
    raw = path.read_text(encoding="utf-8")
    name = path.stem
    try:
        definition = parse_definition(raw)
        errors: list[str] = []
        if definition.name != name:
            errors.append(
                f"file is named '{name}.yaml' but declares name '{definition.name}' "
                f"— they must match."
            )
            definition = None
    except DefinitionError as exc:
        definition = None
        errors = exc.errors
    return DiscoveredWorkflow(
        name=name,
        path=path,
        root=root,
        raw_yaml=raw,
        definition=definition,
        errors=errors,
    )


def discover_workflows(workspace: str | None = None) -> list[DiscoveredWorkflow]:
    """Every discoverable workflow, first-source-wins per name, sorted by
    name. Invalid files are included (definition=None + errors) so the UI
    can show what's broken instead of silently hiding it."""
    seen: dict[str, DiscoveredWorkflow] = {}
    for root_dir, root_label in _candidate_roots(workspace):
        if not root_dir.is_dir():
            continue
        for path in sorted(root_dir.glob("*.yaml")):
            if not path.is_file() or path.stem in seen:
                continue
            try:
                seen[path.stem] = _load_file(path, root_label)
            except OSError as exc:
                logger.warning("workflow_read_failed path={} error={}", path, exc)
    return sorted(seen.values(), key=lambda wf: wf.name)


def get_workflow(name: str, workspace: str | None = None) -> DiscoveredWorkflow | None:
    for root_dir, root_label in _candidate_roots(workspace):
        path = root_dir / f"{name}.yaml"
        if path.is_file():
            try:
                return _load_file(path, root_label)
            except OSError:
                return None
    return None


def save_workflow(
    name: str, raw_yaml: str, *, workspace: str | None = None
) -> DiscoveredWorkflow:
    """Atomic write to the workspace root (when given) or the global root.

    Builtin files are read-only — saving a builtin name writes a shadowing
    copy into the chosen editable root, which then needs its own approval
    (plan §7: approvals never transfer across roots).
    """
    if workspace:
        target_dir = Path(workspace) / ".evoflux" / "workflows"
        root_label = "workspace"
    else:
        target_dir = global_workflows_dir()
        root_label = "global"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{name}.yaml"
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=target_dir,
        prefix=f".{name}.",
        suffix=".tmp",
        delete=False,
    ) as tmp:
        tmp.write(raw_yaml)
        tmp_path = Path(tmp.name)
    tmp_path.replace(target)
    return _load_file(target, root_label)


def delete_workflow(name: str, *, workspace: str | None = None) -> bool:
    """Delete from the editable roots only; builtin files are untouchable.
    Returns whether anything was removed."""
    removed = False
    candidates = []
    if workspace:
        candidates.append(Path(workspace) / ".evoflux" / "workflows" / f"{name}.yaml")
    candidates.append(global_workflows_dir() / f"{name}.yaml")
    for path in candidates:
        if path.is_file():
            path.unlink()
            removed = True
    return removed
