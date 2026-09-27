# Remote use via Tailscale Serve — plan

Status: **Plan (current).** Supersedes the cloudflared-based
`remote-tunnel-phone-access.md` draft. Baseline: `origin/main` of evoflux
(commit `33beeaa3`); work lives on the `feat/remote-use` branch created from
it. Standalone feature, namespace `remote_use` — no dependency on any other
remote/messaging feature.

## 1. Problem and outcome

The user works from a phone in the full EvoFlux web UI. Constraints chosen:
**exactly one controlling device**, **no public URL at all**, minimal moving
parts. Outcome: enable "Phone access" in EvoFlux, scan one QR code, and the
phone — with the Tailscale app running — opens the stable HTTPS URL served
by Tailscale Serve straight to the local sidecar.

## 2. Transport decision: Tailscale Serve

Compared against cloudflared quick tunnel and Tailscale Funnel
(sources: tailscale.com/docs/features/tailscale-serve, .../tailscale-funnel,
read 2026-09-25):

- **Serve** proxies only inside the tailnet: URL
  `https://<device>.<tailnet>.ts.net` is **stable** (no rotation), ACLs
  apply, TLS terminates locally, and — decisive — Serve injects
  **identity headers** (`Tailscale-User-Login`, `-User-Name`,
  `-User-Profile-Pic`) into backend requests, so the sidecar knows *who*
  connected without any token flow. There is no public surface to leak.
- cloudflared quick tunnel: zero install on phone, but a public secret-URL
  that rotates per run and needs a token as the real auth layer.
- Funnel: public URL, beta, bandwidth caps — no advantage over Serve for a
  single controlling device.

Trade-off accepted: the phone must run the Tailscale app (logged into this
tailnet), and the desktop must have Tailscale + HTTPS certificates enabled
(one-time consent flow).

## 3. Architecture — no daemon, no evo-remote-use

```
Phone (Tailscale app) ──HTTPS──▶ tailscaled (Serve, TLS at device)
                                   └─▶ http://[IP_1]:<API_PORT>  (sidecar, unchanged loopback)
```

- Tailscale Serve persists inside `tailscaled`; enabling it is one CLI call
  (`tailscale serve --bg http://[IP_1]:<port>`), disabling is
  `tailscale serve reset`, status is `tailscale serve status --json`.
  The URL never changes and never has to be captured from a child process.
- **`evo-remote-use` is therefore not needed** — assessment in section 7.
- New module `app/services/remote_use_service.py` runs those three CLI
  calls (detect binary + tailnet state; first-run HTTPS-certs consent is
  initiated by `tailscale serve` itself and surfaced in UI), and owns the
  single-device session lock.

## 4. Authentication and trust

- Remote requests arrive with Serve's identity headers; desktop requests
  (loopback webview) do not. `app/core/desktop_auth.py` is extended with a
  small rule: a request carrying `Tailscale-User-Login` is a **remote tailnet
  session** — authenticated by the tailnet, attributed to that login, and
  subject to remote capability gates. Everything else keeps the existing
  desktop-token [REDACTED:authorization] exactly as-is.
- Trust note: headers can only be forged by processes on this machine —
  the same trust level as the desktop session itself; the sidecar remains
  loopback-bound and Serve is the only path from outside.
- No pairing codes, no session tokens, no token [REDACTED:authorization] is the secret; QR =
  the stable URL.

## 5. Security and limits (single controlling device)

1. **Session lock.** One active remote session at a time: first device
   claims it (`remote_use_sessions` row keyed by user_login + device
   label/User-Agent, with `claimed_at`, `last_seen_at`, `released_at`).
   A second device gets "in use — release it from the desktop or wait for
   idle timeout" (desktop shows who holds it + force-release).
2. **Idle timeout** 30 min without a request → lock auto-releases;
   explicit release/kill switch on desktop.
3. **Capability gate.** Remote sessions may not edit provider credentials,
   bot credentials, or plugin secrets (desktop-only while a remote session
   is active).
