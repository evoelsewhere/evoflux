# Multi-Source Import — Development Plan

> **Status**: Draft — v2 (decisions applied)  
> **Created**: 2026-09-30  
> **Updated**: 2026-09-30  
> **Scope**: Import data from Claude, ChatGPT, Codex, Cursor, and other AI tools into EvoFlux

### Design Decisions (confirmed)

| # | Decision | Rationale |
|---|---|---|
| D1 | Imported sessions are **visually marked** with a source badge (e.g. "Imported from Claude") | User can distinguish native vs imported data at a glance |
| D2 | Import runs **locally** via Tauri file dialog; Python sidecar reads files directly from the local filesystem | EvoFlux is a local-first desktop app; web upload is unnecessary overhead |
| D3 | A dedicated **Settings → Import** section manages import sources, default behaviors, and import history | Centralized config for import preferences

---

## 1. Problem Statement

Users migrating to EvoFlux from other AI tools (Claude, ChatGPT, Codex, Cursor, etc.) have accumulated significant data: conversations, custom instructions, knowledge bases, MCP configurations, and agent-like settings. Currently there is no way to bring this data into EvoFlux. This plan defines a unified import system that recognizes multiple source formats, maps them to EvoFlux's native data model, and provides a safe, reviewable import workflow.

---

## 2. Importable Data Taxonomy

### 2.1 EvoFlux Target Models

| EvoFlux Entity | Source Model File | Key Fields |
|---|---|---|
| `ChatSession` | `app/models/chat.py` | id, title, mode, kind, agent, lead, folder, project, archived |
| `SessionMessage` | `app/models/chat.py` | session_id, role, content, tool_calls, tool_results, timestamps |
| `SessionGoal` | `app/models/goal.py` | session_id, objective, status, token_budget |
| `MemoryFact` | `app/models/memory.py` | namespace, text, confidence, evidence |
| Agent Config (`.md`) | `app/agent/loader.py` | YAML frontmatter + Markdown body |
| Skill (`SKILL.md`) | `app/agent/skills/registry.py` | name, description, allowed_tools, body |
| Plugin (`plugin.json`) | `app/plugin_platform/models.py` | manifest, MCP components, trust |
| MCP Servers (`mcp.json`) | `app/agent/mcp/config.py` | servers dict with transport, command/url, env |
| `settings.yaml` | `app/core/config.py` | dream, memory_extraction, security, team_spawn |
| `ScheduledTask` | `app/models/` | prompt, schedule, enabled |
| Wiki Knowledge Base | `app/services/wiki.py` | topics/, entities/, sources/, notes/ Markdown files |

### 2.2 Source Tool Matrix

| Source | Sessions | Custom Instructions | Memory / Knowledge | Skills / GPTs | MCP Config | API Keys |
|---|---|---|---|---|---|---|
| **Claude.ai** (web) | JSON export | Projects instructions | Projects knowledge files | Artifacts | — | — |
| **Claude Code** (CLI) | JSONL `~/.claude/` | `.claude/settings.json`, `CLAUDE.md` | — | — | `.claude/settings.json` | env vars |
| **ChatGPT** (web) | `conversations.json` | Custom instructions, Memory | Projects files | Custom GPTs config | — | — |
| **Codex** (CLI) | `.codex/sessions/` | `.codex/instructions.md` | — | — | — | env vars |
| **Cursor** | `.cursor/history/` | `.cursor/rules/`, `.cursorrules` | — | — | `.cursor/mcp.json` | settings |
| **Windsurf** | local history | `.windsurfrules` | — | — | MCP config | settings |
| **Cline** | VS Code storage | `.clinerules`, custom instructions | — | — | MCP config | settings |
| **GitHub Copilot** | — | `.github/copilot-instructions.md` | — | — | — | settings |

---

## 3. Architecture

### 3.1 Design Principles

- **Local-first**: Import reads files directly from the user's filesystem via the Python sidecar. No web upload, no temp file staging on a server.
- **Tauri dialog**: The frontend uses `@tauri-apps/plugin-dialog` (`open()` with `directory` or `file` mode + filters) to let the user pick the source. The selected path is passed to the backend via `tauriInvoke` or the existing API bridge.
- **Source tagging**: Every imported entity carries a `source` metadata field (`"claude_web"`, `"chatgpt"`, `"cursor"`, etc.) and an `imported_at` timestamp. Imported sessions show a source badge in the sidebar and session header.
- **Settings-driven**: Import behavior is configured in **Settings → Import** (default source detection, auto-import rules, source badge visibility, conflict resolution defaults).

