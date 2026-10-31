# Phase 1 checkpoint smoke run (2026-10-31)

**Who ran it:** the orchestrator, an AI agent, ran this automatically in the desktop app's built-in browser. It is **not** the owner's personal half-day of use, and it is **not** owner approval. Both are still outstanding and are tracked separately (design §9a).

**Build:** `migrate/rust-v4` at `48417bc9`. It includes the L1b health-live and L2b quote Rust ports, T7 replay/recorder and T8 remote claim.

**Setup:** `codex-bridge/smoke/dev_gateway.py`. `evoflux-server` runs on `:8000` and supervises Python. The Vite web UI runs on `:5173`. Data and state dirs are temporary. The config is a temporary copy of the owner's `~/.config/evoflux`, so the owner's real model providers are used. The copy was deleted after the run, and no key was printed or stored elsewhere.

## Pass A: default routing (every unit Python-owned)

| Journey | Result |
|---|---|
| `/api/health/live` through the gateway | PASS: `{"status":"ok","version":"3.1.1"}` (Python) |
| `/api/quote`, `/api/commands` | PASS: 200 |
| App loads, first-run import dialog, "Not now" | PASS |
| Slash-command menu (`/` in the composer) | PASS: lists `init` |
| Chat with the owner's default model (`mimo-v2.6-flash`) | PASS: exact reply, 4.6 s, $0.005 |
| Reload: the session and messages persist | PASS |

## Pass B: `EVOFLUX_ROUTE_OVERRIDE=edge-stateless=rust`

| Journey | Result |
|---|---|
| `/api/health/live` served by Rust | PASS: `version` is `0.1.0` (the crate version; fix in flight) |
| `HEAD /api/health/live` → 405; `/api/health/live/` → 307 | PASS |
| `/api/quote` served by Rust | PASS: 200 in 2.6 ms, with the **fallback** quote (live fetch not ported yet, fix in flight) |
| `/api/commands`, `/api/snippets` | EXPECTED FAIL: 404, because L3b/L4b are not ported yet. In the UI the slash menu is empty. |
| `/api/health/ready` (still Python) | PASS: 200 |
| Chat with the owner's model while the edge unit is on Rust | PASS |
| Gateway log | no errors from the gateway or the Rust units. One INFO line: the `opencode` provider's model list returned 404, which is an upstream provider issue. |

## Verdict

- **Pass A:** nothing user-facing regressed on the migration branch.
- **Pass B:** Rust correctly serves the two ported routes inside the real app, and chat is unaffected.
- **Not cutover-ready:** the edge-stateless unit can't be cut over yet. Commands and snippets (L3b/L4b), the quote live fetch, and the health version string are all still open, so CO1 stays blocked.
- **Repeat:** this checkpoint repeats with the full edge-stateless unit on Rust after L3b/L4b and the `evoflux-net` task land, before CO1.

## Limitations and observations

- **Smoke test scope:** this is a smoke test, not a soak. No long session, no packaged Tauri build (T5 pending), and no macOS or Linux.
- **First send after typing `/` then Backspace:** the message was consumed and nothing was sent, because no request left the browser. This is frontend input handling, not the backend: a clean retry worked in both passes. The frontend is unchanged on this branch, so it is presumably also in v3. It is unverified on v3 and logged for triage.
- **Stale browser route:** the browser kept `oa-last-route` pointing at a session from an earlier smoke data dir, and showed "Session not found" until a new chat was created. This is existing frontend behaviour that only shows up when the data dir is reset.
- **Owner's half-day of use:** not done. The owner was away during this run.
