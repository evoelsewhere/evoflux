"""Prompt-snippet discovery and rendering for coding workspaces.

Snippets are markdown files with optional YAML frontmatter:

    ---
    description: One-line description shown in the picker
    ---

    Body becomes the inserted prompt snippet.

Discovery walks EvoFlux-native snippet roots in precedence order — first hit
wins on a name collision:

    1. ``{workspace}/.EvoFlux/snippets/``      (project; coding mode only)
    2. ``{EVOFLUX_CONFIG_DIR}/snippets/``      (global)

Nested folders are honoured one level deep: ``snippets/git/commit.md`` registers
as ``git/commit``.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.core.config import settings
from app.services.commands import _iter_md, _md_tree_signature, _parse_frontmatter


@dataclass(frozen=True)
class Snippet:
    """A discovered prompt snippet."""

    name: str
    description: str
    body: str
    path: Path
    source: str  # one of: project-EvoFlux / global-EvoFlux


def _candidate_roots(workspace: Path) -> list[tuple[Path, str]]:
    config = Path(settings.EVOFLUX_CONFIG_DIR)
    return [
        (workspace / ".EvoFlux" / "snippets", "project-EvoFlux"),
        (config / "snippets", "global-EvoFlux"),
    ]


def discover_snippets(workspace: Path) -> dict[str, Snippet]:
    """Return ``{name: Snippet}`` for snippets available to *workspace*.

    Uses an mtime-keyed cache (same pattern as command/skill discovery) so
    repeated picker requests skip the walk + read + YAML parse when nothing
    changed.
    """
    roots = tuple((str(root), source) for root, source in _candidate_roots(workspace))
    signature = tuple(_md_tree_signature(Path(root)) for root, _ in roots)
    return _discover_snippets_cached(roots, signature)


@lru_cache(maxsize=16)
def _discover_snippets_cached(
    roots: tuple[tuple[str, str], ...], signature: tuple[int, ...]
) -> dict[str, Snippet]:
    snippets: dict[str, Snippet] = {}
    for root_str, source in roots:
        for path, name in _iter_md(Path(root_str)):
            if name in snippets:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            meta, body = _parse_frontmatter(text)
            description = meta.get("description", "")
            if not isinstance(description, str):
                description = ""
            snippets[name] = Snippet(
                name=name,
                description=description.strip(),
                body=body,
                path=path,
                source=source,
            )
    return snippets
