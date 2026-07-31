# Plan: Native File Manager (No HTTP Proxy)

## Problem Analysis

### Current Architecture
```
Work mode:
  Browser → HTTP → Python Backend → Filesystem
  (/api/team/{sid}/media/{path})

Coding mode:
  Browser → HTTP → Python Backend → Filesystem
  (/api/team/workspace/files/list)
```

### Issues
1. **Transient failures**: HTTP proxy can timeout/fail on large files
2. **Performance**: Every file read goes through HTTP round-trip
3. **File limit**: 10K files max (was 2K, just increased)
4. **No lazy loading**: All files fetched at once

### Root Cause
Files are loaded via HTTP proxy instead of native filesystem access.

---

## Proposed Solution: Native File Manager

### Architecture (Tauri Desktop)
```
Browser → Tauri IPC → Rust → Filesystem
  (direct, no HTTP)
```

### Key Components

#### 1. Lazy Directory Loading
Instead of fetching all files at once:
- Only fetch directory listing when user clicks a folder
- Each directory is a separate IPC call
- Cache results in memory

#### 2. Virtual Scrolling
For directories with thousands of files:
- Only render visible files (viewport + buffer)
- Use react-window or similar library
- Smooth scrolling experience

#### 3. Native File Reading
- Read file content directly via Tauri IPC
- No HTTP round-trip
- Support for streaming large files

---

## Implementation Plan

### Phase 1: Native Directory Listing (Tauri)

**New Rust Command: `list_directory`**
```rust
#[tauri::command]
pub fn list_directory(path: String) -> Result<Vec<DirEntry>, String> {
    // List only immediate children (not recursive)
    // Return: name, path, is_dir, size, mtime, mime
}
```

**Benefits:**
- Only loads what's visible
- No 10K file limit per call
- User controls depth by clicking folders

### Phase 2: Lazy Tree Component

**New Component: `NativeFileTree`**
- Loads directories on-demand (click to expand)
- Caches loaded directories in React state
- Shows loading spinner while fetching

### Phase 3: Virtual Scrolling

**For large directories (>100 files):**
- Use `react-window` for virtualized list
- Only render visible items
- Smooth scroll performance

### Phase 4: Native File Reading

**Already implemented:**
- `tauriReadWorkspaceFile` - reads file via Tauri IPC
- Used in TextPreview for content loading

**Enhancement:**
- Add streaming support for large files
- Progress indicator for slow reads

---

## File Changes Required

### Rust (desktop/src-tauri/src/workspace.rs)
```rust
#[tauri::command]
pub fn list_directory(path: String) -> Result<DirEntryList, String> {
    // List immediate children only
    // Return: entries[], parent_path
}

#[tauri::command]
pub fn get_file_info(path: String) -> Result<FileInfo, String> {
    // Get single file metadata
}
```

### TypeScript (web/src/api/tauri-workspace.ts)
```typescript
export async function tauriListDirectory(path: string): Promise<DirEntry[]> {
  return tauriInvoke<DirEntry[]>('list_directory', { path })
}
```

### React Component (web/src/components/NativeFileTree.tsx)
```tsx
// Lazy-loading file tree
// - Loads directory contents on click
// - Caches results
// - Virtual scrolling for large dirs
```

---

## Comparison: Current vs Proposed

| Aspect | Current | Proposed |
|--------|---------|----------|
| File loading | HTTP proxy | Native Tauri IPC |
| Directory listing | Recursive (all files) | Lazy (on-click) |
| File limit | 10K total | No limit (lazy) |
| Performance | HTTP round-trip | Direct filesystem |
| Large dirs | Slow (all loaded) | Fast (virtual scroll) |

---

## Migration Strategy

1. **Keep HTTP fallback** for web browser mode
2. **Add Tauri native path** for desktop
3. **Graceful degradation**: If Tauri unavailable, use HTTP

---

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| Tauri IPC overhead | Batch multiple reads |
| Cache invalidation | Use file watcher (already exists) |
| Memory usage | Evict old cache entries |
| Cross-platform | Test on Windows/macOS/Linux |
