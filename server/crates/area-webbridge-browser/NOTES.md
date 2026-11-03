# area-webbridge-browser NOTES

Python source: `app/api/routes/team/{webbridge,browser,computer}.py` (all of
`webbridge.py` except `/sessions/**` and `/interactions`, which belong to
`area-webbridge-agent`), the WebBridge, agent-browsing and computer-app routes of
`app/api/routes/settings.py`, `app/api/schemas/settings.py`,
`app/services/{webbridge_service,webbridge_pairing_service,webbridge_appearance,direct_browser_bridge,direct_computer_bridge}.py`,
`app/models/webbridge.py`, `app/webbridge_tags.py`, `app/core/desktop_auth.py` (the
custom-auth list and `websocket_authorized`). Contract tests:
`contract-tests/webbridge-browser/`.

**Status:** La (this stub, NOTES, contract tests). The crate is not mounted; `units.rs`
and `routing.toml` are untouched. Routing of the board row (`webbridge-browser`, unit
`webbridge-browser`) is unchanged.

## Scope

| Prefix | Notes |
|---|---|
| `/api/team/webbridge/{native-discovery,pairing/native,pairings,relay-ticket,appearance,bindings,teach-drafts,status,audit}` | pairing, bindings, Teach, status |
| `/api/team/webbridge/relay` (WS), `/api/team/webbridge/agent/{session_id}` (WS) | extension relay and external agent socket |
| `/api/team/browser/agent/sessions`, `/api/team/{session_id}/browser[/agent[/command]]`, `/browser/{agent,presence}` (WS) | desktop in-app browser bridge |
| `/api/team/{session_id}/computer/{agent,closed}` | desktop computer-app bridge |
| `/api/settings/webbridge[/agent-browsing]`, `/api/settings/computer-app` | settings |

`/api/team/webbridge/sessions/**` and `/interactions` are the `webbridge-agent` lane. The
router must send them there; both lanes share the `/api/team/webbridge` prefix.

## Authentication (three tiers)

1. **Access key** (`Authorization: Bearer <key>` or `?_token=`; middleware): every route
   except the ones below. Missing or wrong: `401 {"detail":"Unauthorized — EvoFlux access
   key required."}`, before validation.
2. **Pairing credential** (exact paths `pairing/native`, `relay-ticket`, `interactions`,
   `bindings`, `sessions`, `models`, `appearance`, `teach-drafts` and the prefixes
   `bindings/`, `sessions/`): the middleware lets them through. `Authorization: Bearer
   <credential>`; the access key itself is *not* accepted. Missing/unknown/revoked/lacking
   the scope: `401 {"detail":{"code":"invalid_pairing","message":"Pair WebBridge first."}}`
   with `WWW-Authenticate: Bearer`. FastAPI validates the body and path **before** this
   check, so an anonymous caller gets `422` with the schema errors for a malformed body.
   `/teach-drafts/review`, `/teach-drafts/{id}/...`, `/pairings...`, `/status`, `/audit`
   are *not* in the list: they need the access key.
3. **Socket rules**: the HTTP middleware does not see WebSockets. The three desktop
   sockets and `/agent/{id}` call `websocket_authorized` (access key in `?_token=`) and
   refuse with an HTTP `403` at the handshake. `/relay` accepts only a single-use ticket
   `?_ticket=` (missing/unknown/used/expired/revoked: handshake `403`; the access key does
   not open it).

Scopes: `relay`, `interactions:write`, `bindings:write`, `sessions:list`,
`sessions:create`, `session-stream:read`, `teach:drafts:write`, `session:messages:write`,
`handoff:reply` (a new pairing gets all nine, sorted). Three historical sets (P0, P1, P3)
are treated as the full set on authentication and rewritten to it on the first
non-`GET` request.

## Endpoints

