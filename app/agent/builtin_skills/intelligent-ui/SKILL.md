---
name: intelligent-ui
description: "Evaluates whether an interactive in-chat interface would make an answer more useful, then chooses and composes an appropriate ui_block. Judge the user's goal and likely answer, not keyword matches: use controls when they help someone explore, compare, calculate, track, learn, or act; use prose when interaction adds no value. Covers native tables, plans, checklists, metrics, calculators, study cards, timers, games, and sandboxed custom HTML. An in-chat dashboard is a stat_cards block, never an HTML file or a designed web page; frontend-design is for real sites. Mermaid diagrams stay in a fenced code block."
metadata:
  runtime-preload-tool: ui_block
---

# Intelligent UI

`ui_block` renders shadcn-native UI blocks inline in the conversation. One
tool call renders one complete frame; the block payload is the tool's own
arguments, so renders persist across reloads. This skill decides *when*
interactive UI is the right answer and *which* block type fits.

## Decide from the user's goal

Do not select UI because the request contains a word such as "plan",
"compare", "chart", or "calculate". Infer what the user is trying to get
done and what response would best help them finish that task. Ask yourself:

1. Would a visual structure make the information easier to understand or
   compare?
2. Would the user benefit from changing an input, exploring a part, tracking
   progress, or taking an action in this conversation?
3. Can an available native block provide that benefit with clear labels,
   meaningful outputs, and honest assumptions?

Render only when the interaction improves the user's next step. Use the
smallest useful UI, combine it with concise explanation, and ensure each
control has a clear effect. If no control helps the user understand, decide,
calculate, track, learn, or act, answer with prose or ordinary markdown.
When choosing a format, evaluate the shape of the answer you intend to give,
not just the user's phrasing. An opinion may merit a comparison if the user
needs to choose among options; a request mentioning a chart may still be
better answered directly if it asks for one simple fact.

## Hard rules

1. **Never write interactive HTML to disk.** Timers, pomodoro widgets,
   countdowns, games, dashboards, and bespoke widgets must render live in the
   chat through a `custom` block that carries the full HTML inline. The block
   runs sandboxed (CSP plus a storage shim) and survives reloads; a `.html`
   file on disk never appears in the conversation and forces the user to open
   it themselves.
2. **Do not ask a multiple-choice clarifying question when the user already
   said "render" or "build".** Render the best guess in one `ui_block` call
   and offer to adjust afterwards. A rendered frame is easier to correct than
   an exchanged round of questions.
3. Prefer `ui_block` over static markdown when interaction materially helps
   the user compare, sort, track, recompute, inspect, or act. Judge the
   underlying need and the usefulness of the resulting controls. A
   comparison or plan does not automatically need UI; render it when
   interaction gives the user a meaningful advantage. Static markdown is
   appropriate when it communicates the answer more directly.
4. **One call, one frame.** Pass up to 6 top-level blocks in a single
   `ui_block` call (at most 50 nodes total, `layout` nesting at most 3
   levels) instead of several sequential calls.

## Decision table

Render when **your answer** would take this shape — regardless of how the
user phrased the question:

| When your answer would be | Render with |
| --- | --- |
| Comparing plans, pricing, options, features | `table`; or `layout` with a `key_value` per option when each column is rich |
| A plan, schedule, timeline, roadmap, phases | `steps` for ordered phases; wrap with `checklist` in a `layout` for tasks |
| Tasks, a todo list, requirements to track | `checklist` |
| Metrics, KPIs, a dashboard summary | `stat_cards`; add a `chart` for a trend |
| A trend over time or category comparison | `chart` (a lone chart in prose may instead be a `chart` fence) |
| Math with variables that may change — splits, budgets, pricing | `calculator` |
| Study or review material — terms, verbs, concepts | `flashcards` |
| A timer, pomodoro, countdown, game, or bespoke widget | `custom` with the full HTML inline |
| A Mermaid diagram | the `mermaid` fence in markdown, never a block |
| A warning, tip, or success/error note | `callout` |
| Structured facts as labels and values | `key_value` |
| Status or progress toward a known goal | `progress` |
| Gathering structured input from the user | `form` |
| Offering canned follow-up actions | `buttons` |
| Several of the above belonging side by side | `layout` (`columns` or `stack`) |

## Call shape

```
ui_block(blocks=[...], title="launch_plan", block_id="launch_plan")
```

- `blocks`: 1–6 top-level blocks, each `{ "type": ..., ...fields }`.
- `title`: short snake_case group title, at most 80 characters.
- `block_id` / `replace_id`: stable ids that let a later call update the
  rendered group in place instead of appending a duplicate — read
  [reference/update-protocol.md](reference/update-protocol.md) before
  changing blocks that are already on screen.

## Where to go deeper

- [reference/block-catalog.md](reference/block-catalog.md) — read when
  choosing a block type; exact field names, caps, and a one-line fit test for
  all 14 types.
- [reference/worked-examples.md](reference/worked-examples.md) — read when
  you need a copy-adaptable template: hosting-plan comparison, multi-step
  plan with checklist, live calculator, pomodoro widget rendered inline.
- [reference/update-protocol.md](reference/update-protocol.md) — read when
  the user asks to change, pause, add to, or revise blocks that are already
  rendered.

Fences cover only charts and Mermaid: a single trend or category chart may be
a `chart` fence carrying the same ChartSpec JSON (or the simple
`type` / `label - value` rows form); everything else goes through `ui_block`.
