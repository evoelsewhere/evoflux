# Remote use (embedded Tailscale)

Packaged desktop builds include an `evoflux-tailnet` helper based on Tailscale
`tsnet`. A phone or another tailnet machine reaches the running EvoFlux
sidecar without installing a CLI or system daemon on the desktop. Enrollment
is still explicit: the owner clicks **Connect**, signs in through Tailscale
once, and the machine identity persists in the EvoFlux state directory.

Source/server deployments retain the external `tailscale serve` provider as a
fallback. Pairing codes and copied session tokens are not part of either flow.

## Settings page (Remote Control)

The feature appears in the UI as **Settings → Remote Control**
(`web/src/routes/settings.remote-use.tsx`; route and API keep the
`remote-use` name).

- Entering the page first shows a policy warning
  (`RemoteControlPolicyDialog`): a remote device acts with this computer's
  access, use only your own devices, follow your organization's policy, and
  access ends when EvoFlux quits. **I understand** continues; **Go back**,
  Escape or the outside click return to the Settings hub. **Don't show this
  again** stores `oa.remoteControl.policyAcknowledged` in localStorage.
- A **How to set up** walkthrough lists the four steps (connect this computer,
  get Tailscale on the phone, turn on Remote Control, open it from the phone),
  ticked off from live status, with a link to the full Guidelines topic.

## What the backend exposes

HTTP routes under `/api/remote-use` (see
[HTTP API](../reference/http-api.md#remote-use)):

| Route | Purpose |
| --- | --- |
| `GET /status` | Tailscale state + serve state + current lock holder |
| `POST /bootstrap` | Start bundled tsnet early and restore persisted access |
| `POST /connect` | Begin/refresh interactive embedded-node login |
| `POST /enable` | Start embedded listener, or external `tailscale serve` |
| `POST /disable` | Stop embedded listener, or external Serve reset |
| `POST /release` | Desktop force-release of every live remote session |

Every route returns the same payload:
`{tailscale: {installed, logged_in, https_certs, error}, serve: {enabled, url}, lock: {...}|null}`.

## Providers

### Embedded provider (packaged desktop default)

The Go helper runs as a child of the Python sidecar and exits with it. It owns
the persistent tsnet machine state, a bearer-protected loopback control API,
and a reverse proxy to the ephemeral FastAPI port. It prefers a tailnet HTTPS
listener when certificate domains are available; otherwise it serves HTTP
inside the already encrypted tailnet, avoiding a separate HTTPS-admin setup
step.

Before proxying a request it resolves the peer with Tailscale `WhoIs`, removes
caller-supplied identity headers, and injects the verified login/device. Those
headers carry a per-process secret shared only with FastAPI. Both HTTP and
WebSocket authentication verify that secret.

The enabled preference is stored beside tsnet state, so desktop startup can
restore phone access after Tauri calls `/bootstrap` with the new ephemeral
backend port.

### External CLI fallback

`app/services/remote_use_service.py` treats the `tailscale` CLI as optional
and reports distinct user-facing states instead of failing:

- **not installed** — binary not on PATH (`installed: false`, error
  explains);
- **not logged in** — `tailscale status --json` reports a `BackendState`
  other than `Running`;
- **HTTPS certs unavailable** — negative signal from status `Health`
  entries, or from a failed `serve --bg` whose message mentions
  https/cert/tls; `null` means "unknown" (the UI treats it as "not
  confirmed" and `enable` surfaces the authoritative error);
- **ready** — installed, logged in, with positive cert evidence
  (`CertDomains` non-empty or an active `https://` serve entry).

`serve: {enabled, url}` is parsed from `tailscale serve status --json`
(active Web handlers; `https://` preferred, default port stripped).

CLI calls are `asyncio.create_subprocess_exec` with a literal argv — never
a shell string, never user-supplied interpolation — and always run outside
any database transaction. Tests point `EVOFLUX_TAILSCALE_BIN` at a stub
script; no test touches the network or a real tailscaled.

## Single-device session lock

`remote_use_sessions` holds one *live* session at a time
(`released_at IS NULL AND idle_expires_at > now`):

- A remote-attributed API request **claims** the lock transparently inside
  the identity hook (`DesktopTokenMiddleware._dispatch_remote`), so no route
  can forget the check. A live holder from a different
  `(user_login, device_label)` pair yields **HTTP 409** with
  `{detail, current: {user_login, device_label, claimed_at, last_seen_at},
  live_window_minutes: 30}`.
- Re-claiming with the same pair is a **heartbeat**: `last_seen_at` and
  `idle_expires_at` (= last seen + 30 minutes) refresh in place.
- **Idle expiry**: 30 minutes without a heartbeat makes the session not
  live; the sweep stamps `released_at` opportunistically on claim/status
  reads, so a lapsed session never blocks the next claim.
- `release(user_login, device_label)` frees that pair's live session;
  `force_release()` (exposed as `POST /release` for the desktop UI) frees
  every live session.

Device label resolution for transparent claims: optional
`X-EvoFlux-Device-Label` request header, falling back to `User-Agent`
(truncated to 128 characters), else `null`.

## Identity and trust

- Embedded mode resolves identity with `WhoIs` and signs the forwarded
  `Tailscale-User-Login` header using an in-memory secret. External Serve
  mode continues to trust the header injected by `tailscaled`.
- The header **replaces** the desktop bearer token for those requests; the
  desktop-token tiers are untouched for every other request.
- Embedded mode rejects unsigned identity headers, closing the previous local
  header-spoofing gap. External CLI mode retains the older trust boundary.

## Code ownership

- Service: `app/services/remote_use_service.py`
- Embedded helper: `desktop/tailnet/`
- Desktop packaging/supervision: `desktop/src-tauri/src/sidecar.rs`
- Identity hook: `app/core/desktop_auth.py`
- Model + migration: `app/models/remote_use.py`,
  `app/migrations/versions/00000069_create_remote_use_sessions.py`
- Routes: `app/api/routes/remote_use.py` (mounted at `/api/remote-use` in
  `app/api/app.py`)
- Tests: `tests/remote_use/` (stub `tailscale` fixture in `conftest.py`)

## Known limitations and open questions

- External `tailscale serve` configuration remains machine-wide. Embedded
  state belongs only to EvoFlux and does not modify the system Tailscale app.
- The lock is exclusive across the tailnet (one live session total) while
  sessions are identified by `(user_login, device_label)`. Whether two
  devices sharing one tailnet login should share or split the lock is open
  question 2 of the plan.
- The phone still needs the Tailscale mobile app and must join the same
  tailnet. A public app cannot safely bundle a reusable auth key to remove
  this account enrollment step.
- A cloudflared transport fallback (plan open question 1) is out of scope
  for v1; no pairing codes exist in this design.
