"""Tests for cross-repo candidate generation in the indexer.

An edge that fails to resolve *within* a workspace is either dropped (dead
reference/typo), kept as an ``AmbiguousEdge`` (2+ local candidates), or —
for a precise subset of edge kinds — kept as an ``UnresolvedReference`` so
the service layer can offer it up for cross-repo resolution against a
sibling repo in the same project. See ``_CROSS_REPO_CANDIDATE_KINDS`` in
``app/services/code_graph/indexer.py``.
"""

from __future__ import annotations

from pathlib import Path

from app.services.code_graph.indexer import index_workspace


def _write(root: Path, rel_path: str, content: str) -> None:
    path = root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_unresolved_uses_edge_becomes_cross_repo_candidate(tmp_path: Path) -> None:
    """A DI-wired field with no local definition is a plausible cross-repo
    reference, not a typo — it must survive as an UnresolvedReference."""
    _write(
        tmp_path,
        "ConceptResource.java",
        "public class ConceptResource {\n"
        "    private final ConceptService conceptService;\n"
        "    public ConceptResource(ConceptService conceptService) {\n"
        "        this.conceptService = conceptService;\n"
        "    }\n"
        "}\n",
    )

    idx = index_workspace(tmp_path)

    refs = [u for u in idx.unresolved_references if u.kind == "uses"]
    assert len(refs) == 1
    assert refs[0].raw_reference == "ConceptService"
    assert refs[0].dst_name_hint == "ConceptService"
    assert idx.ambiguous_edges == []


def test_inherits_and_implements_become_cross_repo_candidates(tmp_path: Path) -> None:
    """An undefined supertype/interface is likely defined in a sibling repo."""
    _write(
        tmp_path,
        "ConceptResource.java",
        "public class ConceptResource extends BaseResource implements Handler {\n"
        "}\n",
    )

    idx = index_workspace(tmp_path)

    kinds_and_names = {
        (u.kind, u.raw_reference) for u in idx.unresolved_references
    }
    assert ("inherits", "BaseResource") in kinds_and_names
    assert ("implements", "Handler") in kinds_and_names


def test_ambiguous_uses_edge_is_not_a_cross_repo_candidate(tmp_path: Path) -> None:
    """2+ local candidates for the same name is same-workspace ambiguity —
    it must go to ambiguous_edges, not unresolved_references, since the
    target very much does exist locally (just not uniquely)."""
    _write(tmp_path, "one/ConceptService.java", "public class ConceptService {}\n")
    _write(tmp_path, "two/ConceptService.java", "public class ConceptService {}\n")
    _write(
        tmp_path,
        "ConceptResource.java",
        "public class ConceptResource {\n"
        "    private final ConceptService conceptService;\n"
        "    public ConceptResource(ConceptService conceptService) {\n"
        "        this.conceptService = conceptService;\n"
        "    }\n"
        "}\n",
    )

    idx = index_workspace(tmp_path)

    assert any(a.dst_name == "ConceptService" for a in idx.ambiguous_edges)
    assert all(u.raw_reference != "ConceptService" for u in idx.unresolved_references)


def test_unresolved_call_and_reference_edges_are_still_dropped(tmp_path: Path) -> None:
    """EDGE_CALLS/EDGE_REFERENCES are deliberately excluded from cross-repo
    candidate generation (too high-volume/low-precision without receiver-type
    inference) — this locks in that scope boundary against silent expansion."""
    _write(
        tmp_path,
        "ConceptResource.java",
        "public class ConceptResource {\n"
        "    public Concept getConcept(String id) {\n"
        "        return conceptService.getConcept(id);\n"
        "    }\n"
        "}\n",
    )

    idx = index_workspace(tmp_path)

    assert idx.unresolved_references == []
    assert idx.ambiguous_edges == []