### 3.2 Layer Overview

```
┌─────────────────────────────────────────────────────────┐
│                    Import UI (web/)                       │
│  Settings → Import  (config + trigger + history)          │
│  - "Import from Claude / ChatGPT / Codex / ..." buttons  │
│  - Tauri dialog opens file/folder picker                  │
│  - Preview & conflict resolution table                    │
│  - Progress bar with SSE                                  │
└────────────────────────┬────────────────────────────────┘
                         │ Tauri invoke: selected path(s)
                         │ or API call with local path
┌────────────────────────▼────────────────────────────────┐
│               Import API Routes                          │
│  POST /api/import/detect       {path: "/Users/..."}     │
│  GET  /api/import/preview/{id}                           │
│  PATCH /api/import/preview/{id}  (update resolutions)    │
│  POST /api/import/execute/{id}  (SSE progress stream)    │
│  GET  /api/import/history        (past imports)          │
│  DELETE /api/import/{id}         (clean up)              │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│            Import Orchestrator (service)                   │
│  app/services/import_service.py                           │
│  - Accept local path, auto-detect source format           │
│  - Route to correct parser                                │
│  - Run parsers, collect ImportBundle                       │
│  - Present preview / conflict report                      │
│  - Execute import with transactional safety               │
│  - Tag every item with source + imported_at               │
│  - Record import in history table                         │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│               Parsers (per source)                        │
│  app/services/importers/                                  │
│    base.py        — ImportBundle, ImportItem, source tag  │
│    claude_web.py  — Claude.ai JSON/ZIP export             │
│    claude_code.py — Claude Code ~/.claude/ directory      │
│    chatgpt.py     — ChatGPT conversations.json ZIP        │
│    codex.py       — Codex CLI .codex/ directory            │
│    cursor.py      — Cursor .cursor/ directory              │
│    generic.py     — MCP JSON, SKILL.md, AGENTS.md         │
│    _mapping.py    — field-level mapping + source tagging  │
└────────────────────────┬────────────────────────────────┘
                         │ writes to
┌────────────────────────▼────────────────────────────────┐
│              EvoFlux Native Writers                       │
│  Reuse existing services:                                 │
│    chat_service.py       — sessions + messages (tagged)   │
│    memory.py / wiki.py   — memory facts + wiki notes      │
│    agent/loader.py       — agent .md files                │
│    skills/registry.py    — skill directories              │
│    plugin_platform/      — plugin packages                │
│    mcp/config.py         — MCP server merge               │
│    settings.yaml         — settings merge                 │
└─────────────────────────────────────────────────────────┘
```

### 3.3 Source Tagging — Model Extension

Every imported entity gets two extra metadata fields. These are stored alongside existing fields (not in a separate table) so queries and filters stay simple.

**ChatSession** (`app/models/chat.py`) — add:
```python
source: str | None = Field(default=None, sa_column=Column(String(50), nullable=True))
# Values: "claude_web", "claude_code", "chatgpt", "codex", "cursor", "generic", None (native)

imported_at: datetime | None = Field(default=None, sa_column=Column(TZDateTime(), nullable=True))
# Set once at import time; None for native sessions
```

**MemoryFact** (`app/models/memory.py`) — add:
```python
source: str | None = Field(default=None, sa_column=Column(String(50), nullable=True))
imported_at: datetime | None = Field(default=None, sa_column=Column(TZDateTime(), nullable=True))
```

**Agent / Skill / Plugin files** — store source in YAML frontmatter:
```yaml
---
name: my-agent
source: claude_code
imported_at: "2026-09-30T10:00:00Z"
---
```

**Source badge in UI**:
- Sidebar session row: small chip next to title (e.g. `Claude` in muted color)
- Session header: "Imported from Claude.ai on 2026-09-30" line under title
- Settings → Import → History: full table of all imports with source, date, counts
- Badge visibility controlled by Settings → Import → "Show source badges" toggle

### 3.4 Core Data Types

