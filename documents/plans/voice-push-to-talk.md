# Push-to-Talk Voice Input — V1 Implementation Plan

Status: Approved; implementation complete, pending real-provider and device validation.

## Objective

Add push-to-talk voice input to EvoFlux chat with a provider system that can use multiple speech-to-text (STT) models and automatically fail over when a configured provider is unavailable, its credentials expire, quota is exhausted, or the selected model is missing. Keep transcription independent from the selected chat model and make local/self-hosted endpoints first-class.

The user reviews and edits the transcript in the composer. Voice input never sends a chat message automatically.

## Product and architecture decisions

1. Add a **separate STT provider registry and contract** that follows EvoFlux provider principles: curated adapters, plugin adapters, custom endpoints, per-provider credentials, model configuration, and normalized failures. Do not reuse LLM adapters; their chat/tool/streaming contracts do not fit audio uploads and transcription responses.
2. A provider profile owns its adapter, endpoint, authentication, and supported options. Models are children of that profile. Routing stores a primary provider/model pair and an ordered list of explicit fallbacks.
3. The initial generic adapter is OpenAI-compatible. A single configurable adapter can cover OpenAI, Groq, local `whisper.cpp`/LocalAI/faster-whisper servers that implement the same contract, and other compatible endpoints. The URL and model remain user-configurable.
4. Include named native adapters for **Deepgram, Azure AI Speech fast transcription, and Google Cloud Speech-to-Text** so v1 covers materially different auth, request, and response protocols. Keep the adapter interface open for plugins and future named adapters. AssemblyAI's upload/job/poll lifecycle is a follow-on adapter because it has different remote-file retention and cancellation behavior; do not claim local-only audio handling for it.
5. Provider/model discovery is adapter-specific and optional. Never assume a chat `/models` endpoint lists transcription models. Always support manual model IDs and a provider test.
6. Automatic fallback is sequential and only through the user's explicitly ordered list. Audio is never sent to an unconfigured endpoint or silently escalated from local to hosted service. Show each configured endpoint's destination class (EvoFlux host, private network, hosted service) and which provider/model handled each transcription.
7. Web and Tauri share the browser recorder and same-origin EvoFlux transcription API. The backend owns upstream API keys and calls configured endpoints. A later direct-to-client adapter may be considered for endpoints only reachable from a phone, but it must not expose authenticated credentials to browser storage.

## V1 provider coverage

| Adapter | Intended coverage | Request/auth characteristics | V1 behavior |
|---|---|---|---|
| OpenAI-compatible | OpenAI, Groq, local Whisper-compatible servers, custom endpoints | Multipart audio + model and optional language; bearer/API-key style auth varies by endpoint | User supplies base URL, model, key and optional supported fields. Normalize JSON `text` and plain-text response only when configured/advertised. |
| Deepgram native | Deepgram pre-recorded transcription | Binary audio body, `Token` auth, model/language/options in query | Map Deepgram `results.channels[].alternatives[0].transcript` to common transcript result. |
| Azure Speech fast transcription | Azure Speech resource and compatible fast-transcription container | Multipart `audio` + JSON `definition`; subscription-key or supported bearer auth | Map `combinedPhrases`/`phrases` into common transcript result; allow region/locale/model options exposed by adapter. |
| Google Cloud Speech-to-Text | Google Cloud synchronous recognition | JSON audio/config request; OAuth/ADC credentials are resolved by the backend, never pasted into the browser | Concatenate first alternatives in result order; handle service-account/ADC setup and project/region requirements in the provider form. |

The generic endpoint adapter is the extensibility baseline, not a promise that every service with a similar URL is wire-compatible. Native API differences belong in named adapters. Avoid arbitrary user-provided request templates in v1: they make credential forwarding, error classification, and support difficult to audit.

## User experience

### Composer

- Add a microphone control beside existing composer actions; keep typed text intact.
- Desktop interaction: press and hold to record, release to stop. Also support explicit stop/cancel controls and keyboard users.
- Touch interaction: tap to start and tap to stop; do not require a sustained press.
- Show permission prompt guidance, elapsed time, recording state, cancel, upload/transcribing state, retry and accessible errors.
- On success, insert the transcript at the caret (or append predictably if caret placement is unavailable), preserving existing text. Let the user edit, discard, or send it normally.
- If all providers fail, preserve the draft and show a safe per-provider summary with a link to STT settings.
- If a fallback succeeds, identify the provider/model in a subtle status message. Do not show keys, raw upstream bodies, audio contents, or transcript in diagnostics.

