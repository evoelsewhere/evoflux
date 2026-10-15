# Intelligent UI

The Intelligent UI package lets the model choose prose, native interactive
blocks, or a richer dashboard, motion explainer, or 3D scene when that format
improves the user's next step. It also includes inline charts and diagrams,
interactive markdown tables, theme-aware rendering, and transcript replay.
This page documents the shipped behavior and its current boundaries.

Implementation plan: `documents/plans/2026-10-15-rich-intelligent-ui-implementation.md`.

## Response style (Simple / Visual)

**Settings → Agents** carries a **Response style** choice with two options:

- **Simple** asks the assistant to default to plain prose paragraphs and to
  skip markdown headings, tables, bullet lists, emojis and interactive UI
  blocks unless the user explicitly asks for them.
- **Visual** (default) asks the agent to infer the user's goal and choose the
  clearest useful format: prose, structured markdown, or an interactive UI.
  It asks the model to consider whether controls improve what the user can
  understand, decide, calculate, track, learn, or do, and to prefer prose
  when they add no practical value. When `ui_block` is available, the prompt
  identifies only visual tools available to this run and gives this decision
  rubric. The built-in **intelligent-ui** Skill supplies detailed selection
  guidance to Visual-mode agents that have a declared tool. Simple style still suppresses
  interactive blocks unless requested.

The choice is stored in `settings.yaml` under `response_style.style` and
served by `GET/PUT /api/settings/response-style`. A `@dynamic_prompt` hook
(`inject_response_style`, registered at `BASE_CONTEXT` next to
`inject_current_date`) appends the matching directive to the system prompt on
every model call, so changing the setting applies to the next message in any
mode — Work or Coding, single agent or team — without restarting EvoFlux. It
never rewrites replies that already happened. An unreadable settings file
degrades to **Visual** rather than failing the prompt build.

Primary code: `app/core/runtime_settings.py`, `app/api/routes/settings.py`,
`app/agent/hooks/response_style.py`, `web/src/routes/settings.agents.tsx`.

## Inline charts and Mermaid diagrams

Assistant replies render two fence languages natively instead of as code:

- ` ```chart ` — a small JSON spec (`type`: `line` / `bar` / `area` / `pie`,
  `xKey`, `series` of at most 6, `data` of at most 500 rows, optional
  `title`, `yLabel`, `unit`, `stacked` for bars) renders through Recharts
  with the app's theme colors. The spec is structurally validated on both
  sides of the wire; invalid specs never reach the chart renderer. When the
  fence is not JSON, a lenient tabular form is accepted instead: a first
  line naming the chart type, then `label value` rows (for example
  `bar` followed by `Mon 12`), rendered as a single `value` series with a
  `label` axis.
- ` ```mermaid ` — the diagram renders through the Mermaid runtime with
  `securityLevel: 'strict'`, so diagram text cannot execute scripts.

Both renderers lazy-load: Recharts and Mermaid stay out of the initial
bundle and only load when such a fence is actually rendered. While a reply
is still streaming, a half-finished fence shows a placeholder; if the fence
settles invalid or Mermaid cannot parse it, the reply falls back to the
regular copyable code block with a one-line notice. This applies in every
prose surface that uses the shared markdown pipeline — chat, side chat,
diff summaries and the wiki editor.

Primary code: `web/src/components/markdown/` (`chart-spec`, `ChartFence`,
`ChartBlock`, `MermaidFence`), fence dispatch in `web/src/utils/markdown.tsx`.

## Interactive markdown tables

Tables in assistant replies gain sort and filter controls as soon as the
reply finishes streaming. A table becomes interactive only with a
single-row header, at least 3 columns and at least 6 body rows; smaller
tables, tables still streaming and multi-row raw-HTML headers stay plain.

- Clicking a column header sorts by it and clicking again flips the
  direction; the header exposes the state through `aria-sort`. A column
  sorts numerically only when every non-empty cell parses as a number, so
  mixed columns such as `"7"` and `"n/a"` stay in text order and the
  comparator stays consistent.
- From 10 body rows a **Filter rows** input appears above the table. It
  matches case-insensitively against any cell and shows a "No matches" row
  when nothing qualifies.

Sorting and filtering are view state over the parsed table — the source
markdown is never rewritten, so a reload re-renders the reply and the
controls start fresh. This applies in every prose surface that uses the
shared markdown pipeline — chat, side chat, diff summaries and the wiki
editor.

Primary code: `web/src/components/markdown/MarkdownTable.tsx`.

## Native `ui_block` tool