```python
# app/services/importers/base.py

@dataclass
class ImportItem:
    """One importable unit from any source."""
    kind: Literal[
        "session",        # -> ChatSession + SessionMessages
        "agent",          # -> agent .md file
        "skill",          # -> Skill directory with SKILL.md
        "plugin",         # -> Plugin package
        "mcp_server",     # -> entry in mcp.json
        "memory_fact",    # -> MemoryFact
        "knowledge",      # -> wiki Markdown files
        "custom_instruction",  # -> agent prompt addition or skill
        "setting",        # -> settings.yaml merge
        "scheduled_task", # -> ScheduledTask
    ]
    source: str           # source tool name (claude_web, chatgpt, cursor, etc.)
    source_id: str        # original ID from source for dedup
    data: dict            # parsed payload, schema depends on kind
    label: str            # human-readable preview label
    conflicts: list[str]  # detected conflicts with existing data

@dataclass
class ImportBundle:
    """Complete parsed result from one import operation."""
    source: str
    detected_format: str
    items: list[ImportItem]
    warnings: list[str]
    metadata: dict        # source version, export date, counts

@dataclass
class ImportResult:
    """Outcome of executing an import."""
    imported: dict[str, int]   # kind -> count
    skipped: dict[str, int]    # kind -> count (conflicts/duplicates)
    errors: list[dict]         # {item, error}
```

---

## 4. Source Parsers — Detailed Mapping

### 4.1 Claude.ai Web Export

**Input**: ZIP or JSON file from Claude Settings → Export Data

**Format**:
```json
[
  {
    "uuid": "...",
    "name": "Conversation title",
    "created_at": "2024-01-01T00:00:00Z",
    "updated_at": "2024-01-01T00:00:00Z",
    "chat_messages": [
      {
        "uuid": "...",
        "sender": "human|assistant",
        "text": "...",
        "content": [...],  // multimodal parts
        "created_at": "...",
        "attachments": [...]
      }
    ]
  }
]
```

**Mapping**:

| Claude | EvoFlux | Notes |
|---|---|---|
| `uuid` | `ChatSession.id` (new UUID) | Generate new UUID7, store source_id for dedup |
| `name` | `ChatSession.title` | Direct |
| `chat_messages[].sender: "human"` | `SessionMessage(role="user")` | Map `text` or `content` to content |
| `chat_messages[].sender: "assistant"` | `SessionMessage(role="assistant")` | Preserve thinking/reasoning if present |
| `chat_messages[].content` (array) | Multi-part message | Handle text, images, tool_use, tool_result |
| `attachments` | File references | Store as metadata, prompt user for files |
| Projects instructions | Agent config or Skill | Custom instructions → `.md` with frontmatter |
| Projects knowledge files | Wiki knowledge | Import as `sources/` or `topics/` |

**Special handling**:
- Artifacts → detect code/document artifacts, offer to import as Skills or files
- Projects with instructions → create an Agent config + associated Skill

### 4.2 Claude Code (CLI)

**Input**: `~/.claude/` directory or selected subpaths

**Key files**:
```
~/.claude/
├── settings.json              # global settings, MCP servers
├── projects/
│   └── <project-hash>/
│       ├── settings.json      # project-level settings
│       ├── sessions/
│       │   └── <session-id>.jsonl   # session transcript
│       └── CLAUDE.md          # project instructions
├── commands/                   # custom slash commands
│   └── <name>.md
└── .mcp.json                  # MCP server config
```

**Mapping**:

| Claude Code | EvoFlux | Notes |
|---|---|---|
| `sessions/*.jsonl` | `ChatSession` + messages | Parse JSONL, each line is a message/event |
| `CLAUDE.md` | Agent config `.md` | Wrap in frontmatter, set as workspace instructions |
| `settings.json` (global) | `settings.yaml` merge | Map API keys, model preferences |
| `settings.json` (project) | Project-level agent config | Map project settings to agent frontmatter |
| `commands/*.md` | Skills | Each command → a Skill with SKILL.md |
| `.mcp.json` | `mcp.json` merge | Parse `mcpServers` object, map to EvoFlux format |

### 4.3 ChatGPT Web Export

**Input**: ZIP from ChatGPT Settings → Data Controls → Export

