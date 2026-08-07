<div align="center">
  <img src="web/public/brand-assets/evoflux-app-icon.png" width="88" height="88" alt="EvoFlux logo" />

  # EvoFlux

  ### A harness-first desktop workspace for agents that do real work.

  **Lead-and-specialists. Orchestrated. Parallel. Verified.**

  Work for cowork and Coding for software engineering —
  powered by one local-first agent harness and any model you choose.

  [![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-2563EB.svg)](LICENSE)
  [![Desktop only](https://img.shields.io/badge/Product-Desktop%20only-1764FF)](desktop/)
  [![Python 3.12+](https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white)](pyproject.toml)
  [![React 19](https://img.shields.io/badge/React-19-149ECA?logo=react&logoColor=white)](web/package.json)
  [![Tauri v2](https://img.shields.io/badge/Tauri-v2-FFC131?logo=tauri&logoColor=white)](desktop/)
  [![BYOM](https://img.shields.io/badge/Models-12%20providers-7C3AED)](#bring-your-own-model)

  [Two modes](#two-specialized-modes) ·
  [Quick start](#quick-start) ·
  [Working model](#agent-working-model) ·
  [Architecture](#architecture) ·
  [Capabilities](#core-capabilities) ·
  [WebBridge](#webbridge)
</div>

<br />

<p align="center">
  <img src="documents/images/generated/harness-and-modes.jpg" width="820" alt="One EvoFlux harness connects any LLM to Work and Coding" />
</p>

> [!NOTE]
> Since **30 June 2026**, fixes, optimizations, and new EvoFlux features have been developed and delivered using **EvoFlux Coding mode**. The agents build, review, and ship themselves.

---

## Two specialized modes

One desktop app. One harness. Two different kinds of work.

| | **Work** | **Coding** |
|---|---|---|
| Product role | Cowork | Software engineering workspace |
| Workspace | Temporary sandbox | Persistent repo or multi-repo project |
| Best for | Research, documents, data, browser work, quick scripts | Build, test, refactor, review, git operations |
| Default specialists | Executor, Explorer, Consultant, Debate | Coder, Explorer, Architect, Debate |
| Verification | Artifact and tool-result review | Tests, diffs, code graph, git |

### Work · cowork without a repository

Work is the fast execution sandbox. Start with a request instead of a project: research a topic, draft a document, build a slide deck, analyze data, work with files, automate a browser task, or prototype a script.

### Coding · persistent engineering

Coding opens your real repository — or several repositories as one project — and keeps that workspace available across sessions. Agents can navigate the structural code graph, inspect the file tree, edit and test code, review diffs, and use the complete git surface.

<table>
  <tr>
    <td width="50%" align="center"><strong>Work</strong></td>
    <td width="50%" align="center"><strong>Coding</strong></td>
  </tr>
  <tr>
    <td><a href="documents/images/showcase/work-mode.jpg"><img src="documents/images/showcase/work-mode.jpg" width="360" alt="Work coordinating an artifact task" /></a></td>
    <td><a href="documents/images/showcase/coding-mode.jpg"><img src="documents/images/showcase/coding-mode.jpg" width="360" alt="Coding working across a multi-repository project" /></a></td>
  </tr>
  <tr>
    <td><sub>Agent collaboration, files, previews, and verification</sub></td>
    <td><sub>Repository context, tool history, implementation, verification</sub></td>
  </tr>
</table>

---

## Quick Start

### Install the desktop app

Download the [latest release](https://github.com/evoelsewhere/evoflux/releases/latest) for macOS (`.dmg`), Windows (`-setup.exe`), or Linux (`.deb` / AppImage). The packaged app includes its Python sidecar.

On first launch:

1. Connect an LLM provider.
2. Start a Work session or open a repository for Coding.
3. Choose the model, reasoning level, skills, tools, and permissions for each agent.

### Run the desktop app from source

Requirements: Python 3.12+, [uv](https://docs.astral.sh/uv/), [Bun](https://bun.sh/), Rust, and the Tauri prerequisites for your operating system.

```sh
git clone https://github.com/evoelsewhere/evoflux.git
cd evoflux

uv sync
cd web && bun install && cd ..

# Terminal 1 — local API sidecar + React development server
make dev

# Terminal 2 — Tauri desktop shell
make -C desktop dev
```

`localhost:5173` is the internal frontend development server used by Tauri during development. EvoFlux is shipped and positioned as a **desktop product**, not a standalone web app.

---

## Agent working model

EvoFlux operates under a **lead-and-specialists** model. Each request is analyzed by the Lead Agent to determine scope and complexity.

- A simple task stays with the Lead.
- A complex task is broken into well-defined subtasks with explicit goals, outputs, and constraints.
- Specialists activate on demand, work in parallel, and exchange results through a shared mailbox.
- The Lead evaluates handoffs and evidence, requests rework when needed, and synthesizes the final response.

<p align="center">
  <img src="documents/images/generated/agent-working-model.jpg" width="780" alt="Six-stage EvoFlux lead-and-specialists working model" />
</p>

### Configurable per agent

| Configuration | Why it matters |
|---|---|
| **LLM model** | Use a fast model for routine execution and a stronger reasoning model for architecture or review |
| **Thinking level** | Tune latency and reasoning depth by role and model capability |
| **Skills and tools** | Add agent-specific capabilities or disable code-owned defaults with explicit opt-outs |
| **Permissions and access scope** | Limit what an agent can read, write, execute, or approve |

The result is higher parallel capacity, less context noise, the right model for each job, verified delivery, and an execution history that can be inspected instead of trusted blindly.

Agent Markdown is the user-owned override surface. Runtime and Settings compile
the same effective config from the mode profile plus frontmatter additions and
`tools_opt_out`; reads and validation never materialise
configuration files. See
[`documents/architecture/application-harness.md`](documents/architecture/application-harness.md).

---

## Architecture

EvoFlux is desktop-only:

`Tauri Desktop → React UI → local FastAPI sidecar → local state / model providers`

The production app launches a local sidecar through an ephemeral port and token handshake. The React interface, agent runtime, code graph, memory engine, scheduler, permissions, and MCP client all run on the user's machine.

<p align="center">
  <img src="documents/images/generated/system-architecture.jpg" width="780" alt="EvoFlux desktop-only local-first system architecture" />
</p>

### What makes it a harness

A language model generates reasoning. The harness turns that reasoning into controlled action:

| Layer | Responsibility |
|---|---|
| **1. Tool orchestration** | Shell, filesystem, git, browser automation, MCP, and agent-to-agent actions |
| **2. Guardrails** | Permissions, policies, approvals, filesystem sandboxing, command checks |
| **3. Context and memory** | Workspace state, sessions, code graph, compaction, knowledge wiki |
| **4. Verification loops** | Test, compare, review, debate, reject, rework, and evidence |
| **5. Observability** | Streaming events, telemetry, logs, metrics, diagnostics, and audit history |

The model is replaceable. The harness — context, action, policy, verification, and state — is the product.

---

## Core capabilities

### Multi-agent teams

Agents are Markdown files with YAML frontmatter (`name`, `role`, `model`, `thinking_level`), making teams readable, diffable, and versionable. A team has one Lead and any number of on-demand members. Multiple instances of the same blueprint can work in parallel without becoming always-on background processes.

### Durable Goal mode

Start an autonomous objective in any mode with `/goal <objective>`. Goal state,
elapsed time, token usage, and an optional token budget survive reconnects and
app restarts. The team continues through hidden internal turns until the Lead
records completion, the budget pauses execution, the user pauses it, or the
same concrete blocker is reported three turns in a row. Goal mode never expands
the session's permissions or sandbox scope.

Use `/goal` to inspect status, `/goal:budget <tokens|none>` to change the budget,
and `/goal:pause`, `/goal:resume`, or `/goal:stop` to control the objective.

### Structural code knowledge graph

Twenty-five tree-sitter parsers cover Python, TypeScript/TSX, JavaScript, Go, Rust, Java, C#, C, C++, Swift, Kotlin, PHP, Ruby, Scala, Dart, Objective-C, Lua, Luau, R, Pascal, Svelte, Vue, Astro, and Liquid.

Indexing extracts symbols and typed edges — including `calls`, `inherits`, `implements`, `imports`, `references`, `overrides`, `reads`, and `writes` — and links a reference only when it resolves unambiguously. Incremental indexing follows file changes automatically; every graph query also performs a synchronous incremental freshness pass, including while background indexing is paused during an agent run.

#### Cross-repository resolution

A `CodingProject` can contain several repositories. Graph tools automatically use the active repository and its linked project when sibling lookup is needed; there is no model-facing scope argument. Three deterministic resolver tiers reconnect cross-repo references without an LLM call:

1. Reattach a previously resolved edge.
2. Match static manifests, identities, and Java fully qualified names.
3. Search sibling FTS5 indexes for remaining lexical candidates.

<p align="center">
  <img src="documents/images/generated/code-graph-cross-repo.jpg" width="760" alt="Deterministic three-tier cross-repository code graph resolution" />
</p>

<details>
  <summary><strong>Token-efficient code graph investigation</strong></summary>
  <br />

  Code graph has one native execution tool, `code_graph`, while exact-symbol workflow guidance is progressively disclosed inside the relevant Coding skills. EvoFlux does not inject graph prose into mode prompts, create a graph-routing skill, or route user requests with hard-coded keywords.

  | Question | Action |
  |---|---|
  | Where is known symbol X defined? | `code_graph(symbol=X, operation="definition")` |
  | Who calls X? | `code_graph(symbol=X, operation="callers")` |
  | What does X call? | `code_graph(symbol=X, operation="callees")` |
  | What references or transitively depends on X? | `references` or `impact` |
  | Which symbol does the request mean? | Discover an identifier with normal source search, then call `code_graph` |

  `code_graph` is not semantic search: it accepts one raw identifier, resolves exact definitions, and traverses structural edges. Reuse its returned definition and call-site evidence instead of re-reading the same ranges. Use `grep` for symbol discovery, literals, comments, configuration keys, prose, generated files, and unsupported languages; use LSP, tests, logs, or runtime evidence only where the graph reports limitations or static analysis cannot observe the behavior.

  The complete prompt, schema, ambiguity, fallback, evidence, and regression rules are documented in [`documents/architecture/coding-agent-code-navigation.md`](documents/architecture/coding-agent-code-navigation.md).

  The `/metrics` endpoint exposes graph-first versus fallback-first navigation turns, per-tool query count and latency, result-token volume, and estimated file-read/token savings. Saving estimates use a transparent baseline: each unique source location returned by the graph replaces one full-file read, with UTF-8 bytes divided by four as the token estimate.
</details>

### Memory and Dream

The scheduled or manually triggered **Dream** agent consolidates sessions and notes into an inspectable Markdown wiki: `topics/`, `entities/`, `notes/`, and `imports/`, with `INDEX.md`, an append-only `LOG.md`, source citations, confidence, and related-page metadata.

### Bring your own model

Twelve provider integrations ship behind one streaming abstraction, including Anthropic, OpenAI, Google Gemini, AWS Bedrock, Ollama, DeepSeek, xAI, Vertex AI, and GitHub Copilot. Models can be selected independently for each agent.

### Skills and MCP

Twenty-eight built-in skills cover mode-scoped Work and Coding workflows, specialized artifacts/design, EvoFlux configuration/installers, and provider-neutral PR lifecycle operations. Work and Coding each expose one implicit router; broad specialists are explicit-only so they do not compete on every request. Custom skills can be created, edited, diagnosed, and filtered as Work, Coding, or Both in Settings. A bounded 2%/8K metadata catalog is always available for model-driven selection, while `SKILL.md` bodies and bundle resources load only after exact activation. EvoFlux is also an MCP client for stdio, HTTP, and SSE servers; connected tools inherit the same permission rules as native tools.

### Permissions and sandboxing

Wildcard `(tool, pattern) → allow | deny | ask` rules use last-match-wins evaluation. The denylist filesystem sandbox protects EvoFlux state and cache directories, rejects symlinks into blocked roots, and tokenizes shell commands for denied-path checks.

### Git and session UX

Coding mode exposes diff review, commits, branches, merge, rebase, cherry-pick, stash, and worktrees to agents and the source-control UI. Long sessions support prompt navigation, revert/undo boundaries, context compaction, four-pane Split view, and a unified Monitor view.

---

## WebBridge

WebBridge is an external browser companion for the EvoFlux desktop app — not a web version of EvoFlux.

It connects an agent to the user's real Chrome or Edge session through a persistent, policy-checked relay. Control flows from the desktop agent to the browser over CDP; selections, page context, and human handoff flow back to the desktop session.

<p align="center">
  <img src="documents/images/generated/webbridge.jpg" width="790" alt="WebBridge connecting EvoFlux Desktop to the user's real browser" />
</p>

| Capability | What it does |
|---|---|
| **Secure connection** | Pairs the browser extension with scoped credentials, uses one-time session tickets, enforces domain policies, and maintains a complete audit trail. |
| **Safe context sharing** | Lets users intentionally share a selection, link, or page while sanitizing metadata, preserving provenance, and treating browser content as untrusted input. |
| **Live collaboration** | Streams the agent session into the browser side panel, supports questions and element selection, and allows seamless control handoff between the user and agent. |
| **Teach and monitor** | Records meaningful browser actions without capturing raw keystrokes, redacts sensitive fields, creates reviewable workflows, and requires confirmation before monitored results are shared. |

Pairings, tickets, tab bindings, and Teach drafts are persisted through Alembic migrations. Revoking a pairing closes the live relay and invalidates outstanding tickets. See [`extensions/webbridge/README.md`](extensions/webbridge/README.md) for installation and policy configuration.

### Beyond the real-browser bridge

EvoFlux also includes direct control of its persistent in-app browser, PDF/DOCX/HTML intake through `markitdown`, cron-driven agent prompts, OpenTelemetry, Prometheus, and DuckDB-backed observability summaries.

---

## How EvoFlux compares

<details>
  <summary><strong>Compare deployment, models, memory, code intelligence, and browser integration</strong></summary>
  <br />

  | | **EvoFlux** | Claude Code | Cursor | Devin | OpenAI Codex | OpenHands |
  |---|---|---|---|---|---|---|
  | Interface | **Desktop app** | CLI, IDE, desktop, web | VS Code fork | Cloud + desktop + CLI | CLI, cloud, IDE | Web, CLI, API |
  | Deployment | **Local, self-hosted** | Local + optional cloud | Local IDE + cloud agents | Cloud/VPC + local desktop | Local + cloud sandbox | Self-hosted or cloud |
  | Open source | **Apache-2.0** | No | No | No | CLI only | MIT |
  | Bring your own model | **12 providers** | Partial proxy setups | Partial BYOK | Provider choice | OpenAI only | Any model |
  | Non-project cowork | **Work** | Ad hoc | No | Limited | No | Yes |
  | Multi-agent | Lead + on-demand specialists + mailbox | Subagents and teams | Agent fleets + worktrees | Sub-Devins | Up to six subagents | Parallel delegation |
  | Code understanding | Structural graph, 25 parsers, cross-repo | Search + optional LSP | Embedding search | Codebase Q&A | Repo-aware loop | Agent-computer interface |
  | Persistent memory | Inspectable wiki + Dream | Markdown + auto-memory | Project Memories | Org knowledge base | `AGENTS.md` + session memory | Condenser + skills |
  | Real-browser bridge | **WebBridge, two-way** | No | No | No | No | No |
  | Pricing | Free; pay model costs | Subscription or API | Subscription | Subscription + usage | ChatGPT or API | Free self-hosted / paid cloud |

  EvoFlux leans into local ownership, model choice, inspectable memory, general cowork, and structural code intelligence. Commercial products lead in vendor-specific coding models, cloud infrastructure for long unattended runs, and editor-native maturity.

  <sub>Competitor information reflects publicly reported product capabilities and pricing around mid-2026 and may change.</sub>
</details>

---

## Tech stack

| Layer | Technology |
|---|---|
| Desktop | Tauri v2, Rust, bundled Python sidecar |
| Frontend | React 19, TypeScript 5.9, Vite 7, Tailwind CSS v4, Zustand, TanStack Query and Router |
| Backend | Python 3.12+, FastAPI, SQLModel, Alembic |
| Streaming | Server-Sent Events through `sse-starlette`; one feed per session |
| Data | SQLite WAL or PostgreSQL/MySQL; Markdown knowledge wiki |
| Code intelligence | `tree-sitter`, `tree-sitter-language-pack`, SQLite FTS5 |
| Observability | OpenTelemetry, Prometheus, DuckDB-backed aggregation |

## Project layout

```text
app/        Local FastAPI sidecar — agents, code graph, memory, scheduler, MCP
web/        React interface embedded by the Tauri desktop app
desktop/    Tauri v2 shell and Python sidecar packaging
seed/       Work and Coding blueprints, skills, and config
tests/      Backend and frontend tests
documents/  Design notes, analyses, and README media
```

## Contributing

Issues and pull requests are welcome. Keep changes focused and include the smallest relevant test run. Please report vulnerabilities privately through GitHub Security Advisories.

## License

EvoFlux is released under the [Apache License 2.0](LICENSE).

<div align="center">
  <br />
  <strong>Your models. Your machine. One desktop harness.</strong>
  <br /><br />
  <a href="#quick-start">Start with EvoFlux ↑</a>
</div>
