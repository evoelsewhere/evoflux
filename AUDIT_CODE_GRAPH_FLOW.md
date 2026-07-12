# Audit: Code Graph & Cross-Repo Flow

## Executive Summary

Code Graph và Cross-Repo là 2 features phức tạp nhất trong EvoFlux. Cả 2 đều chạy hoàn toàn trên Python backend, không có Rust/Tauri native implementation.

---

## 1. Code Graph Architecture

### Flow hiện tại

```
User clicks "Build index" → API call → Python indexer → SQLite DB → Frontend queries
```

### Components

| Component | Location | Mô tả |
|-----------|----------|-------|
| **Indexer** | `app/services/code_graph/indexer.py` | Parse code, build symbol graph |
| **Manifest** | `app/services/code_graph/manifest.py` (70KB!) | Parse package.json, requirements.txt, etc. |
| **FTS Store** | `app/services/code_graph/fts_store.py` | Full-text search index |
| **Watcher** | `app/services/code_graph/watcher.py` | Auto-reindex on file changes |
| **Cross-Repo** | `app/services/code_graph/cross_repo.py` | Multi-repo resolution |
| **API Routes** | `app/api/routes/code_graph.py` | HTTP endpoints |
| **Frontend** | `web/src/components/CodeGraphPanel.tsx` | UI panel |

### Code Graph Flow

```
1. User clicks "Build index"
2. Frontend: POST /api/code-graph/{workspace}/reindex
3. Backend: indexer.index_workspace()
   - Walk files (skip .git, node_modules)
   - Parse with tree-sitter (Python, TS, JS, Rust, Go, etc.)
   - Extract: functions, classes, methods, variables, imports
   - Build edges: calls, imports, inherits
4. Save to SQLite: code_nodes, code_edges tables
5. Build FTS5 index for search
6. Frontend polls status until complete
7. User can search symbols
```

### Issues identified

1. **No Rust native implementation** - All parsing runs in Python (CPU-bound)
2. **Large manifest.py (70KB)** - Complex dependency parsing logic
3. **Watcher still HTTP-based** - `CodeGraphWatcher` uses Python's watchdog
4. **No Tauri integration** - Code graph is separate from native file system

---

## 2. Cross-Repo Architecture

### Flow hiện tại

```
Multi-repo project → Index each repo → Static matching → FTS5 matching → Result
```

### Components

| Component | Location | Mô tả |
|-----------|----------|-------|
| **Cross-Repo Resolver** | `app/services/code_graph/cross_repo.py` | Main resolution logic |
| **LLM Fallback** | `app/services/code_graph/cross_repo_llm.py` | LLM-based matching (removed) |
| **Jobs** | `app/services/code_graph/cross_repo_jobs.py` | Background job management |
| **Path Resolve** | `app/services/code_graph/path_resolve.py` | Import path resolution |
| **Frontend** | `web/src/components/CrossRepoLinksPanel.tsx` | UI panel |
| **Graph Modal** | `web/src/components/RepoGraphModal.tsx` | Full-screen graph view |

### Cross-Repo Resolution Flow

```
1. User has multi-repo project (e.g. frontend + backend)
2. Click "Build index" in CrossRepoLinksPanel
3. Backend: reindex each repo's code graph
4. Wait for all repos to finish indexing
5. Run cross-repo resolution:
   a. Static matching:
      - Java FQN (com.example.MyClass → src/com/example/MyClass.java)
      - Package.json name matching
      - Explicit path-dependencies
   b. FTS5 lexical matching:
      - For ambiguous references
      - Find best match across repos
6. Save CrossRepoEdge to database
7. Frontend displays edges in graph view
```

### Cross-Repo Matching Algorithm

```python
# From cross_repo.py (simplified)
def resolve_cross_repo(project):
    # 1. Collect all unresolved references from each repo
    references = collect_unresolved_references(project.repos)
    
    # 2. Static matching (fast, deterministic)
    static_matches = []
    for ref in references:
        match = try_static_match(ref, project.repos)
        if match:
            static_matches.append(match)
    
    # 3. FTS5 matching (for remaining ambiguous refs)
    fts_matches = fts_cross_match(references - static_matches)
    
    # 4. Save edges
    save_cross_repo_edges(static_matches + fts_matches)
```

---

## 3. Frontend Components

### CodeGraphPanel (Single Repo)

```
┌─────────────────────────────────────┐
│ Status: Indexed (123 files, 456 nodes) │
├─────────────────────────────────────┤
│ 🔍 Search symbols...               │
├─────────────────────────────────────┤
│ 📁 function_name                   │
│    src/utils/helper.py:42          │
│ 📦 ClassName                       │
│    src/models/user.py:15           │
└─────────────────────────────────────┘
```

### CrossRepoLinksPanel (Multi-Repo)