**Format** (`conversations.json`):
```json
[
  {
    "title": "Conversation title",
    "create_time": 1704067200.0,
    "update_time": 1704067200.0,
    "mapping": {
      "root": { "children": ["msg1", "msg2"] },
      "msg1": {
        "message": {
          "author": { "role": "user" },
          "content": { "content_type": "text", "parts": ["..."] },
          "create_time": 1704067200.0
        }
      },
      "msg2": {
        "message": {
          "author": { "role": "assistant" },
          "content": { "content_type": "text", "parts": ["..."] },
          "metadata": { "model_slug": "gpt-4", ... }
        }
      }
    }
  }
]
```

**Mapping**:

| ChatGPT | EvoFlux | Notes |
|---|---|---|
| `title` | `ChatSession.title` | Direct |
| `create_time` (Unix) | `ChatSession.created_at` | Convert to datetime |
| `mapping` tree | Messages in order | Walk tree from root, flatten by `create_time` |
| `author.role: "user"` | `SessionMessage(role="user")` | `parts` joined or structured |
| `author.role: "assistant"` | `SessionMessage(role="assistant")` | Include code blocks, markdown |
| `author.role: "system"` | System prompt | Store as session prefix or agent config |
| `metadata.model_slug` | Store as metadata | Can map to provider:model |
| `content_type: "code"` | Code block in message | Preserve formatting |
| `content_type: "image_url"` | Image reference | Store URL, note may expire |
| Custom instructions | Agent config or Skill | Parse from `user_preferences.json` if present |
| Memory (`user_system_message.json`) | Memory facts or wiki | Extract structured facts |
| GPT configurations | Skills or Agents | Each Custom GPT → Skill with instructions |

**Special handling**:
- ChatGPT's tree-based message structure requires careful flattening (DFS traversal)
- DALL-E image generations → note as metadata, actual images may not be in export
- Code interpreter sessions → preserve code + output as structured message

### 4.4 Codex CLI

**Input**: `.codex/` directory or export

**Mapping**:

| Codex | EvoFlux | Notes |
|---|---|---|
| Session transcripts | `ChatSession` + messages | Parse session format |
| `instructions.md` | Agent config or Skill | Workspace instructions |
| Config (`config.json`) | `settings.yaml` merge | Model, provider preferences |

### 4.5 Cursor

**Input**: `.cursor/` directory or project workspace

**Mapping**:

| Cursor | EvoFlux | Notes |
|---|---|---|
| `.cursor/rules/*.mdc` | Skills | Each rule → SKILL.md with description |
| `.cursorrules` | Agent config or workspace instruction | Single rules file → agent prompt |
| `.cursor/mcp.json` | `mcp.json` merge | Direct MCP server config |
| Chat history (if exportable) | Sessions | Parse Cursor's local storage format |
| `.cursor/settings.json` | `settings.yaml` merge | Editor/model preferences |

### 4.6 Generic / Ad-Hoc Import

For loose files that don't come from a specific tool:

| Input | Detection | Target |
|---|---|---|
| `mcp.json` (any format) | JSON with `servers`/`mcpServers` key | MCP server merge |
| `SKILL.md` | YAML frontmatter + body | Skill installation |
| `plugin.json` + directory | Plugin manifest | Plugin installation |
| Agent `.md` with frontmatter | YAML frontmatter pattern | Agent config |
| `AGENTS.md` | Workspace instructions | Workspace instruction file |
| `.env` with `*_API_KEY` | Key-value pairs | Credential import (encrypted) |
| Markdown knowledge files | `.md` with headers/links | Wiki knowledge base |

---

## 5. Conflict Detection & Resolution

### 5.1 Conflict Types

| Conflict | Detection | Default Resolution |
|---|---|---|
| Duplicate session (same source_id) | Check `source_id` in metadata | Skip, offer replace |
| Duplicate agent name | Agent file already exists | Rename with suffix, offer overwrite |
| Duplicate skill name | Skill directory exists | Rename, offer overwrite |
| Duplicate MCP server name | Server name in `mcp.json` | Skip, offer replace |
| Duplicate memory fact (similar text) | Fuzzy match on fact text | Skip if >90% similar, else import |
| Credential already exists | Same env var name | Skip, warn user |

### 5.2 Resolution UI

The preview step presents a table:

```
┌──────────────────────────────────────────────────────────┐
│ Import Preview — Claude.ai (23 conversations, 2 agents)  │
├──────────┬─────────────────────────┬──────────┬──────────┤
│ Type     │ Name                    │ Action   │ Conflict │
├──────────┼─────────────────────────┼──────────┼──────────┤
│ Session  │ "Debug auth flow"       │ Import   │ —        │
│ Session  │ "API design review"     │ Import   │ —        │
│ Session  │ "EvoFlux architecture"  │ Skip     │ Exists   │
│ Agent    │ "consultant"            │ Rename   │ Name     │
│ Skill    │ "report-generator"      │ Import   │ —        │
│ MCP      │ "filesystem"            │ Replace  │ Exists   │
│ Setting  │ model preference        │ Merge    │ Conflict │
└──────────┴─────────────────────────┴──────────┴──────────┘
[ Import All ]  [ Import Selected ]  [ Cancel ]
```

User can toggle individual items, change resolution (import/skip/replace/rename), then execute.

---

## 6. API Design

### 6.1 Endpoints

All endpoints accept a **local filesystem path** — the Python sidecar reads files directly. No upload, no temp staging.

```
POST   /api/import/detect          # {path: "/Users/..."} -> auto-detect format, return import_id
GET    /api/import/preview/{id}    # Return full ImportBundle with conflicts
PATCH  /api/import/preview/{id}    # Update item resolutions (skip/replace/rename)
POST   /api/import/execute/{id}    # Execute import, return SSE stream of progress
GET    /api/import/history         # Past imports with source, date, counts
DELETE /api/import/{id}            # Cancel in-progress import
```

### 6.2 Request/Response Schemas

```python
# Detect request
{"path": "/Users/alice/Downloads/claude-export.json"}
# or
{"path": "/Users/alice/.claude/"}

# Detect response
{
    "import_id": "uuid",
    "detected_source": "claude_web",
    "path": "/Users/alice/Downloads/claude-export.json",
    "summary": {
        "sessions": 23,
        "agents": 2,
        "skills": 1,
        "mcp_servers": 3,
        "total_items": 29
    }
}

# Preview response
{
    "import_id": "uuid",
    "source": "claude_web",
    "items": [
        {
            "id": "item_001",
            "kind": "session",
            "label": "Debug auth flow",
            "preview": "12 messages, created 2024-01-15",
            "action": "import",      # import | skip | replace | rename
            "conflict": null,
            "target_name": "Debug auth flow"
        },
        ...
    ],
    "summary": {
        "sessions": 23,
        "agents": 2,
        "skills": 1,
        "mcp_servers": 3,
        "conflicts": 4
    }
}

# Execute SSE events
event: progress
data: {"phase": "sessions", "current": 5, "total": 23, "item": "Debug auth flow"}

event: item_done
data: {"id": "item_001", "kind": "session", "status": "imported", "target_id": "new_uuid"}

event: error
data: {"id": "item_007", "kind": "session", "error": "Malformed message at line 42"}

event: complete
data: {"imported": {"sessions": 22, "agents": 2}, "skipped": {"sessions": 1}, "errors": 0}

# History response
{
    "imports": [
        {
            "import_id": "uuid",
            "source": "claude_web",
            "path": "/Users/alice/Downloads/claude-export.json",
            "imported_at": "2026-09-30T10:00:00Z",
            "counts": {"sessions": 22, "agents": 2, "skills": 1},
            "status": "completed"
        }
    ]
}
```

### 6.3 Frontend — Tauri Dialog Integration

```typescript
// web/src/api/import.ts
import { open } from '@tauri-apps/plugin-dialog'

/** Open Tauri file/folder picker for a given source type. */
export async function pickImportSource(source: ImportSource): Promise<string | null> {
  const filters = SOURCE_FILTERS[source] // e.g. [{ name: 'JSON', extensions: ['json'] }]
  const isDirectory = DIRECTORY_SOURCES.includes(source) // claude_code, codex, cursor

  const selected = await open({
    directory: isDirectory,
    multiple: false,
    filters: isDirectory ? undefined : filters,
    title: `Select ${SOURCE_LABELS[source]} export`,
  })

  return selected // string path or null if cancelled
}

// Then call the detect endpoint with the selected path
```

