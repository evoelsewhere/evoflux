# Voice input

Voice input adds push-to-talk speech-to-text to the chat composer. The microphone control sits beside **Send** for quick access. The transcript is inserted into the current draft for review and editing; recording never sends a chat message automatically.

## Configure providers

Open **Settings → Voice input** and add one or more profiles:

- **OpenAI compatible** supports OpenAI, Groq, Whisper-compatible local servers and custom endpoints that implement multipart `/audio/transcriptions` and return a `text` field.
- **Deepgram** uses the prerecorded `/v1/listen` API.
- **Azure AI Speech** uses fast transcription.
- **Google Cloud Speech-to-Text** uses backend Application Default Credentials.

For OpenAI-compatible profiles, save the endpoint and credential, then use **Load models** to request its `/models` catalog through the EvoFlux backend. The API key stays server-side and only model IDs are returned to the browser. Keep manual model entry for endpoints without a compatible catalog. New profiles can be saved as drafts with no endpoint; add a valid endpoint before loading models, testing, or adding the profile to the route. EvoFlux does not assume chat model catalogs list speech models. API reads return only whether a credential is configured. Local HTTP endpoints are allowed for loopback/private networks. Public hosted endpoints must use HTTPS.

Choose a first provider/model and optional ordered backups. Online speech services are blocked by default; enable **Allow online speech services to receive recordings** to permit them to receive audio. EvoFlux calls one endpoint at a time, retries a transient timeout/server error once, then advances through the configured order for recoverable provider errors. It stops on request-wide validation errors. **Use local or private-network providers only** skips online endpoints even when they appear in the backup list.

An optional managed **Local Whisper small** runtime can be installed from **Settings → Voice input** after verified assets are published for the host platform. The speech engine and multilingual model are separate on-demand downloads; neither is included in the default desktop installer. The local profile becomes available only after the model passes its load check. It runs on the machine hosting the EvoFlux backend, supports automatic language detection plus English, Vietnamese and Japanese, and requires no endpoint or API key. Removing the managed runtime does not remove other provider settings. Until assets are published and pinned in an app release, Settings reports the download as unavailable and custom/remote providers continue to work. See the [Local Whisper asset release procedure](../development/local-stt-runtime-release.md).

## Record and review

On desktop, hold the microphone button and release to stop. On a touch device, tap to start and tap again to stop. Recording is limited to two minutes. In Settings, **Record test sample** captures a user-recorded four-second clip and sends it only to that profile for a connection/model check. EvoFlux stops microphone tracks after recording/cancel and uploads audio to its backend, which calls the selected STT provider. The recognized text is inserted at the current composer caret. Edit or discard it, then send it through the normal chat controls.

Microphone capture requires browser permission and a secure origin (HTTPS or localhost). Remote phone access over Tailscale therefore needs HTTPS. Microphone denial, a missing device, or an unsupported browser leaves typed chat available.

## Data handling

EvoFlux keeps audio and transcript in memory only. It does not save recordings/transcripts or include their content in provider errors or logs. Local Whisper receives audio in memory through a worker pipe, uses only its installed model files, and does not fetch model assets while transcribing. Selected hosted providers still process audio according to their own terms. Explicit fallback order controls which endpoints can receive a recording; no hosted fallback is added automatically. Google credentials are resolved on the backend host and are not sent to the browser.

## API

See [HTTP API reference](../reference/http-api.md#voice-transcription) for configuration, transcription and local runtime management endpoints.
