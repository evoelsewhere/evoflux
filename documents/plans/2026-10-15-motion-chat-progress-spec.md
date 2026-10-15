# Motion Frame Progress and Review in Chat

**Date:** 2026-10-15
**Status:** Proposed; awaiting user review
**Repository baseline:** `feat/intelligent-ui` at `b12339e4`

## Goal

When an agent chooses to make a motion explainer, EvoFlux should show the work
as it happens in the conversation. The user should see which stage is active,
how many output frames have actually rendered, which beat is being worked on,
and representative images that can be opened in the Workbench. The Workbench
should let the user inspect the full timeline one frame at a time.

The interface must make a clear distinction between authored story beats,
frames selected for visual review, and the encoded video frames. More output
frames improve temporal sampling; they do not require one model call per frame
or create more choreography by themselves.

## User outcome

For a request that benefits from motion, the agent plans a short sequence of
causal beats, creates a visual direction, writes deterministic drawing code,
renders and reviews representative samples, and revises the affected beat when
there is a concrete defect. The chat card updates through those stages instead
of leaving the user with a long silent wait. The user can open a sample at its
exact timestamp, inspect every output frame in the Workbench, and see a truthful
terminal result, including whether the requested soundtrack was included.

For a request that does not benefit from motion, this flow does not run. Static
`ui_block`, dashboard, or prose responses continue to use their existing
selection rules.

## Verified current behavior

- `visual_artifact` currently emits one complete validated artifact event. The
  saved tool-call arguments rebuild the artifact in conversation history.
- The chat card is compact and opens the full artifact in Workbench. It does not
  currently display live motion-job or frame progress.
- `MotionArtifact` renders deterministic canvas frames at fixed 30 fps through
  the sandbox bridge and Mediabunny. Its export control currently displays a
  percentage and supports cancellation, but the progress is local to Workbench
  and does not expose the completed frame index in chat.
- The sandbox bridge transfers one `ImageBitmap` per frame request. The video
  is built in the app page, separate from generated code.
- The existing export has no audio track. The on-demand motion-production
  reference describes an authoring and review loop, but the runtime does not
  yet give the agent rendered samples to inspect or revise.

## Design principles

1. **Progress describes real work.** The completed-frame count comes from the
   renderer after it receives a frame. Agent stages and beats come from the
   agent runtime. The UI must not infer progress from elapsed time or pretend
   that the model is reviewing frames it has not received.
2. **The model works at beat and sample level.** It authors a composition and
   reviews selected visual evidence. JavaScript renders each encoded frame by
   evaluating the composition at an absolute timestamp. A 15-second, 30-fps
   output is 450 render operations, not 450 model calls.
3. **The chat stays compact.** Show the current stage, exact frame count when
   available, the active beat, and a small contact sheet of representative
   samples. Do not append one chat message or SSE event for every output frame.
4. **The Workbench is the detailed review surface.** It can seek to any frame,
   step one frame backward or forward, and open a contact sheet grouped by
   narrative beat.
5. **A revision owns its render.** A progress update or frame from an older
   artifact revision must never replace or appear inside the current revision.
6. **Keep output in EvoFlux.** Generated source and temporary frame previews
   stay in the session/runtime. Nothing is written into the project unless the
   user explicitly saves it. A downloaded video remains an explicit user action.

## Proposed user experience

### Live chat card

Create one motion-job card when the agent starts the motion workflow. Update
that card in place through composition, sample review, revision, and final
render. When a complete visual artifact is available, the same card gains the
normal **Open in Workbench** action instead of leaving a duplicate progress
card and artifact card.

The card shows:

- a plain-language phase such as **Planning beats**, **Rendering samples**,
  **Reviewing transitions**, **Revising beat 3**, or **Rendering video**;
- the active beat name and `beat N of M` when the beat plan exists;
- the exact `frames completed / frames total` and frame rate while rendering
  the final timeline;
- an indeterminate phase indicator when no meaningful denominator exists;
- a small, bounded contact sheet of selected frames, with each thumbnail
  labeled by beat, frame index, and timestamp;
- a **Review frames** action that opens Workbench at the selected sample;
- a truthful terminal state for success, cancellation, or failure.