| Endpoint | Behaviour | Errors |
|---|---|---|
| `GET native-discovery` | `{discovery_token}`, process-lifetime constant (access key if configured, else loopback only) | `401`, `403 "Native discovery is loopback-only."` |
| `POST pairing/native {label?,browser?,version?,discovery_token}` | `201 {pairing_id,credential,scopes}`; needs a loopback client, `Origin: chrome-extension://lghglpnddenmebbhkfachafichhglafi` (or an id in `EVOFLUX_WEBBRIDGE_EXTENSION_IDS`) and the token | `403 {"detail":{"code":"native_pairing_refused",...}}`; `422` (label blank/over 120, token 32-256, extra fields) answered first |
| `GET pairings` | active pairings, most recently seen first: `pairing_id,label,browser,version,scopes,created_at,last_seen_at` | |
| `DELETE pairings/{id}` | revokes, deletes bindings, interactions and Teach drafts, strips the session tag, kills tickets, closes the relay socket `4403`; `204` | `404 "Pairing not found."` (also when already revoked) |
| `PUT pairings/{id}/sessions/{sid}` | adds tag `webbridge_pairing:<id>` to the session; returns the session option | `404` pairing, `404 session_not_found`, `403 webbridge_disabled` (in that order) |
| `POST relay-ticket` | `201 {ticket,expires_in:30}`, scope `relay` | `401` |
| `PUT/GET appearance` | desktop publishes (`PUT`, access key checked in the route, or a loopback `Origin` when no key is configured), paired panel reads (`sessions:list`); `revision` only moves when the snapshot changes | `401 "Desktop authentication required."`, `403 "Appearance sync is local-only."`, `422` |
| `GET bindings`, `PUT bindings/{tab}`, `POST bindings/{tab}/sessions`, `DELETE bindings/{tab}` | scope `bindings:write` (create also `sessions:create`); origin normalised to `scheme://host[:port]`, or `tab:<id>`; one tab per session and one session per tab (newest wins); the bound session must carry the pairing's tag and WebBridge must be enabled | `422 invalid_tab_scope`, `422 invalid_idempotency_key`, `403 session_not_pairing_assigned`, `403 "Pairing lacks binding scope."`, `409 running_session_rebind_refused / running_session_unbind_refused` (not tested: needs a running agent) |
| `POST teach-drafts` | scope `teach:drafts:write`, stores a normalised trace; start URL and navigations lose query and fragment; secret fills keep only the parameter name | `422 invalid_teach_scope / invalid_teach_action`, `403 sharing_policy_refused`, `409 teach_binding_required` |
| `GET teach-drafts/review`, `POST .../{id}/approve`, `DELETE .../{id}` | app-side review (access key) | `404 "Teach draft not found."`, `409` |
| `POST teach-drafts/{id}/replay`, `.../replay/resolve` | one durable step per call, `Idempotency-Key` required; every step goes to the extension as a command carrying `tab_id` and `_webbridge_expected_origin`; ambiguous outcomes block until the user resolves them | `409` (several states, see the tests), `422` |
| `GET status`, `GET audit?limit` | live extensions (`extension_id,browser,version,protocol_version,capabilities,connected_at,current_url,current_title,tabs,automation`); newest-first audit ring buffer (`ts,session_id,extension_id,action,url,success,error,direction`) | `422` bad `limit`; a negative `limit` gives an empty list |
| `WS relay?_ticket` | `register` -> `{"type":"registered","extension_id","pairing_id","protocol_version":2}`; `response`, `event` (`tab_updated`, `automation_state`), `ping` -> `pong`; frames over 1,000,000 bytes close `1009`; a second registration closes the first `4409` | handshake `403` |
| `WS agent/{session_id}?_token` | `{"action":...}` frames; `no_extension` when none is connected (except `status`); responses `{"type":"response",success,data,error,request_id?}` | tab-scoped commands with no bound or explicit tab fail closed (`UNBOUND_TARGET`) |
| `WS {sid}/browser/presence`, `WS {sid}/browser/agent`, `GET browser/agent/sessions`, `GET {sid}/browser[/agent]`, `POST {sid}/browser/agent/command {action,params}` | desktop WebView bridge; `status` and `get_tabs` answer offline results without mounting; other actions mount through the presence socket and wait 8 s (`409`); desktop errors are `422 {"detail":"<message>"}`; a newer attach closes the older socket `4409` | |
| `WS {sid}/computer/agent`, `GET {sid}/computer/agent`, `POST {sid}/computer/closed` (`204`) | desktop computer bridge, no HTTP command route (the agent tool calls the bridge in process) | |
| `GET/PUT settings/webbridge`, `.../agent-browsing`, `settings/computer-app` | `WebBridgeSettingsBody` (extra fields forbidden, missing fields default), `permission` is `ask|allow`, app names are stripped and de-duplicated | `422` |

