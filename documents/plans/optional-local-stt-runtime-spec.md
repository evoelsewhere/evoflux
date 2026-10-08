# Optional Local STT Runtime — Design Specification

Status: Proposed; awaiting product review.

## Summary

EvoFlux can offer local speech-to-text without increasing the initial desktop installer by downloading an optional, versioned STT runtime and model after the user chooses **Install**. Once installed, the local provider can transcribe without sending audio to a hosted STT service. Before installation, users can still use any remote or self-hosted STT providers they have configured; local transcription is unavailable until its runtime and model are installed.

This extends the existing push-to-talk provider chain. It does not replace custom endpoints or add an implicit cloud fallback.

## Goals

- Keep the default EvoFlux desktop and web distributions free of STT model weights.
- Let the user install, update, cancel, retry, and uninstall local STT explicitly.
- Support English, Vietnamese, and Japanese with a multilingual model.
- Keep audio local to the EvoFlux machine for this provider, with no network calls during transcription after installation.
- Reuse the existing provider selection and ordered fallback behavior, including explicit user control over whether a remote provider may receive audio.
- Provide one user-facing flow across Windows, macOS Intel, macOS Apple Silicon, and Linux desktop builds where the runtime is supported.

## Non-goals

- Installing STT packages dynamically through npm, pip, or another end-user package manager.
- Bundling model weights into the standard installer.
- Browser-only local inference or a browser speech-recognition dependency.
- Always-on listening, wake words, TTS, or realtime duplex voice.
- Automatically sending a local transcription to a remote provider after a local error.
- Supporting arbitrary model URLs or third-party runtime manifests in the first release.

## User-visible behavior

### Provider availability

| Runtime state | Local STT behavior | Other configured providers |
|---|---|---|
| Not installed | Show **Download to enable** and model size; local transcription is unavailable | Continue to work as configured |
| Downloading or verifying | Show progress and allow cancellation; do not route audio to a partial install | Continue to work as configured |
| Installed and healthy | Local provider can be selected as primary or an explicitly ordered fallback | Continue to work as configured |
| Missing/corrupt/incompatible | Mark local provider **Needs repair** and offer re-download | Only try another provider if the user explicitly configured it in the chain |
| Uninstalled | Remove managed runtime/model files and mark local STT unavailable | Continue to work as configured |

Settings should explain that no download means no **local** STT. It does not disable remote/custom STT profiles. A local-only routing policy must fail clearly when local STT is unavailable rather than quietly using a hosted service.

### Download and management

The Voice Input settings page contains a local model card with:

- Language coverage and model name/quality tier.
- Download size and estimated installed size where known.
- **Download**, progress, **Cancel**, **Retry**, **Check**, **Update**, and **Remove** actions as appropriate.
- Installed runtime/model version and integrity/health state.
- A clear notice that the selected download comes from the EvoFlux release distribution and that audio is processed locally after installation.

The install is opt-in. A first use of local STT must not trigger a silent download; it can offer a direct action to install and resume after installation completes.

## Proposed architecture

### Components

1. **Local STT provider adapter** — implements the existing STT provider contract. It checks runtime readiness, submits a transient audio clip to the local engine, maps the transcript to the common response, and normalizes local runtime errors.
2. **Runtime manager** — owns manifest validation, downloads, progress, cancellation, integrity checks, safe extraction, activation, health checks, update and uninstall. Reuse the lifecycle patterns already used for the optional Office runtime where they fit.
3. **Curated manifest** — shipped with EvoFlux and defines supported app/runtime/model versions, platform/architecture assets, HTTPS URLs, byte sizes, SHA-256 digests, extraction layout, and model metadata. The application must not accept arbitrary manifest URLs or download locations.
4. **Managed runtime directory** — stores immutable versioned assets below EvoFlux's application data directory, for example `runtimes/stt/<runtime-version>/` and `models/stt/<model-id>/<model-version>/`. Resolve the actual platform data path using existing EvoFlux conventions; do not hard-code user paths.
5. **Voice settings UI** — exposes installation state and actions, then makes the installed local provider available in the existing provider chain. Keep local runtime lifecycle independent of ordinary remote-provider credential settings.

The runtime engine should be behind an adapter boundary so the provider contract is not tied to one inference implementation. The initial engine/model pair must be selected after a focused packaging feasibility check for all target operating systems; candidate packages must preserve multilingual English, Vietnamese, and Japanese support. The current candidate is a multilingual Whisper-family `small` model, with a smaller `base` tier considered only if quality and language behavior remain acceptable. Do not promise exact sizes until the release assets are built and measured.

### Runtime and model packaging

