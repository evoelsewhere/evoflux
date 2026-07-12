# Audit: Code Graph Tools — Final Report

**Date:** 2025-07-13
**Scope:** 7 code graph tools in `app/agent/tools/builtin/code_graph.py`
**Method:** 4 parallel explorers analyzing different tool groups

---

## Executive Summary

Code graph tools có thiết kế core tốt (FTS5 dual path, cross-repo resilience, token-efficient output) nhưng có **23 vấn đề** cần fix: 8 medium, 12 low, 3 design decisions.

### Overall Assessment

| Aspect | Rating | Notes |
|--------|--------|-------|
| Architecture | ⭐⭐⭐⭐ | Well-organized, clear phases |
| Search accuracy | ⭐⭐⭐ | FTS5 + ILIKE dual path works, but edge cases |
| Cross-repo handling | ⭐⭐⭐ | Resilient design, but semantic mismatches |
| Token efficiency | ⭐⭐⭐⭐ | Compact output, good limits |
| Tool descriptions | ⭐⭐ | Inconsistent, some misleading |
| Test coverage | ⭐⭐ | code_map, code_path have no tests |

---

## Issues by Severity

### Medium Issues (8) — Should Fix

| # | Tool | Issue | Impact |
|---|------|-------|--------|
| 1 | code_search | `kind` filter post-FTS blocks ILIKE fallback | Wrong empty results |
| 2 | code_search | FTS 'success' blocks ILIKE fallback | No results when should have |
| 3 | code_search | Cross-repo fallback uses substring, local uses exact | Semantic mismatch |
| 4 | code_map | No `scope` parameter (only tool without it) | Can't filter to workspace |
| 5 | code_map | Ranking is simple in-degree, not PageRank | Misleading description |
| 6 | code_neighbors | Cross-repo renders with wrong arrow direction (← instead of →) | Semantic error |
| 7 | code_path | Docstring mentions 4 edge kinds, BFS uses 6 | Undocumented behavior |
| 8 | code_symbol | Performance: up to 40+ DB queries per call | Slow for large projects |

### Low Issues (12) — Nice to Fix

| # | Tool | Issue |
|---|------|-------|
| 9 | code_search | Single-char queries inconsistent between FTS/ILIKE |
| 10 | code_search | Workspace 'taste' limit undocumented |
| 11 | code_symbol | Multiple matches without disambiguation |
| 12 | code_symbol | Preview duplicates code_neighbors/code_references |
| 13 | code_neighbors | Cross-repo cap hardcoded at 10 |
| 14 | code_neighbors | No sorting by edge kind |
| 15 | code_references | `line` can be None (shows full span) |
| 16 | code_path | N+1 query pattern per BFS depth |
| 17 | code_path | Hop direction rendering confusing |
| 18 | code_overview | No per-language breakdown |
| 19 | code_overview | No cross-repo edge stats |
| 20 | code_overview_injection | Missing 3 tools in resume detection |

### Design Decisions (3)

| # | Issue | Options |
|---|-------|---------|
| 21 | Unresolved cross-repo edges invisible | Add flag or separate tool |
| 22 | `contains` edge asymmetry | Document or change behavior |
| 23 | Consolidate 7 → 4 tools | Major refactor needed |

---

## Top 5 Recommendations

### 1. Fix FTS/ILIKE Fallback (Issues #1, #2, #3)

```python
# code_graph_service.py:916
# Before
if not nodes:
    nodes = await _ilike_search(...)

# After
if not nodes and fts_ids:
    # FTS returned IDs but kind filter removed them
    # Fall back to ILIKE
    nodes = await _ilike_search(...)
elif not nodes:
    nodes = await _ilike_search(...)
```

### 2. Add scope to code_map (Issue #4)

```python
async def _code_map(
    budget: int = 25,
    scope: Literal["workspace", "project"] = "workspace",  # NEW
) -> str: ...
```

### 3. Fix Cross-repo Arrow Direction (Issue #6)

```python
# code_graph.py:469
# Before
rows.append(f"    ← {repo_label}/{loc} ...")

# After
rows.append(f"    → {repo_label}/{loc} ...")  # Outbound tool
```

### 4. Update _REFERENCE_EDGE_KINDS (Issue #5)

```python
# code_graph_service.py:1105
# Before
_REFERENCE_EDGE_KINDS = frozenset({
    'calls', 'references', 'imports', 'inherits', 'implements', 'decorated_by'
})

# After - add missing kinds
_REFERENCE_EDGE_KINDS = frozenset({
    'calls', 'references', 'imports', 'inherits', 'implements', 'decorated_by',
    'uses', 'overrides', 'reads', 'writes', 'throws'
})
```

### 5. Add Tests for code_map and code_path (Issue #20)

Create tests in `tests/services/test_code_graph.py`:
- `test_code_map_ranking`
- `test_code_map_workspace_scope`
- `test_code_path_shortest`
- `test_code_path_same_symbol`

---

## Consolidation Proposal (Issue #23)

### Current: 7 tools, 21+ params

```
code_search     (query, kind, limit, scope)
code_symbol     (name, cross_repo_limit, scope)
code_neighbors  (name, edge_kind, limit, scope)
code_references (name, limit, scope)
code_overview   ()
code_map        (budget)
code_path       (source, target, max_hops)
```

### Proposed: 4 tools, 6 params

```
code_search  (query, scope)        # search + symbol lookup
code_graph   (name, direction)     # neighbors + references
code_overview ()                   # overview + ranking
code_path    (source, target)      # shortest path
```

**Benefits:**
- 43% fewer tools (7 → 4)
- 71% fewer params (21+ → 6)
- Auto-detect scope
- Combined inbound/outbound view

---

## Priority Matrix

| Priority | Effort | Impact | Items |
|----------|--------|--------|-------|
| P0 | Low | High | Fix FTS/ILIKE fallback (#1, #2, #3) |
| P1 | Low | Medium | Add scope to code_map (#4) |
| P2 | Low | Medium | Fix cross-repo arrow (#6) |
| P3 | Medium | Medium | Update _REFERENCE_EDGE_KINDS (#5) |
| P4 | Medium | Low | Add tests (#20) |
| P5 | High | High | Consolidate tools (#23) |

---

## Conclusion

**Code graph tools có foundation tốt nhưng cần polish:**

1. ✅ FTS5 dual path search works well
2. ✅ Cross-repo resilience design is solid
3. ✅ Token-efficient output format
4. ❌ FTS/ILIKE fallback logic has bugs
5. ❌ Inconsistent behavior between tools
6. ❌ Missing tests for code_map/code_path

**Fix P0-P2 items first (low effort, high impact), then consider consolidation.**
