# Remote use (Tailscale Serve)

Remote use lets a phone or another tailnet machine reach a running EvoFlux
sidecar through the HTTPS endpoint provided by `tailscale serve`, with
identity carried by Tailscale's request headers and exactly one live remote
session at a time. The plan that defines this feature
(`documents/plans/remote-use-tailscale-serve.md`, branch `feat/remote-use`)
supersedes the earlier cloudflared draft; pairing codes and token
session-token checks are not part of this design.

## What the backend exposes

HTTP routes under `/api/remote-use` (see
[HTTP API](../reference/http-api.md#remote-use)):

| Route | Purpose |
| --- | --- |
| `GET /status` | Tailscale state + serve state + current lock holder |
| `POST /enable` | `tailscale serve --bg http://127.0.0.1:<sidecar-port>` |
| `POST /disable` | `tailscale serve reset` |
| `POST /release` | Desktop force-release of every live remote session |

Every route returns the same payload:
`{tailscale: {installed, logged_in, https_certs, error}, serve: {enabled, url}, lock: {...}|null}`.

## Tailscale is optional infrastructure

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

- `tailscale serve` injects `Tailscale-User-Login` (plus name/profile-pic)
  on requests arriving via the tailnet HTTPS endpoint; desktop loopback
  requests never carry it. A non-empty header attributes the request as a
  remote session, readable through `remote_session_login(request)`.
- The header **replaces** the desktop bearer token for those requests; the
  desktop-token tiers are untouched for every other request.
- Residual risk: a local process could forge the header on loopback while
  token auth is enabled. Browser pages cannot (custom headers force a CORS
  preflight the sidecar never approves), and a local process that can reach
  loopback can usually read the desktop token anyway. This note also lives
  in [system overview](../architecture/system-overview.md#core-boundaries).

## Code ownership

- Service: `app/services/remote_use_service.py`
- Identity hook: `app/core/desktop_auth.py`
- Model + migration: `app/models/remote_use.py`,
  `app/migrations/versions/00000069_create_remote_use_sessions.py`
  (`SCHEMA_HEAD = "00000069"`)
- Routes: `app/api/routes/remote_use.py` (mounted at `/api/remote-use` in
  `app/api/app.py`)
- Tests: `tests/remote_use/` (stub `tailscale` fixture in `conftest.py`)

## Known limitations and open questions

- `tailscale serve` configuration is machine-wide: `serve: {enabled}`
  reflects the whole tailscaled state, not only EvoFlux's entry.
- The lock is exclusive across the tailnet (one live session total) while
  sessions are identified by `(user_login, device_label)`. Whether two
  devices sharing one tailnet login should share or split the lock is open
  question 2 of the plan.
- A cloudflared transport fallback (plan open question 1) is out of scope
  for v1; no pairing codes exist in this design.
