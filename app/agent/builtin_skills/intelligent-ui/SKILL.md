---
name: intelligent-ui
description: "Decides when to render interactive UI in the chat with the ui_block tool instead of static markdown or writing HTML files to disk, and how to compose the 14 declarative block types — comparison tables, plans and timelines, checklists, metrics dashboards, math with changing variables, study flashcards, timers, pomodoro widgets, games, and custom sandboxed HTML. Use when the user asks to compare plans or options, schedule or timeline a project, track a checklist, render or visualize UI, build a widget, timer, pomodoro or game, show metrics or a dashboard in the chat, or do math with variables that may change — splits, tips, budgets, pricing — and whenever your own answer would lay out contenders, options, tradeoffs, a plan, or metrics, render it as UI even if the user never said render or compare. An in-chat dashboard is a stat_cards block, never an HTML file or a designed web page; frontend-design is for designing real sites, not chat answers. Not for Mermaid diagrams, which stay a fenced code block."
---

# Intelligent UI

`ui_block` renders shadcn-native UI blocks inline in the conversation. One
tool call renders one complete frame; the block payload is the tool's own
arguments, so renders persist across reloads. This skill decides *when*
interactive UI is the right answer and *which* block type fits.

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
3. **Prefer `ui_block` over a static markdown table** whenever the user will
   interact with or revisit the data — comparing, sorting, ticking off,
   recomputing. **Judge by the shape of your answer, not the verb the user
   used.** If your reply to a plain-prose question would be a comparison, a
   plan, a checklist, a set of metrics, or a recomputable split, render it
   instead of listing it. "What do you think I should use?", "help me pick",
   and "is it worth it" all land here. Static markdown is for short answers,
   code, and one-shot excerpts.
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
