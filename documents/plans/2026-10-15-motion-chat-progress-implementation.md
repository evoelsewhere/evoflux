# Motion Frame Progress and Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show truthful, frame-accurate motion production and export progress in chat, let users and vision-capable agents review bounded frame samples in Workbench, and produce an honest audio outcome in the rendered video.

**Architecture:** Keep frame rendering and preview media in the EvoFlux webview, with one revision-pinned local render state shared by the chat card and Workbench. Use typed, replayable lifecycle events for agent stages and a session-scoped, bounded rendezvous for selected samples; never put frame bytes or per-frame events in the SSE journal. Keep the generated artifact sandbox unchanged and synthesize optional soundtrack cues through the existing local video encoder.

**Tech Stack:** FastAPI/Pydantic sidecar, in-memory stream replay, built-in agent tools, React/TypeScript, Zustand, sandboxed `MessageChannel` iframe, Mediabunny/WebCodecs, Vitest, pytest.

**Spec:** `documents/plans/2026-10-15-motion-chat-progress-spec.md`

## Global Constraints

- Rendered progress comes from completed renderer work; never infer frame counts, review results, or ETA from elapsed time.
- Model reasoning happens at story-beat and selected-sample level; never call the model once per encoded frame.
- Keep each frame sample at or below 640 × 360 and 200 KiB, with no more than 12 samples or 2.4 MiB per review pass.
- Bind every lifecycle event, preview sample, and render result to the active session, job, artifact ID, and artifact revision.
- Keep image pixels out of SSE events and replay history; coalesce replay to the latest snapshot per job.
- Preserve the generated iframe's no-network, no-same-origin sandbox and do not persist preview output or source into the project without an explicit user action.
- Keep the legacy MediaRecorder path indeterminate; it does not expose deterministic frame totals.
- Show audio as included only after a real audio track is muxed and verified; otherwise report not requested or unavailable/not rendered.
- Do not add a database migration for transient motion progress or preview samples.
- Follow the existing theme, reduced-motion, keyboard, screen-reader, and localized Help contracts.

## Review Focus

- A late frame, sample, or event from an older revision must never replace the current artifact's progress or preview.
- Cancelling or failing deterministic export must not leave a complete counter, stale completed video, or retained preview resources.
- A renderer that never answers a sample request must time out with an explicit unavailable result and release the waiting agent tool.
- A text-only provider must never receive image blocks or be told that it visually reviewed samples.
- Legacy real-time recording must show an indeterminate state instead of inventing a frame total.

## File Map

- `app/agent/schemas/events.py` owns the typed motion lifecycle, sample descriptors, beat descriptors, and audio status contracts.
- `app/services/stream_envelope.py` and `app/services/memory_stream_store.py` own typed event transport and bounded reconnect replay.
- `app/agent/tools/builtin/visualize/` owns agent-facing progress and sample-review tools; `app/api/routes/team/` owns authenticated browser-to-sidecar sample submission.
- `web/src/api/types.ts` and `web/src/stores/useTeamStore/` own SSE parsing and one-card transcript state.
- `web/src/lib/visual-artifact-bridge.ts`, `web/src/components/VisualArtifactFrame.tsx`, and `web/src/components/visual-artifact/MotionArtifact.tsx` own the isolated renderer bridge, deterministic frame counter, and local export.
- `web/src/components/VisualArtifactRenderer.tsx` and `web/src/components/workbench/VisualArtifactWorkbench.tsx` own the compact chat card and detailed frame review surface.
- `web/src/help/locales/`, `documents/features/intelligent-ui.md`, `documents/plans/`, and `CHANGELOG.md` own the user guidance and current feature contract.

## Tasks

### Task 1: Validate and expose beat timeline metadata

**Files:**
- Modify: `web/src/lib/visual-artifact-bridge.ts`
- Modify: `web/src/components/VisualArtifactFrame.tsx`
- Test: `web/src/__tests__/lib/visual-artifact-bridge.test.ts`
- Test: `web/src/__tests__/components/VisualArtifactFrame.test.tsx`

