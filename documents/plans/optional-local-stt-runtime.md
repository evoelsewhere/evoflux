# Optional Local STT Runtime Implementation Plan

> **For agentic workers:** Use `superpowers:executing-plans` to implement this plan task by task. Keep the approved specification as the behavior authority.

**Goal:** Add an opt-in, on-demand multilingual local STT runtime and model that joins EvoFlux's existing provider chain without implicit cloud fallback.

**Architecture:** Reuse the Office runtime's pinned-manifest download lifecycle, but keep Local STT assets and state separate. Package a pinned CPU `faster-whisper` runtime for the app's embedded Python and download the multilingual `small` model as a distinct artifact; a backend adapter sends audio over stdin to a persistent, serialized local worker process so the model stays loaded between prompts. Only published platform assets are installable.

**Tech Stack:** FastAPI, Pydantic, Python 3.12 sidecar, `faster-whisper`/CTranslate2/PyAV, React/TanStack Query, GitHub Actions.

**Spec:** [Optional Local STT Runtime specification](optional-local-stt-runtime-spec.md)

## Global Constraints

- Keep model weights out of the default desktop installer; install only after an explicit user action.
- Support only artifacts present in the pinned manifest; unsupported platform/architecture reports unavailable.
- Use English, Vietnamese, and Japanese with one multilingual Whisper model; do not select an English-only model.
- Do not use runtime `npm`, `pip`, arbitrary manifest URLs, or model auto-download behavior.
- Verify HTTPS artifact byte size and SHA-256 before staging/activation; never load a partial or unverified asset.
- Preserve the prior healthy install until a replacement is verified and passes model-load health check.
- Keep audio in memory and pass it to the local worker over stdin; do not write recordings to disk or log audio/transcripts.
- Local is relative to the host running EvoFlux's sidecar. Remote phone audio is processed on that host.
- Never add a hosted fallback; route only through the user's configured chain and local-only policy.
- Do not remove or rewrite the existing dirty push-to-talk changes in this worktree.
- Do not publish release artifacts or trigger an external release as part of implementation.

## Review Focus

- Absent or empty manifest: Local STT is unavailable and remote providers remain usable.
- Local runtime missing after a saved route: the local route fails safely; no unconfigured/cloud route is added.
- Model load/download or worker failure: keep previous good install, return a normalized provider failure, and obey explicit chain policy.
- Remote phone session: transcribe on EvoFlux host; show that local means host-local.
- macOS/Linux/Windows asset mismatch: do not claim support until a matching verified artifact is published.

## Plan Rulings

- First release uses one multilingual `small` model. Adding `base` creates another model-selection and quality-validation path; the smaller model can be reconsidered after the first cross-platform measurements.
- Use `faster-whisper` with CPU inference, PyAV decoding, and CTranslate2 wheels. The upstream package documents PyAV audio decoding without a system FFmpeg dependency; CTranslate2 documents wheels for macOS x86-64/ARM64 and Windows/Linux x86-64. EvoFlux will declare support only for built and verified artifact targets.
- Build the optional engine package and model as separate artifacts. A manual GitHub workflow may build/upload test artifacts; release publication requires an explicit workflow input and is outside this task.
- Runtime updates are user initiated through the app's normal update/release cycle; no background update check is added.
- Require enough free space for the pinned download, extraction staging, and currently installed version before starting an update. Show sizes from the manifest and fail early when space is insufficient.

## File Map

- `app/services/local_stt_runtime/manifest.py`: platform keys, model/runtime assets, safe manifest validation, and unavailable-by-default pinned assets.
- `app/services/local_stt_runtime/installer.py`: status, background installation, resumable download, verification, safe extraction, activation, rollback, health, cancellation, and uninstall.
- `app/services/local_stt_runtime/worker.py`: persistent local `faster-whisper` worker protocol; read framed requests/audio from stdin, write normalized JSON results to stdout, and keep diagnostics off the audio/transcript channels.
- `app/services/local_stt_runtime/worker_client.py`: start/reuse/restart the serialized worker, bound request time and output, and stop it when the host shuts down.
- `app/voice/providers.py`: add the `local_faster_whisper` adapter while keeping existing HTTP adapters unchanged.
- `app/voice/registry.py`, `app/services/voice_transcription.py`, `app/api/routes/voice.py`: register local provider, expose runtime status/actions, and make the local provider eligible only when installed and explicitly configured.
- `app/api/schemas/local_stt_runtime.py`: typed runtime status/job responses.
- `scripts/build_local_stt_runtime.py`, `scripts/verify_local_stt_runtime.py`, `scripts/local_stt_runtime/requirements.in` and lock file: deterministic engine artifact and multilingual model packaging, hashes, sizes, layout, and smoke verification.
- `.github/workflows/local-stt-runtime.yml`: manual per-platform artifact build/verification and opt-in release upload, mirroring the Office runtime workflow.
- `web/src/api/client/localSttRuntime.ts`, `web/src/api/client/index.ts`, and API types: typed management calls and status.
- `web/src/routes/settings.voice.tsx`: opt-in model card, install progress/cancel/retry/check/update/remove, platform readiness, and clear local-versus-remote explanation.
- `web/src/help/locales/en.ts`, `vi.ts`, `ja.ts`: setup, host-local processing, download size and fallback privacy guidance.
- `documents/features/voice-input.md`, `documents/README.md`, `documents/reference/http-api.md`, `CHANGELOG.md`: shipped behavior and route reference.

