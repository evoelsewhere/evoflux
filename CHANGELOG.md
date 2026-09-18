# Changelog

All notable changes to EvoFlux are documented in this file.

## [Unreleased]

## [2.0.4] - 2026-09-17

### Changed — EASD is now ASDD, and a change lives in the repository

EASD (Evo Agent Specification-Driven Development) is replaced by **ASDD — Agent
Specification-Driven Development**, built on OpenSpec's file model. A change is
a folder of Markdown under the repository's catalogue: its phase is the `status`
in `proposal.md`, its contract is the delta under `specs/<capability>/spec.md`,
and its identity is the folder's name.

- Removed content-hash binding. No operation restates a `content_hash`,
  `spec_hash`, `plan_hash` or `expected_hash`. Verification still
  content-addresses its own result cache, which nobody has to carry.
- Removed session binding. `trace_runs.session_id` and its one-run-per-session
  unique index are gone; any Coding chat can run any phase of any change, and
  several chats can work on one change.
- Dropped the five `trace_*` tables. `delegation_tasks.trace_run_id` becomes
  `asdd_change_id`, a slug rather than a foreign key.
- Replaced `/api/easd/*` and the hidden `/api/trace` alias with `/api/asdd/*`,
  addressed by change slug and capability.
- Replaced the five `easd-*` Skills with six `asdd-*` Skills, one per phase of
  the Agent-Driven Development cycle. They write Markdown with the ordinary file
  tools; there are no typed submission tools.
- Kept the driven UI: the board, the action rail and the human approval gates
  for proposal, specs, design and tasks.

### Added — Autopilot

A change can carry `autopilot: true` in its own `proposal.md`, and the agent
then decides at each gate whether a person is actually needed.

- What the agent clears is recorded under `auto_approvals`; `approvals` stays
  the user's signature and only the approve endpoint writes it. The panel draws
  the two differently, so a reader can see which gates a person read.
- An agent that wants a decision writes a `hold` naming the gate and the
  reason. The rail shows it above everything else, approving clears it, and it
  suspends autopilot everywhere rather than only at that gate.
- Autopilot carries implementation and verification too. Those are not gates,
  so the agent finishes the phase and advances `status` itself. The rail leads
  with **Continue** throughout and keeps the manual actions beside it. It stops
  at `ready` — archiving is a person's click at every risk tier.
- `cross_layer` and `critical` keep the design gate and the archive for the
  user regardless. Archiving is refused when a reserved gate was cleared by
  autopilot rather than signed.
- `POST /api/asdd/changes/{change_id}/autopilot` toggles it; `POST
  .../actions/autopilot_continue` runs the phase after the current gate.

### Added — every phase Skill ships its output contract

Each `asdd-*` Skill now installs a `TEMPLATE.md` beside its `SKILL.md`: the
exact shape of what the phase produces, and what gets it rejected. A Skill says
how to think about a phase; its template says what the phase has to leave
behind.

- Replaces three shipped templates (`design.md`, `tasks.md`, `spec.md`) that
  nothing ever read and that never reached a repository. Only `proposal.md`,
  which the product itself seeds, remains central.
- Every Skill gained a **Tools** section naming the tools that phase actually
  needs — `ask_user`, `todo_manage`, `shell`, `lsp_*`, `code_context` — instead
  of describing `code_context` alone.
- A repository installed before this reads as `upgrade_required` until setup is
  re-run.

### Changed — a new change asks for three things

The create form takes a **title**, the **problem**, and **what should be true
when it is done**. The slug, the capabilities and the risk tier moved behind a
disclosure and are derived by the propose phase when left blank. Nobody can
tier a change they have not read, and the tier decides whether it owes a design
and an independent review.

- `problem` and `outcome` are written into `proposal.md` under `## Why` and
  `## What Changes` — the file the propose phase reads — rather than stored
  beside the change as a second description that could go stale.
- `risk` is now **omitted** from the front matter rather than defaulted to
  `standard`, and **the proposal gate refuses until something sets it**. An
  unset tier used to silently mean "no design required".

### Changed — open questions are asked, not filed

New rule 7, **Ask; do not defer**. A phase that meets a question it cannot
answer from the repository calls `ask_user` and records the answer; writing the
question into a document and carrying on was making the decision silently.

- `design.md` gained a `## Decisions` section for answers, and its
  `## Open questions` section now means *unresolved*.
- **The design gate refuses a `design.md` that still lists open questions**, and
  the blocker names them. Under autopilot an unanswered question is a `hold`.

### Added — the capability catalogue is reachable from the panel

The counts in the Changes header open a Catalogue view: every
`specs/<capability>/spec.md` the repository contracts today, and the archived
changes that produced them. The spec endpoints existed but nothing rendered
them.

### Changed — the product surface is now **Agent Spec-Driven**

Renamed from "Agent Specs". The method keeps its name, Agent
Specification-Driven Development. A repository installed under the old name
reads as `upgrade_required` rather than `invalid`, and Reinstall rewrites the
manifest — the manifest is not broken, it was written by an older build.

### Fixed — an end-to-end sweep of every ASDD surface

