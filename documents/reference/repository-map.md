# Repository map

## Top-level layout

```text
app/          Python sidecar: API, agent harness, persistence and services
web/          React/TypeScript interface embedded in the desktop WebView
desktop/      Tauri/Rust shell, native capabilities and packaging
seed/         First-install agent/config templates
scripts/      Build, release, validation and smoke-test utilities
tests/        Python backend, service, CLI and packaging tests
documents/      Project documentation plus repository-owned EASD knowledge/Run data
test-artifacts/  Checked-in visual evidence used by selected tests/reviews
```

## Backend map

| Path | Responsibility |
|---|---|
| `app/api/app.py` | FastAPI lifecycle, middleware and router mounting |
| `app/api/routes/` | Thin HTTP, SSE, upload and WebSocket boundaries |
| `app/api/schemas/` | Shared request/response contracts |
| `app/agent/agent_loop/` | Streaming model loop, retries and tool dispatch |
| `app/agent/mode/team/` | Lead/specialist lifecycle, mailbox and delegation |
| `app/agent/hooks/` | Context, memory, streaming, telemetry and post-edit stages |
| `app/agent/providers/` | Nineteen provider adapters and model metadata |
| `app/agent/tools/` | Built-in and multimodal tool registry |
| `app/agent/skills/` | Skill discovery, catalog, resolution and activation |
| `app/easd_skills/` | Packaged EASD phase Skills, core rules, knowledge skeleton, and YAML/Markdown templates installed only by setup |
| `app/agent/mcp/` | User-global MCP configuration and runtime |
| `app/plugin_platform/` | Portable Agent Plugin lifecycle and isolated MCP |
| `app/services/` | Business logic shared by API, CLI and agents |
| `app/services/code_index/` | Repository-local parsing, indexing and graph queries |
| `app/workflow/` | Workflow schema, graph, runner and node handlers |
| `app/scheduler/` | At/every/cron scheduling and team dispatch |
| `app/conductor/` | Optional managed-resource control plane client |
| `app/models/` | Application SQLModel tables |
| `app/migrations/` | Alembic schema history |
| `app/core/` | Paths, configuration, database, auth and observability primitives |
| `app/cli/` | `evoflux` command-line interface |

Backend changes must follow the nearest `AGENTS.md`; routes stay thin and
durable logic belongs in services, agent runtime, workflow, or core modules.

## Frontend map

| Path | Responsibility |
|---|---|
| `web/src/router.ts` | Work, Coding, Telemetry and Scheduler route tree |
| `web/src/routes/work.tsx` | Work/Coding layout selection and session focus |
| `web/src/components/TeamChatView/` | Main chat/workbench composition and SSE integration |
| `web/src/components/workbench/` | Dock, tool registry and open-with behavior |
| `web/src/components/settings/` | Shared Settings editors and controls |
| `web/src/stores/` | Zustand client/stream state |
| `web/src/queries/` | TanStack Query server-state hooks |
| `web/src/api/` | HTTP, SSE, auth and Tauri API boundary |
| `web/src/help/locales/` | Localized in-app Help Center content |
| `web/src/lib/` and `web/src/utils/` | Cross-feature browser-side contracts |
| `web/src/__tests__/` | Vitest component, store, API and utility tests |

Settings open as an application overlay rather than a standalone TanStack
route. Workbench features are lazy-loaded from `TeamChatView` so the initial
chat surface does not eagerly load every editor, graph, Git, preview and browser
dependency.

## Desktop and packaging map

| Path | Responsibility |
|---|---|
| `desktop/src-tauri/src/main.rs` | Tauri application assembly and native commands |
| `desktop/src-tauri/src/sidecar.rs` | Sidecar discovery, launch, handshake and health |
| `desktop/src-tauri/src/workspace.rs` | Native workspace and filesystem integration |
| `desktop/src-tauri/src/native_messaging.rs` | Browser/native messaging bridge |
| `desktop/src-tauri/capabilities/` | Tauri permission grants |
| `desktop/src-tauri/tauri*.json` | Production and development configurations |
| `desktop/Makefile` | Sidecar, dev, icon and package targets |
| `scripts/build_sidecar.py` | Standalone Python runtime and dependency bundle |
| `scripts/build_dmg.sh`, `scripts/build_msi*` | Platform installer helpers |

## Test ownership

The Python suite mirrors the backend layout: `tests/agent`, `tests/api`,
`tests/services`, `tests/core`, `tests/workflow`, `tests/scheduler`,
`tests/plugin_platform`, `tests/conductor`, `tests/cli`, and packaging tests.
Frontend tests live under `web/src/__tests__`; Rust unit tests are colocated in
`desktop/src-tauri/src`.

Prefer the smallest focused suite during iteration, then run the component's
documented checks before handoff. See [Development and testing](../development/setup-and-testing.md).
