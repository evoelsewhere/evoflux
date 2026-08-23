# Feature catalogue

This catalogue is the implementation index for EvoFlux. It was derived from
FastAPI routers, service modules, agent tools and hooks, React routes and
components, SQLModel tables, Alembic migrations, and test coverage.

Status meanings:

- **Implemented**: available in the current runtime and backed by tests.
- **Optional**: implemented but requires configuration, credentials, an
  external executable, or a companion product.
- **Internal**: shipped infrastructure without a primary end-user surface.
- **Planned**: represented only by a plan; not an implemented claim.

## Product surfaces

| Area | Status | User surface | Primary implementation | Detailed contract |
|---|---|---|---|---|
| Work mode | Implemented | `/`, Work sidebar and chat | `web/src/routes/work.tsx`, `app/api/routes/team/chat.py` | [Modes and sessions](modes-workspaces-and-sessions.md) |
| Coding mode | Implemented | `/coding/:focusId/:sessionId?` | `web/src/routes/work.tsx`, coding project/workspace services | [Modes and sessions](modes-workspaces-and-sessions.md) |
| Lead and specialists | Implemented | Agent transcript, Monitor, delegation cards | `app/agent/mode/team/`, `app/services/team_manager.py` | [Agent runtime and teams](agent-runtime-and-teams.md) |
| Streaming chat | Implemented | Chat transcript and activity blocks | `app/agent/agent_loop/`, team SSE routes, `useTeamSse.ts` | [Agent runtime and teams](agent-runtime-and-teams.md) |
| Session history | Implemented | Sidebars, folders, pin/rename/duplicate/delete | chat/session services and Zustand/query caches | [Modes and sessions](modes-workspaces-and-sessions.md) |
| Plan review and questions | Implemented | Plan panel, permission and question modals | execution policy, interactive-message service, SSE | [Security and permissions](security-and-permissions.md) |
| Durable Goal mode | Implemented | `/goal` commands and progress row | goal model/service/hooks and team continuation | [Automation](automation.md) |
| Workflows | Implemented | Slash invocation, browser composer and API | `app/workflow/`, workflow routes and models | [Automation](automation.md) |
| Scheduler | Implemented | `/scheduler`, workbench panel, schedule tool | `app/scheduler/`, scheduler routes | [Automation](automation.md) |
| Files and uploads | Implemented | File tree, upload, media and preview surfaces | team file routes, workspace watcher, preview service | [Workbench and files](workbench-files-and-side-chat.md) |
| Terminal and processes | Implemented | Workbench terminal and process panels | terminal/process services, HTTP and WebSocket routes | [Workbench and files](workbench-files-and-side-chat.md) |
| Side Chat (`/btw`) | Implemented | Docked Side Chat panel | side-chat routes and `SideChatPanel/` | [Workbench and files](workbench-files-and-side-chat.md) |
| Document preview | Optional | Read-only PDF/DOCX/XLSX/PPTX/HTML preview | `app/services/document_preview/` | [Workbench and files](workbench-files-and-side-chat.md) |
| Code index and graph | Implemented | Code graph, search, agent `code_context` tool | `app/services/code_index/` | [Coding intelligence](coding-intelligence.md) |
| LSP and Problems | Optional | Problems, rename, quick fixes, semantic actions | LSP manager/service, ChangeSets, Problems service | [Coding intelligence](coding-intelligence.md) |
| Git source control | Implemented | Changes, history, branches, stash and sync | Git routes/services and `GitWorkspacePanel.tsx` | [Git and guarded edits](git-reviews-and-guarded-edits.md) |
| Pull/merge request review | Optional | Pull Requests panel and review sessions | review routes, code-review service, provider connections | [Git and guarded edits](git-reviews-and-guarded-edits.md) |
| Memory facts | Implemented | Automatic recall and `memory_search` | scoped memory models/service and memory hooks | [Memory and Dream](memory-and-dream.md) |
| Markdown wiki and Dream | Optional | Wiki panel and Dream settings/run | wiki/dream services and Dream scheduler | [Memory and Dream](memory-and-dream.md) |
| Model providers | Optional | Providers, model picker and per-agent model | provider catalog/factory/adapters | [Models and providers](models-and-providers.md) |
| Agent Skills | Implemented | Composer selection and Settings editor | skill discovery, resolution and activation | [Tools and integrations](tools-skills-mcp-and-plugins.md) |
| MCP client | Optional | MCP settings and agent tools | `app/agent/mcp/` and MCP routes | [Tools and integrations](tools-skills-mcp-and-plugins.md) |
| Agent Plugins | Optional | Plugin Center and CLI | `app/plugin_platform/` | [Tools and integrations](tools-skills-mcp-and-plugins.md) |
| Built-in browser | Optional | Persistent browser workbench | direct-browser bridge and Tauri commands | [Browser and WebBridge](browser-and-webbridge.md) |
| WebBridge | Optional | Browser companion status and side panel | WebBridge routes/models/services; external extension | [Browser and WebBridge](browser-and-webbridge.md) |
| Sandbox and permissions | Implemented | Permission modes and Settings | permission engine, sandbox and outbound redaction | [Security and permissions](security-and-permissions.md) |
| Telemetry and diagnostics | Implemented | `/telemetry`, Diagnostics, health and metrics | OTEL, DuckDB aggregation, Prometheus, diagnostics routes | [Observability](observability-and-diagnostics.md) |
| Conductor managed resources | Optional | Connection/enterprise settings | `app/conductor/` and settings routes | [Security and permissions](security-and-permissions.md) |
| Desktop packaging and updates | Implemented | Native app, updater and installers | `desktop/`, packaging scripts and CI | [Release and packaging](../development/release-and-packaging.md) |

## Explicit non-claims

- EvoFlux is a desktop product. Vite and the FastAPI-only wheel are development
  and integration surfaces, not a separately positioned hosted web product.
- WebBridge extension source and distribution live in the separate
  `evo-webbridge` repository.
- Workflow node kinds `workflow` and `wait` validate as reserved Phase 2 kinds
  but are rejected by the current runner.
- Coding semantic intelligence does not claim code completion, next-edit
  prediction, a debugger, or automatic OS package-manager installation.
- Office previews are read-only. Core PDF/HTML intake is distinct from optional
  Office rendering engines.

## Coverage rule

A new top-level API router, persistent model, standalone page, workbench tool,
agent tool family, or settings section should either map to an existing row or
add a new row here. A feature is not completely documented until its runtime,
storage, security boundary, public interface, and focused tests are discoverable
from this catalogue.