### Speech-to-Text settings

Add a dedicated settings page or section with:

- Provider profiles: add, edit, duplicate, test, enable/disable, delete.
- Adapter selection: OpenAI-compatible, Deepgram, Azure Speech, Google Cloud Speech-to-Text, and installed STT plugins.
- Endpoint, auth setup, model list/manual model ID, language/locale, and adapter-supported options.
- A primary provider/model pair and drag/reorderable fallback pairs. Permit multiple models from one endpoint and the same model to appear only once in the active chain.
- A privacy/destination label and explicit opt-in when adding a hosted provider to a chain that otherwise uses a local/private endpoint. Offer “local/private endpoints only” enforcement.
- Masked credential state, credential update/clear flow, last-test result/time, and last runtime failure category. Never expose the secret on reads.
- Model discovery only where the adapter has a reliable transcription-model listing. Manual entry is always available; a successful `/models` response is not proof that a model supports audio.
- “Test” sends a short, user-recorded sample only after an explicit action and clearly says which endpoint receives it. Do not silently upload canned or recorded audio during settings load.

## Routing, retry, and recovery contract

The routing input is one validated in-memory audio clip plus language and non-secret options. The routing chain is a deterministic ordered list of provider/model pairs.

1. Validate media type, duration/size bounds, non-empty audio and configured provider chain before network calls. Request-wide validation errors stop immediately and do not try another provider.
2. Attempt the primary pair, then enabled fallbacks in configured order. Do not call providers in parallel by default: parallel fan-out increases cost and sends the user's audio to more endpoints.
3. Normalize adapter failures into categories: authentication/expired credential, quota/rate limit, transient unavailable/timeout, provider/model unavailable, unsupported audio, invalid request, invalid response, and unknown.
4. Authentication, quota/rate limit, provider unavailable, retired/missing model, and malformed provider response advance to the next pair. Do not retry a rejected credential in the same request.
5. Retry at most once for network timeout/connection reset/5xx with a short bounded delay, then advance. Respect a short `Retry-After` only within the overall transcription deadline; otherwise advance immediately.
6. Unsupported audio, clip too large/long, empty recording, or other request-wide validation errors stop without fallback. A provider-specific unsupported-format response may advance only if the adapter can distinguish it from invalid user audio.
7. First valid, non-empty transcript wins. Return only transcript, selected provider/model IDs, safe fallback metadata, and optional supported timing/language metadata.
8. If all pairs fail, return one normalized error with safe per-provider categories and corrective hints. Preserve the composer draft.
9. Mark auth failures as “Needs attention” without permanently disabling a provider; credentials can be updated. Keep transient health/cooldown state in memory with expiry. Configuration and order persist. A successful explicit test clears attention status.
10. Never follow an upstream redirect while forwarding credentials to another host. Apply URL validation and safe DNS/network rules while explicitly allowing user-configured loopback and private LAN endpoints; block cloud metadata and other unintended link-local targets. Require HTTPS for hosted authenticated endpoints unless the user explicitly configures a trusted local HTTP endpoint.

## Data, credentials, and privacy

- Capture audio with `getUserMedia` + `MediaRecorder` after a direct user gesture; stop every media track immediately after recording/cancel and revoke temporary object URLs.
- Keep captured and uploaded audio transient in client/server memory only. Do not write temporary audio files, persist audio/transcripts separately, or include payloads in application logs, traces, crash reports, or analytics.
- Keep provider metadata and routing in the app's normal settings persistence. Keep secret values in EvoFlux's existing server-side credential mechanism (process environment or `{EVOFLUX_CONFIG_DIR}/.env`); do not store them in SQLite, localStorage, URL parameters, or frontend state beyond the edit form's transient input.
- Namespace credentials by stable provider profile ID and field, sanitize IDs, support secret rotation/clear, and verify configured state without printing secret values.
- Failover is a privacy and cost choice. Only explicitly configured pairs are eligible; clearly label cloud destinations, allow local/private-only policy, and report which configured destination received the clip.
- Minimize retention claims for hosted services: EvoFlux does not persist the clip, but each upstream provider's own processing/retention terms still apply. Document that the user selects the provider and is responsible for its policy.

