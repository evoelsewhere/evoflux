# Intelligent UI

The Intelligent UI package makes chat replies easier to scan: a user-chosen
response style, inline charts and diagrams, interactive markdown tables,
native UI blocks, and saved transcript widgets. It ships in two streams.
This page documents what is currently implemented; the remaining pieces are
marked below.

Plan of record: `documents/plans/2026-10-13-intelligent-ui.md`.

## Response style (Simple / Visual)

**Settings → Agents** carries a **Response style** choice with two options:

- **Simple** asks the assistant to default to plain prose paragraphs and to
  skip markdown headings, tables, bullet lists, emojis and interactive UI
  blocks unless the user explicitly asks for them.
- **Visual** (default) lets the assistant use headings, lists, tables and
  code blocks when they make an answer scannable, and asks for the
  interactive form whenever a **comparison of options** would be easier to
  use as a widget than as flat text. The line is deliberately
  style-only: the when-to-render heuristics for `ui_block` (comparisons,
  schedules, metrics, math with variables, widgets, never write widget
  files to disk) live in the built-in **intelligent-ui** Skill, so the
  system prompt stays tool-agnostic and the guidance loads on demand
  instead of costing tokens on every call. The `ui_block` tool description
  carries a one-line trigger that points at the same skill, and the
  Skill's decision table is framed around the shape of the answer
  ("when your answer would be…") rather than the user's verb, so a
  plain-prose "which should I pick" still reaches a block.

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

**Guidance split.** The model is told to prefer `ui_block` for structured,
scannable answers and to reserve `show_widget` for arbitrary HTML that the
native catalog cannot express — so common cases match the application theme
and the iframe escape hatch keeps full expressive power.

Full contract, block limits and event registration:
[`ui_block` — native structured UI](tools-skills-mcp-and-plugins.md#ui_block--native-structured-ui).

## Saved transcript widgets

`ui_block` and `show_widget` results survive reloads and reconnects. The
block payload is the tool's own persisted arguments, so history rebuilds the
native block losslessly from `tool_calls` JSON (no database migration), and
the live event is deduplicated by `tool_call_id` so a stream replay never
duplicates a block.

## Built-in Skill: `intelligent-ui`

The response-style prompt line alone did not reliably steer smaller models
toward interactive UI, so EvoFlux teaches the behavior through the repo's
progressive-disclosure Skill mechanism instead of more prompt strings. The
built-in `intelligent-ui` Skill (`app/agent/builtin_skills/intelligent-ui/`)
keeps a trigger-rich description in the system prompt at all times; the body
and its `reference/` files load only when a task matches. The Skill carries:

- a decision table mapping requests (compare plans, schedules, metrics,
  math with variables, study material, timers, games, dashboards …) to the
  right block type;
- a block catalog with the real field names and caps of all 14 types;
- four copy-adaptable worked examples with exact `ui_block` payloads,
  including the anti-pattern fix for pomodoro-style widgets: render the HTML
  inline in a `custom` block — never write a `.html` file to disk;
- an in-place update protocol for `block_id` / `replace_id` follow-ups;
- hard rules against the three observed failure modes: static markdown
  tables for interactive data, writing widget HTML to disk, and asking
  clarifying questions instead of rendering a best guess.

The trigger judges the shape of the answer as well as the request: an
opinion or recommendation that lays out contenders with tradeoffs renders
as a `table` plus `callout`, even when the user never said "render" or
"compare". Small tool-use models often skip the read step, so the lead
agent (`seed/agents/evoflux.md` and the local agent copy) preloads the
Skill body through the `skills:` frontmatter field — the decision rules
sit in the system prompt for every lead turn, while other agents still
discover the Skill from the catalog on demand.

Known boundary: on small tool-use models, subjective prompts that never
name a comparison ("which database should I use?", "is it worth it") are
the hardest to reach — with the Skill body preloaded they usually answer
in plain prose, and only sometimes read the Skill and render, verified
live on `xiaomi:mimo-v2.6-flash`. The three tuning passes (the **Visual**
line's "comparison of options" clause, the answer-shape trigger in the
`ui_block` description, and the answer-framed decision table) raise the
hit rate but do not make it deterministic — the same prompt can land one
run and miss the next. This is accepted for now: requests with a lexical
or explicit trigger render reliably, and markdown tables stay interactive
through sortable headers and the ten-row quick filter, so the floor is
still usable. A deterministic `ui` fence — markdown in, rendered block
out, no tool-call decision — is held in reserve if the boundary starts to
matter in practice.

Validation: `uv run python scripts/validate_skills.py --strict-warnings`;
discovery is the existing directory scan of `app/agent/builtin_skills/` — no
runtime or discovery code changed.

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
and `web/src/utils/messages.ts` — see the plan of record for the full map.