## State, files and tables

- **Tables** (schema is frozen): `webbridge_pairings`, `webbridge_tab_bindings`,
  `webbridge_interactions`, `webbridge_teach_drafts`, `webbridge_teach_replays`; the
  pairing tag on `chat_sessions.tags`.
- **Process memory** (lost on restart, shared with agent code): the extension registry and
  pending-command table, the session-to-tab bindings (rehydrated when the extension
  registers, fail-closed until `tab_updated` validates the origin), the audit ring buffer,
  the relay ticket store, the interaction rate limiter, the appearance snapshot, the
  native discovery token, the two desktop bridges and their pending mounts, the active
  Teach replay set, per-pairing revocation events.
- **Files:** `settings.yaml` (`webbridge`, `browser`, `computer_app` sections) read and
  written through `load_runtime_settings` / `save_runtime_settings`; no other files.
- **Background:** `webbridge_manager.run_cleanup_loop()` (stale extensions, policy reload)
  and the artifact cleanup loop (agent lane), both behind `EVOFLUX_DISABLE_SERVICES`.

## Callers outside the routes (adapter needed before cutover)

`webbridge_manager`, `direct_browser_bridge` and `direct_computer_bridge` are in-process
singletons that the agent tools `webbridge`, `browser_use` and `computer_app`, the chat
runtime (`release_browsing`, `add_turn_done_listener(direct_computer_bridge.release_after_turn)`)
and `routes/settings.py` call directly. A Rust unit that owns the sockets would leave those
callers talking to an empty Python registry, so `adapter:webbridge-browser` must bridge
them per `server/AGENTS.md` §9 and ADR 0001. La adds none.

## Odd behaviour (pinned as is)

- A refused first replay (no extension connected) still claims the draft's execution id:
  another execution id then gets `409 "Refresh Teach drafts before continuing this
  replay."` while the draft says `replay_state: ready`, step 0.
- Replay idempotency hashes the execution id, start step and parameter *names* only, so the
  same key with a different secret value returns the cached response.
- `PUT bindings/{tab}` takes a negative `tab_id` (only the session is looked up).
- `register` acknowledges `protocol_version: 2` whatever the extension sent; `status`
  reports what the extension sent (default `1`).
- `POST pairing/native` answers body-validation errors (`422`) before the origin and token
  checks.
- A new pairing from a non-browser caller needs only a header: `Origin` is a plain request
  header for any local HTTP client.
- Audit `limit` of `0` or below gives an empty list; the default is `webbridge.audit_log_size`.
- `PUT appearance` with an identical snapshot does not bump `revision`.

## Security findings (for the Lb stage)

- **S1: native pairing trusts a header and a loopback address.** Any local process can
  `POST pairing/native` with `Origin: chrome-extension://<known id>`. The discovery token
  is the only secret, and `GET native-discovery` hands it to any loopback client when no
  access key is configured (the standalone CLI tier). With a key set, the caller needs the
  key. The credential it receives holds all nine scopes (message send, shell, permission
  approval through the agent lane).
- **S2: the pairing credential is a long-lived bearer with no expiry**, stored as an
  unsalted SHA-256 (fine for 256-bit random values). The only revocation is the app's
  `DELETE pairings/{id}`.
