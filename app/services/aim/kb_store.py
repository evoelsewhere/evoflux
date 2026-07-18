"""Read/write access to an AIM project's KB repo — the system of record for
migration-unit state (``documents/research/aim-framework.md`` §3.5/§3.6).

Frontmatter parsing reuses the exact same shape as skills/commands
(``app.agent.tools.builtin.skill._parse_frontmatter``); only the write side
is new here, since skills/commands always rewrite a file's full content
verbatim from client input, while a unit's state is updated field-by-field
(e.g. ``set_phase``) while preserving everything else in the file.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from app.agent.tools.builtin.skill import _parse_frontmatter
from app.services.aim.models import AimManifest, UnitFrontmatter


def _unit_doc_path(kb_root: Path, module: str, name: str) -> Path:
    return kb_root / "modules" / module / f"{name}.md"


def read_manifest(kb_root: Path) -> AimManifest:
    """Parse ``aim.yaml`` at the root of a KB repo."""
    data = yaml.safe_load((kb_root / "aim.yaml").read_text(encoding="utf-8")) or {}
    return AimManifest.model_validate(data)


def write_manifest_phase(kb_root: Path, phase: str) -> None:
    """Update the project-level ``phase`` field in ``aim.yaml``, preserving
    every other key.
    """
    path = kb_root / "aim.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    data["phase"] = phase
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )


_KB_TEMPLATE_DIR = (
    Path(__file__).resolve().parents[3] / "seed" / "aim-kb-template"
)


def scaffold_kb_from_template(kb_root: Path) -> None:
    """Copy ``seed/aim-kb-template/`` into a fresh (or empty) *kb_root*.

    Only fills gaps — an existing file at the target is left untouched,
    same philosophy as ``install_seed`` (app/cli/seed.py).
    """
    import shutil

    kb_root.mkdir(parents=True, exist_ok=True)
    for src in sorted(_KB_TEMPLATE_DIR.rglob("*")):
        if not src.is_file():
            continue
        rel = src.relative_to(_KB_TEMPLATE_DIR)
        target = kb_root / rel
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, target)


def create_manifest(
    kb_root: Path,
    *,
    rulebook_id: str,
    rulebook_version: str,
    source_identities: list[str],
    target_identities: list[str],
    compare_default_profile: str = "default",
) -> None:
    """Write a brand-new ``aim.yaml`` — the shareable project manifest a
    "join existing" teammate reads (identity strings, not local paths).
    """
    data = {
        "rulebook": {"id": rulebook_id, "version": rulebook_version},
        "roles": {"source": source_identities, "target": target_identities},
        "golden_dir": "golden",
        "compare_default_profile": compare_default_profile,
        "phase": "assess",
    }
    (kb_root / "aim.yaml").write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )


def read_unit(kb_root: Path, module: str, name: str) -> tuple[UnitFrontmatter, str] | None:
    """Read a unit's frontmatter + body. ``None`` if the doc doesn't exist yet."""
    path = _unit_doc_path(kb_root, module, name)
    if not path.exists():
        return None
    meta, body = _parse_frontmatter(path.read_text(encoding="utf-8"))
    return UnitFrontmatter.model_validate(meta), body


def write_unit(
    kb_root: Path,
    module: str,
    name: str,
    *,
    kind: str | None = None,
    phase: str | None = None,
    wave: int | None = None,
    assignee: str | None = None,
    source_paths: list[str] | None = None,
    target_paths: list[str] | None = None,
    depends_on: list[str] | None = None,
    complexity: dict | None = None,
    body: str | None = None,
) -> Path:
    """Create or partially update a unit's KB doc.

    Only the fields explicitly passed (non-``None``) change; everything
    else in the file — including the prose body — is preserved. This is
    what lets ``aim_units`` do a narrow update like ``set_phase`` without
    clobbering the module doc `aim-archaeologist` wrote earlier.
    """
    path = _unit_doc_path(kb_root, module, name)
    existing_meta: dict = {}
    existing_body = ""
    if path.exists():
        existing_meta, existing_body = _parse_frontmatter(
            path.read_text(encoding="utf-8")
        )

    merged = dict(existing_meta)
    updates = {
        "kind": kind,
        "phase": phase,
        "wave": wave,
        "assignee": assignee,
        "source_paths": source_paths,
        "target_paths": target_paths,
        "depends_on": depends_on,
        "complexity": complexity,
    }
    for key, value in updates.items():
        if value is not None:
            merged[key] = value
    merged.setdefault("kind", "unknown")
    merged.setdefault("phase", "inventory")

    final_body = body if body is not None else existing_body
    frontmatter_yaml = yaml.safe_dump(
        merged, sort_keys=False, allow_unicode=True
    ).strip()
    content = f"---\n{frontmatter_yaml}\n---\n\n{final_body}\n".rstrip() + "\n"

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def list_units(
    kb_root: Path,
) -> list[tuple[str, str, UnitFrontmatter, str]]:
    """Walk ``modules/**/*.md`` — yields ``(module, name, frontmatter, doc_path_rel)``.

    Files with no parseable ``UnitFrontmatter`` (missing ``kind``, stray
    non-unit markdown) are skipped rather than raising — a reindex should
    degrade gracefully on an in-progress or malformed doc, not abort.
    """
    modules_dir = kb_root / "modules"
    if not modules_dir.is_dir():
        return []
    results: list[tuple[str, str, UnitFrontmatter, str]] = []
    for module_dir in sorted(p for p in modules_dir.iterdir() if p.is_dir()):
        for doc_path in sorted(module_dir.glob("*.md")):
            meta, _ = _parse_frontmatter(doc_path.read_text(encoding="utf-8"))
            if not meta:
                continue
            try:
                frontmatter = UnitFrontmatter.model_validate(meta)
            except ValidationError:
                continue
            rel = doc_path.relative_to(kb_root).as_posix()
            results.append((module_dir.name, doc_path.stem, frontmatter, rel))
    return results