**Interfaces:**
- Produces `MotionTimelineBeat = { id: string; title: string; startFrame: number; endFrame: number; markers: Array<{ frame: number; kind: 'hit' | 'cut' | 'transition' }> }`.
- `window.evofluxArtifact.registerTimeline(beats)` accepts 1–64 unique beats, bounded title and ID strings, valid non-overflowing frame indices, and at most 32 markers per beat. The trusted host receives a validated `timeline` bridge message; the sandbox receives no new network or parent-window privileges.

```ts
export interface MotionTimelineBeat {
  id: string
  title: string
  startFrame: number
  endFrame: number
  markers: Array<{ frame: number; kind: 'hit' | 'cut' | 'transition' }>
}
```

- [x] Add a failing parser test for a valid beat timeline and verify the current parser rejects the new bridge message.
- [x] Add failing cases for duplicate IDs, more than 64 beats, a negative or reversed frame range, markers outside their beat, and overlong labels.
- [x] Implement the timeline message type and bounded parser in `visual-artifact-bridge.ts`.
- [x] Add `registerTimeline` to the frozen iframe bridge API and forward only validated metadata through the existing `MessagePort` in `VisualArtifactFrame.tsx`.
- [x] Run `cd web && bun test src/__tests__/lib/visual-artifact-bridge.test.ts src/__tests__/components/VisualArtifactFrame.test.tsx`; confirm the new contract passes and the CSP/sandbox assertions remain unchanged.
- [x] Commit as `feat(intelligent-ui): expose validated motion beat timelines`.

### Task 2: Share exact render progress and frame review state

**Files:**
- Create: `web/src/lib/motion-render-store.ts`
- Modify: `web/src/lib/motion-video-export.ts`
- Modify: `web/src/components/visual-artifact/MotionArtifact.tsx`
- Modify: `web/src/components/VisualArtifactRenderer.tsx`
- Modify: `web/src/components/workbench/VisualArtifactWorkbench.tsx`
- Test: `web/src/__tests__/lib/motion-video-export.test.ts`
- Test: `web/src/__tests__/components/VisualArtifactRenderer.test.tsx`
- Test: `web/src/__tests__/components/VisualArtifactWorkbench.test.tsx`

**Interfaces:**
- `MotionRenderSnapshot` is keyed by `(artifactId, revision)` and contains `status`, `completedFrames`, `totalFrames`, `fps`, `lastCompletedIndex`, `currentTimeMs`, validated beats, selected preview descriptors, and explicit audio status.
- `publishMotionRenderSnapshot(snapshot)` rejects stale revisions and decreasing counters; `subscribeMotionRender(artifactId, revision, listener)` returns an unsubscribe function. Keep only the current frame and at most 12 selected preview images in memory.
- `MotionArtifact` publishes every completed deterministic frame; React subscribers may batch paints, while the stored count remains exact. The MediaRecorder fallback publishes `totalFrames: null`.
- `MotionReviewSample` is `{ sampleId, beatId, frameIndex, timestampMs, role, objectUrl }`, with `role` restricted to `style | key_state | before_transition | after_transition | impact`.

```ts
export type MotionRenderSnapshot = {
  artifactId: string
  revision: number
  status: 'idle' | 'rendering' | 'complete' | 'cancelled' | 'failed'
  completedFrames: number
  totalFrames: number | null
  fps: number | null
  lastCompletedIndex: number | null
  currentTimeMs: number
  beats: MotionTimelineBeat[]
  samples: MotionReviewSample[]
  audioStatus: 'not_requested' | 'unavailable' | 'pending' | 'rendering' | 'included'
}
```

