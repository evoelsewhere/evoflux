# Changelog

All notable changes to EvoFlux are documented in this file.

## [Unreleased]

### Changed

- Tool schemas sent to the model are smaller: the registry no longer emits
  Pydantic's nested `title`s, OpenAPI `discriminator` mappings that pointed at
  removed `$defs`, or the `null` branch of optional fields. With a shorter
  guide and one tab-targeting explanation instead of one per action, the
  `webbridge` definition shrank from about 67k to 35k characters and
  `browser_use` from 32k to 23k.

### Added

- WebBridge debugging actions: `debug_summary`, `console`, `network` and
  `network_body` read the console messages, uncaught exceptions and requests
  (status, type, timing, failures, response bodies) of a tab in the user's real
  browser. Coding sessions record from their first command, so the agent can
  run the edit → reload → check-errors loop against a local dev server.
  Requires evo-webbridge 2.7.0.
- WebBridge `inspect` shows an element's computed styles and the component
  chain and source files that rendered it (React, Vue, Svelte, locator
  plugins); `mock` fakes or fails matching requests; `emulate` throttles
  network/CPU or fakes offline, location, time zone and locale; `performance`
  reports load timing and Web Vitals; `storage`/`cookies` inspect page state;
  `upload_file` fills file inputs with workspace files. Storage/cookie values,
  writes and mocks follow `webbridge.allow_evaluate`. Requires evo-webbridge
  2.8.0.
- WebBridge console stacks and component source locations are source-mapped
  to the original files in Coding sessions (evo-webbridge 2.9.0).

### Fixed

- The `webbridge` tool now ships its full usage guide to the model; it was
  defined but never attached, so the model saw a one-line description.
- WebBridge `navigate` no longer stalls until timeout when the page lands on
  a different spelling of the requested URL (`http://localhost:3000` →
  `http://localhost:3000/`) or redirects (`/` → `/login`). `back`, `forward`
  and `reload` now wait for the page instead of returning immediately.
  Requires evo-webbridge with the matching extension change.
- Batched WebBridge actions stay on the session's bound tab and origin
  instead of running on whichever tab is active.
- In a WebBridge session, `preview start` names `webbridge` as the next step
  instead of the unavailable `browser_use`.

### Improved

- WebBridge page-loading actions report the address reached, redirects and
  title, and return a compact snapshot of the page when they end a call.
- Coding sessions drive WebBridge clicks and hovers without the human-paced
  pointer glide (72–360 ms per press in Work sessions).

## [2.0.7] - 2026-09-24

### Added

- Added turn file cards with thumbnails and direct navigation into the Files
  workbench for generated artifacts.
- Let agents choose which generated images should appear as turn cards, while
  skipping transient scratch renders.

### Improved

- Improved live PowerPoint deck previews with per-slide placeholders, compact
  page controls, and stable toolbar layout as rendering progresses.
- Let deck QA repair a finished deck without restarting the original live
  preview or reprocessing unrelated slides.
- Scoped slide edits to their target slides and refined the PPTX/Office Skills
  that drive live deck generation and annotation workflows.

## [2.0.6] - 2026-09-24

### Changed

- Agent Skills now follow Anthropic's Agent Skills architecture
  (documents/architecture/agent-skills.md). The system prompt lists each
  Skill's name, description and `SKILL.md` location; the agent reads
  `SKILL.md` with `read` when a task matches, reads referenced files on
  demand and runs bundled scripts with `shell`. This is a clean break with no
  compatibility layer:
  - the `skill` tool, the per-turn resolver model call and the bounded,
    query-ranked catalog are gone;
  - `SKILL.md` frontmatter is the whole bundle contract (`name`,
    `description`, `license`, `compatibility`, `metadata`, `allowed-tools`,
    plus `disable-model-invocation` and `user-invocable`).
    `agents/evoflux.yaml`, `agents/openai.yaml`, `.evoflux.json` and
    in-bundle `evals/` are no longer read, and nested `parent/child` names
    are no longer skills;
  - Skills are no longer scoped to Work or Coding mode, and Settings keeps a
    single on/off switch per Skill. Older `skill-settings.json` overrides
    are ignored;
  - `$skill-name` works anywhere in a message and may name several Skills;
    `/skill:<name>` is removed. An agent's `skills:` field preloads those
    Skills into its system prompt;
  - discovery scans `.evoflux/skills`, `.agents/skills` and `.claude/skills`
    in projects and the user directory, then plugins, then built-ins.
    `.opencode/skills` and `/etc/codex/skills` are no longer scanned.
  - Every bundled Skill was rewritten to the specification and the authoring
    best practices; `data-analytics` folds its 17 nested workflows into
    reference files, and the Codex-only Google Doc/Slides report workflows
    are removed.

