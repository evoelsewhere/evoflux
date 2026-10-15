---
name: intelligent-ui
description: "Helps choose useful interactive visuals from the user's goal instead of matching keywords. Use when an answer may benefit from native ui_block or a rich dashboard, motion, or 3D visual_artifact in EvoFlux Workbench."
metadata:
  runtime-preload-tools: ui_block,visual_artifact
---

# Intelligent UI

`ui_block` renders shadcn-native UI blocks inline in the conversation. One
tool call renders one complete frame; the block payload is the tool's own
arguments, so renders persist across reloads. `visual_artifact` creates a rich
dashboard, motion explainer, or spatial 3D scene that opens in EvoFlux's
Workbench side panel. A new artifact opens there automatically; the
conversation keeps a compact card that can reopen it. This skill decides
*when* interactive UI is the right answer and *which* tool fits.

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

1. **Never write an interactive artifact to disk just to display it.** Use
   `ui_block` for compact native interactions in the conversation; use
   `visual_artifact` for a custom data dashboard, a controllable animated
   explainer, or a spatial 3D view when those affordances materially help. The
   latter opens in Workbench and persists through tool-call history. The user
   chooses explicitly if source should be downloaded or saved into a Coding
   project. Use `ui_block.custom` for small bespoke interactions that do not
   need the dashboard, motion, or 3D runtime.
2. **Do not ask a multiple-choice clarifying question when the user already
   said "render" or "build".** Choose the smallest suitable tool, render a
   first useful version, then offer to adjust it in chat.
3. Prefer an available visual tool over static markdown when interaction
   materially helps the user compare, sort, track, recompute, inspect, or act. Judge the
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
| A data-backed dashboard with useful source details or refresh | `visual_artifact` dashboard after reading the data |
| A pauseable, seekable explainer or a model the user must rotate | `visual_artifact` motion or scene3d |
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
- [reference/motion-authoring.md](reference/motion-authoring.md) — read when
  authoring or revising an animated explainer/video; it covers the storyboard,
  deterministic canvas/runtime contract, and stable scene ids.
- [reference/update-protocol.md](reference/update-protocol.md) — read when
  the user asks to change, pause, add to, or revise blocks that are already
  rendered.

Fences cover only charts and Mermaid: a single trend or category chart may
be a `chart` fence carrying the same ChartSpec JSON (or the simple
`type` / `label - value` rows form). Use `visual_artifact` only when its
richer dashboard, motion, or scene controls improve the user's next step.

## Rich artifact rules

- A dashboard is data-backed only after reading or querying its inputs. Cite
  successful source tool calls in `sources` with a short query summary; runtime
  verifies these IDs against the active history. If no source is available,
  label the visualization illustrative in the artifact itself.
- Do not invent retrieval timestamps. Use a timestamp only when the source
  result provides one. “Refresh with agent” is a new turn; never imply
  background refresh.
- Motion HTML must be self-contained, include a visible caption or summary,
  support `window.evofluxArtifact.onCommand(...)` for play/pause/restart/seek,
  report accurate playback time and `ended`, and mark the one canvas containing
  the complete composition with `data-evoflux-motion-canvas`. Export captures
  that canvas only; text, captions, or overlays outside it are omitted.
- Register `window.evofluxArtifact.registerFrameRenderer(renderAt)` where
  `renderAt(timeMs)` redraws the entire composition from an absolute timestamp.
  Use the same pure drawing function for preview seeking and frame export. Do
  not depend on `Date.now()`, accumulated animation state, timers, unseeded
  randomness, or an animation loop inside `renderAt`; the host supplies frames
  in timestamp order and encodes them locally. Keep the canvas backing size
  fixed at 1280 × 720 for Balanced or 1920 × 1080 for High while CSS scales it
  for the preview. If an older
  composition has no frame renderer, EvoFlux may fall back to the browser's
  real-time canvas recorder. The MP4/WebM format depends on local encoder
  support; do not promise one format on every OS.
- For motion, decide whether animation helps explain a change, process, or
  comparison before using the rich artifact. Then make a short storyboard with
  audience, destination/aspect ratio, duration, one point per scene, and the
  visual change that carries each point. Keep source claims tied to supplied
  material, make type readable at the target size, and use motion to reveal or
  connect information rather than animate every element. Prefer a few scenes
  with clear pacing to a sequence of unrelated moving cards. Explain the
  takeaway in the artifact's visible caption.
- Use `scene3d` only when spatial structure benefits inspection. Describe
  geometry with supported declarative primitives; do not include scripts,
  URLs, shaders, or remote assets. Keep labels meaningful so the static
  fallback remains understandable.
- Rich HTML runs in an isolated frame without same-origin, network, storage,
  or privileged browser capabilities. Use EvoFlux theme tokens and respect
  the reduced-motion value exposed by the frame.
- Reuse `artifact_id` for revisions so an improved dashboard, explainer, or
  scene replaces the prior view in place. If the Workbench tab is open, the
  preview updates there; do not paste the generated source into the response.
