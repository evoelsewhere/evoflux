# Motion authoring

## Contents

- [Choose motion for the task](#choose-motion-for-the-task)
- [Brief and storyboard](#brief-and-storyboard)
- [Build a deterministic composition](#build-a-deterministic-composition)
- [Revise without losing continuity](#revise-without-losing-continuity)
- [Export limits](#export-limits)

## Choose motion for the task

Use `visual_artifact` motion only when the user explicitly requests video or
animation, or when time itself carries the meaning: sequence, transformation,
cause-and-effect, or a reveal that a static answer would obscure. Prompt length,
detail, and topic words do not select motion. For a fact, summary, or static
comparison, use prose or a chart/table when that serves the goal better.

Infer sensible defaults from the task. Use 16:9 when no destination is given,
and choose vertical or square framing only when the destination calls for it.
For a first explainer, condense the source into about 12–20 seconds and 3–5
scenes, with one clear takeaway; the tool accepts at most 120 seconds. Preserve
important facts and conditions without animating every detail. Do not ask for
details that can be safely inferred; state the defaults in the artifact summary
so the user can redirect them.

## Brief and storyboard

Before writing code, decide the audience, takeaway, destination/aspect ratio,
duration, and what changes over time. Keep the storyboard in the source as
scene data with stable ids, start/end times, one idea, one visual change, a
short visible caption, and an intentional transition. Use varied timing: give
the opening enough time to orient the viewer and pause on the final takeaway.

Choose one visual metaphor that explains the subject, then carry it through
the scenes. Animate only changes that explain a relationship or direct
attention. Avoid turning each beat into a card with the same slide transition.
Keep contrast high, use a small type scale, and leave safe margins around
captions. Draw all essential text, titles, and captions inside the exported
canvas.

## Build a deterministic composition

Send one self-contained `source_html` with a single canvas marked
`data-evoflux-motion-canvas`. A 1920 × 1080 backing canvas supports both the
720p Balanced and 1080p High export choices; CSS should scale it to the
Workbench width. Keep the source below the tool's 200 KB limit. The iframe has
no network access, so use inline vector/canvas shapes and text or assets the
user supplied; do not use remote images, fonts, or scripts.

Implement one pure `drawAt(timeMs)` function. It clears and draws the complete
composition for that absolute time, selecting the scene from the stable scene
data. Register that same function with
`window.evofluxArtifact.registerFrameRenderer(timeMs)`, call it for preview
seeking, and draw the opening frame immediately. Seeking must work in any
order; `drawAt` must not depend on `Date.now()`, accumulated state, timers, or
unseeded randomness. Preview playback may use `requestAnimationFrame` outside
`drawAt`, but it must seek the same function used by export.

Register `window.evofluxArtifact.onCommand(handler)` for `play`, `pause`,
`restart`, and `{ type: "seek", currentTimeMs }`. Report state and time through
`reportPlayback(state, currentTimeMs)`, including `ended` at the declared
`duration_ms`. Keep the playback clock bounded by that duration. Avoid flashing
and rapid camera-like movement; when the frame has
`document.documentElement.dataset.reducedMotion === "true"`, reduce travel and
intensity while preserving the sequence's meaning.

## Revise without losing continuity

Give the artifact a stable `artifact_id`. On a follow-up, reuse it so the
Workbench updates the existing view. Preserve scene ids, pacing, visual
metaphor, and unchanged scene drawing when the user asks to revise one beat;
update the complete source and let the runtime create the next revision. Change
neighboring timing only when the request requires it, and keep other scenes
visually consistent. If the requested change would make the story unclear,
revise the smallest number of affected scenes and briefly say why.

## Export limits

The frame renderer exports the marked canvas at fixed 30 fps, locally, to MP4
or WebM depending on the installed WebView encoder. Balanced is capped at
1280 × 720; High is capped at 1920 × 1080. Smaller source canvases are not
upscaled. The current frame-render path has no audio track: keep spoken words
as readable on-canvas captions and do not claim that a voiceover is embedded.
The older real-time recorder remains a fallback for artifacts without a frame
renderer.