- [x] Add a failing exporter test asserting progress callback indices are `1..totalFrames`, including the final frame, instead of only five-percent boundaries.
- [x] Add failing store tests for monotonic counts, revision replacement, stale update rejection, selected-sample cap, and resource cleanup on cancel.
- [x] Change `exportMotionFrames` to invoke `onProgress(completed, totalFrames)` after every encoded frame and preserve cancellation checks before requesting the next frame.
- [x] Implement the revision-keyed render store and connect validated timeline metadata from `VisualArtifactFrame` to the active motion snapshot.
- [x] Publish deterministic progress and representative preview frames from `MotionArtifact`; leave legacy recorder totals unknown and label audio based on actual output.
- [x] Add Workbench previous/next frame controls, timestamp/frame readout, beat boundaries, hit/cut markers, and selected-sample contact sheets. Seeking requests one frame from the existing bridge and does not change artifact source.
- [x] Extend the compact chat card with exact `completed / total` progress when available, representative thumbnails, an accessible status, and **Review frames** opening the Workbench at that frame/time.
- [x] Run the three focused Vitest files and verify cancellation, hidden-tab teardown, and URL/ImageBitmap cleanup.
- [x] Commit as `feat(intelligent-ui): share exact motion frame progress`.

### Task 3: Add replayable agent motion lifecycle

**Files:**
- Modify: `app/agent/schemas/events.py`
- Modify: `app/services/stream_envelope.py`
- Modify: `app/services/memory_stream_store.py`
- Create: `app/agent/tools/builtin/visualize/motion_progress.py`
- Modify: `app/agent/tools/builtin/visualize/__init__.py` or the existing visual tool registration module
- Modify: `web/src/api/types.ts`
- Modify: `web/src/stores/useTeamStore/types.ts`
- Modify: `web/src/stores/useTeamStore/sse-reducer.ts`
- Modify: `web/src/components/VisualArtifactRenderer.tsx`
- Test: `tests/agent/schemas/test_visual_artifact.py`
- Test: `tests/services/test_memory_stream_store.py`
- Test: new `tests/agent/tools/builtin/visualize/test_motion_progress.py`
- Test: new `web/src/__tests__/stores/useTeamStore.motionProgress.test.ts`

**Interfaces:**
- `MotionProgressEvent` contains `type`, `job_id`, positive `sequence`, `artifact_id`, positive `artifact_revision`, `status`, `phase`, optional `{id,index,total,title}` beat, optional `{scope,completed,total,fps,last_completed_index}` frame counts, optional `{current,budget}` iteration, at most 12 sample descriptors, and `audio_status`.
- During a review request, `MotionProgressEvent` also carries `sample_request_id` plus the bounded descriptors requested from the frontend. The frontend treats a new request ID as work to render and POST; completed samples use the same descriptors without a pending request ID. `included` audio status is owned by the local exporter after mux verification, not guessed by the agent lifecycle tool.
- The `motion_progress` tool accepts only a lifecycle update (phase, artifact ID/revision, optional beat/iteration/audio intent); the sidecar derives a session-and-turn-scoped job ID, owns the increasing sequence, and publishes a typed `MotionProgressEvent` to the active session stream.
- Replay retains only the newest event for each `job_id`; connected subscribers still receive lifecycle updates. No image bytes enter the event model.
- The chat reducer creates one motion card per job and merges the final `visual_artifact` block into that card by artifact ID; duplicate or out-of-order sequence numbers and stale revisions are ignored.

```python
class MotionReviewSampleDescriptor(BaseModel):
    sample_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    beat_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    frame_index: int = Field(ge=0)
    timestamp_ms: int = Field(ge=0, le=120_000)
    role: Literal["style", "key_state", "before_transition", "after_transition", "impact"]


class MotionProgressEvent(BaseModel):
    type: Literal["motion_progress"] = "motion_progress"
    job_id: str = Field(min_length=1, max_length=120)
    sequence: int = Field(ge=1)
    artifact_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,79}$")
    artifact_revision: int = Field(ge=1)
    status: Literal["running", "complete", "cancelled", "failed", "interrupted"]
    phase: Literal["planning", "storyboard", "style_samples", "composing", "rendering_samples", "reviewing", "revising", "final_render", "encoding", "audio"]
    sample_request_id: str | None = Field(default=None, max_length=120)
    selected_samples: list[MotionReviewSampleDescriptor] = Field(default_factory=list, max_length=12)
```