## Platform requirements

- The current response policy blocks microphone access (`microphone=()`). Change it narrowly to allow the EvoFlux origin to request a microphone only through its user-initiated UI. Keep camera/geolocation and background capture disabled.
- Browser microphone capture requires a secure context (HTTPS or localhost). Remote phone use over Tailscale must use HTTPS; HTTP fallback cannot be relied on for microphone capture.
- Inspect the existing Tauri `request_voice_permissions` command and wire it where required for supported desktop platforms. Handle permission denial and unavailable devices without blocking typed chat.
- Check actual MediaRecorder MIME support at runtime and send the file name and MIME type expected by the selected adapter. Do not transcode in the browser unless a provider requires it; if transcode is added later, it belongs in a bounded adapter preprocessing stage.
- Support web desktop, Tauri desktop, and mobile browser remote access. Native mobile apps, offline model downloads, and client-local remote STT are outside this v1.

## Implementation map

Expected code surfaces, to be reconciled with current repository conventions during execution:

### Backend

- `app/voice/` (new): STT provider protocol, registry, normalized result/error types, provider configuration model, and provider adapters (`openai_compatible`, `deepgram`, `azure_speech`, `google_cloud`).
- `app/services/voice_transcription.py` (new): request validation, ordered routing, bounded retries/failover, safe result metadata and provider health state.
- `app/api/routes/voice.py` and `app/api/schemas/voice.py` (new): upload/transcribe endpoint plus provider CRUD, test, model-discovery and routing APIs. Keep route functions thin.
- `app/api/routes/` router registration and `app/core/middlewares.py`: route hookup and narrow microphone Permissions-Policy change.
- `app/core/runtime_settings.py` / `ProviderCredentialStore` integration: persist provider metadata and references separately from secret values. Confirm the existing settings persistence primitive before selecting exact storage tables/files.
- `tests/app/voice/`, `tests/api/`: adapter contracts, failure classification, credential redaction, validation, endpoint calls and failover.

### Frontend and desktop

- `web/src/components/InputBar.tsx`: integrate the voice control without disrupting existing composer behavior.
- `web/src/components/voice/` (new): recorder hook/control and recording/transcription state machine.
- `web/src/api/client/voice.ts` (new): typed voice API methods and response/error contracts.
- `web/src/routes/settings.voice.tsx` (new), settings route/navigation: provider profile editor, model selection, routing order, test and privacy indicators.
- `web/src/help/locales/en.ts`, `vi.ts`, `ja.ts`, help catalog: explain endpoint setup, failover/privacy, microphone permissions and HTTPS requirements.
- `desktop/src-tauri/src/main.rs` and any required Tauri capability/permission files: wire and validate desktop microphone/speech permission behavior only where platform requires it.
- Focused frontend/API tests and an explicit manual browser/Tauri matrix.

### Product documentation

- `CHANGELOG.md`: describe push-to-talk, supported adapter families, failover and privacy behavior under `[Unreleased]`.
- `documents/features/` and `documents/README.md`: add a stable user/architecture guide and link it from the feature index.

## Acceptance criteria

- Users can create multiple provider profiles and multiple model entries per profile, select a primary pair, order fallbacks, test/edit/disable/delete providers, and configure an endpoint independently from chat models.
- OpenAI-compatible local endpoints, OpenAI/Groq-compatible endpoints, Deepgram, Azure Speech and Google Cloud STT each map to the same transcript contract. Provider-specific failures do not leak into the client API.
- Expired/rejected credentials, rate/quota limit, provider outages, and unavailable models fail over to the next configured pair; request-wide invalid audio does not. The successful pair is identified.
- Audio is never sent to a hosted fallback unless the user explicitly added it. A local/private-only policy is enforced server-side, not just by UI.
- Credentials are masked, server-side, rotatable and absent from browser storage, SQLite, logs and traces.
- The user can cancel recording/transcription, fix settings and retry without losing typed prompt text; a transcript is always editable and never auto-submitted.
- Unsupported browser/permission/MIME cases have accessible guidance; web, Tauri and HTTPS remote mobile flows are covered.
- Raw audio does not persist in EvoFlux; no diagnostics contain audio or transcript content. Provider processing policies are disclosed before configuration/testing.
- Automated contract tests cover all adapters, failover/error taxonomy, security, configuration migration and UI state. Manual checks cover real credentials/endpoints and mic permissions on Windows Tauri, desktop browser, and phone over HTTPS.