```
┌─────────────────────────────────────┐
│ 🔄 Reindex all repos               │
├─────────────────────────────────────┤
│     ┌───┐                          │
│   ┌─┤ A ├─┐                        │
│   │ └───┘ │  12 cross-repo refs    │
│ ┌─┴───┐ ┌─┴───┐                    │
│ │  B  │ │  C  │                    │
│ └─────┘ └─────┘                    │
└─────────────────────────────────────┘
```

### RepoGraphModal (Full-screen)

```
┌─────────────────────────────────────────────────┐
│ 🔍 Search...                          [X]       │
├─────────────────────────────────────────────────┤
│                                                 │
│        ┌─────────┐                              │
│        │ frontend │──── import ────┐            │
│        └─────────┘                │            │
│                                   ▼            │
│        ┌─────────┐          ┌─────────┐        │
│        │ backend │◄─uses────│ shared  │        │
│        └─────────┘          └─────────┘        │
│                                                 │
└─────────────────────────────────────────────────┘
```

---

## 4. Database Schema

### SQLite Tables

```sql
-- Code nodes (functions, classes, etc.)
CREATE TABLE code_nodes (
    id UUID PRIMARY KEY,
    workspace_id UUID,
    name TEXT,
    qualified_name TEXT,
    kind TEXT,  -- function, class, method, variable
    file_path TEXT,
    line_start INTEGER,
    line_end INTEGER,
    signature TEXT,
    docstring TEXT,
    created_at TIMESTAMP
);

-- Code edges (calls, imports, inherits)
CREATE TABLE code_edges (
    id UUID PRIMARY KEY,
    source_id UUID REFERENCES code_nodes(id),
    target_id UUID REFERENCES code_nodes(id),
    kind TEXT,  -- calls, imports, inherits
    file_path TEXT,
    line_number INTEGER,
    created_at TIMESTAMP
);

-- Cross-repo edges
CREATE TABLE cross_repo_edges (
    id UUID PRIMARY KEY,
    project_id UUID,
    source_repo_id UUID,
    target_repo_id UUID,
    source_symbol TEXT,
    target_symbol TEXT,
    confidence REAL,
    match_type TEXT,  -- static, fts5
    created_at TIMESTAMP
);

-- FTS5 virtual table for search
CREATE VIRTUAL TABLE code_nodes_fts USING fts5(
    name, qualified_name, file_path
);
```

---

## 5. Performance Analysis

| Operation | Time (1K files) | Time (10K files) | Bottleneck |
|-----------|-----------------|-------------------|------------|
| Single repo index | ~5s | ~45s | Python parsing |
| Cross-repo resolve | ~2s | ~10s | FTS5 matching |
| Search query | ~50ms | ~100ms | FTS5 lookup |
| File watch → reindex | ~1s | ~5s | Debounce + parse |

---

## 6. Issues & Recommendations

### Critical Issues

1. **Python-only parsing** - No Rust native implementation
   - Impact: Slow indexing for large repos
   - Fix: Implement tree-sitter parsers in Rust

2. **CodeGraphWatcher HTTP-based** - Still uses Python watchdog
   - Impact: We just replaced file watchers with native Tauri, but code graph still uses HTTP
   - Fix: Use native Tauri watcher for code graph too

3. **No incremental indexing** - Full reindex on every change
   - Impact: Slow for large codebases
   - Fix: Track file hashes, only reindex changed files

### Medium Issues

4. **manifest.py is 70KB** - Too complex
   - Impact: Hard to maintain
   - Fix: Split into separate parsers per ecosystem

5. **No cross-repo in Rust** - Resolution runs in Python
   - Impact: Slower for multi-repo projects
   - Fix: Implement static matching in Rust

### Low Priority

6. **LLM fallback removed** - Was in earlier versions
   - Impact: Less matching accuracy for edge cases
   - Fix: Re-enable as optional feature

---

## 7. Desktop-Only Considerations

Since we've moved to desktop-only mode:

| Feature | Current State | Recommended |
|---------|---------------|-------------|
| File listing | ✅ Native Tauri | Keep |
| File reading | ✅ Native Tauri | Keep |
| File watching | ✅ Native Tauri (new) | Keep |
| Code graph indexing | ❌ Python only | Add Rust |
| Cross-repo resolution | ❌ Python only | Keep Python (complex) |
| Code graph watcher | ❌ HTTP SSE | Use native watcher |

---

## 8. Conclusion

**Code Graph & Cross-Repo flow is functional but has performance bottlenecks:**

1. All parsing runs in Python (no Rust native)
2. CodeGraphWatcher still HTTP-based (should use native watcher)
3. Full reindex on every change (no incremental)

**Recommendation:**
- Keep Python for complex logic (cross-repo resolution)
- Add Rust parsers for performance-critical paths
- Use native Tauri watcher for code graph reindexing
