# HTTP and streaming API

The FastAPI sidecar serves JSON HTTP routes under `/api`, Prometheus metrics at
`/metrics`, Server-Sent Events for turn/file streams, and WebSockets for
terminal/browser relays. The running build exposes the exact schema at
`/openapi.json` and interactive FastAPI documentation at `/docs`.

## Authentication

When desktop or access-key authentication is configured, send:

```http
Authorization: Bearer <token>
```

Raw media/download navigations may use `?_token=<token>`; middleware removes the
token from the downstream query string to reduce logging exposure. Live/ready
health, metrics and static SPA assets are exempt. WebBridge pairing/relay routes
use narrower scoped credentials where documented by their schemas.

An unconfigured loopback CLI server keeps token middleware disabled. LAN or
external deployments should configure an access key and restrictive CORS.

## Route families

| Prefix | Responsibility | Primary router |
|---|---|---|
| `/api/health` | liveness, readiness and bounded diagnostics | `health.py` |
| `/api/diagnostics` | runtime/platform/path diagnostics | `diagnostics.py` |
| `/api/remote-use` | Tailscale Serve remote access: status, serve control, session lock | `remote_use.py` |
| `/api/team` | chat, sessions, files, terminal, projects and Coding workbench | `routes/team/` |
| `/api/team/webbridge` | pairing, browser-panel chat, relay, bindings and Teach | `team/webbridge.py` |
| `/api/agents` | agent registry and editable/runtime configuration | `agents.py` |
| `/api/skills` | Skill discovery, bundle CRUD and on/off switch | `skills.py` |
| `/api/mcp` | global/plugin server status and global MCP lifecycle | `mcp.py` |
| `/api/plugins` | package inspection/install/editor/credentials/lifecycle, marketplace sources/catalogs, prepared previews and marketplace installs | `plugins.py` |
| `/api/settings` | providers, sandbox, Git, browser, Computer App Control and Conductor | `settings.py` |
| `/api/voice` | speech-to-text provider profiles, routing and transient transcription | `voice.py` |
| `/api/scheduler` | task CRUD, pause/resume and trigger | `scheduler.py` |
| `/api/wiki` | validated Markdown tree/file operations | `wiki.py` |
| `/api/dream` | config, manual run/status and lint | `dream.py` |
| `/api/observability` | aggregates including cache read/write token classes, trace pages and trace detail | `observability.py` |
| `/api/commands` | slash-command catalogue/rendering | `commands.py` |
| `/api/snippets` | snippet catalogue/rendering | `snippets.py` |
| `/api/auth` | provider OAuth login/callback | `auth.py` |
| `/api/quote` | cached quote-of-the-day | `quote.py` |

Plugin marketplace routes add/list/remove sources, sync and search catalogs,
prepare an install preview, and install that preview. `allow_partial` is explicit
and defaults to `false`; the server refuses a preview with unsupported
components until consent is supplied. Marketplace installs are disabled by
default and use the same trust-review lifecycle as local packages. Request and
response details are defined in the generated OpenAPI schema.

## Voice transcription

`GET /api/voice/settings` returns provider profiles, ordered provider/model
pairs, adapter IDs, local/private-only policy, and credential-configured
booleans. It never returns secret values. `PUT /api/voice/settings` replaces
that configuration; optional API keys are accepted only in the write request
and stored in the EvoFlux server-side `.env` credential file. Google Cloud
Speech uses Application Default Credentials on the backend host.
Provider profiles may be saved as drafts with an empty endpoint, but drafts
cannot be routed or tested until an endpoint is configured. `GET
/api/voice/providers/{provider_id}/models` fetches an OpenAI-compatible
`/models` catalog through the backend and returns only model IDs; the API key
is never returned to the browser.

Hosted profiles are blocked until `allow_hosted_fallback` is explicitly enabled.
`local_private_only` overrides that flag and excludes hosted destinations.
`POST /api/voice/providers/{provider_id}/test` accepts a user-recorded multipart
clip and `model_id` to test only that profile; the Settings UI records a
four-second sample after the user clicks the test action.

`POST /api/voice/transcribe` accepts multipart `audio` and optional `language`
fields. Audio is limited to 25 MiB and supported audio MIME types. The response
contains `text`, `provider_id`, `model_id`, `fallback_used`, and sanitized
provider failure categories from earlier attempts. It never persists audio or
transcript content. The client inserts the transcript into the composer for
review; it does not submit a chat message.

The optional Local Whisper runtime is managed separately from provider settings:

| Route | Purpose |
| --- | --- |
| `GET /api/voice/runtime/status` | Return platform availability, installed/current versions, safe byte counts, health and install progress. |
| `POST /api/voice/runtime/install` | Start an explicit download/install of the pinned engine and shared multilingual model. |
| `POST /api/voice/runtime/install/cancel` | Cancel an active download or verification phase. |
| `POST /api/voice/runtime/install/dismiss` | Dismiss the last failed install message. |
| `POST /api/voice/runtime/check` | Load-check the installed model without sending audio to a provider. |
| `DELETE /api/voice/runtime` | Remove only the managed engine and model assets. |

The default manifest remains empty until verified release artifacts are
published and pinned. A platform with no matching pinned assets reports
`available: false`; the local profile cannot be added there, while configured
remote/private providers remain available. The model and engine are separate
archives. Install verifies byte size and SHA-256 before extraction, checks the
model before activation, and retains the previous healthy version during an
update. When configured, local inference runs on the EvoFlux backend host (also
for audio captured by a remote phone), uses only local model files, and does not
add a hosted fallback. Full request and response schemas are defined in the
generated OpenAPI document.