Do not display one overall percentage across planning, review, rendering, and
encoding; their costs differ and the runtime cannot calculate that percentage
honestly. Do not show an ETA until the renderer has a measured estimate for the
current job. In legacy real-time recording mode, show an indeterminate export
state because the browser recorder does not report deterministic frame counts.

### Workbench frame review

The motion Workbench provides the detailed view:

- a timeline indexed by timestamp and output frame number;
- previous-frame and next-frame controls, plus seek by timestamp;
- beat boundaries and cut/hit markers from the composition's beat plan;
- a contact sheet of the selected review samples for each beat;
- a generated frame on demand when the user seeks to an output frame that is
  not already cached;
- the pinned artifact revision, render preset, frame rate, and final export
  status;
- an audio status of **included**, **not requested**, or **unavailable/not
  rendered**, so a silent result is never described as having a soundtrack.

Frame previews are rendered at a bounded review size. Keep a small in-memory
cache for recently opened frames and reclaim `ImageBitmap`, blob, and object
URL resources when a job, revision, or Workbench tab is discarded. The app
does not need to retain a full-resolution PNG for every encoded frame.

The beat timeline is registered from the same machine-readable beat data that
`drawAt(timeMs)` uses. Extend the artifact bridge with a validated
`registerTimeline(beats)` call and expose only compact descriptors to the host:
stable beat ID, title, start/end frame, and hit/transition marker frames. Do not
parse generated JavaScript or maintain a second hand-authored timeline that can
drift from the animation.

### Representative visual review

The default agent review set includes style samples, important states, and
samples immediately before and after transitions or impacts. It can expand
when the scene has a known correctness risk. The agent records a finding with
the frame/beat, expected state, observed defect, and proposed smallest repair.
It then re-renders that beat's samples and neighboring transition samples.

The agent does not automatically send every 30-fps frame through a vision model.
When a configured provider supports image input, only the bounded review set is
sent as model input through the normal provider path. When it does not, the
agent must not claim visual inspection: it can run structural and deterministic
checks, show the samples to the user, and label the limitation clearly.

### Renderer-to-agent handoff

The recommended path keeps rendering in EvoFlux's app-hosted sandbox. The chat
host renders a bounded set of requested timestamps in a sandboxed iframe using
the existing `MessageChannel` frame bridge, then sends the selected thumbnails
to the local sidecar over an authenticated, session- and revision-scoped
channel. The `motion_review` tool waits for that sample set and returns it as a
multimodal tool result. EvoFlux already has a `ToolResult` content-block path
for image results; it does not yet have this browser-to-agent sample handoff or
a motion-review tool.

The handoff validates ownership of the active session and job, the pinned
artifact revision, image MIME types, dimensions, sample count, and total bytes.
Cap one review pass at 12 WebP/JPEG thumbnails, at most 640 × 360 and 200 KiB
each, with a 2.4 MiB combined limit. Higher-resolution checks can be requested
for one selected frame in a later review pass.
It times out if the UI renderer is unavailable and returns an explicit
`samples_unavailable` result so the agent can use structural checks or finish
without claiming visual review. Frame pixels never go into the SSE journal.
The generated iframe keeps its current no-network, no-same-origin sandbox; only
the trusted host page sends bounded sample images to the sidecar.

This app-hosted route is preferred over adding a headless Playwright/FFmpeg
worker to the sidecar. It reuses the renderer that already produces the user's
video and keeps the generated view inside EvoFlux. A worker remains a future
option if unattended rendering becomes a requirement; it would add browser
packaging, process isolation, resource limits, and another renderer parity
problem. A progress-only first slice can ship without the sample handoff, but
it must be described as user review, not agent visual review.

## Job and event model

Progress is a separate transient job state. It does not replace the artifact's
source-of-truth tool arguments or create a new artifact table in the first
implementation.

Proposed session-stream snapshot:

```text
MotionProgressEvent
  type: "motion_progress"
  job_id: stable id for one generation/export operation
  sequence: increasing integer within the job
  artifact_id: stable visual artifact id
  artifact_revision: pinned source revision
  status: running | complete | cancelled | failed | interrupted
  phase: planning | storyboard | style_samples | composing |
         rendering_samples | reviewing | revising | final_render | encoding | audio
  beat: null | { id, index, total, title }
  frames: null | {
    scope: review_samples | final_output
    completed, total, fps: optional, last_completed_index
  }
  iteration: null | { current, budget }
  selected_samples: [{ sample_id, beat_id, frame_index, time_ms, role }]
                    (at most 12 per review pass)
  audio_status: not_requested | unavailable | pending | rendering | included
  error_category: optional safe category for a failed job
```