- [x] Add failing Pydantic tests for invalid phase/status combinations, negative counters, `completed > total`, malformed beat/sample descriptors, and over-limit sample lists.
- [x] Add failing memory-stream tests proving latest-per-job replay, live event ordering, and no per-frame replay growth.
- [x] Implement the typed event, register it in `AnyStreamEvent`, and coalesce only the replay journal entry for a job while preserving live fan-out.
- [x] Add `motion_progress` with server-owned `job_id` and sequence; validate active `session_id`, artifact ID/revision, and injected caller state before publishing.
- [x] Add frontend event types and reducer behavior; merge the artifact into the existing job card and ignore stale revisions/sequences.
- [x] Add reducer tests for one-card behavior, reconnect snapshot replay, duplicate sequence rejection, and revision replacement.
- [x] Run `uv run pytest --no-cov -q tests/agent/schemas/test_visual_artifact.py tests/services/test_memory_stream_store.py tests/agent/tools/builtin/visualize/test_motion_progress.py` and `cd web && bun test src/__tests__/stores/useTeamStore.motionProgress.test.ts`.
- [x] Commit as `feat(intelligent-ui): stream motion job lifecycle`.

### Task 4: Return bounded visual samples to vision-capable agents

**Files:**
- Create: `app/services/motion_review_service.py`
- Create: `app/agent/tools/builtin/visualize/motion_review.py`
- Modify: `app/api/routes/team/chat.py` or a dedicated module under `app/api/routes/team/`
- Modify: `app/api/routes/team/__init__.py` if a dedicated router is used
- Modify: `web/src/api/client/team.ts`
- Modify: `web/src/components/VisualArtifactRenderer.tsx`
- Modify: `web/src/components/VisualArtifactFrame.tsx`
- Modify: `app/agent/builtin_skills/intelligent-ui/reference/motion-production.md`
- Test: new `tests/services/test_motion_review_service.py`
- Test: new `tests/api/routes/test_team_motion_review.py`
- Test: new `tests/agent/tools/builtin/visualize/test_motion_review.py`
- Test: `web/src/__tests__/components/VisualArtifactFrame.test.tsx`

**Interfaces:**
- `POST /api/team/{session_id}/motion-review/{job_id}` accepts `{sample_request_id, artifact_id, artifact_revision, samples:[{sample_id, frame_index, timestamp_ms, mime_type, image_base64}]}` and requires the existing session/API authorization path. Validate the decoded bytes and cap the encoded request body before Pydantic parses it.
- The rendezvous accepts at most 12 WebP/JPEG images, each at most 640 × 360 and 200 KiB, and at most 2.4 MiB total. It validates the pending session, job, artifact revision, sample IDs, image headers, and dimensions before resolving the waiting tool.
- `motion_review(artifact_id, artifact_revision, samples)` emits a bounded request to the frontend, waits at most 20 seconds, then returns `ToolResult` image blocks only when the active model capability has `input.vision == true`. Otherwise it returns a clear `samples_unavailable` text result and never claims inspection.
- The frontend renders only the requested timestamps through the existing sandbox bridge and POSTs encoded thumbnails to the authenticated route; no bytes are included in SSE or tool-call arguments.

```python
class MotionReviewSample(MotionReviewSampleDescriptor):
    mime_type: Literal["image/webp", "image/jpeg"]
    image_bytes: bytes


async def wait_for_motion_samples(
    *, session_id: str, job_id: str, request_id: str, timeout_seconds: float = 20.0
) -> list[MotionReviewSample]: ...

async def submit_motion_samples(
    *, session_id: str, job_id: str, request_id: str, samples: list[MotionReviewSample]
) -> None: ...
```