---

## 7. Security Considerations

1. **Credential handling**: API keys and tokens are NEVER stored in plaintext. Imported credentials go through the existing secret storage pipeline (`app/core/`, encrypted at rest).
2. **Sandbox**: All file operations during import run inside the existing sandbox. Imported agent configs and skills go through trust validation (`plugin_platform/trust.py`).
3. **Content scanning**: Imported messages are treated as untrusted data. No auto-execution of embedded code or tool calls.
4. **Path validation**: The detect endpoint validates that the provided path exists, is readable, and matches an expected import format before parsing. No arbitrary filesystem traversal.
5. **Size limits**: Max file size for parsing (configurable, default 500MB). Max items per import (configurable, default 10,000). Streaming parser for large files.
6. **Audit trail**: Every import operation records source, path, item count, and timestamp in the `import_jobs` table for reproducibility.

---

## 8. Settings → Import

A new section in **Settings** (`web/src/routes/settings.import.tsx`) with three groups:

### 8.1 Sources Group

| Setting | Type | Default | Description |
|---|---|---|---|
| Auto-detect source format | toggle | on | Automatically detect Claude/ChatGPT/Codex/etc. from file content |
| Default conflict resolution | select | "ask" | What to do when an imported item already exists: ask, skip, replace |
| Default session import mode | select | "work" | Import sessions as Work or Coding mode |

### 8.2 Display Group

| Setting | Type | Default | Description |
|---|---|---|---|
| Show source badges | toggle | on | Display "Imported from X" badges on sessions and memory facts |
| Badge style | select | "chip" | Chip (small colored tag) or label (text line) |

### 8.3 History Group

| Setting | Type | Description |
|---|---|---|
| Import history | table | List of past imports: source, date, counts, status |
| Re-import | button | Re-run a previous import from the same path (delta mode) |
| Clear history | button | Remove import records (does not delete imported data) |

### 8.4 Source Quick-Import Buttons

At the top of Settings → Import, prominent buttons for each supported source:

```
┌─────────────────────────────────────────────────────────┐
│  Import data from another AI tool                       │
│                                                          │
│  [Claude.ai]  [Claude Code]  [ChatGPT]  [Codex]  [Cursor] │
│                                                          │
│  Or import a file:  [Select file or folder...]          │
└─────────────────────────────────────────────────────────┘
```

Each button opens the Tauri dialog with the appropriate file filter, then triggers detect → preview → execute flow.

### 8.5 settings.yaml Schema Addition

```yaml
# Add to existing settings.yaml
import:
  auto_detect: true                # auto-detect source format from file content
  default_conflict: ask            # ask | skip | replace
  default_session_mode: work       # work | coding
  show_source_badges: true         # display "Imported from X" badges
  badge_style: chip                # chip | label
  max_items_per_import: 10000      # safety limit
  max_file_size_mb: 500            # safety limit per file
```

This maps directly to the Settings → Import UI fields and is read by `import_service.py` at detect/execute time.

---

## 9. Implementation Phases

### Phase 1 — Foundation + Claude.ai (Week 1-2)

**Goal**: Import infrastructure + source tagging + Settings → Import + Claude.ai web export

| # | Task | Owner | Files |
|---|---|---|---|
| 1 | Alembic migration: add `source`, `imported_at` to `chat_sessions` and `memory_facts` | Backend | `app/migrations/` |
| 2 | Create `app/services/importers/base.py` — `ImportItem`, `ImportBundle`, `ImportResult` | Backend | New |
| 3 | Create `app/services/import_service.py` — orchestrator: detect → parse → preview → execute | Backend | New |
| 4 | Create `app/api/routes/import.py` — detect, preview, execute, history endpoints | Backend | New |
| 5 | Create `app/services/importers/claude_web.py` — Claude.ai JSON/ZIP parser | Backend | New |
| 6 | Register import routes in `app/api/app.py` | Backend | Existing |
| 7 | Create `web/src/routes/settings.import.tsx` — Settings → Import page with source buttons | Frontend | New |
| 8 | Add "Import" section to `SettingsSidebar.tsx` (Data group, with `Import` icon) | Frontend | Existing |
| 9 | Create `web/src/api/import.ts` — API client + Tauri dialog integration | Frontend | New |
| 10 | Create import preview + progress UI components | Frontend | New |
| 11 | Source badge component for sidebar rows + session header | Frontend | New |
| 12 | Add `import` section to `settings.yaml` schema + defaults | Backend | `app/core/` |
| 13 | In-app Help: `import` entry in `web/src/help/locales/` | Frontend | Existing |
| 14 | Tests: parser unit tests, API integration tests, UI component tests | Both | `tests/` |