`selected_samples` carries descriptors only. Image pixels stay in the frontend's
bounded preview cache; they are not copied into chat text or serialized as
large data URLs in SSE. The frontend run state associates those descriptors
with locally rendered thumbnails and is keyed by `(job_id, artifact_revision)`.

The browser renderer updates its local shared motion store after each completed
frame. React display updates may be coalesced to the next paint, while the
counter remains exact. The current exporter invokes its progress callback at
roughly five-percent intervals; Slice 1 must expose each completed frame to the
shared store while keeping React paints coalesced. The backend emits lifecycle
changes, beat changes, and review results rather than one SSE event per output
frame. This keeps the transcript and reconnect journal bounded while
preserving frame-accurate UI progress during local rendering.

Use one app-level motion render host per active artifact revision. The chat card
and Workbench share its timeline, sample cache, and render state so the app
does not run duplicate copies of generated code just to show progress and
preview the same frame.

On reconnect during an active turn, the stream replay restores the latest job
snapshot; sequence and revision checks reject duplicate, out-of-order, or stale
updates. Once the turn completes, the artifact itself continues to reconstruct
from normal message history. Temporary preview frames and the browser-generated
video blob are session-local and are not promised to survive app restart; the
user can download the result explicitly.

## Data flow

1. The model selects motion based on temporal value. The first
   `visual_artifact` `tool_call` creates a job keyed to that tool call; the
   backend assigns its stable job ID and emits the initial phase over the
   existing session stream.
2. The app builds the sandboxed candidate revision and renders review samples
   through the existing deterministic `renderFrame(timeMs)` bridge.
3. The agent calls `motion_review`; the host submits only the bounded sample
   set, and the tool returns it through the configured model's multimodal path
   when that model supports image input.
4. The agent emits findings and a targeted new artifact revision where needed.
   The app sends exact local frame counters to the shared motion-job store; the
   chat card and Workbench consume that same state.
5. Final rendering evaluates each output timestamp in sequence and encodes the
   pinned revision. If soundtrack rendering exists for the chosen route, the
   job reports that stage separately and completes only after the actual mux.
6. The chat card presents the final revision and outcome. **Open in Workbench**
   opens the frame timeline and playable result; downloading remains explicit.

If the current runtime cannot perform a stage, it reports that capability as
unavailable and continues only when the user can still receive a useful result.
It must not fabricate storyboard, review, audio, or frame progress to animate
the card while the agent is waiting on a model call.

## Failure and revision behavior

- Frame counts are monotonic within one `(job_id, artifact_revision)` and never
  exceed the declared total.
- An artifact update cancels the old revision's render and ignores any late
  frame or progress message for that revision.
- Cancellation discards the partial encoded video, clears its partial-frame
  cache, and leaves the last completed artifact available.
- A renderer error identifies the failed phase and a safe error category; it
  does not report `complete` or keep a stale preview as the new result.
- If a local render is interrupted by app reload or renderer loss, report
  `interrupted`; do not resume from a partial encoder state. The user can start
  a new render for the same pinned revision.
- Retrying a beat updates the job iteration and sample set. Final video encode
  uses one coherent revision from first frame through last frame.
- Sound requested but unavailable is surfaced as such. Silent video may be
  delivered only with an explicit status that sound was not rendered.

## Scope and delivery slices

### Slice 1: truthful in-chat export progress

Share the existing deterministic export's exact frame counts with the chat
artifact card. Keep the current Workbench controls and cancellation. Add the
frame timeline and representative contact sheet, with on-demand stepping for
any encoded frame. This slice does not claim that the agent visually reviewed
the output; it closes the current gap between Workbench export progress and the
chat transcript.

### Slice 2: agent job lifecycle