- **A hand-edited `status` returned `500` and blanked the whole list.** The
  response model enforced the twelve-value Literal, so an unrecognised status
  failed validation before `declared_status_problems` could report it — taking
  every other change in the repository down with it. `status` and `risk` are
  plain strings on the way out now; the requests keep their Literals. The panel
  shows the value verbatim, the rail says it is not a phase it knows, and the
  board gained an **Unrecognised** column so the change does not silently
  vanish from it.
- **Archiving needed one evidence page, not evidence.** A change contracting
  five requirements archived on a single unrelated page, and a page citing a
  requirement name that did not exist counted the same. Every requirement a
  delta adds or modifies now needs a page naming it, and a `failed` result
  blocks. `inconclusive` still passes — the archive report names them.
- **A delta for a capability the proposal never named was folded silently.**
  Archiving contracts every delta it finds, so the specs gate now refuses one
  the proposal does not name.
- At `implementing` the rail led with **Run verification**, which is blocked
  until every task is ticked, so arriving at the phase showed a highlighted
  button that refused to run. It now leads with **Run implementation** and
  flips once the checklist is done. A blocked action that is not the primary
  one now carries its blocker as a tooltip.
- A title is no longer validated as though it were already a slug. `Add PDF
  export!!` and `Thêm tìm kiếm ghi chú` now derive `add-pdf-export` and
  `them-tim-kiem-ghi-chu`; a title with no Latin form asks for an explicit
  change id, and the New change form shows the folder before creating it.
- An evidence page written the way `asdd-verify` documents it — with an
  unquoted `recorded:` timestamp — returned `500` for the whole change, because
  YAML types that as a `datetime`. Front matter scalars now read back as the
  text the page meant.
- Approving an artifact is refused unless the change is standing at that gate.
  A new change carries a proposal template, and an existence check alone let an
  untouched one through the proposal gate.
- The panel opens a repository that is set up even when a sibling in the same
  Coding project is not. A catalogue belongs to one repository.

### Upgrade notes

- Migration `00000065` drops the `trace_*` tables. Existing EASD runs are not
  migrated — their state has no equivalent in a file-based catalogue.
- Revisions `00000055`, `00000060`, `00000061` and `00000062` are removed: they
  existed only to build those tables. A database stamped with one of them is
  moved to `00000054` before any migration runs — by the server's automatic
  upgrade, `make migrate` and a bare `alembic upgrade head` alike — and migrates
  forward from there to the same schema. Nothing is lost, because `00000065`
  drops everything those revisions created.
- Re-run setup from the Agent Spec-Driven panel to install `.evoflux/asdd/` and the
  `asdd-*` Skills. Setup writes what is missing and leaves existing files alone.

## [2.0.3] - 2026-09-15

EvoFlux 2.0.3 is a maintenance release focused on updater feedback, coding
skill routing and EASD workspace correctness.

### Highlights

- Added visible updater progress and actionable failure states, including
  recovery that leaves the desktop window usable after a failed update.
- Consolidated thirteen overlapping coding skills into four routing hubs:
  `coding-change`, `coding-investigate`, `coding-operate` and `coding-verify`,
  with refreshed references, eval coverage and loader behavior.
- Centralized observation limits in the new skill hubs so browser and coding
  workflows share consistent context-budget rules.
- Fixed EASD runs so their workspace follows the run context instead of being
  incorrectly pinned to a linked chat request.

### Upgrade notes

- Application, Python, web, Rust, Tauri and lockfile metadata are synchronized
  at `2.0.3`.
- Existing databases continue through the normal Alembic migration path; no
  schema migration is introduced by this release.

For the curated release overview, see
[`documents/releases/v2.0.3.md`](documents/releases/v2.0.3.md).

## [2.0.2] - 2026-09-15

EvoFlux 2.0.2 is a maintenance release focused on deeper WebBridge browser
inspection and more reliable browser interaction workflows.

### Highlights

- Added WebBridge scraping inside a selected element and across shadow roots
  and frames, with `extract_elements` ref/deep traversal controls.
- Added selector/ref-aware scrolling for nested scroll containers through
  `scroll_to_bottom`.
- Added stable element-handle actions, changed-only snapshots, batched action
  chains and broken-chain recovery for WebBridge browser automation.
- Included browser preview handoff, resize/placement, dialog/permission and
  workbench ownership fixes from the 2.0.1 follow-up cycle.

### Upgrade notes

- Application, Python, web, Rust, Tauri and lockfile metadata are synchronized
  at `2.0.2`.
- Existing databases continue through the normal Alembic migration path; no
  schema migration is introduced by this release.

For the curated release overview, see
[`documents/releases/v2.0.2.md`](documents/releases/v2.0.2.md).

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

[2.0.2]: https://github.com/evoelsewhere/evoflux/compare/v2.0.1...v2.0.2
[2.0.3]: https://github.com/evoelsewhere/evoflux/compare/v2.0.2...v2.0.3
[2.0.1]: https://github.com/evoelsewhere/evoflux/compare/v2.0.0...v2.0.1
[2.0.0]: https://github.com/evoelsewhere/evoflux/compare/v1.0.0...v2.0.0
[1.0.0]: https://github.com/evoelsewhere/evoflux/compare/v0.0.8...v1.0.0
