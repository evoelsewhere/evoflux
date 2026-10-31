# HTTPS client decision and stack re-check for the EvoFlux Rust backend (2026-10-31)

Extends `documents/research/rust-backend-stack-2026-10-30.md` in the repo. Not repeated here.

## Summary

Use **one shared `reqwest` 0.13 client** with `default-features = false` and the `rustls` feature. In 0.13 that feature means rustls with the **aws-lc-rs** provider and **rustls-platform-verifier**, so the OS trust store is used on Windows (Windows certificate APIs), macOS (Security.framework) and Linux (system CA bundle). Add `http2`, `stream`, `json`, `gzip` and `system-proxy`. Install the aws-lc-rs provider explicitly at startup, because the Tauri updater plugin brings `ring` into the same graph. The alternatives lose: `ureq` is blocking-only, `isahc` drags in a bundled libcurl, and `hyper-util` used directly means rebuilding redirects, decompression and timeouts by hand. No Rust client, including reqwest, supports **PAC/WPAD**. reqwest's system proxy covers only the manual proxy settings (Windows current-user registry, macOS HTTP/HTTPS proxy) plus env vars. So expose a settings-level proxy override, and treat PAC as a later add-on (`proxy-watch` or a WinHTTP helper). Part B finds four real changes: `utoipa` 6.0, `keyring` 4 / `keyring-core` 1.0, `process-wrap` 10, and `duckdb` 1.2xxxx; plus a tokio/rustls patch-level floor.

## Part A: comparison table

| Criterion | reqwest 0.13.5 | hyper-util legacy client (0.1.21) | ureq 3.5.0 | isahc 2.0.2 | aioduct 0.2.6 / wreq 6.0.0-rc |
|---|---|---|---|---|---|
| Async on tokio, axum/tower fit | Yes, hyper 1 + tokio; tower-http used internally for decompression | Yes (it is the layer under reqwest) | **No**, blocking I/O only | Runtime-agnostic async over libcurl threads | Async hyper 1 / reqwest fork |
| Streaming / SSE | `stream` feature, `bytes_stream()` feeds `eventsource-stream` | Raw `Incoming` body, you wrap it yourself | Blocking `Read`; would need `spawn_blocking` | Async body stream | Young / fork |
| HTTP/2 | `http2` feature (default) | `http2` feature | Not confirmed (sources disagree) | Via libcurl | Yes (claimed) |
| Timeouts | `connect_timeout`, `read_timeout`, total `timeout`, h2 keep-alive | Connect only; rest is DIY | Yes | Yes | n/a |
| Retries | `retry(policy)` builder; reqwest-retry exists in uv | None | None documented | None | n/a |
| Pooling | Built in, 90 s idle default | Built in | Agent pool | libcurl | n/a |
| Proxy: env | Yes | `Matcher::from_env` | Yes | via libcurl env | n/a |
| Proxy: OS settings | `system-proxy` feature: Windows HKCU manual proxy + override list, macOS manual HTTP/HTTPS | Same matcher, you wire it | `win-system-proxy` feature (winreg); no macOS | libcurl only (env) | n/a |
| PAC / WPAD | **None** | None | None | None | None |
| TLS provider | `rustls` = aws-lc-rs; `rustls-no-provider` lets you pick ring | You choose (hyper-rustls) | Default `rustls` = ring + webpki-roots | Rustls default (2.0), libcurl | n/a |
| OS trust store (corporate roots) | **Yes**, platform-verifier by default | Only if you add it | Only with `platform-verifier` feature; default uses bundled webpki-roots | Yes, `TrustStore::native` default | n/a |
| Windows build | aws-lc needs C compiler + NASM (or `prebuilt-nasm`); native-tls alternative needs none | Same as chosen TLS | ring needs C compiler | Bundled libcurl via `curl-sys` (C build) | n/a |
| Maintenance | One maintainer (seanmonstar), 5 releases in 2026, 241M recent downloads | hyperium, 192M recent downloads | algesten, active | Revived: 2.0.0 May 2026 after "passively maintained" badge | 3.7k and 705k recent downloads |
| Advisory history | None found on RustSec (page 404) | None found | None found (page 404) | None checked | n/a |
| Used by | Goose, uv, Tauri updater, rmcp, smithy-transport-reqwest | Codex (as dep), AWS SDK | none of the references | none of the references | none |