- **S3: `WS agent/{session_id}` and the desktop bridge sockets take any session id** with
  only the access key; there is no session lookup. `evaluate` / page reads run in the
  user's real, logged-in browser (guarded by `webbridge.allow_evaluate`,
  `require_tab_binding`, domain lists). The access key travels in the URL (`?_token=`).
- **S4: `POST {sid}/browser/agent/command` forwards an arbitrary `action` and `params` to
  the desktop WebView** after the access key check; the allow-list is the desktop's
  `capabilities.commands`.
- **S5: `/relay` has no `Origin` check**; the ticket in the URL is single use and lasts
  30 s but lands in any log that records query strings.
- **S6: validation errors on pairing-credential routes are returned to anonymous callers**
  (they run before the credential check); this exposes the request schema only.
- **S7: Teach replay values.** Secret parameter values are sent to the browser in a
  `fill` command and never stored, but the replay record keeps the step list and error
  text.

Port rule: keep the order "body/path validation, then credential, then scope, then
session assignment, then WebBridge-enabled" exactly, and keep the three tiers separate;
route registration must keep `/teach-drafts/review` ahead of `/teach-drafts/{draft_id}/...`.

## Test status and map

`contract-tests/webbridge-browser/`: 128 cases, all passing against Python v3.1.1
(`TARGET=python`, Windows, `-n 4`). `TARGET=rust` is not applicable until Lb mounts the
crate. A `FakeExtension` socket stands in for the Chrome extension and plain sockets for
the desktop shell; sessions and pairings with restricted scopes are inserted into SQLite
(the tests never touch a real browser).

| Python tests | Covered by |
|---|---|
| `tests/api/test_webbridge.py` pairing, native discovery, relay tickets, scopes (about 30) | `test_pairing.py`, `test_auth_routes.py` |
| appearance (`test_webbridge_appearance.py`, 3, plus 3 in `test_webbridge.py`) | `test_appearance_settings.py` |
| bindings (CRUD, atomic create, scope, rebind) | `test_bindings.py`; running-session refusals and manager pinning/expiry: `n/a` (need a live agent; Lb unit tests) |
| Teach drafts | `test_teach_drafts.py` |
| relay, status, audit, agent socket (`register_then_status...`, `relay_rejects_oversized_frames`, `command_roundtrip_agent_ws`, `agent_ws_no_extension`, `ping_refreshes_last_seen`, ...) | `test_relay.py`; manager correlation, timeouts, multi-extension choice, policy tables: `n/a` here (Rust unit tests at Lb, they call `webbridge_manager` directly) |
| `test_direct_browser_bridge.py` (7), `test_direct_computer_bridge.py` (10) | `test_direct_bridges.py` (round trip, mount, displacement, status, offline); timeouts and cancel frames: `n/a` (35 s / 60 s waits) |
| `tests/agent/tools/test_webbridge_snapshot.py`, `tool_*` cases | `n/a` (agent tool formatting, lives in the tools lane) |
| settings routes in `tests/api/test_settings_routes.py` | `test_appearance_settings.py` |
| `/sessions/**`, `/interactions`, side-chat history/stream cases | `webbridge-agent` lane |

Not covered: running-session refusals (`409 running_session_*`), `tab_updated`-driven
stale-binding removal, a hostile browser `Origin` on the sockets, `EVOFLUX_WEBBRIDGE_EXTENSION_IDS`,
non-loopback native pairing, replay of an ambiguous step after a crash, the 35 s / 60 s
command timeouts.

## Lb: size and dependencies

Roughly 3,000 lines of Rust: the pairing store and credential/scope logic (small), the
bindings and Teach store (medium), the extension relay with the manager (request
correlation, policy, audit, per-session tab binding; the largest piece), the two desktop
bridges (small), settings and appearance (small). Depends on `core::db`, `core::auth`
(including the WebSocket rules above), `shared-settings` (the `webbridge`, `browser` and
`computer_app` sections), `core::redact`, and the per-turn hook of the chat runtime. The
adapter for the Python agent tools is the blocker for cutover. Suggested slices: pairing
and appearance; bindings; Teach; relay and status/audit; desktop bridges; settings.