### Removed

- Workflows are gone. `/workflow <name>`, the run-inputs dialog, the progress
  pill, workflow hits in Search Everywhere and in the WebBridge side-panel
  composer, `/api/workflows`, and the built-in `pr-hygiene` and
  `second-opinion` definitions are removed; `.evoflux/workflows/*.yaml` files
  are no longer read. Revision `00000068` drops the `workflow_approvals`,
  `workflow_executions`, `workflow_node_runs` and `workflow_gate_requests`
  tables. WebBridge Teach drafts no longer carry a generated `workflow_yaml`,
  and `ask_user` questions no longer have a `strict` mode — it existed only
  for workflow gates.
- The legacy ASDD and code-graph product surfaces are removed from the
  application and repository runtime.

### Added

- StepFun is now a supported provider. `stepfun:` models resolve to the
  global open platform by default, with `STEPFUN_BASE_URL` selecting the
  China host or either Step Plan subscription endpoint. Reasoning traces are
  requested in the spelling EvoFlux renders (`reasoning_content`) rather
  than StepFun's documented default, and the reasoning effort stays inside
  the levels StepFun publishes. StepFun cannot switch thinking off, so the
  off position leaves it at StepFun's own default.

### Added

- `asdd-explore`, a seventh Agent Spec-Driven Skill, fills a freshly installed
  catalogue from the repository it was installed into. Setup wrote `project.md`
  as placeholders and nothing ever filled it, while all six phase Skills read
  it first — so a fresh install ran every phase against blank rules. Explore
  reads what exists (`AGENTS.md`, README, build and test configuration, CI),
  asks only what the repository cannot answer, and writes `project.md` with the
  source beside each claim, plus the `architecture/` and `reference/` pages the
  code already justifies. It writes no `specs/` and no ADR — the first would
  contract whatever the code does today, bugs included, and the second states a
  rejected alternative that does not survive in code — and it defers `AGENTS.md`
  to `/init`, which already writes those properly. The board offers it until the
  repository has been described.

### Changed

- Autopilot now carries a change from phase to phase instead of only signing
  its gates. An agent would clear `auto_approvals`, move the status on and
  stop — every phase Skill says to stop — leaving the rail showing **Continue**
  for a person to click, once per phase. A finished turn now asks the same
  question that button asks and starts the next phase itself, binding the
  session to the change through the phase prompt already in the transcript.
  Whether a hop is allowed stays the rail's decision, so autopilot off, a
  `hold`, an unmet gate or a blocker all end the chain; so do a hop that moved
  nothing and a chain that reaches twelve hops. It still stops at `ready`,
  because archiving is the user's click at every tier.
- The six Agent Spec-Driven phase Skills are rewritten to one shape: the role
  and the single hard boundary first, a gate table that answers "should I even
  be here", the ways an agent arrives at that phase, the decisions it owes with
  the tables behind them, a worked example of the report in the agent's own
  voice, and closing guardrails that each say why. `asdd-plan` now splits its
  two jobs into a Design track and a Tasks track chosen by status rather than
  running them together. The `code_context` instructions each Skill repeated in
  full — 23 lines apiece, on top of the reference file installed beside them —
  are down to the rules that phase actually uses.
- The Agent Spec-Driven catalogue now has a home for each durable kind of
  page — `architecture/` for process, storage, concurrency and trust
  boundaries, `architecture/decisions/` for ADR-style records of why they are
  where they are, `reference/` for the exact API, configuration, schema and
  CLI surface, and `analysis/` for dated investigations — each with a
  `README.md` stating what belongs in it. The phase Skills write into them:
  the plan phase gives every durable page its own task, implementation ships
  the page with the code, and the archive phase refuses to fold a change whose
  decisions and surfaces were never written down. Only `specs/` still waits
  for the archive. An already-installed repository reports `upgrade_required`
  and the existing Upgrade action adds the directories without touching
  anything the repository edited.