**Deliverable**: User opens Settings → Import, clicks "Claude.ai", picks a JSON/ZIP file via Tauri dialog, sees preview with source badges, imports sessions.

### Phase 2 — ChatGPT + Claude Code (Week 3-4)

**Goal**: Cover the two other major sources

| # | Task | Owner | Files |
|---|---|---|---|
| 1 | Create `app/services/importers/chatgpt.py` — ChatGPT conversations.json parser | Backend | New |
| 2 | Create `app/services/importers/claude_code.py` — Claude Code ~/.claude/ directory parser | Backend | New |
| 3 | ChatGPT: DFS tree flattening, Custom GPTs → Skills, memory extraction | Backend | chatgpt.py |
| 4 | Claude Code: JSONL sessions, CLAUDE.md → agent, commands/ → Skills, .mcp.json merge | Backend | claude_code.py |
| 5 | Tauri dialog directory picker for Claude Code source | Frontend | import.ts |
| 6 | ZIP auto-extraction support (ChatGPT export is a ZIP) | Backend | import_service.py |
| 7 | Tests for both parsers + integration tests | Both | New test files |

**Deliverable**: User can import from ChatGPT export ZIP and Claude Code directory.

### Phase 3 — Codex + Cursor + Generic (Week 5-6)

**Goal**: Cover remaining tools and loose-file import

| # | Task | Owner | Files |
|---|---|---|---|
| 1 | Create `app/services/importers/codex.py` — Codex CLI parser | Backend | New |
| 2 | Create `app/services/importers/cursor.py` — Cursor rules/MCP/history parser | Backend | New |
| 3 | Create `app/services/importers/generic.py` — loose file auto-detect | Backend | New |
| 4 | Generic: MCP JSON, SKILL.md, agent .md, plugin.json, .env credentials | Backend | generic.py |
| 5 | Credential import flow with encryption | Backend | generic.py |
| 6 | Conflict resolution UI — toggle individual items, change resolution | Frontend | Import views |
| 7 | Delta import — re-import same source, only process new items | Backend | import_service.py |
| 8 | Tests for all new parsers | Both | New test files |

**Deliverable**: User can import from Codex, Cursor, and any loose files.

### Phase 4 — Polish + Production (Week 7-8)

**Goal**: Production quality, CLI, docs

| # | Task | Owner | Files |
|---|---|---|---|
| 1 | Bulk import CLI command (`evoflux import <path>`) | Backend | `app/cli/` |
| 2 | Import history management (re-import, clear) in Settings | Frontend | settings.import.tsx |
| 3 | EvoFlux → EvoFlux backup/restore (export + import own data) | Both | New |
| 4 | Performance: batch inserts, streaming JSON for large files | Backend | import_service.py |
| 5 | Help page + documentation: feature page, architecture update | Docs | `documents/` |
| 6 | CHANGELOG entry | Docs | `CHANGELOG.md` |
| 7 | E2E tests: full import flow for each source | Both | `tests/` |

**Deliverable**: Production-ready import system with CLI, history, and full documentation.

---

## 9. Testing Strategy

### Unit Tests
- Each parser: parse known-good export files, verify ImportBundle output
- Conflict detection: duplicate session/agent/skill/MCP detection
- Field mapping: verify timestamps, roles, content structure conversion

### Integration Tests
- Full import pipeline: upload → detect → preview → execute → verify DB state
- Error handling: malformed files, missing fields, oversized uploads
- Concurrent import: two imports running simultaneously don't corrupt state

### Test Fixtures
- `tests/fixtures/imports/claude_web_export.json` — sample Claude.ai export
- `tests/fixtures/imports/chatgpt_export.zip` — sample ChatGPT export
- `tests/fixtures/imports/claude_code/` — sample Claude Code directory
- `tests/fixtures/imports/cursor/` — sample Cursor workspace
- `tests/fixtures/imports/generic/` — loose MCP/Skill/Agent files