The route request encodes each thumbnail as base64 JSON, decodes it before the 200 KiB/sample and 2.4 MiB/pass checks, and uses the same API authorization as other team-session writes.

- [x] Add failing service tests for valid submission, wrong session/job/revision, wrong sample ID, invalid MIME/header, oversized image, excessive dimensions/count/total bytes, duplicate submission, timeout, and cancellation cleanup.
- [x] Add failing tool tests proving vision models receive image blocks and text-only models receive an explicit unavailable result without waiting for the renderer.
- [x] Implement the in-memory session/job rendezvous with injected timeout behavior; remove pending requests in `finally` on success, timeout, and cancellation.
- [x] Add the authorized route with strict request-size validation and session ownership checks before reading image data.
- [x] Add the agent tool and verify image input against the configured provider capability through the existing model capability flow.
- [x] Have the chat render host satisfy pending sample requests using only the requested frames; label samples with beat/frame/time and keep the existing iframe CSP unchanged.
- [x] Update the motion-production Skill to request a small representative set around beats, hits, and transitions; revise only when returned evidence identifies a concrete defect; never review every output frame or claim unavailable vision review.
- [x] Run `uv run python scripts/validate_skills.py --strict-warnings` and `uv run pytest --no-cov -q tests/agent/skills/` after changing the Skill.
- [x] Run focused route/service/tool tests and `uv run ruff check app/agent/tools/builtin/visualize app/services/motion_review_service.py app/api/routes/team`.
- [x] Commit as `feat(intelligent-ui): add bounded motion frame review`.

### Task 5: Synthesize and mux optional soundtrack cues

**Files:**
- Modify: `app/agent/schemas/events.py`
- Modify: `app/agent/tools/builtin/visualize/visual_artifact.py`
- Modify: `app/agent/builtin_skills/intelligent-ui/reference/motion-production.md`
- Modify: `web/src/api/types.ts`
- Modify: `web/src/lib/motion-video-export.ts`
- Modify: `web/src/components/VisualArtifactFrame.tsx`
- Modify: `web/src/components/visual-artifact/MotionArtifact.tsx`
- Modify: `web/src/components/VisualArtifactRenderer.tsx`
- Test: `tests/agent/schemas/test_visual_artifact.py`
- Test: `tests/agent/tools/builtin/visualize/test_visual_artifact.py`
- Test: new `web/src/__tests__/lib/motion-soundtrack.test.ts`
- Test: `web/src/__tests__/lib/motion-video-export.test.ts`

**Interfaces:**
- A motion artifact may include a declarative, bounded `soundtrack` with a style label and up to 64 time-based cues. Each cue has a stable ID, start time, duration, waveform/instrument from a fixed allowlist, frequency or note, and bounded gain; arbitrary source code, remote audio URLs, and user-local file paths are rejected.
- `synthesizeMotionSoundtrack(spec, durationMs)` deterministically returns an `AudioBuffer` or `null` when no cues are requested; `exportMotionFrames` adds that buffer as an audio track using Mediabunny `AudioBufferSource` only when the browser supports the required audio encoder and container.
- `audio_status` is `not_requested`, `unavailable`, or `included`; `included` is set only after finalization confirms a muxed audio track. Export progress keeps audio synthesis/encoding as a named stage and does not combine its percentage with frame rendering.

```python
class MotionSoundCue(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    start_ms: int = Field(ge=0, le=120_000)
    duration_ms: int = Field(ge=20, le=10_000)
    waveform: Literal["sine", "triangle", "square", "sawtooth", "noise"]
    frequency_hz: float = Field(ge=30, le=12_000)
    gain: float = Field(ge=0, le=0.35)


class MotionSoundtrackSpec(BaseModel):
    style: str = Field(min_length=1, max_length=80)
    cues: list[MotionSoundCue] = Field(max_length=64)
```