### Fixed

- Any turn in which `stepfun:step-5-preview` called a tool died on a schema
  error before the call could run. StepFun sends `type: ""` on the chunks that
  continue a streaming tool call, where the shared OpenAI-compatible schema
  accepted only `"function"` or nothing at all. The kind of a tool call is
  never read — the call is assembled from its index, id and function — so the
  field is now a plain string on the way in, for the non-streaming shape as
  well. What EvoFlux sends is unchanged.
- A StepFun model cost nothing to run on a Step Plan row and something on the
  open platform, for identical tokens against identical weights. models.dev
  leaves `cost` off a subscription row — a plan seat buys a quota, not tokens
  — and StepFun's two `step_plan` rows are the only blank ones in the whole
  catalogue. They now inherit the vendor's own API rates, which is the number
  EvoFlux already reports for every other subscription it meets. A model only
  a plan row lists, such as `step-router-v1`, stays unpriced rather than
  borrowing a rate nobody published. StepFun's China plan row also counts as a
  variant of the curated provider now, so `step-router-v1` arrives with its
  real name and limits instead of as a bare model ID.
- The Agent Spec-Driven board showed only the repository a session opened on,
  so a Coding project whose changes live in a sibling repository reported an
  empty board — and the panel hid it entirely behind setup until *every*
  repository was installed. The board now lists the changes of every
  repository in the project, filters by repository and names the owner of each
  change, reads and actions a change through the repository it lives in, and
  treats the repositories still to set up as a banner rather than a wall.
- The Overview panel described the repository a Coding session opened on as
  though it were the whole project — one branch, one set of changes, no sign
  the others existed. It now names the repository it is describing and, in a
  project, lets the reader switch between them.
- Context compaction could not shrink a long session. The summariser replayed
  the raw transcript while ordinary turns send one with old tool results
  projected to receipts, so its request was about twice the size of the turn
  that triggered it — a 404K-token compaction call plus a 30K output cap
  against a 262K window, rejected with `context_length_exceeded` on all 137
  attempts in one session while the context grew to 950 messages. Compaction
  now sends the same projected prefix an ordinary turn sends, is budgeted
  against the model's window (with the summary's own cap clamped to a quarter
  of it), retries smaller when the endpoint rejects it anyway, and stops
  attempting every turn once it has failed three times in a row.
- Turn token totals counted a model call once per streaming chunk when the
  provider restated the call's usage on every chunk, which StepFun does: a
  33-minute session reported 1.87 billion tokens. A call's usage is now
  folded across its chunks and recorded once, when the call ends, and a
  cache figure that appears on only one chunk is no longer lost.

## [2.0.5] - 2026-09-19

### Fixed

- Fixed plugin uninstall and update failures on Windows caused by access
  restrictions during replacement.
- Normalized Windows extended-length workspace paths before sending them to
  the sidecar and frontend API clients.
- Fixed portal popups being misclassified as title-bar drag regions.
- Restored the lead agent transcript in Agent view mode.

### Improved

- Added multi-folder selection and parent-directory opening to Coding projects.
- Allowed new ASDD changes from multi-repository Coding projects to target a
  selected repository.
- Simplified team activity UI wiring and clarified turn loading feedback.

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

[2.0.7]: https://github.com/evoelsewhere/evoflux/compare/v2.0.6...v2.0.7
[2.0.6]: https://github.com/evoelsewhere/evoflux/compare/v2.0.5...v2.0.6
[2.0.5]: https://github.com/evoelsewhere/evoflux/compare/v2.0.4...v2.0.5
[2.0.4]: https://github.com/evoelsewhere/evoflux/compare/v2.0.3...v2.0.4
[2.0.2]: https://github.com/evoelsewhere/evoflux/compare/v2.0.1...v2.0.2
[2.0.3]: https://github.com/evoelsewhere/evoflux/compare/v2.0.2...v2.0.3
[2.0.1]: https://github.com/evoelsewhere/evoflux/compare/v2.0.0...v2.0.1
[2.0.0]: https://github.com/evoelsewhere/evoflux/compare/v1.0.0...v2.0.0
[1.0.0]: https://github.com/evoelsewhere/evoflux/compare/v0.0.8...v1.0.0
