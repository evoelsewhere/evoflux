# Migration

Move existing local agent setup from other harnesses into EvoFlux.

EvoFlux migration is focused on reusable setup: agent identity, standing instructions, project context, skills/workflows, and provider configuration. It does not import private runtime state from other tools unless explicitly noted.

## What To Migrate

| Source material | EvoFlux destination |
|-----------------|------------------------|
| Agent identity and behavior prompts | `~/.config/EvoFlux/agents/<name>.md` |
| Reusable workflows or commands | `~/.config/EvoFlux/skills/<skill>/SKILL.md` |
| Project-local instructions | Keep as repo `AGENTS.md` for coding mode |
| API keys | `~/.config/EvoFlux/.env` or **Settings → Providers** |
| OAuth providers | `EvoFlux auth <provider>` or **Settings → Providers** |
| Long-term user memory | `~/.local/share/EvoFlux-wiki/USER.md` |

Run `EvoFlux init` first if this is a fresh EvoFlux install. It creates the config directory and seeds the default agents/skills without overwriting existing files.

## From OpenClaw

EvoFlux has a built-in OpenClaw importer through `EvoFlux migrate`:

```bash
EvoFlux migrate openclaw --from ~/.openclaw/workspace --model openai:gpt-5.5
```

The importer reads these files when present: `AGENTS.md`, `SOUL.md`, `SOULS.md`, `TOOLS.md`.

It writes one lead agent to `~/.config/EvoFlux/agents/openclaw.md`. Existing files are not overwritten unless you pass `--force`. The command also supports `--config-dir` for importing into a non-default EvoFlux config directory.

Use `--name` if you want a different agent filename:

```bash
EvoFlux migrate openclaw --from ~/my-project --name project-agent --model openai:gpt-5.5
```

## From Hermes Agent

EvoFlux has a built-in Hermes importer through `EvoFlux migrate`:

```bash
EvoFlux migrate hermes --from ~/.hermes --model openai:gpt-5.5
```

The importer reads these files when present: `SOUL.md`, `.hermes.md`, `HERMES.md`, `AGENTS.md`, `CLAUDE.md`, `.cursorrules`.

It writes one lead agent to `~/.config/EvoFlux/agents/hermes.md`. Existing files are not overwritten unless you pass `--force`. The command also supports `--config-dir` for importing into a non-default EvoFlux config directory.

Use `--from` with a project directory if your Hermes context is project-local instead of under `~/.hermes`.

See `EvoFlux migrate --help` for the full flag reference.

## From Claude Code

There is no automatic Claude Code importer yet. Migrate the durable setup manually:

1. Copy reusable personal instructions from `~/.claude/CLAUDE.md` into `~/.config/EvoFlux/agents/<name>.md` or `~/.local/share/EvoFlux-wiki/USER.md`.
2. Keep project `CLAUDE.md` content as repo-local instructions by moving or copying it to `AGENTS.md` in that project.
3. Move reusable slash-command or workflow text into `~/.config/EvoFlux/skills/<skill>/SKILL.md`.
4. Configure providers in **Settings → Providers** or `~/.config/EvoFlux/.env`.

Claude Code credentials and session history are not imported.

## From OpenAI Codex CLI

There is no automatic Codex CLI importer yet. Migrate reusable setup manually:

1. Copy durable instructions from Codex project files into repo `AGENTS.md` for coding mode, or into an EvoFlux agent file for global behavior.
2. Connect Codex OAuth in EvoFlux with `EvoFlux auth codex`, or use **Settings → Providers → OpenAI Codex**.
3. Set agent models to the `codex:` provider prefix when you want to use Codex OAuth-backed models.

Codex CLI credentials are not imported because EvoFlux stores its own OAuth token at `~/.cache/EvoFlux/codex_oauth.json`.

## Existing EvoFlux Installs

If you already use EvoFlux before `1.0.0`, you do not need to uninstall first. Install or update EvoFlux normally, then launch the desktop app or run `EvoFlux`.

The CLI and desktop app share the same production paths:

| Data | Path |
|------|------|
| Config, agents, skills, `.env` | `~/.config/EvoFlux/` |
| SQLite database | `~/.local/share/EvoFlux/EvoFlux.db` |
| Wiki memory | `~/.local/share/EvoFlux-wiki/` |
| Session workspaces and uploads | `~/.local/share/EvoFlux-workspace/` |
| Logs and telemetry | `~/.local/state/EvoFlux/` |
| Cache and OAuth tokens | `~/.cache/EvoFlux/` |

Database migrations run automatically on startup. Back up `~/.local/share/EvoFlux/EvoFlux.db` before major upgrades if you have important history.
