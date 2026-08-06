"""Source attachment for exact graph roots and relationship call sites."""

from __future__ import annotations

from dataclasses import replace

from app.services.code_intelligence.models import GraphRelation, SymbolMatch

_ROOT_SOURCE_BUDGET = 20_000
_CALLSITE_SOURCE_BUDGET = 10_000
_CALLSITE_RADIUS = 1


def _safe_lines(match: SymbolMatch, file_path: str) -> list[str] | None:
    try:
        candidate = (match.scope.root / file_path).resolve()
        if match.scope.root != candidate and match.scope.root not in candidate.parents:
            return None
        return candidate.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None


def _numbered_range(lines: list[str], first: int, last: int) -> str:
    first = max(1, first)
    last = min(len(lines), max(first, last))
    return "\n".join(
        f"{number:>5} | {lines[number - 1]}" for number in range(first, last + 1)
    )


def attach_source(
    matches: tuple[SymbolMatch, ...],
    relations: list[GraphRelation],
) -> tuple[list[SymbolMatch], list[GraphRelation], list[str], bool]:
    """Attach complete root definitions and compact call-site windows.

    Graph navigation is intentionally concise: neighbor definitions are not
    dumped into the result.  The relationship gives the exact symbol and call
    site; a follow-up graph call can navigate that neighbor if its body matters.
    """
    root_remaining = _ROOT_SOURCE_BUDGET
    rendered_matches: list[SymbolMatch] = []
    missing: list[str] = []
    truncated = False
    for match in matches:
        lines = _safe_lines(match, match.node.file_path)
        source = (
            _numbered_range(lines, match.node.line_start, match.node.line_end)
            if lines is not None
            else None
        )
        if source is None:
            missing.append(
                f"{match.scope.label}/{match.node.file_path}:"
                f"{match.node.line_start}-{match.node.line_end}"
            )
        elif len(source) > root_remaining:
            source = None
            truncated = True
            missing.append(
                f"{match.scope.label}/{match.node.file_path}:"
                f"{match.node.line_start}-{match.node.line_end}"
            )
        else:
            root_remaining -= len(source)
        rendered_matches.append(replace(match, source=source))

    callsite_remaining = _CALLSITE_SOURCE_BUDGET
    rendered_relations: list[GraphRelation] = []
    cached_windows: dict[tuple[str, str, int], str | None] = {}
    for relation in relations:
        key = (
            str(relation.source.scope.workspace_id),
            relation.callsite_file,
            relation.callsite_line,
        )
        if key not in cached_windows:
            lines = _safe_lines(relation.source, relation.callsite_file)
            cached_windows[key] = (
                _numbered_range(
                    lines,
                    relation.callsite_line - _CALLSITE_RADIUS,
                    relation.callsite_line + _CALLSITE_RADIUS,
                )
                if lines is not None
                else None
            )
        window = cached_windows[key]
        if window is not None and len(window) <= callsite_remaining:
            callsite_remaining -= len(window)
        else:
            window = None
            truncated = True
        rendered_relations.append(replace(relation, callsite_source=window))
    return rendered_matches, rendered_relations, list(dict.fromkeys(missing)), truncated
