# Worked examples

## Contents

- Example 1 — comparing three hosting plans
- Example 2 — a multi-step plan with a checklist
- Example 3 — math with changing variables
- Example 4 — a pomodoro widget rendered inline
- Example 5 — choose sourced dashboard, motion, or 3D only when useful

Each example is a complete `ui_block` tool call. The tool arguments are
`blocks` (the array below), plus optional `title` (≤80 chars, snake_case)
and `block_id` (stable identity for in-place updates). Only `chart` and
`mermaid` have fence equivalents; when an example says "no fence
equivalent", markdown simply cannot render it and `ui_block` is the only
path.

## Example 1 — comparing three hosting plans

User: "Compare DigitalOcean, Hetzner, and Racknerd for a small VPS — what
should I pick?" Pick `table`: the user will compare rows and revisit the
answer. No fence equivalent.

```json
{
  "blocks": [
    {
      "type": "table",
      "columns": [
        { "provider": "Provider" },
        { "plan": "Plan" },
        { "price": "Price / mo" },
        { "vcpu": "vCPU" },
        { "ram": "RAM" },
        { "verdict": "Verdict" }
      ],
      "rows": [
        { "provider": "Hetzner", "plan": "CPX21", "price": "€8.5", "vcpu": 3, "ram": "4 GB", "verdict": "Best price/perf in EU" },
        { "provider": "DigitalOcean", "plan": "Regular", "price": "$24", "vcpu": 2, "ram": "4 GB", "verdict": "Easiest ecosystem" },
        { "provider": "Racknerd", "plan": "Promo", "price": "$12/yr", "vcpu": 1, "ram": "2.5 GB", "verdict": "Cheapest long-term" }
      ]
    },
    {
      "type": "callout",
      "tone": "info",
      "title": "Recommendation",
      "body": "Hetzner CPX21 unless you need a US IP or the DigitalOcean marketplace."
    }
  ],
  "title": "vps_comparison",
  "block_id": "vps_comparison"
}
```

Copy-adaptation: swap the `columns` keys and headers, keep 3–6 `rows`, and
append one `callout` with the recommendation. If each option instead needs
rich prose per column, use a `layout` with one `key_value` section per
option instead of a `table`.

## Example 2 — a multi-step plan with a checklist

User: "Plan my migration to the new CI system." No fence equivalent. Nest
`steps` and `checklist` inside one `layout`.

```json
{
  "blocks": [
    {
      "type": "layout",
      "orientation": "columns",
      "sections": [
        {
          "title": "Timeline",
          "children": [
            {
              "type": "steps",
              "description": "Two-week migration, one stage per week.",
              "steps": [
                { "title": "Inventory current pipelines", "status": "done", "detail": "12 pipelines found" },
                { "title": "Stand up the new runner fleet", "status": "active" },
                { "title": "Port pipelines in two waves", "status": "pending" },
                { "title": "Decommission the old CI", "status": "pending" }
              ]
            }
          ]
        },
        {
          "title": "Your tasks",
          "children": [
            {
              "type": "checklist",
              "title": "Before Friday",
              "items": [
                { "label": "Approve the runner budget", "detail": "~$60/mo" },
                { "label": "Grant me access to the CI repo" },
                { "label": "Freeze deploys during wave 2", "checked": false }
              ]
            }
          ]
        }
      ]
    }
  ],
  "title": "ci_migration_plan",
  "block_id": "ci_migration_plan"
}
```

Copy-adaptation: Timeline section holds one `steps` block (≤12 phases,
mark earlier ones `"done"` and the current one `"active"`); the second
section holds one `checklist`. Use `orientation: "stack"` on narrow
content. When the user later reports a phase finished, update in place with
`replace_id` (see `reference/update-protocol.md`) instead of appending a
second plan.

## Example 3 — math with changing variables

User: "Help me split this dinner bill and try different tip percentages."
No fence equivalent. Use `calculator`; every formula references input
`name`s with only `+ - * / ( )`.

```json
{
  "blocks": [
    {
      "type": "calculator",
      "title": "Dinner split",
      "description": "Adjust the bill, tip, and headcount; totals recompute live.",
      "inputs": [
        { "name": "bill", "label": "Bill total", "value": 120, "unit": "USD" },
        { "name": "tip", "label": "Tip", "value": 18, "unit": "%", "min": 0, "max": 30, "step": 1 },
        { "name": "people", "label": "People", "value": 4, "min": 1, "step": 1 }
      ],
      "outputs": [
        { "label": "Tip amount", "formula": "bill * tip / 100", "unit": "USD", "decimals": 2 },
        { "label": "Total", "formula": "bill + bill * tip / 100", "unit": "USD", "decimals": 2 },
        { "label": "Per person", "formula": "(bill + bill * tip / 100) / people", "unit": "USD", "decimals": 2 }
      ]
    }
  ],
  "title": "bill_split",
  "block_id": "bill_split"
}
```

Copy-adaptation: one input per variable the user might change, one output
per number they keep asking about. Input `name`s must match
`[a-z][a-z0-9_]{0,29}` and formulas may only use numbers, those names, and
`+ - * / ( )` — `"total / people"`, never `"total ** 2"` or a function
call.

## Example 4 — a pomodoro widget rendered inline

