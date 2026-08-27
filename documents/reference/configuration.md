# Configuration reference

EvoFlux combines environment settings, user-editable configuration files and
database-backed UI state. Settings APIs write known schemas atomically and do
not rewrite user Agent/Skill files merely by reading them.

## Runtime roots

Production defaults:

| Variable | Default | Contents |
|---|---|---|
| `EVOFLUX_DATA_DIR` | `~/.local/share/evoflux` | database and durable internal data |
| `EVOFLUX_CONFIG_DIR` | `~/.config/evoflux` | editable configuration and secrets |
| `EVOFLUX_STATE_DIR` | `~/.local/state/evoflux` | logs, telemetry and snapshots |
| `EVOFLUX_CACHE_DIR` | `~/.cache/evoflux` | regeneratable indexes, OAuth cache and previews |
| `EVOFLUX_WORKSPACE_DIR` | `~/.local/share/evoflux-workspace` | Work session files/uploads |
| `EVOFLUX_WIKI_DIR` | `~/.local/share/evoflux-wiki` | Markdown memory wiki |

Development defaults live below `.evoflux/dev/{data,config,state,cache,workspace,wiki}`
in the repository. All roots can be overridden with absolute paths.

Derived values:

- `DATABASE_URL` defaults to `sqlite+aiosqlite:///<data>/evoflux.db`.
- `AGENTS_DIR` defaults to `<config>/agents`.
- `SKILLS_DIR` defaults to `<config>/skills`.
- `EVOFLUX_PLUGINS_DIRS` defaults to `<config>/plugins` and accepts an
  OS-path-separator-delimited list.

## Configuration files

| File/location | Owner | Purpose |
|---|---|---|
| `<config>/.env` | user/Settings | provider and integration credentials |
| `<config>/settings.yaml` | Settings/runtime | typed operational preferences |
| `<config>/agents/**/*.md` | user | agent frontmatter and prompt overrides |
| `<config>/skills/*/SKILL.md` | user | custom Skill bundles |
| `<config>/skill-settings.json` | Settings | per-discovered-variant runtime overlay |
| `<config>/mcp.json` | user/Settings | global stdio/HTTP MCP servers |
| `<config>/sandbox.yaml` | user/Settings | denied paths and outbound policy |
| `<config>/model_registry.yaml` | operator | model capability/metadata corrections |
| `<config>/workflows/*.yaml` | user | global Workflow definitions |
| `<config>/plugins/*.py` | trusted user | legacy in-process hook plugins |
| `<data>/agent-plugins/` | Plugin Center | installed package registry and private data |
| `<workspace>/.evoflux/workflows/*.yaml` | repository | project-local Coding Workflows |
| `<workspace>/.evoflux/launch.json` | repository | preview/process launch definitions |
| `<workspace>/.evoflux/easd/config.json` | repository/EASD setup | safe `data_directory`, core rules/templates, and exact project-skill contract in the current unversioned layout |
| `<workspace>/<data_directory>/` | repository | EASD knowledge base: accepted Specs, adopted feature/architecture/reference docs, templates, historical records, and Run ledgers (default `documents/easd`) |
| `<workspace>/.evoflux/easd/.local/` | machine-local | ignored rebuildable EASD locks/index/session bindings; never normative |
| `<workspace>/.evoflux/skills/easd-*/` | repository | Coding-only portable EASD phase Skills installed by EASD setup |

Project `.env` is loaded first and `~/.config/evoflux/.env` overrides it.
Process environment values follow Pydantic settings precedence. Keep secrets out
of committed repository files.

## `settings.yaml` sections

| Section | Important fields |
|---|---|
| `title_generation` | `enabled`, optional `model` |
| `dream` | `enabled`, optional `model`, cron `schedule` |
| `memory_extraction` | `enabled`, message thresholds, input cap, optional model |
| `memory_vector` | experimental backend enable/model/dimension/index path |
| `server` | loopback/LAN `host`, `port`, optional `access_key` |
| `providers` | per-provider `visible_models` |
| `git` | network timeout, diff cap, pull strategy, prune, force-push policy |
| `code_reviews` | timeouts/retries/page/concurrency caps and mutation/TLS/check policy |
| `browser` | built-in browser domain and action permissions |
| `webbridge` | enable/domain/evaluate, sharing, retention and interaction policy |
| `conductor` | connection, intervals, enforcement and managed identity metadata |

Unknown keys are ignored for forward compatibility; known values are validated
before atomic save. Models use `provider:model`.

## Core environment settings

| Setting | Meaning |
|---|---|
| `APP_ENV` | selects production versus repository-local development defaults |
| `LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING` or `ERROR` |
| `SSL_VERIFY` | TLS verification for supported HTTP clients |
| `CORS_ORIGINS` | allowed development/external API origins |
| `EVOFLUX_MODEL_REGISTRY_REFRESH` | allow refreshed `models.dev` metadata |
| `EVOFLUX_CODE_INDEX_EXECUTION` | `process` (production) or test/embedder `thread` |
| `EVOFLUX_DESKTOP_TOKEN` | random desktop-shell bearer token |
| `EVOFLUX_ACCESS_KEY` | external/LAN bearer fallback |
| `EVOFLUX_BASH` | explicit Bash executable on Windows when auto-detection fails |
| `EVOFLUX_WEBBRIDGE_EXTENSION_IDS` | optional allowed extension IDs |

## Provider credentials

Common keys include `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, `OPENAI_API_KEY`,
`OPENROUTER_API_KEY`, `ZAI_API_KEY`, `NVIDIA_API_KEY`, `XAI_API_KEY`,
`DEEPSEEK_API_KEY`, `DASHSCOPE_API_KEY`, `XIAOMI_API_KEY`, `FCI_API_KEY`,
`MOONSHOT_API_KEY`,
`FOUNDRY_API_KEY`, and provider-specific base URL/resource fields. Bedrock uses
the standard AWS credential chain/profile and region. Vertex uses Google cloud
project/location credentials. Codex and Copilot use OAuth cache files created
by `evoflux auth` or Settings.

QwenCloud uses `DASHSCOPE_BASE_URL` when the key belongs to Token Plan, Coding
Plan, or another host instead of the default international pay-as-you-go API.
The value is the full OpenAI-compatible root, including `/compatible-mode/v1`
where QwenCloud documents it, and must match the selected key type.

The canonical credential field catalogue is `app/agent/providers/catalog.py`;
do not duplicate provider secrets into Agent Markdown.

## Sandbox configuration

`sandbox.yaml` controls denied filesystem patterns, worktree location and
outbound secret/PII policy. Fresh configuration protects `**/.env` and
`**/.env.*`. The sandbox additionally denies internal data/state/cache roots
regardless of the active workspace.

## Configuration safety

- Settings writes use temporary files plus atomic replacement.
- Secret fields are masked in API responses.
- Global MCP `$VAR`/`${VAR}` references resolve at connection time.
- Plugin credentials remain installation-scoped and outside packages.
- Cache files may be deleted and regenerated; config/data/wiki should be
  backed up according to [Data and storage](../architecture/data-and-storage.md).
