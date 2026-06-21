---
title: Paths & XDG Roots
description: Six XDG-aligned roots, development vs production layout, on-disk file map.
status: stable
updated: 2026-05-30
---

# Paths & XDG Roots

**Sources:** `app/core/config.py`, `app/core/paths.py`

EvoFlux splits runtime files across **six** XDG-aligned roots, one per category of data. Each is overridable via an environment variable; all six are derived automatically from `APP_ENV` when unset.

## Roots

| Root | Env var | Production default | Development default | Sandbox |
|------|---------|--------------------|---------------------|---------|
| Data | `EVOFLUX_DATA_DIR` | `~/.local/share/EvoFlux` | `.EvoFlux/dev/data` | denied |
| Config | `EVOFLUX_CONFIG_DIR` | `~/.config/EvoFlux` | `.EvoFlux/dev/config` | allowed |
| State | `EVOFLUX_STATE_DIR` | `~/.local/state/EvoFlux` | `.EvoFlux/dev/state` | denied |
| Cache | `EVOFLUX_CACHE_DIR` | `~/.cache/EvoFlux` | `.EvoFlux/dev/cache` | denied |
| Workspace | `EVOFLUX_WORKSPACE_DIR` | `~/.local/share/EvoFlux-workspace` | `.EvoFlux/dev/workspace` | allowed |
| Wiki | `EVOFLUX_WIKI_DIR` | `~/.local/share/EvoFlux-wiki` | `.EvoFlux/dev/wiki` | allowed |

**What lives where:**

- **Data** — irreplaceable user data. SQLite DB (`EvoFlux.db`) and session artifacts (`sessions/{id}/`). **Back this up.**
- **Config** — hand-edited configuration. Agents (`agents/`), skills (`skills/`), runtime settings (`settings.yaml`), MCP (`mcp.json`), sandbox (`sandbox.yaml`), `.env`. (Summarisation has no file-based config — all tuning lives in `app/agent/hooks/summarization.py`.)
- **State** — historical bookkeeping. Logs (`logs/`), telemetry (`telemetry/`), OTEL rollups (`otel/`), `EvoFlux.pid`. Safe to archive.
- **Cache** — regeneratable throwaway. `quoteoftheday.json`, `copilot_oauth.json`, `codex_oauth.json`. Safe to delete any time.
- **Workspace** — per-session agent workspaces (`{root}/<sid>/`). User uploads live at `{root}/<sid>/uploads/`. Allowed by the sandbox so filesystem tools (`read`/`write`/`shell`) can operate there.
- **Wiki** — agent memory (`USER.md`, `INDEX.md`, `LOG.md`, `LINT.md`, knowledge dirs, `notes/`). See [`agent/memory.md`](../agent/memory.md).

## `.env` location

Two `.env` files are loaded if present — the home-config file takes priority over the project one:

| Mode | `.env` location |
|------|-----------------|
| Production | `~/.config/EvoFlux/.env` |
| Development | `.env` (project root) |

## Full directory layout

Dev-mode paths shown below — substitute the production columns from the table above:

```
.EvoFlux/
├── dev/                                   # local development runtime state
│   ├── data/                              # EVOFLUX_DATA_DIR
│   │   ├── EvoFlux.db                  # main SQLite DB
│   │   └── sessions/{session_id}/         # session runtime artifacts
│   │       ├── .todos.json                # todo_manage store
│   │       └── .tool_results/
│   │           ├── shell/*.txt            # large shell output spills
│   │           └── {agent}/*.txt          # large tool-result offloads
│   ├── wiki/                              # EVOFLUX_WIKI_DIR
│   │   ├── USER.md                        # pure YAML, injected into system prompt
│   │   ├── INDEX.md                       # dream-maintained TOC
│   │   ├── LOG.md                         # service-managed dream/lint log
│   │   ├── LINT.md                        # latest dream lint report
│   │   ├── topics/                        # concept pages
│   │   ├── entities/                      # concrete things
│   │   ├── sources/                       # one page per ingested source
│   │   ├── comparisons/                   # X-vs-Y pages
│   │   └── notes/                         # agent notes
│   ├── workspace/                         # EVOFLUX_WORKSPACE_DIR
│   │   └── {lead_session_id}/             # normal-mode workspace
│   │       └── uploads/<uuid>.<ext>       # user uploads (reachable as `uploads/<filename>`)
│   ├── config/                            # EVOFLUX_CONFIG_DIR
│   │   ├── .env                           # secrets (gitignored)
│   │   ├── agents/*.md                    # per-agent config
│   │   ├── agents/coding/*.md             # coding-mode team
│   │   ├── skills/{name}/SKILL.md         # skills
│   │   ├── settings.yaml                  # Dream + title generation runtime settings
│   │   ├── mcp.json                       # MCP server config
│   │   ├── sandbox.yaml                   # user-defined deny patterns
│   │   └── plugins/                       # user plugin .py drop-ins (EVOFLUX_PLUGINS_DIRS)
│   ├── state/                             # EVOFLUX_STATE_DIR
│   │   ├── logs/
│   │   │   ├── app/app.log                # JSON app log (10 MB / 7 days)
│   │   │   └── sessions/{session_id}/
│   │   │       ├── session.log            # human-readable per-session sink
│   │   │       └── {agent}.jsonl          # structured events (SessionLogHook)
│   │   ├── telemetry/{session_id}/{user_msg_id}.jsonl  # context window snapshots
│   │   ├── snapshot/{session_id}/         # out-of-tree git repo for /undo + /redo
│   │   ├── otel/                          # OTEL spans + metrics
│   │   └── EvoFlux.pid                 # server PID file
│   └── cache/                             # EVOFLUX_CACHE_DIR
│       ├── quoteoftheday.json             # Quote of the Day cache
│       ├── copilot_oauth.json             # GitHub Copilot token
│       └── codex_oauth.json               # OpenAI Codex OAuth token
├── commands/                              # project slash commands
└── skills/                                # project skills
```

## Session path helpers (`app/core/paths.py`)

Backend code never constructs session paths inline. Two pure helpers return the canonical `Path` objects:

| Helper | Path | Ownership |
|--------|------|-----------|
| `workspace_dir(sid)` | `{EVOFLUX_WORKSPACE_DIR}/{sid}` | Agent workspace root. File bytes served at `GET /api/team/{sid}/media/{path}`; flat recursive listing at `GET /api/team/{sid}/files`. |
| `uploads_dir(sid)` | `{workspace_dir(sid)}/uploads` | User uploads (flat, UUID names). Served at `GET /api/team/{sid}/uploads/{filename}`. Lives **inside** the session workspace so filesystem tools can pass uploads to workspace-bound tools as `uploads/<filename>`. |

Session-scoped agent artifacts are centralized in `app/agent/artifacts.py` and live below `{EVOFLUX_DATA_DIR}/sessions/{session_id}/`:

| Artifact | Path | Cleanup |
|----------|------|---------|
| Todos | `.todos.json` | Deleted with the session artifact directory. |
| Shell output spills | `.tool_results/shell/*.txt` | Deleted with the session artifact directory or cleanup. |
| Tool-result offloads | `.tool_results/{agent}/*.txt` | Deleted with the session artifact directory or cleanup. |

Coding sessions use the selected project directory as the sandbox workspace, but runtime artifacts never write into the repo. Upload storage remains under `EVOFLUX_WORKSPACE_DIR`. `DELETE /api/team/sessions/{id}` purges normal session workspaces and the XDG session artifact directory; coding sessions keep the project directory.

## Generated artifact cleanup

`EvoFlux cleanup` performs a dry run by default:

```bash
EvoFlux cleanup                    # list artifacts older than 14 days
EvoFlux cleanup --older-than-days 7
EvoFlux cleanup --apply            # delete the listed artifacts
```

Cleanup targets generated, regeneratable artifacts only:

- orphaned normal session workspaces under `EVOFLUX_WORKSPACE_DIR`;
- orphaned session artifact directories under `{EVOFLUX_DATA_DIR}/sessions/`;
- old state logs, telemetry files, and OTEL files.

It intentionally does not delete `EVOFLUX_DATA_DIR`, `EVOFLUX_CONFIG_DIR`, `EVOFLUX_WIKI_DIR`, or credential/cache files.
