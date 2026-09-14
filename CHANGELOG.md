# Changelog

All notable changes to EvoFlux are documented in this file.

## [2.0.1] - 2026-09-14

EvoFlux 2.0.1 is a focused maintenance release for browser workflows, the
Problems panel, and EASD portability.

### Highlights

- Added a complete browser viewing flow: detached pages, drag-to-resize
  previews, device and layout controls, per-site zoom, download history,
  explicit loading/error states, and browser shortcuts that return to the
  panel.
- Made Problems actionable: filters now describe their scope, counts match
  visible results, severity is read correctly, decisions survive restarts,
  dismissed items can return, sending to chat preserves the draft, and fixed
  problems leave the active list.
- Improved Evo Agent Specs import and removed stale EASD documentation
  artifacts so repository-backed methodology stays portable and current.
- Hardened desktop webview capability scoping and remembered workbench posture
  across restarts.

### Fixed

- Browser dialogs and questions now reach the right panel, including detached
  pages and ownership changes.
- Landscape emulation no longer rotates to portrait, and reset restores the
  real browser window properties.
- Work mode has a usable starting surface and the browser preview stays within
  its available desktop layout.
- Problems no longer report incorrect counts, pluralization, severity, or
  stale repository state.

### Upgrade notes

- Application, Python, web, Rust, Tauri, and lockfile metadata are synchronized
  at `2.0.1`.
- This is a backward-compatible maintenance update on the 2.0.0 baseline.
- Existing databases continue through the normal Alembic migration path.

For the curated release overview, see
[`documents/releases/v2.0.1.md`](documents/releases/v2.0.1.md).

## [2.0.0] - 2026-09-14

EvoFlux 2.0.0 is a major workbench, provider, browser, telemetry, and
organization-governance release built on the first stable baseline.

### Highlights

- Added the Evo Conductor client foundation: authenticated realtime resource
  updates, resilient reconciliation, credential recovery, delivery notices,
  registry integration, inventory, and privacy-safe telemetry fields.
- Rebuilt multi-session workbench behavior so terminals, browsers, files, and
  docked tools survive session switches while background work remains visible.
- Introduced a declarative provider and model-capability layer with runtime
  catalog refresh, accurate thinking-level validation, subscription pricing,
  Xiaomi MiMo support, and more cache-efficient Codex request continuity.
- Expanded browser automation with authenticated WebSocket routes, stable
  element references, selected-browser routing, safer reconnect ownership, and
  workspace development-server launch controls.
- Added measurable context-window controls, per-turn token and cost reporting,
  cache-state telemetry, model-stacked consumption charts, and service-tier
  reporting.
- Refined Evo Agent Specs with portable session rebinding, execution options,
  code-context contracts, measured verification commands, and more reliable
  single-agent convergence.

### Added

- Per-team `ask` or `auto` spawn policy and clearer streaming activity phases.
- Document and HTML preview improvements, including JavaScript execution for
  trusted local previews and direct access to newly generated artifacts.
- Self-healing diagnostics, broader managed language-server availability, and
  richer file explorer actions.
- A unified appearance system with a real accent palette and the new Clay
  default theme.

### Changed

- Reworked transcript scrolling around browser-native anchoring and retained
  recently visited sessions for faster switching.
- Consolidated telemetry under Settings and aligned Conductor payloads with the
  fields the control plane actually persists.
- Replaced duplicated provider configuration and capability logic with one
  shared declarative registry.
- Reduced prompt churn and skill-catalog overhead to improve prefix-cache reuse.
- Changed sandbox out-of-scope handling from an unconditional hard block to a
  visible audit warning while retaining explicit permission boundaries.

### Fixed

- Hardened browser bridge authentication, reconnect recovery, panel ownership,
  element lifetime, selected-browser routing, and Linux/Windows edge cases.
- Fixed empty-window telemetry crashes, request pricing, context-limit
  discovery, model availability, and provider turn ordering after compaction.
- Repaired widget sizing and lost-delta recovery, document reopening, CJK IME
  visibility, background process polling, and multi-session tab cleanup.
- Improved EASD portability, verification trust, migration reconciliation,
  session rebinding, and stale-state recovery.
- Strengthened web-fetch DNS-rebinding protection and private-network guards.

### Upgrade notes

- Product, Python, web, Rust, Tauri, and lockfile versions are synchronized at
  `2.0.0`.
- Existing application databases continue through the normal Alembic migration
  path; back up important workspaces before upgrading a production install.
- This release changes provider, workbench, browser, and Conductor integration
  internals. Validate organization-managed resources and browser workflows
  after upgrading.
- Linux direct browser input continues to require X11/XWayland.

For the curated release overview, see
[`documents/releases/v2.0.0.md`](documents/releases/v2.0.0.md).

## [1.0.0] - 2026-08-27

EvoFlux 1.0.0 is the first stable release.

### Highlights

- Introduced Evo Agent Specs (EASD), a repository-backed specification-driven
  workflow with guided actions, phase retry, review handoff, real-time events,
  traceability, recovery, and local runtime data.
- Expanded agent-team workflows with explicit mode-lead team selection and
  safer delegation and handoff behavior.
- Added QwenCloud support and optimized prompt-cache request shaping across
  supported Anthropic, Bedrock, Codex, DeepSeek, Gemini, OpenAI-compatible,
  OpenRouter, and xAI provider paths.
- Expanded code-graph coverage and hardened language parsing across the primary
  and extended parser set, while isolating and caching index builds.
- Improved Coding workspace navigation, multi-repository chat setup, transcript
  preload/rendering, and request-ingress feedback.

### Added

- Repository knowledge-base initialization, portable EASD project contracts,
  durable trace records, and scoped memory.
- Shared browser-tool result plumbing and richer workbench integration.
- Separate context and turn usage totals for clearer token accounting.

### Changed

- Standardized web selection controls and improved command-message
  presentation.
- Removed the aggregate skill-bundle size limit and reduced built-in skill
  catalog overhead.
- Retired the non-executable terminal agent tool in favor of executable process
  and approved tool paths.
- Reorganized contributor and product documentation under `documents/`.

### Fixed

- Hardened SQLite concurrency, foreign-key repair, migration reconciliation,
  runtime teardown, and cleanup behavior.
- Repaired graph API schemas and numerous code-graph parser edge cases.
- Fixed coding repository visibility, chat working state, plugin scaffolding,
  and overlapping lead selectors.
- Improved outbound redaction and prompt finalization before summarization.

For the curated release overview, see
[`documents/releases/v1.0.0.md`](documents/releases/v1.0.0.md).

[2.0.0]: https://github.com/evoelsewhere/evoflux/compare/v1.0.0...v2.0.0
[1.0.0]: https://github.com/evoelsewhere/evoflux/compare/v0.0.8...v1.0.0
