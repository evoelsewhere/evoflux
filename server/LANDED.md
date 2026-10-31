# Landed on migrate/rust-v4

One line per landed task: date · task · author agent · reviewer · commit range.
- 2026-10-30 · T1 freeze diagnosis (PR #48) · Codex · Claude reviewer (APPROVE d26b9b12) · this commit
2026-10-30 · T7 core basics (config, paths, errors, telemetry, auth, watchdog) · Claude Sonnet 5.5 · Phase 0 PR reviewer (APPROVE) · 2da1031b..HEAD
2026-10-30 · T8 core::db (begin-concurrent SQLite build, read/concurrent/exclusive lanes, PR #53) · Claude Opus 5.5 · Phase 0 PR reviewer (APPROVE 0756d2f2, rebased onto T7) · 40d149ab..HEAD
2026-10-30 · Cutover-unit regroup (adapter/file-lock pin breakers, #55) · Codex + Claude · Phase 0 PR reviewer (APPROVE 1507576e) · 1ca32196..HEAD
2026-10-30 · T4 upgrade fixture, v3.0.0 only (PR #54) · Claude T4 session · Claude reviewer (APPROVE) · cherry-picked 27978ce4
2026-10-30 · T10 gateway (routing, Python supervisor, streaming proxy) · Claude CLI Opus · Codex Luna review (CHANGELOG fix applied) · e4b3c5b2
2026-10-31 · T11 evoflux-server serve + handshake · Claude CLI Opus/Sonnet · Claude Opus reviewer (APPROVE 3b7688ba) · 58c7fbc0..HEAD
2026-10-31 · T15 shadow mode + recording · Codex (start) + Claude Sonnet · Claude Opus reviewer (APPROVE 0d36a96c) · 07683b8a..HEAD
2026-10-31 · T14 perf baseline + open-loop responsiveness gate · Claude Sonnet (desktop + CLI) · Codex Luna review (APPROVE) · 6a3d286d..HEAD
2026-10-31 · T12 desktop launches evoflux-server · Claude CLI Opus · Codex Luna review (APPROVE) · cf76bdfa..HEAD
2026-10-31 · T9 SQLite compat gate, two-process stress, benchmark, WAL checkpoint fix, concurrent writes default off · Codex + Claude (desktop Opus, CLI Sonnet/Haiku) · Claude Opus reviewer + Codex Luna (APPROVE) · 0416e7b7..HEAD
2026-10-31 · T16 Phase 0 exit report (awaiting owner daily-use approval) · Claude CLI Sonnet + orchestrator checks · owner · 2d7b4874..HEAD
2026-10-31 · P1-T1 board/units for Phase 1, merged rows release paths · Claude CLI Haiku · Codex Luna (APPROVE) · d5c69e1b..HEAD
2026-10-31 · P1-T2 CI on push + 3-OS contract job · Codex Terra · Claude CLI Sonnet (APPROVE fdc94af5) · 83e867bf..HEAD
2026-10-31 · P1-T6 serve hosts area units + shadow wiring · Codex Terra · Claude CLI Sonnet (APPROVE 7322598d) · a46b44e7..HEAD
2026-10-31 · P1-L1a health-live + L2a quote contract tests · Claude CLI Sonnet · Claude CLI Sonnet (fresh reviewer, APPROVE) · 6b683862..HEAD
2026-10-31 · P1-L3a commands + L4a snippets contract tests (111) · Claude CLI Sonnet · Claude CLI Sonnet (fresh reviewer, APPROVE; follow-ups: commands 422 order, snippets render file-workspace) · 5c8258e7..HEAD
2026-10-31 · P1-T8 remote device claim on Rust routes (health exempt from claim, not from identity) · Codex Terra draft + Claude CLI Opus · Claude CLI Opus (fresh reviewer, APPROVE); gateway contract 11/11 x4 · 8e53ec2e..HEAD
2026-10-31 · P1-T7 dual-backend replay diff, recorder bodies/redaction/seq, TARGET=rust unit override · Codex Terra draft + Claude CLI Sonnet (fix 5b666eb4) · Claude CLI Sonnet (fresh reviewer: changes requested → re-review APPROVE); follow-up: substring key match (access_token, client_secret, api-key), form bodies · dc4049c3..HEAD
2026-10-31 · P1-T7 follow-up: substring sensitive-key redaction (JSON + form) and gates.sh server-relative mutants diff · Claude CLI Haiku + orchestrator (gates.sh) · Claude CLI Sonnet (fresh reviewer, APPROVE); follow-up: form-looking bodies without form content type · 732e33e9..HEAD
2026-10-31 · P1-L5a observability contract tests (50) + scrubbed OTel fixtures · Claude CLI Sonnet · Claude CLI Sonnet (fresh reviewer, APPROVE); follow-up for L5b: fixtures anchored to wall-clock hour (possible boundary flake) · 6553eb91..HEAD
2026-10-31 · P1-L1b health-live + L2b quote Rust ports (+ shared mount/cache_dir, contract rust_units) · Claude CLI Sonnet + orchestrator (commit split, rust_units) · Claude CLI Sonnet (review: changes requested → re-review APPROVE; mutants 0 missed); pre-cutover: quote live fetch (reqwest), health version source, double-slash 307 · 21a6188b..HEAD
2026-10-31 · P1 pre-cutover: evoflux-net shared reqwest 0.13 client (rustls/aws-lc-rs + OS trust, no redirects, builder bans) + quote live fetch + health app version + double-slash 307 · Claude CLI Sonnet · Claude CLI Opus (review: changes requested, redirect key leak) → Claude CLI Sonnet re-review APPROVE; contract py/rust 33/33 (orchestrator) · 40086a10..HEAD