## Execution plan

1. **Contract and settings model** — define stable provider/model/routing schemas, normalized transcript/errors, credential references, privacy classes, migrations/defaults, and compatibility behavior for existing settings.
2. **Provider framework** — add registry and adapter protocol; implement OpenAI-compatible adapter first, then Deepgram, Azure, and Google adapters with per-adapter request/response/error tests and secret redaction.
3. **Routing service and API** — add upload validation, configured provider CRUD/test/discovery, safe URL handling, deterministic ordered fallback, cancellation/deadline behavior, and safe result/error shapes.
4. **Provider settings UI** — add provider profiles, model lists/manual IDs, routing order, local/cloud badges, explicit hosted fallback opt-in, masked secrets, test flow and last error state.
5. **Push-to-talk composer** — implement accessible recording state machine, secure-context/permission handling, MIME detection, cancel/stop, transcript insertion at caret, preservation of existing text, and fallback success message.
6. **Tauri and remote access** — wire platform permission paths, capability/policy configuration and HTTPS guidance; validate web and Tauri use without weakening unrelated permissions.
7. **Help and release documentation** — update localized in-app Help, `CHANGELOG.md`, feature documentation and navigation.
8. **Verification and review** — run targeted backend/frontend tests, inspect full diff and secret-retention boundaries, exercise real local and hosted provider configurations, then verify Windows Tauri and HTTPS phone workflows. Do not call it release-ready until all required adapter and permission checks are complete.

## Research references

- Open WebUI documents a real product pattern with local Whisper, browser speech recognition, hosted providers, self-hosted OpenAI-compatible STT, and explicit save/cancel controls: [Open WebUI STT configuration](https://github.com/open-webui/docs/blob/main/docs/features/chat-conversations/audio/speech-to-text/stt-config.md).
- OpenAI documents multipart transcription and distinguishes completed-file transcription from realtime streaming: [OpenAI speech-to-text guide](https://developers.openai.com/api/docs/guides/speech-to-text).
- Groq documents an OpenAI-compatible transcription endpoint and model IDs: [Groq speech-to-text](https://console.groq.com/docs/speech-to-text).
- `whisper.cpp` ships a self-hostable HTTP server with an OpenAI-like API and platform support: [ggml-org/whisper.cpp](https://github.com/ggml-org/whisper.cpp).
- Deepgram's prerecorded endpoint accepts binary audio with token auth and returns nested transcript alternatives: [Deepgram prerecorded audio](https://developers.deepgram.com/docs/pre-recorded-audio).
- Azure fast transcription uses multipart audio/definition and supports key or bearer authentication: [Azure fast transcription](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/fast-transcription-create).
- Google Cloud synchronous recognition takes JSON audio/config and returns ordered result alternatives: [Google `speech:recognize`](https://docs.cloud.google.com/speech-to-text/docs/reference/rest/v1/speech/recognize).
- Browser speech recognition may use a server-based service by default; on-device processing depends on browser support and language packs: [MDN Web Speech API](https://developer.mozilla.org/en-US/docs/Web/API/Web_Speech_API/Using_the_Web_Speech_API).
- Microphone capture is permission-gated and secure-context-only: [MDN `getUserMedia`](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia#privacy_and_security).
- Wyoming is an event-stream alternative for realtime audio, but its protocol has no built-in authentication or encryption: [Wyoming protocol](https://github.com/OHF-Voice/wyoming).

## Decisions captured for V1

- Multiple provider profiles and model choices with primary + ordered fallback pairs: required.
- Initial adapter set: OpenAI-compatible, Deepgram, Azure Speech fast transcription, Google Cloud Speech-to-Text.
- Local/self-hosted support: through compatible local endpoints in v1; bundling/downloading an STT model is a later project.
- Hosted failover: only for providers explicitly added by the user; local/private-only mode is available.
- Audio handling: same-origin EvoFlux backend proxy; no browser-held upstream secrets; no automatic chat submission.
- Non-goals: TTS, hotword/always-listening, realtime duplex/WebSocket voice, arbitrary request templates, and AssemblyAI-style remote upload/job/poll integrations.