- Publish signed/release-managed, per-platform engine assets and model weights as separate versioned artifacts. This avoids redownloading the model when a compatible engine patch changes, and avoids shipping platform-specific engine files on every OS.
- The manifest pins each artifact's version, byte size and SHA-256. Require HTTPS, stream to a temporary managed file, verify size and digest, then extract to a staging directory and atomically activate it.
- Support interrupted-download resume only when the server supports byte ranges and the partial file is safely bound to the same pinned asset. Otherwise restart cleanly.
- Never execute or load a partially downloaded or unverified asset. Prevent archive path traversal, symlinks escaping the target, and overwrites outside the managed STT directory.
- Retain the previous known-good runtime/model until the new version passes verification and a health check. Roll back activation if the check fails.
- Uninstall only files recorded as owned by the STT runtime manager. Preserve provider configuration; this feature does not create recording files.
- Do not use npm/pip at runtime. Package all required native engine dependencies in the curated platform runtime artifact so a user does not need developer tools or a global Python installation.

### Transcription flow

1. The user holds/taps the existing push-to-talk control and explicitly stops recording.
2. The client sends the in-memory audio to EvoFlux's existing same-origin transcription endpoint.
3. The configured STT chain resolves the local provider only if its runtime is healthy and the user put it in the chain.
4. The backend dispatches the clip to the managed local engine on the EvoFlux host. The local engine does not download models or call external services during inference.
5. The backend returns the normalized transcript and provider/model identity; the client inserts it into the draft for review. It is never auto-submitted.
6. If local inference fails, the router advances only to the next explicitly configured provider allowed by the selected local-only/hosted policy.

This means “local” is relative to the machine running EvoFlux's backend/runtime. In a remote-phone-to-desktop setup, audio travels over the configured EvoFlux connection to that host, then is transcribed there. It does not mean inference runs on the phone.

## Security and privacy requirements

- Download only pinned, HTTPS release assets whose size and SHA-256 match the curated manifest.
- Keep the manifest and extracted files within a canonical app-managed directory with restrictive permissions where supported.
- Do not log audio, transcript text, credentials, or raw engine output. Return normalized errors and bounded diagnostic metadata only.
- Make the backend enforce provider-chain and local-only policy. UI labels alone are not an enforcement boundary.
- Do not add a hosted fallback automatically. The existing explicit fallback list remains the complete set of destinations allowed to receive audio.
- Treat engine/model updates as executable/runtime supply-chain changes: pin versions, verify digests, retain rollback capability, and document the release source.
- Surface required disk space and installation failures without claiming that downloaded code is sandboxed from the local account.

## Platform and compatibility requirements

- Define supported OS/architecture combinations from actual packaged artifacts, not theoretical upstream support.
- Verify Windows x64, macOS Intel, macOS Apple Silicon, and Linux x64 separately. Report unsupported targets explicitly.
- macOS packaging must account for signing/notarization policy and native-library loading. Do not weaken Gatekeeper or advise users to bypass OS security.
- Confirm the local backend can launch the managed engine under packaged desktop builds and that development mode has a documented equivalent.
- The feature remains optional for web deployments: a web client can use Local STT only when connected to an EvoFlux host with the runtime installed.
- No local STT provider appears as ready until a health check verifies the installed engine and model can load.

## Failure behavior

- Network interruption: preserve a resumable partial download only for the same pinned artifact; otherwise remove the partial and let the user retry.
- Digest mismatch or malformed archive: reject and remove the staged asset; keep the current known-good version active.
- Insufficient disk space: fail before activation and show required/free space where available.
- Unsupported platform/architecture: do not offer installation; keep other STT providers available.
- Engine crash, model load failure, or out-of-memory: return a safe local-provider error. Continue through configured fallbacks only under the user's routing policy.
- Update failure: keep the previous installed version active and report that update did not complete.
- Uninstall failure: retain state that allows retry and do not report the runtime as fully removed while owned files remain.

## Acceptance criteria for the eventual implementation plan

- A clean standard EvoFlux install contains no STT model weights and does not offer local STT as ready.
- A user can install the selected model on each declared supported OS/architecture without global Python/npm setup.
- Download progress, cancellation, retries, validation, activation, update, rollback, and uninstall have defined and visible states.
- A successful local transcription works with network access disabled after assets are installed, and the audio is not sent to a hosted endpoint unless the user explicitly configured an allowed fallback.
- Missing or unhealthy local assets never trigger an implicit cloud fallback.
- English, Vietnamese, and Japanese are validated against the selected model using representative audio and product acceptance thresholds established before release.
- The existing remote/custom STT profiles continue to work when the local runtime is absent or removed.
- Platform-specific packaging and permissions are validated on Windows, both macOS architectures, and Linux before those targets are marked supported.

## Open decisions for review

1. Should the first release ship only the multilingual `small` model, or offer both `base` and `small` with explicit size/quality tradeoffs?
2. Which engine/model packaging pair passes the Windows/macOS/Linux feasibility check while meeting the required transcription quality and download size?
3. Should updates be user-initiated only, or should Settings notify that a newer runtime/model is available while requiring the user to start installation?
4. What minimum disk-space reserve and transcription latency should be release acceptance thresholds?

## Related documentation

- [Push-to-talk voice input plan](voice-push-to-talk.md)
- [Current voice input behavior](../features/voice-input.md)