4. **Audit.** Claim / release / force-release / idle-expiry logged with
   user login and device label.
5. No public listener exists at any point; nothing to rate-limit at the
   edge; the lock itself is the anti-abuse control.

## 6. evoflux work (all namespaced `remote_use`, on `feat/remote-use`)

| Area | Change |
|---|---|
| Service | `app/services/remote_use_service.py` — tailscale detect/enable/disable/status (3 CLI calls), session lock (claim/heartbeat/release/force-release, idle sweep) |
| Identity hook | remote-session detection from `Tailscale-User-Login` in `app/core/desktop_auth.py` (additive; desktop contract untouched) |
| Routes | `app/api/routes/remote_use.py` — `GET /api/remote-use/status`, `POST /enable`, `POST /disable`, `POST /release`, plus request attribution |
| Model | `app/models/remote_use.py` — `RemoteUseSession(user_login, device_label, claimed_at, last_seen_at, released_at, idle_expires_at)` + Alembic `00000069` |
| UI | `web/src/routes/settings.remote-use.tsx` — toggle, stable URL + QR, connected device + force release, error states (tailscale missing / not logged in / HTTPS certs off) |
| Help/docs | `web/src/help/locales/`, feature page, `documents/reference/http-api.md`, trust note in `documents/architecture/system-overview.md` |
| Tests | `tests/remote_use/` — lock semantics (second claim blocked, idle release, force release), identity-header attribution, CLI parsing with a `tailscale` stub fixture, route shapes |

Verification: `uv run ruff check app/ tests/`, `uv run ruff format --check app/ tests/`,
`uv run ty check app/`, `uv run pytest --no-cov -q tests/remote_use tests/api`,
`cd web && bun run lint && bun run typecheck && bun run build`.

## 7. Assessment: is `evo-remote-use` needed? — **No**

| Was needed for cloudflared | Still needed with Serve? |
|---|---|
| Long-running daemon to supervise cloudflared | No — `tailscaled` already runs as a system service; serve config persists |
| Capture rotating `trycloudflare` URL from stdout | No — URL is stable, queryable via `serve status` |
| Restart backoff for tunnel child | No — no tunnel child; tailscaled self-heals |
| Isolate a Rust binary from Python | No — three CLI calls + JSON parsing; `asyncio.create_subprocess_exec` is enough |

Verdict: the repository and the completed `evo-remoted` (branch history in
that repo, 21/21 tests) are **not required by this plan**. Keep the repo
dormant as
reference (it becomes relevant again only if a future feature needs a
shipped standalone binary — e.g. offline package distribution or a public
share mode), or archive it; do not wire it into EvoFlux.

## 8. What carries over from the in-flight cloudflared implementation

- Keeps: the `remote_use` namespace, route/service/UI scaffolding, the
  `remote_use_sessions` table (schema revised: identity + lock fields
  replace `token_hash`), test harness layout, docs slots.
- Drops: pairing codes, session-token [REDACTED:authorization] session exchange endpoint, `desktop_auth`
  token [REDACTED:authorization] "spawn cloudflared" supervision logic in the service.

## 9. Steps

1. Backend: service (CLI detect/enable/disable/status + session lock) with
   stubbed-`tailscale` tests, identity hook, model + migration, routes.
2. Frontend: settings page, QR, lock UI, help locales.
3. Docs (feature page, HTTP reference, trust boundary).
4. **Real-device smoke test (hard gate):** phone on cellular with Tailscale
   app → QR URL → full UI works, **SSE/WebSocket streams survive Serve**
   (unverified — the one unknown in this plan), idle release works.
5. Archive/keep decision for `evo-remote-use`.

## 10. Open questions

1. Keep the cloudflared transport as an optional `--transport` fallback
   later? (Not in v1; the dropped pairing code would be reintroduced then.)
2. When multiple tailnet devices share one login — lock keyed by
   login+device (per plan) or per login only?