Add a validated replayable `motion_progress` event and update the existing chat
card as the agent plans beats, renders samples, reviews, and revises. Keep
progress keyed by job, artifact, revision, and sequence. Add explicit error,
cancel, and reconnect behavior. Do not add a database migration unless the
implementation discovers that the existing turn replay cannot preserve the
active snapshot.

### Slice 3: sample-to-agent review loop

Return bounded rendered samples to the agent only through a supported provider
image-input path. Gate by the active model capability. Add a clear structural
checks/user-review fallback for text-only providers. Measure model calls,
latency, revision quality, and whether findings lead to visible improvements;
do not increase sample count merely to make the process appear more intelligent.

### Slice 4: soundtrack status and rendering

Connect soundtrack planning, synthesis or authorized audio input, and final
muxing as a separate pipeline stage. Keep picture, voice, music, and effects
on one seconds-based timeline. Do not advertise an audio phase as available
until the app can produce and verify an audible final stream.

## Acceptance criteria

1. The chat shows one card from job start through final artifact; live updates
   do not create duplicate transcript blocks.
2. For a 10-second composition at 30 fps, the deterministic exporter reports
   the exact frame total and a monotonic `completed / total` counter. The UI
   reaches completion only after all frames are returned and encoded.
3. Live renderer updates do not create one SSE journal entry per output frame.
   Lifecycle and beat events are replayable, deduplicated by job and sequence,
   and ignored when their artifact revision is stale.
4. The user can click a representative sample in chat and open Workbench at its
   exact frame/time; stepping reaches adjacent frames without changing source.
5. Contact sheets include the selected review samples for all beats and stay
   bounded. The agent does not claim to review frames that were not passed to
   an image-capable model.
6. Failure, cancellation, and revision changes clear or label partial output;
   none can leave a misleading completed video in the card.
7. The progress card and timeline inherit EvoFlux theme and reduced-motion
   preferences and remain keyboard and screen-reader operable.
8. An audio request is explicitly marked included or unavailable/not rendered.
   The UI never labels a silent file as a soundtrack-complete video.
9. Generated HTML remains in the existing isolated artifact sandbox. Progress
   previews and source stay outside the repository unless the user explicitly
   saves them.

## Cross-feature impact

| Area | Proposed impact |
|---|---|
| Agent events and replay | Add a typed progress event, replay policy, and bounded snapshot semantics in `app/agent/schemas/events.py`, `app/services/stream_envelope.py`, and `app/services/memory_stream_store.py`. |
| Agent authoring flow | Start the job from the `visual_artifact` tool lifecycle, add a bounded `motion_review` tool and session-scoped sample rendezvous, and bind every update to the artifact revision. Keep the model prompt tool-agnostic where runtime capability differs. |
| Chat state and card | Parse progress in `web/src/api/types.ts` and `web/src/stores/useTeamStore/sse-reducer.ts`; render and update the motion job card in `web/src/components/VisualArtifactRenderer.tsx`. |
| Workbench renderer | Share frame counters and selected previews with `MotionArtifact.tsx`; add lazy frame stepping and beat navigation, and validate `registerTimeline(beats)` metadata in `web/src/lib/visual-artifact-bridge.ts` and `VisualArtifactFrame.tsx` without weakening sandbox isolation. |
| Provider capabilities | Inspect the active model's image-input support before any automated visual review. MiMo support must be established from its configured capability, not assumed. |
| Help and feature docs | Document the chat progress card, frame review, audio status, privacy boundary, and legacy recorder limitation in the feature page and localized in-app Help. |
| Transcript and storage | Reuse normal artifact tool-call history. Keep progress and rendered previews transient for the first slices; avoid a new table and project writes. |
| Other chat surfaces | Forward only a compact status summary where a remote surface already supports these session events. Do not send thumbnail bytes through text-only bridges. |

## Review questions

The user has selected the review model: show exact progress for all rendered
output frames, show representative previews in chat, and open the full timeline
to inspect every frame. Generated source and preview output remain in EvoFlux
until the user explicitly saves or downloads them. The following decisions
remain for review:

- Is the app-hosted sample handoff plus `motion_review` tool acceptable for
  automated representative-frame review, with a structural/user-review
  fallback for text-only models?
- Should implementation begin with Slice 1 and then add agent lifecycle and
  sample review, or is a single end-to-end delivery preferred?
