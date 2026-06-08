# Knowledge Base Feature Plan

## Overview

Add a Knowledge Base (KB) system to Evoflux that allows users to index folders and upload files into a searchable knowledge base. The KB integrates with the existing workflow engine for RAG (Retrieval-Augmented Generation) pipelines.

---

## Current State

| Component | Status |
|---|---|
| Dashboard | Single tab — workflow list only |
| DB Schema | No KB tables exist |
| File handling | Only as workflow nodes (file-explorer, file-reader, context-loader) |
| Embedding | Local model (`@xenova/multilingual-e5-small`, 384d) with hash fallback |
| Vector search | Brute-force cosine similarity in `memory_semantic` |
| Folder/file dialog | No IPC handlers exist |
| markitdown | Already implemented in `src/engine/file-reader/markitdown.ts` |

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│  Dashboard                                       │
│  ┌──────────┐ ┌──────────────┐                  │
│  │Workflows │ │ Knowledge    │                  │
│  │  Tab     │ │ Base Tab     │                  │
│  └──────────┘ └──────┬───────┘                  │
│                       │                          │
│  ┌────────────────────▼───────────────────────┐ │
│  │  KB List (cards)                           │ │
│  │  ┌─────┐ ┌─────┐ ┌─────┐  [+ New KB]     │ │
│  │  │KB 1 │ │KB 2 │ │KB 3 │                  │ │
│  │  └──┬──┘ └─────┘ └─────┘                  │ │
│  │     │ click                                │ │
│  │     ▼                                      │ │
│  │  KB Detail View                            │ │
│  │  ├── Info (name, description, stats)       │ │
│  │  ├── Sources (folders + files)             │ │
│  │  │   ├── [+ Add Folder] → dialog          │ │
│  │  │   ├── [+ Upload Files] → dialog        │ │
│  │  │   └── File list with status             │ │
│  │  ├── Chunks (preview indexed chunks)       │ │
│  │  └── Settings (chunk size, overlap, model) │ │
│  └────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────┘
         │ IPC                    │ IPC
         ▼                        ▼