### E2E Tests
- Upload → preview → import → verify sessions visible in sidebar
- Import agent → verify appears in Settings → Agents
- Import Skill → verify appears in Skills catalog
- Import MCP servers → verify merged into mcp.json

---

## 10. Open Questions — Resolved & Remaining

### Resolved (confirmed by user)

| # | Question | Decision |
|---|---|---|
| 1 | Should imported sessions be marked differently? | **Yes** — source badge + `source`/`imported_at` metadata fields on sessions, memory, and file-based entities |
| 2 | File upload or local filesystem? | **Local filesystem** — Tauri dialog picks files/folders, Python sidecar reads directly. No web upload. |
| 3 | Where to configure import behavior? | **Settings → Import** — dedicated section with source buttons, defaults, display options, and history |

### Remaining (to decide during implementation)

| # | Question | Options | Current lean |
|---|---|---|---|
| 4 | Import Claude Code sessions as Work or Coding mode? | Always Work, detect from context, ask user | Detect from session content; default to Work, let user reclassify |
| 5 | How to handle ChatGPT's DALL-E image references? | Skip, download, note-as-metadata | Note as metadata with original URL; images may expire |
| 6 | Should we support direct API import (call Claude/ChatGPT API)? | File-only, file+API, API-only | Phase 1: file-only. Future: optional API pull |
| 7 | How to merge imported MCP servers with existing ones? | Skip, replace, rename, merge-by-name | Merge-by-name with conflict resolution UI |
| 8 | Memory import granularity: facts or raw text? | Extract facts with LLM, import raw, both | Offer both: raw text as wiki notes, optional LLM extraction for facts |
| 9 | Multi-language support for import UI? | EN only, EN+VI, full i18n | EN first, VI in Phase 4 |

---

## 11. Success Metrics

- **Coverage**: Import from 5+ source tools (Claude.ai, Claude Code, ChatGPT, Codex, Cursor)
- **Fidelity**: >95% of messages imported with correct role, content, and timestamps
- **Performance**: 1000-session import completes in <60 seconds
- **UX**: User can go from "I have a Claude export" to "all my data is in EvoFlux" in <5 minutes
- **Zero data loss**: Every importable item is either imported or explicitly skipped by user choice

---

## 12. File Inventory (New Files)

```
app/services/importers/
├── __init__.py
├── base.py              # ImportItem, ImportBundle, ImportResult dataclasses
├── claude_web.py        # Claude.ai web JSON parser
├── claude_code.py       # Claude Code directory parser
├── chatgpt.py           # ChatGPT conversations.json parser
├── codex.py             # Codex CLI parser
├── cursor.py            # Cursor rules/MCP parser
├── generic.py           # Loose file detection and import
└── _mapping.py          # Shared mapping helpers (timestamps, roles, content)

app/services/import_service.py   # Orchestrator: detect → parse → preview → execute

app/api/routes/import.py         # FastAPI routes for import workflow

tests/fixtures/imports/          # Test fixture files
tests/services/importers/        # Parser unit tests
tests/api/routes/test_import.py  # API integration tests

web/src/views/Import/            # Import UI components
web/src/api/import.ts            # Import API client
```

---

## 14. Dependencies & Risks

| Risk | Impact | Mitigation |
|---|---|---|
| ChatGPT export format changes | Parser breaks | Version detection + fallback parsing + clear error messages |
| Large exports (>1GB) cause memory issues | OOM | Streaming JSON parser (ijson), batch processing |
| Claude Code JSONL format undocumented | Incomplete parsing | Start with observed format, add tolerance for unknown fields |
| Cursor stores history in SQLite (not easily exportable) | Cannot import chat history | Document limitation; import rules/MCP only |
| User picks wrong file/folder | Confusion | Auto-detect with clear error: "This doesn't look like a Claude export" |
| Imported sessions lack tool call details | Lower fidelity | Preserve what's available, note missing data in metadata |
| Tauri dialog permissions on macOS/Linux | File picker may fail | Fallback to manual path input field; document required permissions |
| Source format has nested ZIP (ChatGPT export) | Double extraction | Handle ZIP extraction in orchestrator before passing to parser |
