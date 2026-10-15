# Motion authoring

For complex scenes, reference-matched styles, soundtrack requests, or a draft
that feels like slides, also read [motion-production.md](motion-production.md).
It describes task assessment and iterative production; the runtime contract
and audio-export limits below still apply.

## Contents

- [Choose motion for the task](#choose-motion-for-the-task)
- [Brief and storyboard](#brief-and-storyboard)
- [Choreograph beats, not slides](#choreograph-beats-not-slides)
- [Hits, transitions, and sound cues](#hits-transitions-and-sound-cues)
- [Build a deterministic composition](#build-a-deterministic-composition)
- [Review the motion](#review-the-motion)
- [Revise without losing continuity](#revise-without-losing-continuity)
- [Export limits](#export-limits)
- [Research references](#research-references)

## Choose motion for the task

Use `visual_artifact` motion when the user explicitly requests video or
animation, or when understanding depends on seeing how one state changes into
another or why one stage enables the next. For a process, choose motion when
the learner needs to understand what changes at each stage and why the next
stage depends on the previous one, even if a static flowchart could list those
stages. Use a static diagram, checklist, or document when the stages are mainly
for lookup, comparison, or printing, or their order does not carry the
explanation. Prompt length, detail, and topic words do not select motion.

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
scene data with stable ids, start/end times, one idea, one main visual change,
a short visible caption, and an intentional transition. Use varied timing:
give the opening enough time to orient the viewer and pause on the final
takeaway.

Choose one visual metaphor that explains the subject, then carry it through
the scenes. Animate only changes that explain a relationship or direct
attention. Keep contrast high, use a small type scale, and leave safe margins
around captions. Draw all essential text, titles, and captions inside the
exported canvas.

## Choreograph beats, not slides

Plan at two scales: 3–5 narrative sections, then write a **beat-level
timeline** with roughly 6–10 timed action beats across a 12–20 second
explainer. These are authoring defaults, not hard limits. A beat is an
interval of motion, not a single frame. For each beat,
record its frame or time range, what changes (before → after), the moving
subject, its path or transformation, the easing and any intentional hold, and
how it connects to the next beat. On this 30 fps renderer, frame ranges make
short accents and transitions precise.

Keep this as machine-readable beat data in the source, and make
`drawAt(timeMs)` derive the active actions from that data instead of maintaining
a separate, untracked animation schedule. Give each beat a stable `id`,
`startFrame`, `endFrame`, `subject`, `before`, `after`, `motion` (path/transform
and easing), `holdFrames`, `transitionIn`, and optional `hit` and `soundCue`
records with their own `frame` and short description; use `null` when omitted.
At render time, convert `timeMs` to a 30 fps frame and compute each active
beat's progress from its frame range. Beats may overlap when labels or
secondary motion need to enter while the main action continues.

```js
{
  id: 'scan', startFrame: 45, endFrame: 90, subject: 'parcel',
  before: 'label unscanned', after: 'scan accepted',
  motion: { path: 'into scanner, then route east', easing: 'easeInOut' },
  holdFrames: 8, transitionIn: 'follow route line',
  hit: { frame: 78, description: 'one expanding ring' },
  soundCue: { frame: 78, description: 'soft scan tick (not exported)' },
}
```

Keep the records compact, but do not leave frame ranges, motion, or hit timing
only in prose outside the data used by `drawAt`.

For example, a parcel `scan` beat can move the same parcel into a scanner,
sweep a line across its label, change the status from “unscanned” to “accepted,”
then release a brief ring hit and settle. The next beat follows that parcel
along a route that grows behind it. One continuous object and cause/effect
changes do more explanatory work than five isolated stage cards.

Keep one **persistent visual anchor**—for example a parcel, droplet, route,
machine part, or number—moving through the story. Let the camera, route, or
composition follow it. Preserve spatial relationships across section changes;
when a jump in time or place is necessary, reconnect the anchor with a match
cut, a continuing line/path, or a deliberate reveal. Do not reset every
section to a centered icon, heading, and caption. Vary shot scale and layout
only when the explanation benefits from the change.

For each beat, state the motion plainly: what moves, from where to where, what
causes it, and what state is different at the end. Use easing that fits the
material—smooth acceleration for travel, a crisp stop for a scan, a restrained
spring for a handoff. Stagger labels only to follow reading order or attach
them to the subject; avoid unrelated floating text. Secondary motion should
react to the main event, such as a ring expanding from a scan or a route
lighting up behind a moving parcel.

## Hits, transitions, and sound cues

Use a visual **impact hit** only at a meaningful event: a scan succeeds, a
valve closes, a contaminant is removed, a package changes hands, or the parcel
arrives. Build the hit as a quick anticipation → action/accent → settle, then
hold long enough to read the changed state. Pick one or two accents that fit
the event—compression and release, a color/stroke snap, a brief glow or ripple,
a tiny camera bump, or a few particles. Avoid stacking flashes, shake, blur,
and scale on every beat. Constant intensity makes important events harder to
notice.

Choose a **transition grammar** from the causal relationship between beats:
a continuing camera/subject move for travel, a match cut for the same object
changing state, a path-following mask reveal for a process flow, a hard cut or
brief push-cut accent for a decisive hit, and a quieter dissolve for a real
time/place change. Vary transitions by purpose; swapping decorative wipes on
otherwise static cards still reads as a slideshow. Use a hold as a deliberate
part of the rhythm, not as an accidental gap.

When sound adds value, align a sparse effect with a meaningful visual event.
The deterministic frame exporter accepts an optional `soundtrack` object with
a short `style` label and at most 64 cues. Each cue has a stable `id`,
`start_ms`, `duration_ms`, one of `sine`, `triangle`, `square`, `sawtooth`, or
`noise`, `frequency_hz` from 30 to 12000, and `gain` from 0 to 0.35. Cues are
locally synthesized with bounded envelopes; they do not accept code, remote
URLs, or local file paths. Use a few quiet sine or triangle tones for ticks and
impacts, leave meaningful silence, and do not approximate a full music bed,
voiceover, or supplied soundtrack with dozens of oscillators. Omit the
`soundtrack` field when sound has no user value.

Audio is optional and depends on the WebView's `AudioBuffer` and container
encoder support. The Workbench reports whether the finished file includes the
soundtrack or sound was unavailable; only say it is included after that status
confirms the mux. Older real-time canvas recordings remain silent. The
`soundCue` in beat data remains useful for planning even when the export has no
audio, but do not imply the planning cue was rendered.

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
`window.evofluxArtifact.registerFrameRenderer(drawAt)`, call it for preview
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

## Review the motion

Before presenting the artifact, inspect the opening, middle, ending, each
transition, and each impact hit at its start, accent, and settle. Seek in a
nonsequential order and confirm the same timestamp redraws the same composition.
Check that the anchor remains connected, every major move explains a state
change, captions stay readable, and any still moment is an intentional hold.
Preview or decode the export when the runtime allows it; compare its key frames
with the storyboard. If you cannot inspect the rendered result, say so rather
than claiming visual review. Recheck reduced-motion behavior for any large
camera move or repeated flash.

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
upscaled. Keep spoken words as readable on-canvas captions. Frame-based export
can mux the optional synthesized cues when an audio codec is available; check
the final Workbench audio status. The older real-time recorder captures a
canvas-only stream and remains silent.

## Research references

These sources inform the craft guidance; their features are not EvoFlux
capabilities. Claude describes code-authored animations whose text and timing
can be edited. Remotion documents scene transitions and overlays as separate
tools, including a sound-effect hook for transitions. Its agent skill repo
structures specialized guidance for transitions, audio, and effects. Motion
Canvas explains eased tweens and timing events for syncing action to a cue.
Mediabunny documents the audio source and output-track path used for optional
local cue muxing. The current EvoFlux implementation does not import music or
voice tracks and does not use the external Playwright/FFmpeg workflow.

- [Claude Motion announcement](https://claude.com/resources/articles/dashboards-and-motion)
- [Remotion transitions](https://www.remotion.dev/docs/transitions/)
- [Remotion transition overlays and sequences](https://www.remotion.dev/docs/transitions/transitionseries)
- [Remotion agent transition guide](https://github.com/remotion-dev/skills/blob/main/skills/remotion-markup/transitions.md)
- [Remotion sound and audio guide](https://github.com/remotion-dev/remotion/blob/main/packages/skills/skills/remotion-markup/audio.md)
- [Motion Canvas tweening](https://motioncanvas.io/docs/tweening/) and [time events](https://motioncanvas.io/docs/time-events/)
- [Mediabunny audio media sources](https://mediabunny.dev/guide/media-sources)
- Community reports of generic slideshow output and motion with weak easing are anecdotal: [AI-generated motion discussion](https://www.reddit.com/r/SaasDevelopers/comments/1u2whml/my_project_humbled_me_completely_i_spent_14_days/), [motion-design feedback](https://www.reddit.com/r/VideoEditors/comments/1vlggl3/i_am_so_sick_of_everyone_shoving_ai_video_editing/).
