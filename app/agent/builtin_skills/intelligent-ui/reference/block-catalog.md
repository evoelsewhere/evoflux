# `ui_block` block catalog

## Contents

- Envelope caps
- stat_cards
- chart
- steps
- table
- key_value
- callout
- buttons
- form
- progress
- flashcards
- checklist
- calculator
- layout
- custom

Field limits come from the server models in `app/agent/schemas/events.py`;
unknown fields are ignored, so keep payloads to the fields listed here.

## Envelope caps

One `ui_block` call takes 1–6 top-level `blocks`, an optional `title` (at
most 80 characters, snake_case), and optional `block_id` / `replace_id` ids
(at most 128 characters; letters, digits, `.`, `_`, `-`, starting with a
letter or digit). A whole event may contain at most 50 nodes; `layout`
nests at most 3 levels (root layout = level 1).

## stat_cards

`{ "type": "stat_cards", "cards": [ ... ] }` — 1–6 cards, each
`{ "label": ≤80, "value": string|number, "delta"?: ≤40, "delta_tone"?:
"up"|"down"|"neutral", "hint"?: ≤160 }`.

Pick when: a dashboard-style row of headline numbers with optional deltas.

## chart

`{ "type": "chart", "spec": { ... } }` — `spec` is a ChartSpec dict:
`"type"` one of `line` | `bar` | `area` | `pie`, `"xKey"`, `"series"`:
`[{ "key", "label"?, "color"? }]` (at most 6), `"data"`: row objects (at
most 500), plus optional `"title"` (≤120), `"yLabel"`, `"unit"`,
`"stacked"`. The server stores `spec` opaquely; the web renderer validates.
A single-series chart may instead be a `chart` fence with the same JSON or
the simple text form (`line` / `label - value` rows).

Pick when: a trend over time or a category comparison that a table cannot
express.

## steps

`{ "type": "steps", "steps": [ ... ], "description"?: ≤240 }` — 1–12
steps, each `{ "title": ≤160, "status"?: "done"|"active"|"pending"|"error",
"detail"?: ≤400 }`.

Pick when: an ordered plan, runbook, or timeline the user reads top to
bottom.

## table

`{ "type": "table", "columns": [ ... ], "rows": [ ... ] }` — 1–12
`columns`, each a single-entry `{ "key": "Header label" }` mapping; up to
200 `rows`, each an object keyed by those keys.

Pick when: structured data the user will compare, sort, or revisit —
hosting plans, feature matrices, option lists.

## key_value

`{ "type": "key_value", "pairs": [ ... ] }` — 1–20 `{ "key", "value" }`
string pairs.

Pick when: compact label/value facts — a spec summary, environment details,
release metadata.

## callout

`{ "type": "callout", "tone"?: "info"|"success"|"warning"|"error",
"title"?: ≤120, "body": ≤1000 }`.

Pick when: one warning, caveat, tip, or result note needs emphasis.

## buttons

`{ "type": "buttons", "buttons": [ ... ], "hint"?: ≤160 }` — 1–5
buttons, each `{ "label": ≤80, "prompt": ≤500, "style"?:
"primary"|"secondary" }`.

Pick when: offering the user canned follow-up actions; a click fills the
composer with `prompt` (the user still sends it).

## form

`{ "type": "form", "title"?: ≤120, "description"?: ≤240, "fields": [
... ], "submit_label"?: ≤40 }` — 1–8 fields, each `{ "name": ≤40 matching
[a-z0-9_], "label": ≤80, "kind"?: "text"|"textarea"|"select"|"checkbox",
"options"?: ≤30 entries, "placeholder"?: ≤120, "helper"?: ≤160, "default"? }`.

Pick when: collecting several structured inputs from the user in one step.

## progress

`{ "type": "progress", "label": ≤120, "value": ≥0 integer, "max": >0
integer, "unit"?: ≤20 }`.

Pick when: showing completion against a known total — uploads, migrations,
install steps.

## flashcards

`{ "type": "flashcards", "title"?: ≤120, "cards": [ ... ] }` — 1–20
cards, each `{ "front": 1–400, "back": 1–800 }`. Flip state lives in the
browser.

Pick when: study or review material — vocabulary, concepts, revision decks.

## checklist

`{ "type": "checklist", "title"?: ≤120, "description"?: ≤300, "items": [
... ] }` — 1–40 items, each `{ "label": 1–200, "detail"?: ≤300,
"checked"?: false }`. Ticks and the done-counter live in the browser.

Pick when: tasks the user will tick off — todos, acceptance criteria,
launch checklists.

## calculator

`{ "type": "calculator", "title"?: ≤120, "description"?: ≤300, "inputs":
[ ... ], "outputs": [ ... ] }` — 1–12 inputs, each `{ "name": matching
[a-z][a-z0-9_]{0,29}, "label": 1–80, "value"?: number (default 0), "unit"?:
≤20, "min"?, "max"?, "step"?: >0 }`; 1–2 outputs, each `{ "label": 1–80,
"formula": 1–200, "unit"?: ≤20, "decimals"?: 0–6 }`. Formulas may use only
numbers, input names, and `+ - * / ( )` — e.g. `"total / people"`.

Pick when: math whose variables the user will tweak — bill splits, budgets,
unit pricing, estimates.

## layout

`{ "type": "layout", "orientation"?: "columns"|"stack", "sections": [
... ] }` — 1–4 sections, each `{ "title"?: ≤80, "children": 1–8 blocks }`.

Pick when: several structured blocks belong side by side — a plan column
next to its checklist, metrics next to a chart.

## custom

`{ "type": "custom", "html": 1–100000 characters, "height"?: 64–2000 }` —
full HTML document carried inline; the web renderer runs it through the
sandboxed widget renderer (CSP wrap plus a storage shim).

Pick when: a timer, pomodoro, countdown, game, or bespoke widget that no
declarative type fits. Never write this HTML to a `.html` file on disk —
the inline block is what makes it run live in the chat and persist across
reloads.