- [x] Add failing schema tests for valid cues, duration overflow, out-of-range gain/frequency, duplicate IDs, excessive cue count, and audio cues on non-motion artifacts.
- [x] Add failing deterministic synthesis tests asserting buffer duration, cue timestamps, amplitude bounds, and identical output for identical cue specs.
- [x] Add an exporter test proving the video-only path remains valid and the audio path writes a track before finalization; assert unavailable audio never produces `included` status.
- [x] Implement cue validation and a deterministic local synthesizer with bounded oscillators, envelopes, and seeded noise; do not evaluate generated JavaScript for audio.
- [x] Mux the synthesized `AudioBuffer` with Mediabunny when supported, cancel synthesis/encoding with the video job, and report explicit fallback status otherwise.
- [x] Extend the chat card and Workbench status text so a silent result says sound was not rendered, while a soundtrack is called included only after successful mux.
- [x] Update the Skill to author sparse hit/transition cues and a few restrained tonal effects from the story's emotional tone; add no cues when sound has no user value.
- [x] Run focused Python and Vitest tests, then `cd web && bun run typecheck && bun run lint`.
- [x] Commit as `feat(intelligent-ui): mux synthesized motion soundtracks`.

### Task 6: Update product contract and verify the integrated flow

**Files:**
- Modify: `documents/features/intelligent-ui.md`
- Modify: `web/src/help/locales/en.ts`
- Modify: `web/src/help/locales/vi.ts`
- Modify: `web/src/help/locales/ja.ts`
- Modify: `CHANGELOG.md`
- Test: relevant existing visual-artifact, SSE replay, Workbench, Help, and motion-export suites
- Test: new `web/src/__tests__/help/motion-progress-locales.test.ts`

- [x] Add failing locale contract assertions for the new in-chat frame progress, Workbench review, vision-capability fallback, soundtrack status, and legacy recorder behavior.
- [x] Document shipped behavior and its limits in the feature page and all three in-app Help locales; distinguish deterministic export from legacy real-time recording and agent review from user review.
- [x] Add one `[Unreleased]` entry under the matching changelog group describing the user-visible progress, review, and optional soundtrack behavior.
- [x] Run focused backend and frontend suites, `uv run ruff check app/ tests/`, `uv run ruff format --check app/ tests/`, `uv run ty check app/`, `cd web && bun run lint && bun run typecheck && bun run build`, and `git diff --check`.
- [x] Review the combined diff against every acceptance criterion in the spec; leave unrelated pre-existing worktree changes unstaged and untouched.
- [x] Commit as `docs(intelligent-ui): document motion progress and review` if documentation changes remain after the feature commits.

## Spec Coverage

- Criteria 1–3: Tasks 2 and 3.
- Criteria 4 and 7: Tasks 1, 2, and 6.
- Criteria 5: Task 4.
- Criteria 6 and 9: Tasks 2 and 4.
- Criterion 8: Task 5.
- Theme/reduced-motion, keyboard, and screen-reader behavior: Tasks 2 and 6.
- Provider capability and truthful fallback: Task 4.

## Self-Review Notes

- The spec's remaining implementation choice is resolved by delivering the slices in dependency order: renderer/timeline, exact progress UI, lifecycle replay, sample review, then soundtrack, followed by integrated docs and verification.
- The renderer reports exact counts locally and does not emit one SSE event per output frame. Backend lifecycle replay is one latest snapshot per job; live lifecycle events remain ordered.
- The app-hosted renderer remains authoritative for generated frames; the sidecar receives only explicitly bounded review samples. The legacy recorder path reports an unknown total.
- Soundtrack generation is declarative and deterministic so generated source cannot execute audio-export code. Unsupported audio is surfaced as unavailable rather than silently marked complete.
