# CLI reference

The `evoflux` CLI manages first-run configuration, an API-only background
server, embedded foreground serving, diagnostics, migration, upgrades and
portable Agent Plugins. The native desktop app normally supervises `serve`
directly.

## Command map

| Command | Purpose |
|---|---|
| `evoflux init` | choose provider/model, save credentials and install seed config |
| `evoflux migrate` | import an OpenClaw or Hermes agent configuration |
| `evoflux auth` | authenticate Codex or Copilot OAuth providers |
| `evoflux start` | launch the API server as a background process |
| `evoflux serve` | run a foreground embedded/API server |
| `evoflux stop` / `restart` | manage the background server |
| `evoflux status` / `address` | show process state and local/LAN URLs |
| `evoflux health` / `doctor` | server diagnostics or install/config checks |
| `evoflux logs` | tail the background server log |
| `evoflux cleanup` | list or remove old generated artifacts |
| `evoflux upgrade` | upgrade through Homebrew, uv tool, pipx or pip |
| `evoflux plugin` | portable Agent Plugin lifecycle |
| `evoflux version` | print the installed version |

Run any command with `--help` for the current flags.

## First-time setup

```bash
evoflux init
```

The interactive flow writes/merges `<config>/.env`, installs seed agents and
`mcp.json` without overwriting existing user files, and creates typed runtime
settings. Existing installations retain their edited agent/Skill files.

OAuth providers use:

```bash
evoflux auth --list
evoflux auth codex
evoflux auth copilot
```

## Server lifecycle

```bash
evoflux start
evoflux status
evoflux address
evoflux health
evoflux logs
evoflux stop
```

`start` uses `settings.yaml` server host/port unless overridden. `--lan` binds
`0.0.0.0`; pair it with `--key` or a configured access key.

`serve` is for Tauri, CI and supervisors:

```bash
evoflux serve --host 127.0.0.1 --port 0 \
  --handshake --generate-token --parent-pid <pid>
```

It stays in the foreground, lets the server socket choose an ephemeral port,
emits one handshake line and exits when the parent dies.

## Migration

```bash
evoflux migrate openclaw --from ~/.openclaw/workspace \
  --model openai:gpt-5.5
evoflux migrate hermes --from ~/.hermes --model anthropic:claude-sonnet-4-6
```

`--name` controls the imported lead name, `--config-dir` changes the target and
`--force` replaces an existing imported agent. Migration converts supported
prompt/context files; it does not execute source-tool plugins.

## Artifact cleanup

Cleanup is dry-run by default:

```bash
evoflux cleanup --older-than-days 14
evoflux cleanup --older-than-days 30 --apply
```

Candidates are generated artifacts, not user configuration or arbitrary
workspace roots. Review dry-run output before `--apply`.

## Agent Plugins

```bash
evoflux plugin inspect ./plugin
evoflux plugin create ./plugin --name example
evoflux plugin pack ./plugin
evoflux plugin install ./plugin.evoplugin
evoflux plugin link ./plugin
evoflux plugin list
evoflux plugin show <installation-id>
evoflux plugin enable <installation-id>
evoflux plugin disable <installation-id>
evoflux plugin update <installation-id> ./plugin.evoplugin
evoflux plugin uninstall <installation-id>
```

Install/link defaults are deliberately disabled until trust review. See the
[Agent Plugin guide](../guides/agent-plugins.md).

## Development commands

Repository development primarily uses `make`, `uv`, `bun` and `cargo` rather
than the installed CLI. See [Development and testing](../development/setup-and-testing.md).
