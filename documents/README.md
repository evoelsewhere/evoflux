# EvoFlux documentation

This directory is the single documentation root for EvoFlux. The current-state
documents are reverse-engineered from the application code, API routes, data
models, desktop shell, frontend surfaces, and tests. When prose and code differ,
code is authoritative and the document should be updated in the same change.

## Start here

| Audience | Entry point | Purpose |
|---|---|---|
| Product and support | [Feature catalogue](features/README.md) | Every implemented product area and its owning code |
| Product and engineering | [EASD methodology](reference/easd-methodology.md) | Normative SDD + ADD lifecycle, contracts, roles, and gates |
| Engineers | [System overview](architecture/system-overview.md) | Processes, boundaries, and end-to-end request flow |
| New contributors | [Repository map](reference/repository-map.md) | Where code, state, tests, and documentation live |
| Local operators | [Configuration reference](reference/configuration.md) | Runtime directories, files, settings, and credentials |
| API clients | [HTTP and streaming API](reference/http-api.md) | Route families, auth, SSE, and WebSockets |
| CLI users | [CLI reference](reference/cli.md) | Setup, lifecycle, diagnostics, migration, and plugins |
| Contributors | [Development and testing](development/setup-and-testing.md) | Toolchain, run modes, checks, and change workflow |
| Release maintainers | [Release and packaging](development/release-and-packaging.md) | Web build, Python sidecar, native packages, and updates |

## Current architecture

- [System overview](architecture/system-overview.md)
- [Application harness](architecture/application-harness.md)
- [Backend runtime](architecture/backend-runtime.md)
- [Web frontend](architecture/web-frontend.md)
- [Desktop shell](architecture/desktop.md)
- [Data and storage](architecture/data-and-storage.md)
- [Memory architecture](architecture/memory-system.md)
- [SQLite concurrency](architecture/sqlite-concurrency.md)
- [Coding-agent code context](architecture/coding-agent-code-context.md)
- [Coding semantic intelligence](architecture/coding-semantic-intelligence.md)
- [EASD development architecture](architecture/evo-agent-specs.md)
- [Provider model capability flow](architecture/model-capability-flow.md)
- [Portable Agent Plugins](architecture/agent-plugins.md)

## Implemented features

- [Modes, workspaces, and sessions](features/modes-workspaces-and-sessions.md)
- [Agent runtime and teams](features/agent-runtime-and-teams.md)
- [Workbench, files, and Side Chat](features/workbench-files-and-side-chat.md)
- [Coding intelligence](features/coding-intelligence.md)
- [Evo Agent Specs](features/evo-agent-specs.md)
- [Git, reviews, and guarded edits](features/git-reviews-and-guarded-edits.md)
- [Memory and Dream](features/memory-and-dream.md)
- [Goals, workflows, and scheduler](features/automation.md)
- [Models and providers](features/models-and-providers.md)
- [Skills, tools, MCP, and plugins](features/tools-skills-mcp-and-plugins.md)
- [Browser and WebBridge](features/browser-and-webbridge.md)
- [Security and permissions](features/security-and-permissions.md)
- [Observability and diagnostics](features/observability-and-diagnostics.md)

The in-app Help Center in `web/src/help/locales/` is the source for end-user UI
walkthroughs and is localized in English, Vietnamese, and Japanese. The pages
under `features/` describe implementation contracts and code ownership instead
of duplicating every UI instruction.

## Guides and project records

- `guides/` contains task-oriented operator guides.
- `analysis/` contains dated audits and competitive/implementation analyses,
  including the completed [EASD benchmark report](analysis/easd-benchmark-2026-08-24.md).
- `research/` contains investigations and proposals, including the
  [EASD repository-skill prior-art review](research/easd-skill-prior-art-2026-08-24.md).
- `plans/` contains design plans, including plans for features that may have
  changed after implementation.
- `releases/` contains submission and release evidence.
- `images/` contains documentation and README media.

Files in `analysis/`, `research/`, `plans/`, and `releases/` are historical
records. They may explain why a decision was made, but they do not override the
current-state architecture and feature documents.

## Documentation contract

For a feature change, update all applicable layers:

1. the feature page and feature catalogue row;
2. the architecture page when a process, trust, storage, or concurrency
   boundary changes;
3. the API or configuration reference when a public contract changes;
4. in-app Help when user-visible behavior changes;
5. tests and code comments that link to the old contract.

Use repository-relative Markdown links. Keep generated screenshots under
`documents/images/`; do not create another documentation root.