┌─────────────────────────────────────────────────┐
│  Main Process                                    │
│  ├── kb:create, kb:list, kb:delete, kb:update   │
│  ├── kb:addFolder, kb:addFiles, kb:removeSource │
│  ├── kb:reindex, kb:search                      │
│  ├── file:selectFolder, file:selectFiles         │
│  └── Document Pipeline:                          │
│      file → extract text → chunk → embed → store │
└─────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────┐
│  SQLite (sql.js)                                 │
│  ├── knowledge_bases (id, name, desc, config)   │
│  ├── kb_sources (id, kb_id, path, type, status) │
│  ├── kb_documents (id, kb_id, source_id, path,  │
│  │                 name, ext, size, status)      │
│  └── kb_chunks (id, doc_id, kb_id, content,     │
│                 embedding BLOB, metadata_json)   │
└─────────────────────────────────────────────────┘
```

---

## Implementation Phases

### Phase 1: Database Schema

**File: `src/engine/db/schema.ts`**

Add 4 new tables, bump schema version 2 → 3:

```sql
CREATE TABLE IF NOT EXISTS knowledge_bases (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT,
  config_json TEXT,
  stats_json TEXT,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS kb_sources (
  id TEXT PRIMARY KEY,
  kb_id TEXT NOT NULL,
  path TEXT NOT NULL,
  type TEXT NOT NULL,         -- 'folder' | 'file'
  status TEXT NOT NULL,       -- 'pending' | 'indexing' | 'indexed' | 'error'
  file_count INTEGER DEFAULT 0,
  error TEXT,
  created_at INTEGER NOT NULL,
  FOREIGN KEY (kb_id) REFERENCES knowledge_bases(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS kb_documents (
  id TEXT PRIMARY KEY,
  kb_id TEXT NOT NULL,
  source_id TEXT,
  path TEXT NOT NULL,
  name TEXT NOT NULL,
  extension TEXT,
  size INTEGER,
  content_preview TEXT,
  chunk_count INTEGER DEFAULT 0,
  status TEXT NOT NULL,       -- 'pending' | 'processing' | 'indexed' | 'error'
  error TEXT,
  created_at INTEGER NOT NULL,
  FOREIGN KEY (kb_id) REFERENCES knowledge_bases(id) ON DELETE CASCADE,
  FOREIGN KEY (source_id) REFERENCES kb_sources(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS kb_chunks (
  id TEXT PRIMARY KEY,
  doc_id TEXT NOT NULL,
  kb_id TEXT NOT NULL,
  chunk_index INTEGER,
  content TEXT NOT NULL,
  embedding BLOB,
  metadata_json TEXT,
  created_at INTEGER NOT NULL,
  FOREIGN KEY (doc_id) REFERENCES kb_documents(id) ON DELETE CASCADE,
  FOREIGN KEY (kb_id) REFERENCES knowledge_bases(id) ON DELETE CASCADE
);
```

---

### Phase 2: KB Repository

**New file: `src/engine/db/kb-repo.ts`**

| Function | Description |
|---|---|
| `createKB(name, description, config)` | Create KB → KBRow |
| `getKB(id)` | Get KB by ID → KBRow \| null |
| `listKBs()` | List all KBs → KBRow[] |
| `updateKB(id, patch)` | Update name/desc/config |
| `deleteKB(id)` | Delete KB + CASCADE all data |
| `addSource(kbId, path, type)` | Register folder/file source |
| `listSources(kbId)` | List sources for KB |
| `removeSource(id)` | Remove source + docs + chunks |
| `addDocument(kbId, sourceId, path, name, ext, size)` | Register document |
| `listDocuments(kbId)` | List documents for KB |
| `updateDocStatus(id, status, error?)` | Update processing status |
| `addChunks(docId, kbId, chunks[])` | Batch insert chunks |
| `listChunks(docId)` | List chunks for document |
| `searchChunks(kbId, queryEmbedding, limit)` | Semantic search (cosine similarity) |
| `getKBStats(kbId)` | Aggregate stats |

---

### Phase 3: Document Processing Pipeline

**New file: `src/engine/kb/pipeline.ts`**

```
processSource(kbId, sourcePath, type):
  if type === 'folder':
    scan directory recursively (reuse file-explorer logic)
    for each file:
      processFile(kbId, sourceId, filePath)
  if type === 'file':
    processFile(kbId, sourceId, filePath)

processFile(kbId, sourceId, filePath):
  1. create kb_document row (status: 'processing')
  2. extract text via convertFile() from markitdown.ts
  3. split into chunks (reuse text-splitter.ts)
  4. embed each chunk (reuse embedding.ts)
  5. batch insert kb_chunks
  6. update doc status: 'indexed'
  7. update kb stats
```

**Supported file types:**

| Category | Extensions | Method |
|---|---|---|
| Code | `.js`, `.ts`, `.py`, `.go`, `.rs`, `.java`, `.cpp`, `.c`, `.rb`, `.php`, `.swift`, `.kt` | Direct read |
| Docs | `.md`, `.txt`, `.rst`, `.adoc` | Direct read |
| Data | `.json`, `.yaml`, `.yml`, `.toml`, `.csv`, `.xml` | Direct read |
| Office | `.pdf`, `.docx`, `.xlsx`, `.pptx` | markitdown CLI → Python API → fallback |
| Web | `.html`, `.css`, `.scss` | Direct read |
| Image | `.jpg`, `.png`, `.gif`, `.webp` | markitdown (OCR if available) |
| Binary | Everything else | Skip |

**markitdown fallback chain** (already implemented in `src/engine/file-reader/markitdown.ts`):

| Priority | Method | Command |
|---|---|---|
| 1 | markitdown CLI | `markitdown <file>` |
| 2 | Python API | `python -c "from markitdown import MarkItDown; ..."` |
| 3 | Plain text | `fs.readFile()` |

---

### Phase 4: IPC Handlers

**New file: `electron/ipc/knowledge-base.ts`**

| Handler | Type | Description |
|---|---|---|
| `kb:create` | invoke | Create new KB |
| `kb:list` | invoke | List all KBs |
| `kb:get` | invoke | Get KB by ID |
| `kb:update` | invoke | Update KB name/desc/config |
| `kb:delete` | invoke | Delete KB + all data |
| `kb:addFolder` | invoke | Open folder dialog → scan → index |
| `kb:addFiles` | invoke | Open file dialog → index |
| `kb:removeSource` | invoke | Remove source + its docs/chunks |
| `kb:reindex` | invoke | Re-index a source |
| `kb:search` | invoke | Semantic search within KB |
| `kb:listDocuments` | invoke | List documents in KB |
| `kb:listChunks` | invoke | List chunks for a document |
| `kb:getStats` | invoke | Get KB statistics |

**File: `electron/preload.ts`** — Add `api.kb` namespace:

```ts
kb: {
  create: (name, description, config) => ipcRenderer.invoke('kb:create', name, description, config),
  list: () => ipcRenderer.invoke('kb:list'),
  get: (id) => ipcRenderer.invoke('kb:get', id),
  update: (id, patch) => ipcRenderer.invoke('kb:update', id, patch),
  delete: (id) => ipcRenderer.invoke('kb:delete', id),
  addFolder: (kbId) => ipcRenderer.invoke('kb:addFolder', kbId),
  addFiles: (kbId) => ipcRenderer.invoke('kb:addFiles', kbId),
  removeSource: (sourceId) => ipcRenderer.invoke('kb:removeSource', sourceId),
  reindex: (sourceId) => ipcRenderer.invoke('kb:reindex', sourceId),
  search: (kbId, query, limit) => ipcRenderer.invoke('kb:search', kbId, query, limit),
  listDocuments: (kbId) => ipcRenderer.invoke('kb:listDocuments', kbId),
  listChunks: (docId) => ipcRenderer.invoke('kb:listChunks', docId),
  getStats: (kbId) => ipcRenderer.invoke('kb:getStats', kbId),
}
```

**File: `electron/main.ts`** — Register KB handlers.

---

### Phase 5: Dashboard UI — Tabs

**File: `src/components/dashboard/Dashboard.tsx`**

Changes:
- Add tab bar at top: `Workflows` | `Knowledge Base`
- Active tab stored in local state
- Each tab renders its content area
- Remove the separate stats cards (move into each tab)

---

### Phase 6: KB List Component

**New file: `src/components/kb/KBList.tsx`**

- Grid of KB cards
- Each card: name, description, doc count, chunk count, last updated
- "New Knowledge Base" card with + icon
- Click card → navigate to KB detail
- Delete with confirmation
- Empty state: illustration + create button

---

### Phase 7: KB Detail Component

**New file: `src/components/kb/KBDetail.tsx`**

Layout: 3-column split view

```
┌─────────────────────────────────────────────────────────────┐
│ Header: KB Name · Description · [Back] [Delete]              │
│ Stats: 24 docs · 1,847 chunks · 12.4 MB · 98% indexed       │
├────────────────┬────────────────────────────────────────────┤
│                │                                              │
│  Sources       │  Content Area (tabbed)                      │
│  ─────────     │  ┌──────┬──────┬──────┬──────┐             │
│  📁 /project   │  │ Docs │ Tree │ Search│ Settings│           │
│  📁 /docs      │  └──────┴──────┴──────┴──────┘             │
│  📄 readme.md  │                                              │
│                │  (content based on selected tab)             │
│  [+ Folder]    │                                              │
│  [+ Files]     │                                              │
│                │                                              │
├────────────────┤                                              │
│ Git Changes    │                                              │
│ ─────────      │                                              │
│ M auth.ts      │                                              │
│ A helper.ts    │                                              │
│ [Sync Now]     │                                              │
│                │                                              │
└────────────────┴────────────────────────────────────────────┘
```

#### 7a. Sources Panel (left sidebar)

- Tree list of added sources (folders + files)
- Each source: icon + path + status badge + git indicator
- Right-click context menu: Reindex, Remove, Open in Finder, Copy Path
- Drag-drop files/folders onto the panel to add

#### 7b. Folder Tree View (tab: Tree)

**New file: `src/components/kb/KBFolderTree.tsx`**

Interactive tree showing indexed folder structure:

```
┌──────────────────────────────────────────────────┐
│ 🔍 Filter files...                               │
├──────────────────────────────────────────────────┤
│ ▼ 📁 src                                         │
│   ▼ 📁 engine                                    │
│     ▼ 📁 kb                                      │
│       ├── 📄 pipeline.ts        3 chunks  ✅      │
│       ├── 📄 file-scanner.ts    2 chunks  ✅      │
│       ├── 📄 git-ops.ts         4 chunks  ⏳      │
│       └── 📄 chunker.ts         1 chunk   ✅      │
│     ▼ 📁 nodes                                     │
│       ├── 📄 llm.ts             5 chunks  ✅      │
│       ├── 📄 code.ts            3 chunks  ✅      │
│       └── 📄 condition.ts       2 chunks  ✅      │
│     ├── 📄 graph.ts             8 chunks  ✅      │
│     └── 📄 graph-engine.ts     12 chunks  ✅      │
│   ▼ 📁 components                                  │
│     ▼ 📁 workflow                                  │
│       ├── 📄 WorkflowEditor.tsx 15 chunks ✅      │
│       └── 📄 NodePopup.tsx      6 chunks  ✅      │
│ ▼ 📁 docs                                          │
│   ├── 📄 README.md              4 chunks  ✅      │
│   └── 📄 knowledge-base-plan.md 22 chunks ✅      │
├──────────────────────────────────────────────────┤
│ 32 files · 87 chunks · 2.4 MB indexed            │
└──────────────────────────────────────────────────┘
```

**Features:**

| Feature | Description |
|---|---|
| Expand/collapse | Click folder to toggle, keyboard arrows |
| File status icons | ✅ indexed, ⏳ processing, ❌ error, ⬜ pending |
| Chunk count badge | Per-file chunk count |
| Filter | Search/filter files by name or extension |
| Multi-select | Shift+click to select multiple files |
| Context menu | Right-click: Reindex, View Chunks, View Diff, Open File |
| Click file | Show chunks preview in content area |
| Drag to reorder | Drag files between folders (virtual, not actual move) |
| Size column | File size per file |
| Extension icons | Color-coded by category (code=blue, docs=green, data=yellow) |

**Implementation:**

```tsx
// src/components/kb/KBFolderTree.tsx
interface TreeNode {
  name: string
  path: string
  type: 'file' | 'folder'
  extension?: string
  size?: number
  chunkCount?: number
  status?: 'pending' | 'processing' | 'indexed' | 'error'
  children?: TreeNode[]
  expanded?: boolean
}

function KBFolderTree({ kbId, sourceId }: { kbId: string; sourceId?: string }) {
  const [tree, setTree] = useState<TreeNode[]>([])
  const [filter, setFilter] = useState('')
  const [selected, setSelected] = useState<Set<string>>(new Set())

  // Build tree from kb_documents grouped by path
  // Expand/collapse with local state
  // Filter by name/extension
  // Click → show chunks in detail panel
}
```

**Tree data source:**
- Build from `kb_documents` table grouped by directory path
- Each document → leaf node with chunkCount, status
- Each directory → branch node with children
- Sort: folders first, then files alphabetically

**Keyboard shortcuts:**

| Key | Action |
|---|---|
| `↑/↓` | Navigate files |
| `←` | Collapse folder / go to parent |
| `→` | Expand folder |
| `Enter` | Open file (show chunks) |
| `Space` | Toggle select |
| `Cmd+A` | Select all visible |
| `Cmd+F` | Focus filter input |

#### 7c. Documents Table (tab: Docs)

- Table view: name, extension, size, chunks, status, last indexed
- Sort by any column
- Filter by status (pending/processing/indexed/error)
- Bulk actions: Select All → Reindex, Delete

#### 7d. Chunks Preview (per document)

- Each chunk: index, content preview (first 200 chars), metadata (heading, line range)
- Click chunk → expand full content
- "Re-index this document" button

#### 7e. Settings Panel

- Chunk size (default: 1000 chars)
- Chunk overlap (default: 200 chars)
- Embedding model (display only: `multilingual-e5-small`)
- Exclude patterns (comma-separated glob patterns)
- Max file size limit (default: 1MB)

---

### Phase 8: KB Search Component

**New file: `src/components/kb/KBSearch.tsx`**

- Search input at top of KB detail view
- Semantic search using `kb:search` IPC
- Results list:
  - Document name
  - Chunk content (highlighted match)
  - Similarity score (0.0 — 1.0)
  - Metadata (heading, line range)
- Click result → scroll to chunk in documents panel
- Debounced search (300ms)

---

### Phase 9: Workflow Integration

**File: `src/engine/nodes/knowledge-retrieval.ts`**

Add third mode: `kb_search`

```ts
interface KBSearchConfig {
  mode: 'search' | 'ingest' | 'kb_search'  // add 'kb_search'
  knowledge_base_id?: string                 // KB to search
  query?: string
  top_k?: number
  min_similarity?: number
}
```

In `run()`:
- `kb_search` mode: call `searchChunks(kbId, queryEmbedding, top_k)`
- Filter by `min_similarity` threshold
- Return chunks with metadata

**File: `src/components/workflow/registry.ts`**

Update knowledge-retrieval node config to include KB selector.

---

## File Changes Summary

| File | Action | Description |
|---|---|---|
| `src/engine/db/schema.ts` | Modify | Add 4 KB tables, bump schema to v3 |
| `src/engine/db/kb-repo.ts` | **New** | CRUD + search for KB, sources, docs, chunks |
| `src/engine/kb/pipeline.ts` | **New** | Document processing pipeline |
| `electron/ipc/knowledge-base.ts` | **New** | IPC handlers for all KB operations |
| `electron/preload.ts` | Modify | Add `api.kb` namespace |
| `electron/main.ts` | Modify | Register KB IPC handlers |
| `src/components/dashboard/Dashboard.tsx` | Modify | Add tab bar (Workflows / KB) |
| `src/components/kb/KBList.tsx` | **New** | KB grid list |
| `src/components/kb/KBDetail.tsx` | **New** | KB detail (3-column: sources, tree/docs/search, settings) |
| `src/components/kb/KBFolderTree.tsx` | **New** | Interactive folder tree with expand/collapse, filter, context menu |
| `src/components/kb/KBSearch.tsx` | **New** | Semantic search UI |
| `src/engine/nodes/knowledge-retrieval.ts` | Modify | Add `kb_search` mode |
| `src/components/workflow/registry.ts` | Modify | Update KB node config |

---

## Execution Order

| # | Task | Dependencies | Estimate |
|---|---|---|---|
| 1 | DB schema + migration | — | Small |
| 2 | kb-repo.ts (CRUD + search) | 1 | Medium |
| 3 | pipeline.ts (file → chunks → embed) | 2 | Medium |
| 4 | IPC handlers + preload | 2, 3 | Medium |
| 5 | Dashboard tabs | — | Small |
| 6 | KBList component | 4, 5 | Medium |
| 7 | KBDetail component | 4, 6 | Large |
| 8 | KBSearch component | 4, 7 | Medium |
| 9 | Workflow integration | 2 | Small |
| 10 | Build + test | all | — |

---

## Audit Findings & Fixes

### Gap 1: No shared file scanner utility

**Problem:** Scanning logic duplicated across `file-explorer.ts`, `context-loader.ts`, `directory-tree.ts`.

**Fix:** Create `src/engine/kb/file-scanner.ts` that extracts the common pattern:

```ts
// src/engine/kb/file-scanner.ts
export interface ScannedFile {
  path: string
  relativePath: string
  name: string
  extension: string
  size: number
  modifiedAt: number
  isBinary: boolean
  category: FileCategory
  language?: string
}

export async function scanDirectory(
  dirPath: string,
  options?: {
    maxDepth?: number       // default: 20
    maxFiles?: number       // default: 10000
    includeHidden?: boolean // default: false
    fileTypes?: string[]    // filter by extension, null = all
    excludePatterns?: string[] // default: node_modules, .git, dist, out, ...
  }
): Promise<ScannedFile[]>

export async function scanFiles(filePaths: string[]): Promise<ScannedFile[]>
```

Reuses: `detectFileType()`, `getExtension()`, `getFileName()`, `isBinaryFile()`, `shouldSkipFile()` from `file-detector.ts`.

### Gap 2: Chunk metadata undefined

**Problem:** Plan mentions "heading, line range" metadata but `text-splitter.ts` produces none.

**Fix:** Define `ChunkMetadata` interface and add metadata extraction step:

```ts
interface ChunkMetadata {
  heading?: string        // nearest heading (from markdown-parser.ts)
  headingLevel?: number   // 1-6
  lineStart?: number      // character offset in original document
  lineEnd?: number
  sourceFile?: string     // file path
  sourceType?: string     // file extension
}
```

Pipeline steps:
1. Extract text → get raw content
2. Parse markdown structure → get heading map (line → heading)
3. Split into chunks → track character offsets
4. For each chunk: look up nearest heading from heading map
5. Store metadata as JSON in `kb_chunks.metadata_json`

Uses: `parseMarkdownToStructured()` from `markdown-parser.ts` for heading extraction.

### Gap 3: Missing DB indexes

**Problem:** Schema has no `CREATE INDEX` statements. Search performance will degrade.

**Fix:** Add indexes in schema migration:

```sql
CREATE INDEX IF NOT EXISTS idx_kb_sources_kb ON kb_sources(kb_id);
CREATE INDEX IF NOT EXISTS idx_kb_documents_kb ON kb_documents(kb_id);
CREATE INDEX IF NOT EXISTS idx_kb_documents_source ON kb_documents(source_id);
CREATE INDEX IF NOT EXISTS idx_kb_chunks_kb ON kb_chunks(kb_id);
CREATE INDEX IF NOT EXISTS idx_kb_chunks_doc ON kb_chunks(doc_id);
```

### Gap 4: `@xenova/transformers` not in package.json

**Problem:** Embedding model assumed available but not declared.

**Fix:** Two options:
- **Option A**: Add `@xenova/transformers` to `dependencies` in `package.json`
- **Option B** (recommended): Keep it optional. In `embedding.ts`, the fallback hash-based embedder already exists. Document that real embeddings require `npm install @xenova/transformers`. Show a warning in KB UI when fallback is active.

KB UI should show:
- Green badge: "Using multilingual-e5-small (384d)" — when real model loaded
- Yellow badge: "Using hash-based fallback — install @xenova/transformers for real embeddings"

### Gap 5: No diff library

**Problem:** `KBDiffViewer` needs a diff algorithm but no diff package installed.

**Fix:** Two options:
- **Option A**: Use `git diff` output directly (already available via `git-ops.ts`) — render as pre-formatted text
- **Option B** (recommended): Install `diff` npm package for inline/side-by-side rendering

```bash
npm install diff
npm install -D @types/diff
```

```ts
import { diffLines } from 'diff'
const changes = diffLines(oldContent, newContent)
// Render: green for added, red for removed, gray for unchanged
```

### Gap 6: No file dialog IPC handlers

**Problem:** Architecture diagram references `file:selectFolder` and `file:selectFiles` but no implementation.

**Fix:** Add to `electron/ipc/knowledge-base.ts`:

```ts
import { dialog } from 'electron'

ipcMain.handle('kb:selectFolder', async () => {
  const result = await dialog.showOpenDialog({
    properties: ['openDirectory'],
    title: 'Select folder to index'
  })
  if (result.canceled || result.filePaths.length === 0) return null
  return result.filePaths[0]
})

ipcMain.handle('kb:selectFiles', async () => {
  const result = await dialog.showOpenDialog({
    properties: ['openFile', 'multiSelections'],
    title: 'Select files to index',
    filters: [
      { name: 'Documents', extensions: ['md', 'txt', 'pdf', 'docx', 'xlsx', 'pptx'] },
      { name: 'Code', extensions: ['js', 'ts', 'py', 'go', 'rs', 'java', 'cpp', 'c'] },
      { name: 'Data', extensions: ['json', 'yaml', 'yml', 'csv', 'xml', 'toml'] },
      { name: 'All Files', extensions: ['*'] }
    ]
  })
  if (result.canceled || result.filePaths.length === 0) return null
  return result.filePaths
})
```

Preload additions:

```ts
kb: {
  selectFolder: () => ipcRenderer.invoke('kb:selectFolder'),
  selectFiles: () => ipcRenderer.invoke('kb:selectFiles'),
  // ... existing handlers ...
}
```

### Gap 7: `embedBatch` is sequential

**Problem:** Batch embedding processes texts one at a time. Large KBs will be very slow.

**Fix:** The `@xenova/transformers` pipeline already supports batch input in theory, but the current code loops. For now:
1. Keep sequential for correctness
2. Add progress events during embedding: `kb:embedProgress { current, total, docId }`
3. Future optimization: batch multiple texts in a single `pipe()` call if the model supports it

### Gap 8: `.adoc` extension not supported

**Problem:** Plan mentions AsciiDoc but `file-detector.ts` doesn't register it.

**Fix:** Add to `file-detector.ts` docs category:

```ts
// In file-detector.ts, add to docs extensions:
{ extensions: ['rst', 'tex', 'txt', 'log', 'diff', 'patch', 'adoc'], parser: 'plain' }
```

### Gap 9: Schema version migration strategy

**Problem:** Plan says "bump schema version 2 → 3" but doesn't specify the migration SQL.

**Fix:** Add to `src/engine/db/schema.ts`:

```ts
export const MIGRATIONS: Record<number, string> = {
  1: `...existing migration 1...`,
  3: `
    CREATE TABLE IF NOT EXISTS knowledge_bases (...);
    CREATE TABLE IF NOT EXISTS kb_sources (...);
    CREATE TABLE IF NOT EXISTS kb_documents (...);
    CREATE TABLE IF NOT EXISTS kb_chunks (...);
    CREATE INDEX IF NOT EXISTS idx_kb_sources_kb ON kb_sources(kb_id);
    CREATE INDEX IF NOT EXISTS idx_kb_documents_kb ON kb_documents(kb_id);
    CREATE INDEX IF NOT EXISTS idx_kb_documents_source ON kb_documents(source_id);
    CREATE INDEX IF NOT EXISTS idx_kb_chunks_kb ON kb_chunks(kb_id);
    CREATE INDEX IF NOT EXISTS idx_kb_chunks_doc ON kb_chunks(doc_id);
  `
}
```

### Gap 10: `electron/main.ts` registration

**Problem:** New KB handler registration must be added to `main.ts`.

**Fix:** Add to `electron/main.ts`:

```ts
import { registerKBHandlers } from './ipc/knowledge-base'

app.whenReady().then(async () => {
  // ... existing setup ...
  registerKBHandlers()  // add this line
})
```

---

## Revised File Changes Summary

| File | Action | Description |
|---|---|---|
| `src/engine/db/schema.ts` | Modify | Add 4 KB tables + 5 indexes, migration v3 |
| `src/engine/db/kb-repo.ts` | **New** | CRUD + vector search for KB |
| `src/engine/kb/file-scanner.ts` | **New** | Shared directory/file scanning utility |
| `src/engine/kb/chunker.ts` | **New** | Chunking with metadata extraction |
| `src/engine/kb/pipeline.ts` | **New** | Document processing pipeline |
| `src/engine/kb/git-ops.ts` | **New** | Git operations |
| `electron/ipc/knowledge-base.ts` | **New** | IPC handlers (CRUD + dialogs + sync) |
| `electron/preload.ts` | Modify | Add `api.kb` namespace + TypeScript type |
| `electron/main.ts` | Modify | Register KB handlers |
| `src/components/dashboard/Dashboard.tsx` | Modify | Add tab bar |
| `src/components/kb/KBList.tsx` | **New** | KB grid list |
| `src/components/kb/KBDetail.tsx` | **New** | KB detail (3-column: sources, tree/docs/search, settings) |
| `src/components/kb/KBFolderTree.tsx` | **New** | Interactive folder tree with expand/collapse, filter, context menu |
| `src/components/kb/KBSearch.tsx` | **New** | Semantic search UI |
| `src/components/kb/KBDiffViewer.tsx` | **New** | Side-by-side diff view |
| `src/components/kb/KBGitChanges.tsx` | **New** | Changed files list |
| `src/engine/nodes/knowledge-retrieval.ts` | Modify | Add `kb_search` mode |
| `src/engine/file-reader/file-detector.ts` | Modify | Add `.adoc` extension |
| `src/components/workflow/registry.ts` | Modify | Update KB node config |
| `package.json` | Modify | Add `diff` + `@types/diff` |

---

## Revised Execution Order

| # | Task | Dependencies | Status |
|---|---|---|---|
| 1 | DB schema + migration + indexes | — | Pending |
| 2 | file-scanner.ts (shared scanning) | — | Pending |
| 3 | chunker.ts (splitting + metadata) | — | Pending |
| 4 | kb-repo.ts (CRUD + search) | 1 | Pending |
| 5 | pipeline.ts (file → text → chunks → embed) | 2, 3, 4 | Pending |
| 6 | git-ops.ts | — | Pending |
| 7 | IPC handlers + preload + main.ts | 4, 5, 6 | Pending |
| 8 | Dashboard tabs | — | Pending |
| 9 | KBList component | 7, 8 | Pending |
| 10 | KBDetail + KBFolderTree components | 7, 9 | Pending |
| 11 | KBSearch component | 7, 10 | Pending |
| 12 | KBDiffViewer + KBGitChanges | 6, 7 | Pending |
| 13 | Workflow integration (kb_search mode) | 4 | Pending |
| 14 | Install `diff` package | — | Pending |
| 15 | Add `.adoc` to file-detector.ts | — | Pending |
| 16 | Build + test | all | Pending |

---

## Key Design Decisions

| Decision | Choice | Reason |
|---|---|---|
| Storage | SQLite (sql.js) | Already used, no new deps |
| Embedding | Local `@xenova/multilingual-e5-small` | Offline, zero cost, no API |
| Text extraction | markitdown (local CLI/Python) | Already implemented, no cloud |
| Chunking | Local heuristics (heading + char split) | No LLM call needed |
| Vector search | Brute-force → SQLite-VSS if needed | All local, no external service |
| Full-text search | SQLite FTS5 (built-in) | No deps, BM25 ranking |
| Diff | `diff` npm package + git diff | Local computation |
| File dialog | Electron `dialog.showOpenDialog` | Native OS dialog |
| KB scope | Global (shared across workflows) | More useful for local user |

### Constraints: 100% Local, Zero Cost

| Constraint | Implication |
|---|---|
| **No 3rd-party API calls** | Embedding via local `@xenova/transformers` only |
| **No paid services** | No OpenAI embeddings, no Pinecone, no cloud vector DB |
| **No cloud storage** | No S3/GCS/Azure connectors — local folders + files only |
| **No LLM for chunking** | Semantic chunking via heuristics (heading detection, paragraph boundaries) — not LLM-guided |
| **No external dependencies** | All processing happens in Electron main process |
| **Offline capable** | Works without internet after initial `@xenova/transformers` model download |

---

## Git Control for Knowledge Base

### Overview

KB sources linked to Git repositories get automatic change tracking, smart re-indexing, and version-aware search. Non-Git folders still work normally (full re-index on demand).

### Architecture

```
┌─────────────────────────────────────────────────────────┐
│  KB Detail — Sources Panel                               │
│                                                          │
│  ┌────────────────────────────────────────────────────┐ │
│  │ Source: /path/to/project                           │ │
│  │ Type: folder | Git: ✓ (main) | Status: indexed     │ │
│  │                                                     │ │
│  │ ┌──────────────────────────────────────────────┐   │ │
│  │ │ Git Changes (3 files changed since last sync) │   │ │
│  │ │ ├── M  src/api/auth.ts     (modified)        │   │ │
│  │ │ ├── A  src/utils/helper.ts (new file)        │   │ │
│  │ │ └── D  src/old-module.ts   (deleted)         │   │ │
│  │ │                                               │   │ │
│  │ │ [Sync Now] [View Diff] [Auto-sync: ON]       │   │ │
│  │ └──────────────────────────────────────────────┘   │ │
│  └────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

### Features

| Feature | Description |
|---|---|
| **Git detection** | Auto-detect if source path is inside a Git repo |
| **Change tracking** | Compare indexed snapshot vs working tree via `git diff` |
| **Smart re-index** | Only re-index changed/added files, remove deleted file chunks |
| **Auto-sync** | Optional: watch Git repo for new commits, auto-reindex |
| **Diff viewer** | Show content diff between indexed version and current file |
| **Branch awareness** | Track which branch was indexed, warn if branch changed |
| **Commit snapshot** | Store Git commit hash with each index run |

### DB Schema Additions

**Extend `kb_sources` table:**

```sql
ALTER TABLE kb_sources ADD COLUMN git_repo_path TEXT;
ALTER TABLE kb_sources ADD COLUMN git_branch TEXT;
ALTER TABLE kb_sources ADD COLUMN git_commit_hash TEXT;
ALTER TABLE kb_sources ADD COLUMN git_synced_at INTEGER;
ALTER TABLE kb_sources ADD COLUMN auto_sync INTEGER DEFAULT 0;
```

**Extend `kb_documents` table:**

```sql
ALTER TABLE kb_documents ADD COLUMN git_status TEXT;        -- 'clean' | 'modified' | 'added' | 'deleted'
ALTER TABLE kb_documents ADD COLUMN indexed_content_hash TEXT;
ALTER TABLE kb_documents ADD COLUMN current_content_hash TEXT;
ALTER TABLE kb_documents ADD COLUMN git_diff_preview TEXT;
```

**New table: `kb_git_snapshots`**

```sql
CREATE TABLE IF NOT EXISTS kb_git_snapshots (
  id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL,
  commit_hash TEXT NOT NULL,
  branch TEXT NOT NULL,
  file_count INTEGER,
  synced_at INTEGER NOT NULL,
  FOREIGN KEY (source_id) REFERENCES kb_sources(id) ON DELETE CASCADE
);
```

### Git Operations

**New file: `src/engine/kb/git-ops.ts`**

| Function | Command | Description |
|---|---|---|
| `detectGitRepo(path)` | `git -C <path> rev-parse --git-dir` | Check if path is in a Git repo |
| `getCurrentBranch(path)` | `git -C <path> branch --show-current` | Get current branch name |
| `getCurrentCommit(path)` | `git -C <path> rev-parse HEAD` | Get current commit hash |
| `getChangedFiles(path, sinceCommit)` | `git -C <path> diff --name-status <since>..HEAD` | Files changed since last sync |
| `getFileDiff(path, filePath, sinceCommit)` | `git -C <path> diff <since> -- <file>` | Content diff for a specific file |
| `getFileContent(path, filePath, ref)` | `git -C <path> show <ref>:<file>` | Get file content at a specific commit |
| `getContentHash(content)` | `crypto.createHash('md5').update(content).digest('hex')` | Fast content hash for change detection |
| `watchRepo(path, callback)` | `fs.watch()` on `.git/refs/` + `.git/HEAD` | Watch for new commits |

### Sync Pipeline

```
syncSource(kbId, sourceId):
  1. Get source record (path, git_commit_hash, git_branch)
  2. detectGitRepo(path) → if not Git, do full re-index
  3. getCurrentBranch(path) → warn if different from indexed branch
  4. getCurrentCommit(path) → if same as git_commit_hash, skip (no changes)
  5. getChangedFiles(path, git_commit_hash) → list of {status, filePath}
  6. For each changed file:
     a. status='M' (modified):
        - Read new content → hash → compare with indexed_content_hash
        - If different: delete old chunks → extract → chunk → embed → insert
        - Update git_status='clean', indexed_content_hash=new hash
     b. status='A' (added):
        - Process as new document → extract → chunk → embed → insert
     c. status='D' (deleted):
        - Delete document + its chunks
        - Mark git_status='deleted'
  7. Save kb_git_snapshot (commit_hash, branch, file_count, synced_at)
  8. Update source: git_commit_hash=current, git_synced_at=now
  9. Update kb stats
```

### Auto-Sync (Optional)

When `auto_sync=1` on a source:

```
watchRepo(sourcePath):
  - Watch .git/refs/ and .git/HEAD for changes
  - On change detected:
    1. getCurrentCommit() → compare with stored commit
    2. If different → trigger syncSource() in background
    3. Emit 'kb:syncProgress' event to renderer
```

IPC events:
- `kb:syncStart` — sync started for a source
- `kb:syncProgress` — per-file progress `{ sourceId, fileName, status, current, total }`
- `kb:syncComplete` — sync finished `{ sourceId, filesChanged, chunksAdded, chunksRemoved }`
- `kb:syncError` — sync failed `{ sourceId, error }`

### IPC Additions

| Handler | Type | Description |
|---|---|---|
| `kb:syncSource` | invoke | Trigger manual sync for a source |
| `kb:getGitStatus` | invoke | Get Git change list for a source |
| `kb:getFileDiff` | invoke | Get content diff for a document |
| `kb:setAutoSync` | invoke | Toggle auto-sync for a source |
| `kb:onSyncProgress` | on | Listen for sync progress events |

**Preload additions:**

```ts
kb: {
  // ... existing handlers ...
  syncSource: (sourceId) => ipcRenderer.invoke('kb:syncSource', sourceId),
  getGitStatus: (sourceId) => ipcRenderer.invoke('kb:getGitStatus', sourceId),
  getFileDiff: (docId) => ipcRenderer.invoke('kb:getFileDiff', docId),
  setAutoSync: (sourceId, enabled) => ipcRenderer.invoke('kb:setAutoSync', sourceId, enabled),
  onSyncProgress: (callback) => {
    const handler = (_event, data) => callback(data)
    ipcRenderer.on('kb:syncProgress', handler)
    return () => ipcRenderer.removeListener('kb:syncProgress', handler)
  }
}
```

### UI Changes

**KBDetail.tsx — Sources panel:**

Each source row shows:
- Path, type, status badge
- Git indicator: branch name + short commit hash
- If Git detected:
  - "Changes detected" badge with file count
  - Expand to show changed files list (M/A/D)
  - "Sync Now" button → `kb:syncSource`
  - "View Diff" button → opens diff modal
  - Auto-sync toggle switch
- Last synced timestamp

**New component: `src/components/kb/KBDiffViewer.tsx`**

- Side-by-side or unified diff view
- Shows indexed content vs current content
- Syntax highlighted (reuse CodeEditor component)
- "Re-index this file" button

**New component: `src/components/kb/KBGitChanges.tsx`**

- List of changed files with status icons (M/A/D)
- File path relative to repo root
- Click file → open diff viewer
- "Sync All" button
- "Discard" button (skip file in next sync)

### File Changes Summary — Git Control

| File | Action | Description |
|---|---|---|
| `src/engine/kb/git-ops.ts` | **New** | Git operations (detect, diff, hash, watch) |
| `src/engine/kb/pipeline.ts` | Modify | Add `syncSource()` with smart re-index |
| `src/engine/db/schema.ts` | Modify | Extend kb_sources + kb_documents for Git |
| `src/engine/db/kb-repo.ts` | Modify | Add Git-related queries |
| `electron/ipc/knowledge-base.ts` | Modify | Add sync/diff/auto-sync handlers |
| `electron/preload.ts` | Modify | Add `kb.syncSource`, `kb.onSyncProgress` etc. |
| `src/components/kb/KBDetail.tsx` | Modify | Git status in sources panel |
| `src/components/kb/KBDiffViewer.tsx` | **New** | Side-by-side diff view |
| `src/components/kb/KBGitChanges.tsx` | **New** | Changed files list with actions |

### Execution Order — Git Control

| # | Task | Dependencies |
|---|---|---|
| G1 | Git schema extensions (kb_sources, kb_documents, kb_git_snapshots) | Phase 1 |
| G2 | git-ops.ts (detect, diff, hash, watch) | — |
| G3 | kb-repo.ts Git queries | G1 |
| G4 | pipeline.ts syncSource() | G2, G3, Phase 3 |
| G5 | IPC handlers (sync, diff, auto-sync, events) | G4, Phase 4 |
| G6 | KBGitChanges component | G5 |
| G7 | KBDiffViewer component | G5 |
| G8 | KBDetail Git integration | G6, G7, Phase 7 |

---

## Local Architecture — 100% Offline, Zero Cost

```
┌─────────────────────────────────────────────────────────────────┐
│  Evoflux KB — Local-Only Architecture                           │
│  No API calls · No paid services · No cloud deps · Offline OK   │
│                                                                   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Sources (local only)                                     │   │
│  │  ┌─────────┐ ┌──────────┐                                │   │
│  │  │ Local   │ │ Git Repo │                                │   │
│  │  │ Folder  │ │ (local)  │                                │   │
│  │  └────┬────┘ └────┬─────┘                                │   │
│  │       └───────────┘                                       │   │
│  └──────────────────────┬───────────────────────────────────┘   │
│                          │                                       │
│  ┌──────────────────────▼───────────────────────────────────┐   │
│  │  Ingestion Pipeline (all local)                           │   │
│  │                                                           │   │
│  │  ┌──────────┐  ┌──────────────┐  ┌────────────────────┐  │   │
│  │  │ Extract  │→ │ Chunk        │→ │ Embed              │  │   │
│  │  │          │  │              │  │                    │  │   │
│  │  │ markit-  │  │ Heuristic    │  │ @xenova/           │  │   │
│  │  │ down     │  │ semantic     │  │ transformers       │  │   │
│  │  │ (local   │  │ (heading +   │  │ (local model       │  │   │
│  │  │  CLI or  │  │  paragraph   │  │  multilingual-     │  │   │
│  │  │  Python) │  │  + recursive │  │  e5-small 384d)    │  │   │
│  │  │          │  │  split)      │  │                    │  │   │
│  │  └──────────┘  └──────────────┘  └────────────────────┘  │   │
│  └──────────────────────┬───────────────────────────────────┘   │
│                          │                                       │
│  ┌──────────────────────▼───────────────────────────────────┐   │
│  │  Storage (all SQLite — same file)                         │   │
│  │                                                           │   │
│  │  ┌─────────────┐  ┌──────────────┐  ┌─────────────────┐  │   │
│  │  │ SQLite      │  │ Vector Store │  │ Full-text       │  │   │
│  │  │ (metadata,  │  │ (BLOB in     │  │ (SQLite FTS5    │  │   │
│  │  │  docs, KBs, │  │  kb_chunks + │  │  BM25 ranking)  │  │   │
│  │  │  git state) │  │  brute-force │  │                 │  │   │
│  │  │             │  │  cosine sim) │  │                 │  │   │
│  │  └─────────────┘  └──────────────┘  └─────────────────┘  │   │
│  └──────────────────────┬───────────────────────────────────┘   │
│                          │                                       │
│  ┌──────────────────────▼───────────────────────────────────┐   │
│  │  Retrieval (hybrid search — all local)                    │   │
│  │                                                           │   │
│  │  ┌──────────┐  ┌──────────────┐  ┌────────────────────┐  │   │
│  │  │ Vector   │→ │ BM25 Merge   │→ │ Score Fusion       │  │   │
│  │  │ (cosine  │  │ (FTS5 rank)  │  │ (Reciprocal Rank   │  │   │
│  │  │  sim)    │  │              │  │  Fusion)           │  │   │
│  │  └──────────┘  └──────────────┘  └────────────────────┘  │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Retrieval extras (all local)                             │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌────────────────┐  │   │
│  │  │ Metadata     │  │ Embedding    │  │ Content-hash   │  │   │
│  │  │ Filters      │  │ Cache        │  │ Change detect  │  │   │
│  │  │ (ext, date,  │  │ (skip re-    │  │ (MD5, skip     │  │   │
│  │  │  path glob)  │  │  embed same) │  │  unchanged)    │  │   │
│  │  └──────────────┘  └──────────────┘  └────────────────┘  │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Semantic Chunking — Local Heuristic (No LLM)

Không gọi LLM để chunk. Dùng heuristics dựa trên document structure:

```
Input: Markdown document with headings, paragraphs, code blocks

Step 1: Parse structure
  ┌─────────────────────────────────────────┐
  │ # Heading 1          → section boundary │
  │ ## Heading 2         → subsection       │
  │ paragraph text       → content block    │
  │ ```code block```     → atomic unit      │
  │ - list items         → content block    │
  │ table                → atomic unit      │
  └─────────────────────────────────────────┘

Step 2: Group by section
  ┌─────────────────────────────────────────┐
  │ Section: "Introduction"                  │
  │   blocks: [para1, para2, list1]         │
  │                                          │
  │ Section: "Methods"                       │
  │   blocks: [para3, code1, table1]        │
  └─────────────────────────────────────────┘

Step 3: Split oversized sections
  If section > chunk_size:
    Split by paragraph boundaries
    If paragraph > chunk_size:
      Split by sentence boundaries
      If sentence > chunk_size:
        Split by character (last resort)

Step 4: Merge undersized sections
  If section < min_chunk_size:
    Merge with adjacent section

Step 5: Add overlap
  Each chunk includes last N chars of previous chunk
  (overlap respects word boundaries)
```

**Implementation: `src/engine/kb/chunker.ts`**

```ts
interface ChunkInput {
  content: string
  filePath: string
  extension: string
}

interface ChunkOutput {
  content: string
  metadata: {
    heading?: string
    headingLevel?: number
    lineStart: number
    lineEnd: number
    sourceFile: string
    sourceType: string
    chunkIndex: number
  }
}

function semanticChunk(input: ChunkInput, options?: {
  chunkSize?: number       // default: 1000
  chunkOverlap?: number    // default: 200
  minChunkSize?: number    // default: 100
  strategy?: 'auto' | 'heading' | 'paragraph' | 'character'
}): ChunkOutput[]
```

**Strategy selection (auto mode):**

| File type | Strategy | Reason |
|---|---|---|
| `.md`, `.mdx` | heading | Preserve markdown structure |
| `.txt`, `.log` | paragraph | Natural break points |
| `.py`, `.ts`, `.js`, etc. | function/class | Code-aware boundaries |
| `.json`, `.yaml`, `.csv` | character | Flat data, no structure |
| `.pdf`, `.docx` | paragraph | Converted to text by markitdown |

**Code-aware chunking (no LLM):**

```
Input: TypeScript file

Step 1: Regex-based boundary detection
  - Function: /^(export\s+)?(async\s+)?function\s+\w+/
  - Class: /^(export\s+)?class\s+\w+/
  - Interface: /^(export\s+)?interface\s+\w+/
  - Comment block: /^\/\*\*[\s\S]*?\*\//

Step 2: Group by function/class boundaries
  Each function/class = one chunk (if < chunk_size)
  If > chunk_size: split by statement boundaries

Step 3: Include context
  Each code chunk includes:
  - File path
  - Function/class name in metadata.heading
  - Line numbers
```

---

## Hybrid Search — Local Implementation

```
User query: "how to handle authentication errors"

Step 1: Vector search (semantic understanding)
  embed(query, 'query') → [0.12, -0.34, ..., 0.56]  (384d)
  cosine_similarity(query_vec, all_chunk_vectors)
  → Top 20 results by vector score

Step 2: BM25 keyword search (exact match)
  FTS5: "authentication OR errors OR handle"
  → Top 20 results by BM25 rank

Step 3: Reciprocal Rank Fusion (merge)
  For each result:
    score = Σ 1/(k + rank_i)  where k=60
    (sum across both lists)
  → Final sorted results

Step 4: Metadata filters (optional)
  Filter by: extension, date range, path glob
  → Final results
```

**SQLite FTS5 setup:**

```sql
-- Create FTS5 virtual table (synced with kb_chunks)
CREATE VIRTUAL TABLE kb_chunks_fts USING fts5(
  content,
  content='kb_chunks',
  content_rowid='rowid',
  tokenize='porter unicode61'  -- stemming + unicode
);

-- Triggers to keep FTS in sync
CREATE TRIGGER kb_chunks_ai AFTER INSERT ON kb_chunks BEGIN
  INSERT INTO kb_chunks_fts(rowid, content) VALUES (new.rowid, new.content);
END;
CREATE TRIGGER kb_chunks_ad AFTER DELETE ON kb_chunks BEGIN
  INSERT INTO kb_chunks_fts(kb_chunks_fts, rowid, content) VALUES('delete', old.rowid, old.content);
END;
CREATE TRIGGER kb_chunks_au AFTER UPDATE ON kb_chunks BEGIN
  INSERT INTO kb_chunks_fts(kb_chunks_fts, rowid, content) VALUES('delete', old.rowid, old.content);
  INSERT INTO kb_chunks_fts(rowid, content) VALUES (new.rowid, new.content);
END;
```

**Hybrid search function:**

```ts
// src/engine/kb/hybrid-search.ts
async function hybridSearch(
  kbId: string,
  query: string,
  options?: {
    limit?: number           // default: 10
    vectorWeight?: number    // default: 0.6
    bm25Weight?: number      // default: 0.4
    filters?: {
      extensions?: string[]  // e.g. ['ts', 'js']
      pathGlob?: string      // e.g. 'src/**'
      dateFrom?: number
      dateTo?: number
    }
  }
): Promise<SearchResult[]>
```

---

## Revised Execution Order — Local Product

### Phase 1: Core Engine (DB + Pipeline + Search)

> Mục tiêu: Tạo KB, index files, search hoạt động end-to-end.

| # | Task | File | Output |
|---|---|---|---|
| 1.1 | DB schema v3 | `schema.ts` | 4 KB tables + FTS5 + indexes |
| 1.2 | KB Repository | `kb-repo.ts` | CRUD + vector search + FTS5 |
| 1.3 | File scanner | `file-scanner.ts` | `scanDirectory()` + `scanFiles()` |
| 1.4 | Semantic chunker | `chunker.ts` | Heading/paragraph/code-aware split |
| 1.5 | Hybrid search | `hybrid-search.ts` | Vector + BM25 fusion |
| 1.6 | Pipeline | `pipeline.ts` | extract → chunk → embed → store |
| 1.7 | IPC handlers | `knowledge-base.ts` | All KB IPC channels |
| 1.8 | Preload + main.ts | `preload.ts`, `main.ts` | `api.kb` namespace |
| 1.9 | Install deps | `package.json` | `diff` + `@types/diff` |
| 1.10 | Add `.adoc` | `file-detector.ts` | AsciiDoc support |

**Deliverable:** Tạo KB → add folder → files indexed → search ra kết quả.

**Test:** Unit test cho chunker, kb-repo, hybrid-search. Integration test pipeline.

---

### Phase 2: Dashboard UI + KB Management

> Mục tiêu: User thấy KB trong dashboard, tạo/xóa/browse KB.

| # | Task | File | Output |
|---|---|---|---|
| 2.1 | Dashboard tabs | `Dashboard.tsx` | Workflows \| Knowledge Base tabs |
| 2.2 | KB List | `KBList.tsx` | Grid cards + create/delete |
| 2.3 | KB Detail layout | `KBDetail.tsx` | 3-column: sources, content, settings |
| 2.4 | Folder tree | `KBFolderTree.tsx` | Expand/collapse, filter, context menu |
| 2.5 | Sources panel | in `KBDetail.tsx` | Add folder/files buttons, source list |
| 2.6 | Documents table | in `KBDetail.tsx` | Table: name, ext, size, chunks, status |
| 2.7 | Chunks preview | in `KBDetail.tsx` | Per-document chunk list + content |
| 2.8 | Settings panel | in `KBDetail.tsx` | Chunk size, overlap, exclude patterns |
| 2.9 | Folder/file dialogs | `knowledge-base.ts` | `kb:selectFolder`, `kb:selectFiles` |

**Deliverable:** User tạo KB → add folder → thấy folder tree → click file → thấy chunks.

---

### Phase 3: Search UI + Diff + Git

> Mục tiêu: Search hoạt động trong UI, Git tracking, diff viewer.

| # | Task | File | Output |
|---|---|---|---|
| 3.1 | Search component | `KBSearch.tsx` | Input + results + similarity scores |
| 3.2 | Git operations | `git-ops.ts` | detect, diff, hash, watch |
| 3.3 | Git sync pipeline | in `pipeline.ts` | `syncSource()` smart re-index |
| 3.4 | Git IPC handlers | `knowledge-base.ts` | sync, diff, auto-sync events |
| 3.5 | Git changes UI | `KBGitChanges.tsx` | Changed files list + sync button |
| 3.6 | Diff viewer | `KBDiffViewer.tsx` | Side-by-side diff |
| 3.7 | Git status in tree | in `KBFolderTree.tsx` | Git badges per file |

**Deliverable:** Cmd+F search → kết quả hybrid. Git repo → detect changes → sync → diff viewer.

---

### Phase 4: Workflow Integration + Polish

> Mục tiêu: KB usable trong workflow engine, polish UX.

| # | Task | File | Output |
|---|---|---|---|
| 4.1 | KB search node | `knowledge-retrieval.ts` | `kb_search` mode |
| 4.2 | Node config KB selector | `registry.ts` | Dropdown chọn KB trong node config |
| 4.3 | Embedding cache | in `pipeline.ts` | Skip re-embed same content hash |
| 4.4 | Metadata filters | in `hybrid-search.ts` | Filter by ext, date, path glob |
| 4.5 | Code-aware chunking | in `chunker.ts` | Function/class boundary detection |
| 4.6 | Progress events | `knowledge-base.ts` | `kb:indexProgress` per-file events |
| 4.7 | Error handling polish | all files | Graceful errors, retry logic |
| 4.8 | Empty states | all KB components | Illustrations + CTAs |
| 4.9 | Keyboard shortcuts | all KB components | Cmd+F, Escape, arrows |
| 4.10 | Build + test | — | Full test suite |

**Deliverable:** Workflow node "Knowledge Retrieval" → chọn KB → search → lấy context cho LLM.

---

### Phase 5: Scale (Optional — khi cần)

> Mục tiêu: Xử lý KB lớn (>10K chunks), backup/restore.

| # | Task | File | Output |
|---|---|---|---|
| 5.1 | SQLite-VSS | `kb-repo.ts` | Replace brute-force cho >10K |
| 5.2 | Batch embedding | `embedding.ts` | True batch processing |
| 5.3 | Backup/restore | `knowledge-base.ts` | Export/Import .kb file |
| 5.4 | Index stats dashboard | `KBDetail.tsx` | Query latency, index size chart |

**Deliverable:** KB 100K+ chunks vẫn search nhanh. Backup/restore an toàn.

---

## Revised File Changes Summary — Local Product

| File | Action | Description |
|---|---|---|
| `src/engine/db/schema.ts` | Modify | KB tables + FTS5 + indexes + migration v3 |
| `src/engine/db/kb-repo.ts` | **New** | CRUD + vector search + FTS5 search |
| `src/engine/kb/file-scanner.ts` | **New** | Shared directory/file scanning |
| `src/engine/kb/chunker.ts` | **New** | Semantic chunking (heuristic, no LLM) |
| `src/engine/kb/hybrid-search.ts` | **New** | Vector + BM25 Reciprocal Rank Fusion |
| `src/engine/kb/pipeline.ts` | **New** | Extract → chunk → embed → store |
| `src/engine/kb/git-ops.ts` | **New** | Git operations |
| `electron/ipc/knowledge-base.ts` | **New** | IPC handlers |
| `electron/preload.ts` | Modify | Add `api.kb` namespace + types |
| `electron/main.ts` | Modify | Register KB handlers |
| `src/components/dashboard/Dashboard.tsx` | Modify | Add tab bar |
| `src/components/kb/KBList.tsx` | **New** | KB grid list |
| `src/components/kb/KBDetail.tsx` | **New** | KB detail (3-column) |
| `src/components/kb/KBFolderTree.tsx` | **New** | Interactive folder tree |
| `src/components/kb/KBSearch.tsx` | **New** | Hybrid search UI |
| `src/components/kb/KBDiffViewer.tsx` | **New** | Diff view |
| `src/components/kb/KBGitChanges.tsx` | **New** | Git changes list |
| `src/engine/nodes/knowledge-retrieval.ts` | Modify | Add `kb_search` mode |
| `src/engine/file-reader/file-detector.ts` | Modify | Add `.adoc` |
| `package.json` | Modify | Add `diff` + `@types/diff` |