## Implementation Tasks

### Task 1: Pin the local runtime contract

1. Define the runtime/model asset records and platform identity independent of the Office runtime module.
2. Define status states (`unavailable`, `not_installed`, `installing`, `ready`, `needs_repair`, `failed`) and job phases (`downloading_runtime`, `downloading_model`, `verifying`, `extracting`, `checking`, `failed`).
3. Keep built-in asset pins empty until CI has generated and verified artifacts; reject malformed, non-HTTPS, oversized, or path-escaping manifest records.
4. Define the worker request/result JSON contract and local provider profile/model IDs. Worker accepts bounded audio bytes from stdin with filename, MIME type, language and model path, and returns text/provider/model only.

### Task 2: Implement safe optional installation

1. Store assets under `EVOFLUX_DATA_DIR/runtimes/stt/` with versioned runtime and model directories and an atomic install record.
2. Download only manifest-pinned runtime and model assets. Check free space before work; report progress for each asset; resume only an exact pinned partial asset when HTTP range semantics are valid.
3. Verify digest and size before extraction; reject traversal, symlink/hardlink, special-file, duplicate-case, entry-count, and expanded-size attacks.
4. Extract to staging, run the worker's health check against the new model, atomically switch the active record, then prune only older manager-owned versions.
5. On failure retain the previous good install. Support cancel during network download, retry/dismiss failed state, integrity check, update, and uninstall without removing provider configuration.

### Task 3: Add model packaging and platform artifact generation

1. Pin all `faster-whisper` runtime dependencies in a dedicated runtime lock file; do not change the default app dependency set.
2. Build a per-platform package for the supported desktop targets using the embedded Python 3.12 ABI and CPU-only dependencies. Keep the package outside the regular Tauri sidecar resources.
3. Package a pinned multilingual Whisper `small` model directory separately, with local config/tokenizer/weights and no request-time model fetch.
4. Generate a JSON manifest containing platform, version, URL template/release URL, archive sizes, installed sizes, SHA-256, extraction roots, Python ABI and model metadata.
5. Verify archive layout and digests and run a model-load smoke check in each CI target. Do not mark unsupported platform entries ready.

### Task 4: Add local inference and provider-chain behavior

1. Invoke/reuse the worker with the packaged sidecar's `sys.executable`, a runtime-only `PYTHONPATH`, and model path; pass each clip through framed stdin bytes and parse a bounded JSON response.
2. Use `local_files_only`/local model path behavior and disable worker network access by design; cap audio size, worker lifetime, CPU threads and returned text size.
3. Normalize missing runtime, missing model, load error, timeout, crash and malformed worker output to provider failures without putting transcript/audio into logs.
4. Register a `local_faster_whisper` adapter and allow a local profile with no endpoint or credential. Settings validation must special-case this adapter while preserving validation for all existing adapters.
5. Filter the local pair from routing when its runtime is not healthy; if it was the only configured pair, return a safe not-installed/needs-repair action. Advance only to explicitly configured allowed fallback pairs.

### Task 5: Add API and Settings management UI

1. Add status, install, cancel, dismiss, check, and uninstall routes under `/api/voice/runtime`; keep install work in the runtime service.
2. Expose only safe state: availability, current/installed version, platform, byte counts, progress, health and normalized error. Never return filesystem paths or asset internals.
3. Add typed browser API functions and a Voice Input Settings card. Poll only while a job is active; support explicit install/cancel/retry/check/update/remove.
4. Let users add the managed local provider to the primary/fallback list only while healthy. If a saved route becomes unavailable, show the configuration error and do not silently mutate the saved route or privacy policy.
5. Clarify audio flows to the EvoFlux host for remote clients and that a hosted fallback receives audio only when explicitly configured and allowed.

### Task 6: Release integration and documentation

1. Add a manual runtime build workflow for Windows x64, macOS Intel, macOS Apple Silicon and Linux x64. Verification runs on PRs touching runtime code; release upload is guarded by an explicit input and contents-write permission.
2. Add generated manifest instructions in workflow summary. Pin asset records in source only after checksums and sizes are produced by a successful build; never invent values.
3. Update the voice feature guide, docs index, HTTP API reference, in-app help for English/Vietnamese/Japanese, and the existing `[Unreleased]` changelog section.
4. Record any platform that has not passed packaged-sidecar and real audio validation as unavailable; do not call the feature release-ready until each declared platform and all three languages meet product thresholds.

## Completion Contract

- A clean install has no STT model weights and offers remote/custom STT unchanged.
- An explicit install downloads only pinned assets, exposes progress and cancellation, verifies before activation, and can recover without losing the previous good install.
- Local transcription loads the installed multilingual model without network access, preserves audio in memory, and inserts a transcript for user review.
- The backend enforces readiness and explicit provider-chain privacy; missing local files never create an implicit cloud fallback.
- User can check/update/uninstall the managed assets without losing provider config.
- API/UI/help/docs/changelog describe actual supported platforms and size/host-local behavior.
- No release is published by the implementation task.

## Research References

- [`faster-whisper`](https://github.com/SYSTRAN/faster-whisper): PyAV audio decoding and Python requirements.
- [CTranslate2 installation](https://github.com/OpenNMT/CTranslate2/blob/master/docs/installation.md): published wheel platform coverage.
- [CTranslate2 hardware support](https://opennmt.net/CTranslate2/hardware_support.html): CPU architecture support and runtime expectations.