## Team subresources

The `/api/team` router includes:

- accepted chat/command ingress and per-session SSE;
- session CRUD, history, metadata, duplicate, queue, goal and todos;
- mode-scoped `GET /api/team/leads`, session-aware `GET /api/team/agents`, and
  idle-only `PATCH /api/team/sessions/{session_id}/lead` selection;
- Work folders and shared-folder context;
- workspace files/uploads/media/previews and file-watch SSE;
- Coding projects, workspace authorization/tree/files and worktrees;
- Git, Git AI, code reviews and Git server connections;
- ChangeSets, editor actions/context, LSP/language-server and Problems;
- terminal and direct-browser WebSockets;
- managed processes and `preview` dev-server targets/start/stop;
- Side Chat messages and stream;
- command-palette search: workspace-scoped
  `POST /api/team/workspace/search-everywhere` and application-wide
  `POST /api/team/search-app`.

Use the OpenAPI document rather than copying request/response field definitions
from this overview.

## Remote use

Remote access over embedded Tailscale or external Tailscale Serve lives under
`/api/remote-use` (`app/api/routes/remote_use.py`). All routes return one
payload:

```json
{
  "tailscale": {"installed": true, "logged_in": true, "https_certs": true, "error": null},
  "serve": {"enabled": true, "url": "https://machine.tailnet-example.ts.net"},
  "lock": {"user_login": "[EMAIL_6]", "device_label": "phone", "claimed_at": "...", "last_seen_at": "..."}
}
```

| Route | Purpose |
| --- | --- |
| `GET /status` | Tailscale + serve state and the current lock holder (`lock` is `null` when unlocked) |
| `POST /bootstrap` | Start the bundled tsnet helper and restore persisted phone access |
| `POST /connect` | Start interactive login and return `tailscale.auth_url` |
| `POST /enable` | Runs `tailscale serve --bg http://127.0.0.1:<sidecar-port>` — port comes from the ASGI server scope, falling back to `API_PORT` |
| `POST /disable` | Runs `tailscale serve reset` |
| `POST /release` | Desktop force-release: retires every live remote session |

`tailscale.https_certs` is tri-state: `true`/`false` when the CLI gives
evidence, `null` when unknown. `tailscale.error` carries the first
user-facing CLI failure (missing binary, not logged in, HTTPS certs
unenabled, unparseable JSON). `serve.url` is the tailnet HTTPS origin when
serve is active.

Packaged desktop responses additionally include
`tailscale.provider = "embedded"` and `tailscale.auth_url`. Embedded enable
starts the bundled tsnet listener and falls back to HTTP inside the encrypted
tailnet when HTTPS certificates are unavailable. External deployments keep
the CLI behavior described above.

**Identity.** Embedded mode resolves the peer through Tailscale `WhoIs` and
forwards a signed `Tailscale-User-Login` header. External Serve mode receives
the equivalent header from `tailscaled`. The request is attributed as a remote
tailnet session and does not require the desktop bearer token. The first API
or WebSocket request from a device claims the single-device session lock;
while another session holds it, API requests from a second device fail with
HTTP 409:

```json
{
  "detail": "remote session lock is held by [EMAIL_6] (phone)",
  "current": {"user_login": "[EMAIL_6]", "device_label": "phone", "claimed_at": "...", "last_seen_at": "..."},
  "live_window_minutes": 30
}
```

An optional `X-EvoFlux-Device-Label` header names the device (the
`User-Agent` is the fallback). Sessions idle for 30 minutes are released
automatically and never block the next claim. See
[Remote use](../features/remote-use.md) for states and trust notes.

## Asynchronous chat contract

Chat/command endpoints normally return `202 Accepted` after validation and
queueing. Subscribe to `GET /api/team/{session_id}/stream` for live output and
load history for reconnect. Side Chat and browser-panel chat have separate
stream endpoints.

The SSE `data` payload is a structured envelope. Event types include content
deltas, tool/activity blocks, member status, permissions,
questions, queues, usage, goal updates, errors and completion. Clients
must tolerate additional event fields/types and reconnect using durable history
rather than assuming one uninterrupted socket.

## WebSockets

| Path | Purpose |
|---|---|
| `/api/team/{session_id}/terminal` | bidirectional PTY input/output/resize |
| `/api/team/{session_id}/browser/agent` | direct browser agent commands |
| `/api/team/{session_id}/browser/presence` | visible browser mount/presence |
| `/api/team/{session_id}/computer/agent` | Computer App Control commands relayed to the Windows or macOS desktop shell |
| `/api/team/{session_id}/computer/closed` | POST: the user closed the chat's app preview card; `computer_app` refuses to attach until the turn ends |
| `/api/team/webbridge/relay` | extension relay |
| `/api/team/webbridge/agent/{session_id}` | external browser-agent relay |

WebSocket authentication is validated at the endpoint because HTTP middleware
does not wrap the upgraded channel. Protocols are versioned where the desktop
or extension advertises capabilities.

## Error and pagination conventions

Validation errors use FastAPI/Pydantic `422`; missing resources use `404`;
authorization/policy conflicts use `401`, `403` or `409`; database admission may
surface retryable `503 database_busy`. Long lists use explicit `limit`,
`offset` or cursor fields and include a next/has-next indicator.

Never depend on provider-specific raw payloads: Git reviews, model providers,
MCP and agent streams expose normalized EvoFlux schemas.
