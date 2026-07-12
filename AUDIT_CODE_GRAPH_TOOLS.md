# Audit: Code Graph Tools

## Executive Summary

Code graph tools hiện tại có 7 tools, nhưng có nhiều vấn đề về effectiveness và usability. Các tools quá phức tạp, trùng lặp chức năng, và không hỗ trợ tốt cho common workflows.

---

## 1. Danh sách Tools hiện tại

| # | Tool | Mô tả | Tokens | Limit |
|---|------|-------|--------|-------|
| 1 | `code_search` | Search symbols by name | ~100-200 | 50 |
| 2 | `code_symbol` | Lookup symbol details | ~200-400 | - |
| 3 | `code_neighbors` | List outbound relationships | ~150-300 | 100 |
| 4 | `code_references` | List inbound usages | ~150-300 | 60 |
| 5 | `code_overview` | Codebase summary | ~100-200 | - |
| 6 | `code_map` | Most-referenced symbols | ~200-400 | 50 |
| 7 | `code_path` | Shortest path between symbols | ~150-300 | 8 hops |

**Tổng**: 7 tools, ~1000-2100 tokens per full exploration

---

## 2. Phân tích từng Tool

### 2.1 code_search

```python
# Current implementation
async def _code_search(query, kind, limit, scope):
    # Search active repo + light taste of siblings
    # Returns: [kind] qualified_name — file:line\n   sig: ...
```

**Vấn đề**:
- ❌ Fuzzy search không hoạt động (chỉ substring matching)
- ❌ Không support regex hoặc wildcard
- ❌ Không show context (chỉ tên + file:line)
- ❌ Cross-repo search quá phức tạp (scope parameter)

### 2.2 code_symbol

```python
# Current implementation
async def _code_symbol(name, cross_repo_limit, scope):
    # Returns: kind, location, signature, docstring, relationships
```

**Vấn đề**:
- ❌ Quá nhiều thông tin trong một response
- ❌ Không có "quick view" option
- ❌ cross_repo_limit parameter thừa (luôn show)
- ❌ Không support partial name match

### 2.3 code_neighbors

```python
# Current implementation
async def _code_neighbors(name, edge_kind, limit, scope):
    # Returns: outbound relationships (calls, inherits, etc.)
```

**Vấn đề**:
- ❌ Chỉ show outbound (phải dùng code_references cho inbound)
- ❌ edge_kind parameter phức tạp
- ❌ Không có "full graph" view
- ❌ Cross-repo handling phức tạp

### 2.4 code_references

```python
# Current implementation
async def _code_references(name, limit, scope):
    # Returns: inbound usages (callers, importers, etc.)
```

**Vấn đề**:
- ❌ Trùng lặp với code_neighbors (inbound vs outbound)
- ❌ Không show impact analysis
- ❌ Không filter được theo file/package

### 2.5 code_overview

```python
# Current implementation
async def _code_overview():
    # Returns: totals, languages, densest files
```

**Vấn đề**:
- ✅ Đơn giản, dễ dùng
- ❌ Không show dependency graph
- ❌ Không show architecture overview

### 2.6 code_map

```python
# Current implementation
async def _code_map(budget):
    # Returns: most-referenced symbols
```

**Vấn đề**:
- ✅ Hữu ích cho finding entry points
- ❌ Không show relationships giữa symbols
- ❌ Không filter được theo kind/package

### 2.7 code_path

```python
# Current implementation
async def _code_path(source, target, max_hops):
    # Returns: shortest path between two symbols
```

**Vấn đề**:
- ✅ Rất hữu ích cho impact analysis
- ❌ Không show all paths (chỉ shortest)
- ❌ Không show cycle detection
- ❌ max_hops limit quá thấp (8)

---

## 3. Vấn đề chung

### 3.1 Trùng lặp chức năng

```
code_search  ─────┐
                   ├──→ Cả 2 đều tìm symbols
code_symbol  ─────┘

code_neighbors  ──┐
                   ├──→ Cả 2 đều show relationships
code_references ──┘
```

