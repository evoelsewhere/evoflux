# Motion production and review

## Contents

- [Assess the task and capabilities](#assess-the-task-and-capabilities)
- [Choose the story, stage, clock, and medium](#choose-the-story-stage-clock-and-medium)
- [Build cheap visual evidence first](#build-cheap-visual-evidence-first)
- [Render frames with code](#render-frames-with-code)
- [Run a bounded improvement loop](#run-a-bounded-improvement-loop)
- [Design the soundtrack](#design-the-soundtrack)
- [Deliver evidence and preserve revisions](#deliver-evidence-and-preserve-revisions)
- [Sources](#sources)

## Assess the task and capabilities

Use this reference after selecting motion for a complex explainer, product
demonstration, reference-matched design, or soundtrack request. Judge what the
viewer must understand or feel; prompt keywords and length do not choose a
workflow. Carry forward preferences and an approved brief. Infer routine
defaults; ask only about information that materially changes the result.

Read the active tool contract before choosing a production route. EvoFlux's
in-app motion route accepts self-contained HTML/JavaScript and a canvas with
deterministic frame rendering. It exports at 30 fps and has no audio track.
It does not expose an audio renderer, a Playwright/FFmpeg render job, or an
automatic importer for externally rendered videos. Never invent those APIs.

When the `motion_review` tool is available, first check that the active provider
accepts image input. After rendering a draft or a targeted revision, request a
small set of representative beat/key-state and before/after transition frames.
The browser captures only those requested timestamps inside the sandbox and
returns bounded thumbnails to vision-capable models. Use returned pixels as
evidence for a concrete revision. If the tool reports `samples_unavailable`,
the provider is text-only, or a frame failed to render, continue from available
metadata without saying that the animation was visually inspected. Do not ask
the model to review every output frame; the renderer creates encoded frames and
the model reviews only a few representative samples.

If authorized shell/browser tools and a local media workflow are available,
check the actual Node/browser/encoder capabilities before choosing that route.
Keep render inputs and outputs in the session workspace. External rendering
is a separate route; do not describe it as an in-app capability. Missing audio
support does not prevent improving the visual draft, but disclose its silent
export when sound is requested. Keep the Workbench preview useful with the
existing artifact tool.

## Choose the story, stage, clock, and medium

Record four decisions, each justified by the task:

| Decision | Fit to the viewer's goal |
| --- | --- |
| Story | Process transformation, chronology, problem/solution, product proof, or visual variation. A parcel journey follows one parcel and its changing status. |
| Stage | One continuous world with a following camera, accumulating layers on a fixed stage, shape-linked scenes, or deliberate cuts. Spatial processes often benefit from continuity. |
| Clock | Spoken cues for a narrated explanation; verified musical events for a music-led reel; action and reading time for a silent explainer. |
| Medium | A coherent palette, type scale, line weight, texture, motion cadence, and camera language. Choose them for the subject and references. |

Treat these as independent choices, not universal format laws. Calm teaching
does not require rapid cuts or a dramatic impact. A product dashboard remains
interactive when inspection is the goal; record a walkthrough only when the
user needs a timed demonstration. Show real product UI from supplied or
retrieved assets, or clearly identify a proposed design.

## Build cheap visual evidence first

Make two to four representative style frames before polishing the full
timeline: an opening/wide, a detailed mechanism or UI state, and a contrasting
payoff. Derive them from the same drawing functions that will animate them.
Compare with the supplied references for hierarchy, composition, palette,
material, typography, and motion intent. Then sample every narrative beat as
a storyboard with its transition and optional sound cue.

Give the moving idea a consistent visual identity and show the change itself.
A caption naming a scan is weaker than a line crossing the parcel label and
its status changing. Vary framing to explain detail and restore context.
Theme tokens govern the Workbench shell and contrast; a video's art direction
can retain a deliberate palette without copying every app surface color.

Keep a compact ledger in source data or session files: brief, target runtime,
format, fps, narrative decisions, style parameters, stable scene/beat ids,
frame ranges, asset provenance, review findings, and revisions. Preserve it
across model-context compaction; read the ledger and latest findings instead
of regenerating from the prompt. Use the beat schema in motion-authoring.

## Render frames with code

Distinguish style frames (design samples), keyframes (poses/important states),
encoded frames (output samples), and model iterations (reasoning and edits).
A 15-second video at 30 fps needs 450 output frames, not 450 model calls.
Generate drawing functions and timing data; let the renderer evaluate them.
Adding output samples does not add story, choreography, or visual detail.

Use the runtime's actual fps. Prefer frame-aligned durations. If a duration is
not aligned, the current export uses `ceil(durationSeconds * 30)` frames;
evaluate frame `i` at `1000 * i / 30` milliseconds. All frames must be complete
and seekable in any order, with seeded randomness and decoded assets ready.
Treat the final timestamp at the declared duration as a playback state,
separately from the last encoded sample.

For an external browser renderer, wait for fonts/assets and a ready signal,
seek the paused composition, capture the marked canvas or viewport, and repeat
for each index. Playwright records pixels; it does not author the animation.
FFmpeg encodes/muxes media; it does not repair choreography. Real-time browser
recording is not a substitute for a deterministic frame loop. Prevent stale
frames from an earlier, longer revision entering a new encode.

Choose cadence deliberately: smooth camera/UI motion and hand-drawn stepped
motion have different needs. More fps or sub-frame samples cost render time.
Temporal supersampling can create motion blur when explicitly implemented;
it is not a motion-quality switch, and EvoFlux has no built-in blur flag.
Do not import another framework's 24 fps clock into the 30 fps bridge.

## Run a bounded improvement loop

Start with a small draft or sampled frames before a full-resolution render.
Inspect the opening, each key state, and frames before/at/after every cut or
hit; include a sheet at intended viewing size. Look for detached anchors,
text clipping, unreadable captions, discontinuities, unexplained state jumps,
repetitive framing, and accidental dead time. Intentional holds are valid;
do not add noise or movement just to increase a pixel-difference score.

For each finding, record timestamp, expected state, observed defect, and the
smallest affected beat or drawing function. Patch that area, re-render its
samples, and check neighboring transitions. Use two refinement passes as a
starting budget; extend for material improvement or a blocking defect. Stop
repeating an unchanged attempt and preserve unresolved findings explicitly.
Do not stop early while a known, fixable correctness defect remains.
If the in-app `motion_review` tool is available, submit only the selected sample
descriptors (sample id, beat id, frame index, timestamp, and review role); never
place image bytes in tool arguments or lifecycle events. Interpret its returned
images together with the beat labels and timestamps.

Separate runtime checks from aesthetic judgment. Check frame count, dimensions,
fps, duration, decode errors, repeated-time determinism, and missing assets.
Then assess hierarchy, causal clarity, pacing, consistency, and sound fit.
Read actual findings: an upstream script can print FAIL and still exit zero.
Metrics complement inspection; neither captions in a storyboard nor passing
metadata checks prove the final video looks good. If rendered images or sound
cannot be inspected, state that limit.

## Design the soundtrack

Decide mood, energy arc, instrumentation/timbre, density, important hits, and
the role of silence. A process explainer might use sparse pulses and tactile
scan sounds; a launch reel might use a stronger groove. Do not put a whoosh
on every transition. Choose supplied/authorized music or a procedural score;
Python and MoviePy are optional implementation choices, not requirements.

If an audio-capable route exists, use one timeline in seconds for picture,
music, SFX, and voice, with frame indices derived from it. A supplied track
needs a verified beat/phrase map; constant-BPM detection can choose half/double
tempo and can fail on ambient or changing-tempo music. Never speed up a track
only to make its grid fit fps; record rounding error when snapping picture cues.
When speech carries the explanation, sync key states to actual word/phrase
timing rather than forcing every sentence onto musical beats. ASR timestamps
can misrecognize words; verify cue text and select a model/language appropriate
to the user, including Vietnamese. Estimates are not measured alignment.

Keep music, SFX, and voice as separate stems. Fade boundaries, allow tail/decay,
duck music under speech, prevent clipping, and verify actual loudness and true
peak. A target such as -16 to -14 LUFS is a delivery choice, not a universal
quality metric. A dramatic dip/hit suits some stories; do not force it on
every explanation. Reuse unchanged video frames when only the mix changes.

For procedural sound, JavaScript OfflineAudioContext can produce offline PCM
or WAV; an audio-capable exporter can encode and mux it. Python can analyze or
mix audio and invoke FFmpeg instead. These are reference implementation paths,
not new EvoFlux tool names. In the current in-app route keep sound cues as
planning data and explicitly report that the exported file is silent.

## Deliver evidence and preserve revisions

Inspect the encoded file as well as the composition preview. Verify picture
and audio refer to the same revision and use the actual exported soundtrack;
a composed preview track cannot validate a different track mixed at export.
Report the artifact, checks performed, important fixes, and remaining limits.
Reuse the stable artifact id for Workbench revisions. Keep generated frames,
stems, references, and videos in session storage unless the user chooses to
save source or output into the project for review and commit.

## Sources

The workflow is adapted to EvoFlux from source inspection, not a benchmark of
the upstream engines. Do not inherit upstream approval prompts, installation
commands, style restrictions, or numerical thresholds as mandatory product rules.

- [Animate story/stage/clock formats](https://github.com/cth9191/animate/blob/7e5eb56feb2dd573f890e1b7b34748af43d58263/plugins/animate/skills/animate/grammar/FORMATS.md)
- [Animate deterministic export and audio mix](https://github.com/cth9191/animate/blob/7e5eb56feb2dd573f890e1b7b34748af43d58263/plugins/animate/skills/animate/tools/export.mjs)
- [Animate review findings](https://github.com/cth9191/animate/blob/7e5eb56feb2dd573f890e1b7b34748af43d58263/plugins/animate/skills/animate/tools/review.mjs)
- [HyperFrames frame capture](https://hyperframes.heygen.com/packages/engine)
- [Playwright screenshots](https://playwright.dev/docs/screenshots)
- [MoviePy audio composition](https://zulko.github.io/moviepy/user_guide/compositing.html)
- [FFmpeg audio filters](https://www.ffmpeg.org/ffmpeg-filters.html)
