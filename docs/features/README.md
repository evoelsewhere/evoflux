# Feature catalogue

Every feature with a Software Design Document (SDD). Add a row when you start
a Draft, and keep Status in step with the SDD's header. Rules and the
workflow: [docs/README.md](../README.md). Template:
[templates/sdd.md](../templates/sdd.md).

| Feature | Status | Area | Format |
| --- | --- | --- | --- |
| [Agent tools for working with the person](agent-tools/sdd.md) — `ask_user`, `update_todos`, `send_file`, `notify` | Implemented | engine, desktop UI | legacy |
| [Application database and provider settings](app-database/sdd.md) — `evo.db`, migrations, models.dev cache | Implemented (planned tables open) | `evo-store`, engine, shell | legacy |
| [Code intelligence](code-intelligence/sdd.md) — language servers and the `lsp` tool | Implemented | `evo-lsp`, engine, desktop UI | legacy |
| [Customize: skills, connectors, plugins, hooks](customize-skills-plugins-connectors/sdd.md) | Implemented (phases 1–5) | engine, `evo-mcp`, `evo-plugins`, `evo-hooks`, desktop | legacy |
| [Git in the Files tool](files-git/sdd.md) — changed files in the tree, changed lines in the editor | Implemented | `evo-worktrees`, shell, desktop UI | template |
| [Memory and the Scheduler](memory-and-scheduler/sdd.md) | Implemented | engine, desktop UI | legacy |
| [Notifications](notifications/sdd.md) — toasts, bell, OS notifications | Implemented | desktop UI, shell | legacy |
| [Session mesh protocol](session-mesh-protocol/sdd.md) | Implemented (phases 1–4); phase 5 proposed | `evo-mesh`, `evo-protocol`, engine, shell | legacy |
| [Subagents and nested sessions](subagents-and-nested-sessions/sdd.md) | Implemented (phases 1–4) | engine, `evo-worktrees`, desktop | legacy |
| [Usage and cost history](usage-and-cost/sdd.md) — every response's tokens and models.dev cost, Usage page | Implemented | `evo-store`, engine, desktop | template |
| [Web search and web fetch](web-search-and-fetch/sdd.md) | Implemented (layers 1–2); layer 3 proposed | `evo-web`, engine | legacy |

**Format:** `template` = follows [templates/sdd.md](../templates/sdd.md);
`legacy` = written before the template, with a header table added. Move a
legacy SDD to the template the next time it changes substantially.