### 3.2 Quá phức tạp

- 7 tools quá nhiều cho agent remember
- Mỗi tool có 3-4 parameters
- scope parameter xuất hiện ở mọi tool
- cross_repo_limit, edge_kind, kind parameters thừa

### 3.3 Không hỗ trợ common workflows

| Workflow | Hiện tại | Cần gì |
|----------|----------|--------|
| "Where is X defined?" | code_search → code_symbol | Một tool đơn giản |
| "What calls X?" | code_references | OK |
| "What does X call?" | code_neighbors | OK |
| "How does A reach B?" | code_path | OK |
| "Show me the architecture" | code_overview + code_map | Cần better overview |
| "What breaks if I change X?" | code_references + code_path | Cần combined view |

### 3.4 Performance issues

- Mỗi tool query SQLite riêng biệt
- Không caching giữa các tool calls
- Cross-repo queries chậm (multiple DB roundtrips)

---

## 4. Recommendations

### 4.1 Consolidate Tools (7 → 4)

| New Tool | Replaces | Mô tả |
|----------|----------|-------|
| `code_search` | code_search, code_symbol | Unified search + lookup |
| `code_graph` | code_neighbors, code_references | Unified relationship view |
| `code_overview` | code_overview, code_map | Unified overview + ranking |
| `code_path` | code_path | Keep (already good) |

### 4.2 Simplify Parameters

```python
# Trước: 7 tools × 3-4 params = 21+ params
# Sau: 4 tools × 2 params = 8 params

@tool
async def code_search(
    query: str,           # Only required param
    scope: str = "auto",  # auto-detect workspace/project
) -> str: ...

@tool
async def code_graph(
    name: str,            # Symbol to explore
    direction: str = "both",  # in/out/both
) -> str: ...

@tool
async def code_overview() -> str: ...  # No params needed

@tool
async def code_path(
    source: str,
    target: str,
) -> str: ...  # Already simple
```

### 4.3 Add Smart Features

1. **Auto-detect scope**: Không cần scope parameter, tự detect workspace vs project
2. **Combined views**: Show both inbound + outbound trong code_graph
3. **Impact analysis**: Tích hợp code_references + code_path
4. **Caching**: Cache query results giữa các tool calls

### 4.4 Improve Output Format

```python
# Trước
"""
[function] helper.utils.process_data — src/utils/helper.py:42-58
   sig: def process_data(data: dict, config: Config) -> Result
   calls (3): logger.info, validate_input, transform_data
   called by (5): main.run, api.handle_request, ...
"""

# Sau (cấu trúc hơn, dễ đọc hơn)
"""
📍 src/utils/helper.py:42-58
🔧 process_data(data: dict, config: Config) -> Result

Called by:
  → main.run (src/main.py:15)
  → api.handle_request (src/api.py:89)

Calls:
  → validate_input (src/utils/validate.py:12)
  → transform_data (src/utils/transform.py:34)

Cross-repo:
  ← backend/src/api.py:89 (`from shared.utils import process_data`)
"""
```

---

## 5. Implementation Plan

### Phase 1: Consolidate (7 → 4 tools)

1. Merge code_search + code_symbol → unified code_search
2. Merge code_neighbors + code_references → unified code_graph
3. Merge code_overview + code_map → unified code_overview
4. Keep code_path as-is

### Phase 2: Simplify

1. Remove scope parameter (auto-detect)
2. Remove edge_kind parameter (show all)
3. Remove cross_repo_limit parameter (smart limits)

### Phase 3: Enhance

1. Add caching layer
2. Add combined impact analysis
3. Improve output formatting

---

## 6. Conclusion

**Code graph tools hiện tại có vấn đề:**

1. ❌ Quá nhiều tools (7) và parameters (21+)
2. ❌ Trùng lặp chức năng
3. ❌ Không hỗ trợ tốt common workflows
4. ❌ Output format phức tạp

**Recommendation: Consolidate từ 7 xuống 4 tools, simplify parameters, improve output format.**
