# Intelligent UI

The Intelligent UI package makes chat replies easier to scan: a user-chosen
response style, inline charts and diagrams, native UI blocks, and saved
transcript widgets. It ships in two streams. This page documents what is
currently implemented; the remaining pieces are marked below.

Plan of record: `documents/plans/2026-10-13-intelligent-ui.md`.

## Response style (Simple / Visual)

**Settings → Agents** carries a **Response style** choice with two options:

- **Simple** asks the assistant to default to plain prose paragraphs and to
  skip markdown headings, tables, bullet lists and emojis unless the user
  explicitly asks for them.
- **Visual** (default) lets the assistant use headings, lists, tables and
  code blocks when they make an answer scannable.

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
  sides of the wire; invalid specs never reach the chart renderer.
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

## Native `ui_block` tool

`ui_block` renders declarative, shadcn-native blocks in the conversation as
one complete `ui_block` SSE event: stat cards, chart, steps, table, key/value
list, callout, buttons, form, progress, plus the interactive flashcards,
checklist and calculator blocks (flip-cards, tick-lists with a live done
counter, and steppers whose outputs recompute from safe arithmetic formulas).
One call carries 1–6 blocks; the
server validates every block against the Pydantic `UiBlockEvent` model before
emitting, unknown types return `success: false` with `valid_types` instead of
a broken event, and the frontend keeps a neutral "Unsupported block" card for
anything it does not recognise. The `chart` block reuses the same
`ChartSpec`/`ChartBlock` contract as the ` ```chart ` fence above.

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