`ui_block` renders declarative, shadcn-native blocks in the conversation as
one complete `ui_block` SSE event: stat cards, chart, steps, table, key/value
list, callout, buttons, form, progress, the interactive flashcards,
checklist and calculator blocks (flip-cards, tick-lists with a live done
counter, and steppers whose outputs recompute from safe arithmetic formulas),
plus `layout` and `custom`. `layout` arranges 1–4 titled sections of 1–8
blocks each in columns or a stack, nested up to 3 levels deep; `custom`
embeds sandboxed agent-authored HTML (`html` of 1–100000 chars, `height` of
64–2000 that defaults to 320). One call carries 1–6 top-level blocks (nested
layout children count toward 50 nodes per event); the server validates every
block against the Pydantic `UiBlockEvent` model before emitting, unknown
types return `success: false` with `valid_types` instead of a broken event,
and the frontend keeps a neutral "Unsupported block" card for anything it
does not recognise. The `chart` block reuses the same `ChartSpec`/`ChartBlock`
contract as the ` ```chart ` fence above.

**In-place updates.** Repeating the same `block_id` on a later call updates
that block group in place instead of appending a duplicate, and `replace_id`
retargets the group already carrying that name — keeping its original
position, latest write winning — falling back to a fresh group when nothing
matches. The identity (`replace_id` → `block_id` → `tool_call_id`) travels in
the persisted tool arguments, so a replayed event or a history reload updates
the same block rather than creating a second one.

**Interactivity round-trip.** Buttons dispatch their `prompt` as a normal
user message through the store's `sendMessage` action (the same fallback
`show_widget` uses); form submits compose the block title plus one
`- label: value` line per filled field, so the agent reads the answer as an
ordinary follow-up message. Submission state renders in an ARIA live region.

**Guidance split.** The model is told to judge task utility instead of
matching words. Use `ui_block` for compact native controls and
`visual_artifact` only for a dashboard, motion explainer, or spatial view
whose richer controls matter. The dynamic base context names only tools in
the active run; the detailed Skill preloads from a comma-separated capability
declaration. No runtime keyword router chooses the artifact.

Full contract, block limits and event registration:
[`ui_block` — native structured UI](tools-skills-mcp-and-plugins.md#ui_block--native-structured-ui).

**Native table interaction.** Native `table` blocks sort by any column and
show a case-insensitive filter for 10 or more rows.

**Custom widget actions.** The sandboxed `custom` block forwards its
`sendPrompt` bridge to the active chat, allowing an inline action to continue
the task through a normal agent message.

## Saved transcript widgets

`ui_block` and `show_widget` results survive reloads and reconnects. The
block payload is the tool's own persisted arguments, so history rebuilds the
native block losslessly from `tool_calls` JSON (no database migration), and
the live event is deduplicated by `tool_call_id` so a stream replay never
duplicates a block.

## Rich visual artifacts

`visual_artifact` emits one validated complete event for a dashboard, motion
explainer, or 3D scene. Each artifact has a stable `artifact_id`; later calls
replace it in place. Tool-call arguments are the source of truth for history,
so artifacts survive reloads without a database migration.

The conversation shows a compact artifact card; **Open in Workbench** opens the
actual interactive view in EvoFlux's resizable side panel. The tab belongs to
the current session, and the card can reopen an artifact reconstructed from
history. Generating or previewing an artifact does not create files in the
project. In Desktop Coding mode, **Save to project** asks for a path inside the
active repository and writes the source there for review in Source Control. In
other environments, **Download source** saves a copy outside the repository.

- **Dashboards** use self-contained `source_html`. A source counts as verified
  only when its `tool_call_id` matches a successful tool result in the active
  history. The Workbench view links to the actual tool name, saved arguments
  and result, and displays the model's query summary. With no verified source,
  the dashboard is labeled illustrative. Retrieval time appears only when a
  source explicitly provides one. **Refresh with agent** starts a normal chat
  turn; there is no background polling.
- **Motion** uses a bounded duration, play/pause/restart/seek controls, a
  timeline and an accessible summary. For frame rendering, the artifact
  registers `window.evofluxArtifact.registerFrameRenderer(timeMs)`; it redraws
  the full canvas from that absolute timestamp. The app requests one frame at a
  time from the sandbox, then uses WebCodecs through Mediabunny to encode a
  locally produced MP4 or WebM with fixed 30 fps timestamps. The encoder module
  loads only when the user chooses **Render video**. Progress and cancel are
  available while rendering; the finished video appears in Workbench for
  playback and an explicit download. Choose **Balanced** (up to 1280 × 720) or
  **High** (up to 1920 × 1080); smaller canvases are not enlarged, and output
  dimensions preserve the canvas aspect ratio. A render records the artifact
  revision and is cancelled if the revision changes before completion; the
  downloaded filename and preview identify the pinned revision. Artifacts
  created before frame-render support can still use the browser's real-time
  canvas recorder. Export includes only the marked
  `data-evoflux-motion-canvas`, so titles and captions must be drawn inside it.
  Frame output remains subject to a 150 MB cap and local WebView codec support.
- **3D scenes** are declarative and limited to 100 labeled box, sphere,
  cylinder or torus nodes. The app loads its pinned local Three.js runtime
  only for this artifact kind, caps rendering, stops when offscreen, and
  provides keyboard/pointer rotation plus reset. If WebGL cannot initialize,
  a labeled static preview remains visible.
- Rich HTML runs in a dedicated `sandbox="allow-scripts"` iframe with no
  same-origin or `allow` privileges, a network-denying CSP and a one-time
  `MessageChannel` bridge. The runtime API is installed before generated
  scripts execute, so command handlers and frame renderers register on first
  load. App theme tokens and reduced-motion preference are
  passed into the frame and updated while it is open. Frame export transfers
  only one rendered `ImageBitmap` at a time across this bridge; the encoder and
  file assembly stay in the app page. Existing `show_widget` and `ui_block.custom`
  rendering keep their historic contract.

## Built-in Skill: `intelligent-ui`

The `intelligent-ui` Skill (`app/agent/builtin_skills/intelligent-ui/`)
provides detailed decision guidance, block schemas, and examples. Its body is
preloaded for an enabled Skill in Visual style only when the active agent has
at least one declared visual capability (`ui_block` or `visual_artifact`). This gives models the operating context
without a message-keyword router; the agent still decides whether the current
answer benefits from an interface. Its Level 1 description remains available
through normal Skill discovery in other styles and agents. The Skill carries:

- a task-utility decision table mapping compact controls to `ui_block`,
  custom dashboards/motion/3D to `visual_artifact`, and simple answers to prose;
- a block catalog with the real field names and caps of all 14 types;
- worked examples with exact native payloads and guidance for sourced
  dashboards, motion controls/export, and declarative scene3d;
- an on-demand motion-authoring reference with storyboard, deterministic
  frame/playback contract, visual quality rules, and stable scene ids for
  focused revisions;
- an in-place update protocol for `block_id` / `replace_id` follow-ups;
- hard rules against the three observed failure modes: static markdown
  tables for interactive data, writing widget HTML to disk, and asking
  clarifying questions instead of rendering a best guess.

The Skill asks the model to evaluate the user's underlying goal, whether
interaction changes the user's next step, and whether available controls
have clear effects, labels, outputs, and assumptions. A recommendation may
benefit from a comparison UI when the user needs to choose, but a plan or
chart mention alone does not force a widget. UI is composed with concise
explanation and the smallest useful set of blocks.

Research note: OpenAI describes GPT‑6 Intelligent UI as model training for
composing text, visuals, and interactions, paired with a native streamable
component library and compiler, and evaluation for clarity, usefulness, and
completeness ([OpenAI, October 7, 2026](https://openai.com/index/gpt-6-for-everyone/)).
EvoFlux can improve tool awareness and runtime context, but this prompt and
Skill guidance cannot reproduce trained design judgment by themselves. The
model still chooses and can vary, especially for ambiguous tasks. The lead
agent's cached prompt profile includes response style and a rubric version
so a style or guidance change uses a fresh prefix on the next activation.
Persistent post-interaction state remains future work.

Validation: `uv run python scripts/validate_skills.py --strict-warnings`;
discovery is the existing directory scan of `app/agent/builtin_skills/` — no
new Skill discovery subsystem was added.

## Source ownership

Response style and fence rendering are owned by
`app/core/runtime_settings.py`, `app/api/{schemas,routes}/settings.py`,
`app/agent/hooks/`, `app/agent/mode/team/member.py`,
`web/src/api/client/settings.ts`, `web/src/queries/`,
`web/src/routes/settings.agents.tsx`, `web/src/utils/markdown.tsx` and
`web/src/components/markdown/`. Native blocks are owned by
`app/agent/tools/builtin/visualize/ui_block.py`, `app/agent/schemas/events.py`,
`app/services/{stream_envelope,memory_stream_store}.py`,
`app/api/routes/team/webbridge.py`, `web/src/components/ui/`,
`web/src/components/BlockRenderer.tsx`, `web/src/stores/useTeamStore/sse-reducer.ts`
and `web/src/utils/messages.ts`. Rich artifacts are owned by
`app/agent/tools/builtin/visualize/visual_artifact.py`,
`app/agent/schemas/events.py`, `web/src/components/VisualArtifactRenderer.tsx`,
`web/src/components/VisualArtifactFrame.tsx`,
`web/src/components/visual-artifact/MotionArtifact.tsx`,
`web/src/lib/visual-artifact-{bridge,three-runtime,export}.ts`, and
`web/src/lib/motion-video-export.ts` — see the implementation plan for the full
map.