User: "Make me a pomodoro timer." **Do not write `pomodoro.html` to disk
and tell the user to open it** — that is the exact anti-pattern this skill
exists to fix: nothing renders in the chat, the sandbox never runs it, and
the file does not survive workspace cleanup. Carry the HTML inline in a
`custom` block so it runs live, sandboxed, and persistent. No fence
equivalent.

```json
{
  "blocks": [
    {
      "type": "custom",
      "height": 240,
      "html": "<!doctype html><html><head><meta charset=\"utf-8\"><style>body{margin:0;font-family:system-ui,sans-serif;display:grid;place-items:center;height:100vh;background:#0f172a;color:#e2e8f0}#t{font-size:3rem;font-variant-numeric:tabular-nums}.row{display:flex;gap:.5rem;margin-top:.75rem}button{padding:.4rem 1rem;border-radius:.5rem;border:1px solid #334155;background:#1e293b;color:inherit;cursor:pointer}button:hover{background:#334155}</style></head><body><div><div id=\"t\">25:00</div><div class=\"row\"><button id=\"toggle\">Start</button><button id=\"reset\">Reset</button></div></div><script>(function(){var WORK=25*60,BREAK=5*60,left=WORK,running=false,timer=null,mode=\"work\";var el=document.getElementById(\"t\"),btn=document.getElementById(\"toggle\");function fmt(s){return Math.floor(s/60)+\":\"+(s%60<10?\"0\":\"\")+(s%60)}function render(){el.textContent=fmt(left)}function tick(){if(left>0){left--;render();return}mode=mode===\"work\"?\"break\":\"work\";left=mode===\"work\"?WORK:BREAK;render();btn.textContent=\"Start\";running=false;clearInterval(timer)}btn.onclick=function(){running=!running;if(running){timer=setInterval(tick,1000);btn.textContent=\"Pause\"}else{clearInterval(timer);btn.textContent=\"Start\"}};document.getElementById(\"reset\").onclick=function(){clearInterval(timer);running=false;mode=\"work\";left=WORK;btn.textContent=\"Start\";render()};render()})();</script></body></html>"
    }
  ],
  "title": "pomodoro",
  "block_id": "pomodoro"
}
```

Copy-adaptation: keep the whole widget in one self-contained HTML document
— inline `<style>` and `<script>`, no external requests (the sandbox CSP
blocks them). Persist state with the `localStorage` shim when the user
should keep progress across reloads (`evo-widget` namespaced keys). The
same shape serves countdowns, stopwatches, habit trackers, and small
games; only the HTML changes. A `pomodoro` needs no clarifying question —
render this best guess first, then offer tweaks (durations, break length,
session counter).

## Example 5 — choose a rich artifact from the task

Use `visual_artifact` when a bespoke dashboard, a controllable explanation,
or spatial inspection materially improves what the user can do next. It is
not a more decorative default for every answer.

For a data-backed dashboard, first run the relevant file or connector tool.
Then pass each successful result's actual `tool_call_id` and a query summary:

```json
{
  "artifact_id": "monthly-signups",
  "kind": "dashboard",
  "title": "Monthly signups",
  "summary": "Signups and churn from the attached report.",
  "source_html": "<main><h1>Monthly signups</h1><p>Show a responsive trend from verified source data. Use EvoFlux theme variables.</p><canvas aria-label=\"Signups trend\"></canvas></main>",
  "sources": [{ "tool_call_id": "actual-successful-tool-call-id", "query_summary": "signup and churn by month" }]
}
```

For a requested explainer that the user wants to play, pause, seek, or
export, use `kind: "motion"`, a bounded `duration_ms`, a self-contained
timeline, and a canvas marked `data-evoflux-motion-canvas`. Register an
`onCommand` handler for play/pause/restart/seek and report playback state.
Register `registerFrameRenderer(drawAt)` too: `drawAt(timeMs)` must redraw the
whole canvas from that absolute time so export can request frames independently
of preview playback. Keep the canvas backing size fixed and scale it with CSS.
The host detects local WebCodecs support, shows render progress, and falls back
to real-time recording for older artifacts. Example drawing core:

```js
const canvas = document.querySelector('[data-evoflux-motion-canvas]')
const ctx = canvas.getContext('2d')
const drawAt = (timeMs) => {
  const progress = Math.max(0, Math.min(1, timeMs / 12000))
  ctx.clearRect(0, 0, canvas.width, canvas.height)
  ctx.fillStyle = '#101827'
  ctx.fillRect(0, 0, canvas.width, canvas.height)
  ctx.fillStyle = '#ffffff'
  ctx.font = '700 56px system-ui'
  ctx.fillText('One clear point per scene', 80, 150)
  ctx.fillStyle = '#78a9ff'
  ctx.fillRect(80, 260, (canvas.width - 160) * progress, 18)
}
window.evofluxArtifact.registerFrameRenderer(drawAt)
drawAt(0)
```

The complete composition, including titles and captions, must stay inside this
canvas because it is the only surface included in exported video.

For a spatial task, use `kind: "scene3d"` with `scene.nodes` built only from
box, sphere, cylinder, or torus primitives. Each node needs a unique id,
bounded position/rotation/scale, semantic theme color, and optional useful
label. Choose 3D when rotation or spatial relationships help inspect the
subject; when WebGL is unavailable the app shows a labeled static preview.
