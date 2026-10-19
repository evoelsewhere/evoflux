# Intelligent UI: implementation status and next steps

Status checked against the feat/intelligent-ui tree on 2026-10-19. This is the
living plan for the shipped Intelligent UI package and the remaining quality
work; the old build-ready plans and task logs have been consolidated here.

## Outcome

EvoFlux should infer the answer shape from the user's goal, not from isolated
keywords. It can answer in prose, compose small native controls in chat, or
open a dashboard, motion explainer, or 3D scene in the Workbench when that
format makes the next step easier to understand or act on.

The model remains responsible for the judgment. Runtime context tells it which
visual tools exist, a capability-gated Skill supplies the selection rubric,
and the artifact renderer returns state, progress, and bounded review evidence.
No prompt-length or keyword router forces a visual tool call.

## Shipped in this branch

- **Selection and context:** Simple / Visual response style; per-call context
  names only tools available to the active run; the concise intelligent-ui
  Skill preloads when a declared visual tool exists; detailed block, artifact,
  and motion-production guidance remains on demand.
- **Native chat UI:** validated stat cards, charts, steps, tables, key-value
  lists, callouts, buttons, forms, progress, flashcards, checklists, calculators,
  layouts, and sandboxed custom blocks. Stable block identities support
  in-place updates and history replay.
- **Markdown visuals:** lazy chart and Mermaid fences plus sorting and filtering
  for large settled tables.
- **Workbench artifacts:** dashboards with source provenance, deterministic
  motion explainers, and bounded declarative 3D scenes open in a session-scoped
  Workbench tab. Previews inherit the app theme and reduced-motion preference.
  Generated source stays in session history unless the user explicitly
  downloads it or saves it into a coding project.
- **Motion production:** beat timelines, deterministic frame export, truthful
  chat progress, cancellation, representative frame previews, bounded model
  review when image input is supported, and optional locally synthesized sound
  effects when the active encoder supports audio.

The user-facing contract and implementation map live in
[features/intelligent-ui.md](../features/intelligent-ui.md). Motion-design
evidence and framework trade-offs live in
[research/intelligent-ui-motion.md](../research/intelligent-ui-motion.md).

## Remaining work, in priority order

### P0 — Measure semantic format selection

Build a privacy-safe prompt set covering direct requests, implicit visual
value, static lookup, print/document tasks, ambiguous cases, and long-source
summaries. Include Vietnamese and English. Run the same cases on MiMo 2.6 Pro
and at least one comparison provider.

Measure whether the model selects the expected format, whether a selected
artifact answers the underlying task, and whether it avoids unnecessary
visuals. Record tool names, outcomes, model/provider, and prompt-size metadata;
do not store private prompt text in live reports. Separate tool-selection
accuracy from visual quality.

### P1 — Evaluate the rendered result, not just the tool call

For dashboard, motion, and 3D fixtures, inspect the artifact at its intended
Workbench size. Motion review should include opening, midpoint, action/impact,
transition, and settle frames, plus an exported file when supported. Track
readability, causal continuity, pacing, visual hierarchy, and fallback behavior.
A successful tool call or passing schema test is not evidence of visual quality.

Use representative real product data only when it is already available to the
session, and keep provenance visible. Keep synthetic examples explicitly
labeled illustrative.

### P2 — Close the authoring feedback loop

Verify that the agent can act on truthful renderer feedback: validation errors,
unsupported codecs, export cancellation, artifact revision changes, and image
review availability. On a failed visual review, the model should revise the
relevant scene or explain the constraint instead of merely describing a
successful result.

Keep progress sampling bounded. Route only meaningful state changes; do not
inject a large renderer transcript into every model call.

### P3 — Improve model and style fit

Compare task-aware examples and compact Skill guidance across providers before
adding more base-prompt text. Add opt-in user preferences only when the app can
apply them consistently to theme, motion, contrast, and artifact layout. Use
real screenshot or frame fixtures for visual regression; text-only tests cannot
establish design quality.

### P4 — Decide whether to add another renderer

The current in-app pipeline uses deterministic canvas frames and local
Mediabunny/WebCodecs export; it does not require FFmpeg for that path. Prototype
an optional FFmpeg or Playwright-backed route only if measured requirements
show gaps in codec coverage, DOM capture, or composition complexity. Compare
installation size, startup time, sandboxing, licensing, platform support,
cancellation, and reproducibility before adding another dependency.

## Acceptance criteria

- Static lookup, short factual answers, and print-first requests remain prose,
  a compact diagram, or a document unless the user asks for richer UI.
- A control exists only when it changes an input, reveals a relationship,
  supports inspection, or enables a next action.
- Explicit video or animation requests use the in-app motion artifact when the
  capability is available; a request that depends on state change can select
  motion without the word “video.”
- Source length changes summarization depth, not the format decision.
- A visual artifact is tied to its revision, survives transcript reload, and
  does not write into the repository unless the user explicitly saves it.
- The app reports export/review limits accurately and never claims a silent or
  unreviewed render includes sound or visual inspection.
- Each release candidate has focused backend/frontend tests, a clean diff
  check, and at least one model-driven smoke run. Report static, test, runtime,
  and visual evidence separately.

## Ownership and verification map

- Runtime selection and capability context: app/agent/hooks/, app/agent/loader.py,
  app/agent/mode/team/, and the built-in intelligent-ui Skill.
- Schemas and tools: app/agent/schemas/events.py and
  app/agent/tools/builtin/visualize/.
- Stream, history, and Workbench state: app/services/, app/api/routes/team/,
  web/src/stores/useTeamStore/, and web/src/utils/messages.ts.
- Rendering and export: web/src/components/markdown/,
  web/src/components/ui/, web/src/components/visual-artifact/,
  web/src/components/workbench/, and web/src/lib/.
- Focused coverage: tests/agent/, tests/api/, tests/services/, and
  web/src/__tests__/.