Verdict: reqwest. ureq and isahc fail the "async on tokio with SSE" test or add a C dependency; hyper-util alone is a rebuild of reqwest.

## Evidence

**reqwest state.**
- Latest 0.13.5 on 2026-09-08; 0.13.0 on 2025-12-30; 241,695,799 recent downloads ([crates.io reqwest](https://crates.io/api/v1/crates/reqwest)).
- Feature table: `default = default-tls, charset, http2, system-proxy`; `rustls = __rustls-aws-lc-rs + rustls-platform-verifier`; `rustls-no-provider` = platform-verifier with no provider; `system-proxy = hyper-util/client-proxy-system`; no webpki-roots dependency ([reqwest Cargo.toml](https://raw.githubusercontent.com/seanmonstar/reqwest/master/Cargo.toml)).
- 0.13.0 changelog: rustls is the default backend, aws-lc replaces ring, "rustls roots features removed, `rustls-platform-verifier` is used by default", custom roots via `tls_certs_only` ([CHANGELOG](https://raw.githubusercontent.com/seanmonstar/reqwest/master/CHANGELOG.md)). 0.13.4 strips sensitive headers on scheme-changing redirects; 0.13.5 fixes wrong proxy credentials with several proxies (same file).
- Builder knobs verified: `tls_certs_only`, `tls_certs_merge`, `connect_timeout`, `read_timeout`, `timeout`, `pool_idle_timeout` (90 s default), `http2_keep_alive_*`, `no_proxy()`, `retry(policy)` ([ClientBuilder docs](https://docs.rs/reqwest/latest/reqwest/struct.ClientBuilder.html)).

**System proxy and PAC.**
- hyper-util `Matcher::from_system()` reads env vars, then on Windows only `HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings` (`ProxyEnable`, `ProxyServer`, `ProxyOverride`), and on macOS only the HTTP and HTTPS proxy enable/host/port. The source has no AutoConfigURL or PAC reference ([hyper-util matcher.rs](https://docs.rs/crate/hyper-util/latest/source/src/client/proxy/matcher.rs)). No machine-wide (HKLM/WinHTTP) read appears there either.
- reqwest delegates to that matcher and has no OS-specific code of its own ([reqwest proxy.rs](https://github.com/seanmonstar/reqwest/blob/master/src/proxy.rs)).
- reqwest reads system proxy once at client build. Issue [#2674](https://github.com/seanmonstar/reqwest/issues/2674) is open; the maintainer's answer is "use `Proxy::custom()`, and check the environment yourself".
- `proxy-watch` reads OS proxy config on Windows/macOS/Linux, can watch for changes, and has a `pac-windows-native` feature (WinHTTP does WPAD, download and evaluation); on macOS/Linux you must supply the PAC body. It returns `PacNotSupported` by default. Early release; macOS GUI/MDM behaviour unverified ([README](https://docs.rs/crate/proxy-watch/0.1.1/source/README.md)). crates.io shows 0.3.1, created 2026-09-07, 6,633 downloads ([crates.io](https://crates.io/api/v1/crates/proxy-watch)); the README I read was for 0.1.1, so features may have moved.
- ureq: env vars only in the README, `win-system-proxy` feature (winreg), `socks-proxy` feature ([ureq README](https://raw.githubusercontent.com/algesten/ureq/main/README.md), [ureq features](https://docs.rs/crate/ureq/latest/features)).

**TLS provider and trust store.**
- rustls-platform-verifier 0.7.1 (2026-09-24, 202M downloads) ([crates.io](https://crates.io/api/v1/crates/rustls-platform-verifier)). Windows: Windows certificate store and API verification with revocation; macOS: Security.framework with revocation; Linux/BSD: system CA bundle found with `rustls-native-certs` + `openssl-probe`, verified by webpki, loaded once at startup, no revocation ([README](https://github.com/rustls/rustls-platform-verifier)). So corporate MITM roots in the OS store are trusted on all three OSes; on Linux the root must be in the distro bundle, and a change needs an app restart.
- ureq's default `rustls` feature = ring + webpki-roots, so it does **not** trust the OS store unless `platform-verifier` is enabled ([ureq features](https://docs.rs/crate/ureq/latest/features)).
- aws-lc-rs 1.19.0 (2026-10-28) ([crates.io](https://crates.io/api/v1/crates/aws-lc-rs)). Windows MSVC non-FIPS needs a C/C++ compiler and NASM; prebuilt NASM objects are available via `prebuilt-nasm` feature or `AWS_LC_SYS_PREBUILT_NASM=1`; **CMake, Go and Ninja are needed only for FIPS** ([aws-lc-rs Windows requirements](https://aws.github.io/aws-lc-rs/requirements/windows.html)). I did not measure binary size or compile time; no source gathered.
- Codex installs aws-lc-rs process-wide because "rustls can't pick a provider automatically when both ring and aws-lc-rs are in the dependency graph", and asserts it supports ECDSA P-521/SHA-512 "which some enterprise TLS proxies use" ([codex utils/rustls-provider](https://raw.githubusercontent.com/openai/codex/main/codex-rs/utils/rustls-provider/src/lib.rs)). Relevant to corporate networks.

**Advisories.**
- rustls: five advisories in Sept-Oct 2026 (RUSTSEC-2026-0285, -0346, -0347, -0348, -0349), the latest dated 2026-10-14; all Low/Medium ([RustSec rustls](https://rustsec.org/packages/rustls.html)). Patched in `rustls >= 0.23.46` ([0349](https://rustsec.org/advisories/RUSTSEC-2026-0349.html), [0346](https://rustsec.org/advisories/RUSTSEC-2026-0346.html)); 0.23.46 released 2026-10-14 ([crates.io](https://crates.io/api/v1/crates/rustls)). Floor `Cargo.lock` at 0.23.46. A 0.24.0-dev line exists; reqwest 0.13 pins 0.23.
- aws-lc-sys: five advisories dated 2026-03-20 (PKCS7_verify bypasses, CRL scope, name constraints, AES-CCM timing) ([RustSec aws-lc-sys](https://rustsec.org/packages/aws-lc-sys.html)). Patched versions not read; run `cargo deny` and require a lockfile newer than March 2026.
- hyper: only 2016-2022 advisories ([RustSec hyper](https://rustsec.org/packages/hyper.html)). RustSec package pages for reqwest and ureq returned 404 (consistent with no advisories; not independently confirmed).
- isahc 2.0.2 (2026-10-21) fixed a webpki-root-certs minimum for users who opt in; OS store is default ([isahc CHANGELOG](https://raw.githubusercontent.com/sagebind/isahc/master/CHANGELOG.md)).

**What production Rust apps use.**
- Goose: `reqwest 0.13.2` default-features off, `rustls` with `aws_lc_rs`; `rmcp` with `transport-streamable-http-client-reqwest`; `smithy-transport-reqwest 0.1` with `http2`, `system-proxy`; features `rustls-tls` and `native-tls` switch all three together ([goose Cargo.toml](https://raw.githubusercontent.com/block/goose/main/Cargo.toml), [crates/goose/Cargo.toml](https://raw.githubusercontent.com/block/goose/main/crates/goose/Cargo.toml)).
- Codex: still `reqwest 0.12` (`cookies`), `rustls 0.23.46` + `rustls-native-certs`, `hyper-util 0.1.20`, `eventsource-stream 0.2.3`, `aws-config`/`aws-sigv4`, `rmcp =3.5.1` ([codex-rs Cargo.toml](https://raw.githubusercontent.com/openai/codex/main/codex-rs/Cargo.toml)). Codex uses native roots rather than platform-verifier.
- uv: `reqwest 0.13.1` with `rustls`, `system-proxy`, `socks`, `http2`, `stream`, and Astral forks of reqwest-middleware/retry ([uv Cargo.toml](https://raw.githubusercontent.com/astral-sh/uv/main/Cargo.toml)).
- Zed: its own reqwest fork (`zed-reqwest 0.12.15-zed`, `rustls-tls-native-roots`), `rustls-platform-verifier 0.7`, `webpki-roots` ([Zed Cargo.toml](https://raw.githubusercontent.com/zed-industries/zed/main/Cargo.toml)).
- tauri-plugin-http: reqwest `>=0.12.16`, default features `rustls-tls, http2, charset, system-proxy, cookies` ([Cargo.toml](https://raw.githubusercontent.com/tauri-apps/plugins-workspace/v2/plugins/http/Cargo.toml)). **tauri-plugin-updater: reqwest 0.13, `rustls-no-provider` plus `rustls` with the `ring` provider** ([Cargo.toml](https://raw.githubusercontent.com/tauri-apps/plugins-workspace/v2/plugins/updater/Cargo.toml)). That is why two crypto providers will coexist in EvoFlux.

**AWS SDK.**
- Default HTTPS client is hyper 1.x with rustls on aws-lc (moved from ring in March 2025); `default-https-client` feature; custom clients via `.http_client(...)` ([aws-sdk-rust discussion 1257](https://github.com/awslabs/aws-sdk-rust/discussions/1257)). `aws-sdk-bedrockruntime` default features: `default-https-client`, `rustls`, `rt-tokio` ([docs.rs features](https://docs.rs/crate/aws-sdk-bedrockruntime/latest/features)).
- `aws-smithy-http-client` 1.5.2: features `rustls-aws-lc` and `rustls-ring`; the default client uses `rustls-native-certs`, so the OS store is trusted there as well ([features](https://docs.rs/crate/aws-smithy-http-client/latest/features), [tls.rs](https://docs.rs/crate/aws-smithy-http-client/latest/source/src/client/tls.rs)). The AWS stack therefore already puts aws-lc-rs in the build, so choosing aws-lc-rs for reqwest adds no new native toolchain requirement. Whether its proxy handling reads Windows/macOS settings: not verified.
- `smithy-transport-reqwest` 0.1.0 (2026-05-22) implements the SDK `HttpClient` trait over reqwest `^0.13`; 306,928 downloads; crates.io shows no repository and no license on the page I read ([crates.io](https://crates.io/api/v1/crates/smithy-transport-reqwest), [docs.rs](https://docs.rs/crate/smithy-transport-reqwest/latest)). Goose uses it, so it can share the one reqwest client's proxy and trust configuration.

**rmcp.** 3.8.0 (2026-10-26). Depends on `reqwest 0.13.2`, default-features off, `json`+`stream`; feature `reqwest` = `reqwest/rustls`; `reqwest-tls-no-provider` and `reqwest-native-tls` variants exist; `auth` also pulls reqwest ([rmcp Cargo.toml](https://raw.githubusercontent.com/modelcontextprotocol/rust-sdk/main/crates/rmcp/Cargo.toml)). Same reqwest major as recommended, so one copy in the build. Whether you can inject your own `reqwest::Client` into the transport: not verified in this pass; check `StreamableHttpClientTransport` before relying on it.

**Other candidates.**
- ureq: blocking only, "uses blocking I/O instead of async I/O" ([README](https://raw.githubusercontent.com/algesten/ureq/main/README.md)). Fine for a CLI, wrong inside an axum handler without `spawn_blocking`.
- isahc 2.0.2: libcurl bundled via `curl-sys` (8.21.0 in 2.0.1) ([CHANGELOG](https://raw.githubusercontent.com/sagebind/isahc/master/CHANGELOG.md)); repo shows a "passively maintained" badge, 25 open issues ([GitHub](https://github.com/sagebind/isahc)). Alive again, but no reference project uses it.
- wreq 6.0.0-rc.31 (browser-fingerprint fork of reqwest, 705k recent downloads) ([crates.io](https://crates.io/api/v1/crates/wreq)); aioduct 0.2.6, created 2026-04-20, 3,698 recent downloads ([crates.io](https://crates.io/api/v1/crates/aioduct)). Neither is a candidate. wreq is worth remembering only if the scraper needs TLS fingerprint impersonation.
- August 2026 comparison post agrees reqwest remains the default ([pistack](https://www.pistack.xyz/posts/2026-08-17-rust-http-client-libraries-reqwest-hyper-ureq-comparison/)); weak source.

## Recommendation

**Crate and features.** `reqwest 0.13`, `default-features = false`, features: `rustls`, `http2`, `stream`, `json`, `gzip`, `brotli`, `system-proxy`, `socks`. Add `charset` only if the scraper needs it. No `blocking`, `cookies` (add per-client if web scraping needs a jar), `native-tls`, `http3`, `hickory-dns`.

**TLS.** rustls + aws-lc-rs + rustls-platform-verifier (what `rustls` gives). Call `rustls::crypto::aws_lc_rs::default_provider().install_default()` once in `main`, before building any client, because the Tauri updater brings `ring` (Codex does the same). Fallback if NASM on Windows CI becomes a problem: set `AWS_LC_SYS_PREBUILT_NASM=1`; do not switch to ring unless the AWS SDK is also moved to `rustls-ring`.

**One shared client.**
- Build it once in an `evo-net` crate: `fn build_client(settings: &NetSettings) -> reqwest::Client`. Hold it in `ArcSwap<Client>` inside `AppState`; handlers and the provider layer get `state.http()`. Rebuild and swap on a settings change or a network-change event, since reqwest reads system proxy only at build (issue #2674).
- Defaults: `connect_timeout(10 s)`, `read_timeout(60 s)` for SSE idle detection, **no** total `timeout` on the shared client (a total timeout kills long SSE streams; set per-request timeouts for small JSON calls like API Ninjas), `pool_idle_timeout(60 s)`, `tcp_keepalive(30 s)`, `http2_keep_alive_interval(30 s)` with `while_idle`, `redirect(limited(5))`, `user_agent`.
- Proxy precedence: explicit EvoFlux setting > env vars > OS manual proxy (`system-proxy`). Put the user's "custom CA PEM" in the settings and apply it with `tls_certs_merge`. Show the resolved proxy in a diagnostics screen. Add a "test connection" button that surfaces TLS-verify failures clearly.
- PAC: not supported out of the box. v1: documented limitation plus manual proxy field. Later: `proxy-watch` with `pac-windows-native` through `Proxy::custom`.
- Pass the same client to: provider layer (`bytes_stream()` into `eventsource-stream`), MCP (`rmcp` `reqwest` feature, injecting the client if its API allows), web search/scrape, and Bedrock through `smithy-transport-reqwest` (behind a feature flag and exact pin; fall back to the SDK default client if it misbehaves).
- Retry only before the first byte and only idempotent calls; never auto-retry a model POST after the stream starts.

**Ban.**
- `reqwest::blocking` and `ureq` in async crates (clippy `disallowed-types`/`disallowed-methods`).
- `Client::new()` / `reqwest::get()` outside `evo-net` (`disallowed-methods`).
- `native-tls`, `webpki-roots`, `rustls-webpki-roots` features (they bypass the OS store), and `reqwest-eventsource` auto-reconnect.
- Duplicate reqwest majors: use `cargo deny` `bans.multiple-versions = "deny"` for reqwest and rustls; do not add `tauri-plugin-http` (reqwest 0.12).
- Building clients per request.

## Cargo dependency lines

```toml
reqwest = { version = "0.13.5", default-features = false, features = [
  "rustls", "http2", "stream", "json", "gzip", "brotli", "system-proxy", "socks",
] }
rustls = { version = "0.23.46", default-features = false, features = ["aws_lc_rs", "std", "tls12"] }
eventsource-stream = "0.2.3"
tokio = { version = "1.54.1", features = ["rt-multi-thread", "macros", "time", "sync", "signal"] }
# MCP: same reqwest major, no second HTTP stack
rmcp = { version = "=3.8.0", default-features = false, features = ["client", "transport-streamable-http-client-reqwest", "auth"] }
# Bedrock
aws-config = { version = "1", default-features = false, features = ["rt-tokio", "behavior-version-latest"] }
aws-sdk-bedrockruntime = { version = "1", default-features = false, features = ["rt-tokio"] }
smithy-transport-reqwest = { version = "=0.1.0", default-features = false, features = ["http2", "system-proxy", "rustls"] } # optional, exact pin
# Later, PAC: proxy-watch = { version = "<verify>", features = ["pac-windows-native"] }
```

Feature names for `rmcp`, `aws-config` and `aws-sdk-bedrockruntime` follow the manifests read above, but I did not compile this set. Run `cargo tree -d -i rustls` and `cargo tree -i aws-lc-rs` once before freezing it.

## Risks and open questions

1. **Two crypto providers.** Updater (ring) plus reqwest and AWS (aws-lc-rs). Without `install_default`, rustls panics when it builds a default config. Test at startup in CI.
2. **No PAC.** Corporate networks that rely on PAC/WPAD will fail until a helper is added. Windows HKLM or WinHTTP-only proxy settings are also invisible to hyper-util (it reads HKCU only). Needs a real corporate-network test.
3. **Linux trust store is read once at start.** New corporate root needs an app restart. Platform verifier on Linux has no revocation checking.
4. **aws-lc-sys history.** Five advisories in March 2026; keep it under `cargo deny` and update.
5. **Windows build.** NASM required unless `prebuilt-nasm`. Binary size and compile-time cost not measured here; measure on CI.
6. **`smithy-transport-reqwest`** is 5 months old with one owner, no license shown on docs.rs. Treat as optional.
7. **Bus factor.** reqwest has one primary maintainer; hyper-util and rustls are broader. Mitigation: keep all use behind `evo-net`.
8. **Unverified:** whether rmcp accepts an injected `reqwest::Client`; whether the AWS default client honours Windows/macOS system proxy; ureq HTTP/2 status; the proxy-watch current API (README 0.1.1 vs crate 0.3.1).
9. **rustls 0.24** is in dev; reqwest 0.13 pins 0.23, so expect a later reqwest major to move everything at once.

## Part B: re-check of the other picks

Dates are release dates from crates.io unless stated.

| Row | Current state (2026-10-31) | Verdict |
|---|---|---|
| axum 0.8 | 0.8.9 (2026-04-14), no 0.9 seen; no RustSec page ([crates.io](https://crates.io/api/v1/crates/axum), [RustSec](https://rustsec.org/packages/axum.html) 404) | Keep |
| tokio | 1.54.1 (2026-10-21). **1.54.0 yanked**; RUSTSEC-2026-0384 race in `tokio::time::Interval` on 1.54.0, plus RUSTSEC-2026-0386 INFO on `AsyncFd` ([crates.io](https://crates.io/api/v1/crates/tokio), [RustSec](https://rustsec.org/packages/tokio.html)) | Keep; floor `>=1.54.1` (never 1.54.0) |
| hyper 1 / tower-http | tower-http 0.7.1 (2026-08-31), unchanged ([crates.io](https://crates.io/api/v1/crates/tower-http)) | Keep |
| rusqlite | 0.41.1 (2026-10-28); libsqlite3-sys 0.39.1 bundles SQLite 3.54.0 ([crates.io](https://crates.io/api/v1/crates/rusqlite), [docs.rs](https://docs.rs/crate/libsqlite3-sys/latest)); only 2020-2021 advisories ([RustSec](https://rustsec.org/packages/rusqlite.html)) | Keep; doc's "0.39" referred to libsqlite3-sys, so pin rusqlite 0.41 |
| sqlx | 0.9.0 (2026-05-21) ([crates.io](https://crates.io/api/v1/crates/sqlx)) | Keep (not chosen) |
| utoipa / utoipa-axum | **utoipa 6.0.0 and utoipa-axum 0.3.0 both released 2026-09-22**; MSRV 1.88; utoipa-gen 6 drops expression ignore in `ToSchema`/`IntoParams` ([crates.io](https://crates.io/api/v1/crates/utoipa), [releases](https://github.com/juhaku/utoipa/releases)). The old doc said 5.5 | **Change**: target utoipa 6.0 / utoipa-axum 0.3; check that utoipa-axum 0.3 targets axum 0.8 (not verified) |
| rmcp | 3.8.0 (2026-10-26), weekly minors ([crates.io](https://crates.io/api/v1/crates/rmcp)); Codex pins 3.5.1 | Keep; pin exactly, wrapper crate stays |
| eventsource-stream | 0.2.3, last update 2022-02-17, 14.9M recent downloads ([crates.io](https://crates.io/api/v1/crates/eventsource-stream)); Codex still uses it | Keep (vendor parser as fallback) |
| portable-pty | 0.9.0, last release 2025-02-11, nothing newer ([crates.io](https://crates.io/api/v1/crates/portable-pty)) | Keep, but note ~20 months without release; vendor-able |
| process-wrap | **10.0.1** (2026-09-23); 10.0.0 (2026-08-24) is breaking (typed wrapper extension, removed panicking child accessors) ([CHANGELOG](https://raw.githubusercontent.com/watchexec/process-wrap/main/CHANGELOG.md)). Old doc said 9 | **Change**: use 10.x |
| gix | 0.90.0 (2026-10-22), releases about every two weeks ([crates.io](https://crates.io/api/v1/crates/gix)); RustSec page 404 | Keep; pin exactly |
| notify | 8.2.1 (2026-10-25) stable; 9.0.0-rc.7 (2026-10-27) in RC ([crates.io](https://crates.io/api/v1/crates/notify)) | Keep 8.2.x; re-check 9 when stable |
| ignore | 0.4.34 (2026-10-27) ([crates.io](https://crates.io/api/v1/crates/ignore)) | Keep |
| keyring | **keyring 4.0 (2026-08-29: 4.2.0) is now only a "sample app"; library users should use `keyring-core` 1.0 plus a store crate** such as `windows-native-keyring-store` 1.1.0 ([v4.0.0 release](https://github.com/open-source-cooperative/keyring-rs/releases/tag/v4.0.0), [crates.io keyring-core](https://crates.io/api/v1/crates/keyring-core)) | **Change**: evaluate keyring-core 1 + native stores; must re-verify that the Windows target-name format still matches the Python `keyring` entries (docs.rs page for the store did not say). Until verified, the 3.6 pin (Goose 3.6.3) is the safe fallback |
| tracing | 0.1.44 (2025-12-18), no 0.2 ([crates.io](https://crates.io/api/v1/crates/tracing)) | Keep |
| genai | 0.7.2 (2026-10-28) ([crates.io](https://crates.io/api/v1/crates/genai)) | Keep (reference only) |
| duckdb | **1.20000.1 (2026-10-28)**, previous 1.10506.x ([crates.io](https://crates.io/api/v1/crates/duckdb)); old doc said 1.4.x | **Change/verify**: version scheme encodes the bundled DuckDB version; I did not confirm it is DuckDB 2.0 or what changed. Check release notes before pinning |
| rustls / aws-lc | rustls 0.23.46 patches five 2026 advisories; aws-lc-sys has five March 2026 advisories (links above) | Keep; set lockfile floor, add cargo-deny |
| reqwest (this doc) | 0.13.5; the old doc said only "reqwest" | Pinned per Part A |
| Not re-checked | pdfium-render, htmd, croner, deadpool-sqlite, lsp-types, wiremock, insta, scraper, tauri sidecar | Not checked in this pass |

## Selection (orchestrator decision, 2026-10-31)

The owner asked for the selection to be made from this research, so it is made here and applies from now on:

- **HTTPS client:** one shared `reqwest` 0.13 client, built in a new `evoflux-net` crate (`server/crates/net`) and injected through `UnitState`. Features: `default-features = false`, plus `rustls`, `http2`, `stream`, `json`, `gzip` and `system-proxy`. `brotli` and `socks` are added only when a provider needs them.
- **TLS:** rustls with the aws-lc-rs provider and `rustls-platform-verifier`, so corporate root CAs in the OS store are trusted. Install the provider once at startup. On Windows CI, set `AWS_LC_SYS_PREBUILT_NASM=1`.
- **Proxy:** env vars and the per-user system proxy, through `system-proxy`. An EvoFlux proxy and custom-CA setting is a Phase 2 item. PAC/WPAD is deferred; Python v3 does not support it either, so this is not a regression.
- **Timeouts:** connect and read timeouts on the shared client; total timeouts per request only for small JSON calls, never on SSE streams.
- **Banned** (enforced with `cargo deny` bans or clippy `disallowed-methods`): `reqwest::blocking`, `ureq`, `isahc`, `native-tls`, `webpki-roots`, `reqwest-eventsource`, `Client::new()` and `reqwest::get()` outside `evoflux-net`, and a second reqwest major version.
- **Version floors:** tokio ≥ 1.54.1 (the lockfile is already on 1.54.1) and rustls ≥ 0.23.46 once it enters the graph.
- **Part B:** keep every pick except the following.
  - `utoipa` 6.0 is adopted with the first lane that emits OpenAPI, once a spike confirms that utoipa-axum 0.3 targets axum 0.8.
  - `keyring` stays on 3.6 until a check shows that `keyring-core` 1.0 uses the same Windows target names as Python `keyring`.
  - `process-wrap` 10 and `duckdb` are re-checked when the lanes that use them start.
- **Unverified, so check when used:** whether rmcp accepts an injected client, whether the AWS SDK default client honours the OS proxy, and the binary-size and compile-time impact.
