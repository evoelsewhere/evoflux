# P-006: pinned downloads

Python references: `app/plugin_platform/marketplaces.py` (`validate_marketplace_url`,
`_assert_public_dns`, `_fetch_bytes`), `app/cli/seed.py` (seed tarball download).
This shared library has no endpoints, persistence or HTTP error-body contract.
The existing general client and its provider proxy behavior stay unchanged.

`pinned_client(host, policy)` accepts a hostname/authority or HTTPS URL. It resolves
the initial hostname once, checks **every** answer, then binds a private reqwest
client to those addresses. Only `PinnedClient::fetch(url, limit)` is exposed;
the initial URL must use the constructor's origin. HTTPS, ordinary certificate
verification and original SNI/Host remain in effect. Proxies are disabled because
a proxy can resolve the name independently. No credential headers are accepted.

Redirects (301, 302, 303, 307, 308) are resolved relative to the current URL and
validated/pinned anew, including same-host redirects. The default is three hops,
as in Python. Private-address opt-in is per normalized hostname, never inherited
by another redirect host. IPv4-mapped IPv6 is always refused. Policy supplies the
resolver, request deadline and optional additional trusted CA certificates.
Decoded bytes, not compressed bytes, count towards the caller's limit.

Test map: Python marketplace public-HTTPS URL cases -> `tests/pinned.rs` URL tests;
DNS screening -> special-address/mixed-answer tests; download size/redirect behavior
(previously not covered by route contracts) -> local TLS tests. No external network
or production trust store is required for those tests. Existing `src/lib.rs` tests
cover general-client JSON, redirects, gzip and idle-read behavior.

## Request builder (P-009 prerequisite)

Python references: `app/agent/providers/model_discovery.py` (OpenAI-compatible
`/models` with `Authorization`/`api-key`, Gemini `x-goog-api-key`, Anthropic
`x-api-key` + `anthropic-version`, Copilot/Codex OAuth catalogs, Ollama
`GET /api/tags` + `POST /api/show` JSON) and the Codex, Copilot and OpenCode
`usage.py` GETs (5 s timeouts, `raise_for_status`).

`PinnedClient::request(method, url)` returns a `PinnedRequest`: `.header` adds a
credential header, `.public_header` a non-secret one (known credential names such
as `Authorization`, `x-api-key`, `api-key`, `x-goog-api-key`, `Cookie` stay
credentials), `.json(&T)` a JSON body, `.timeout(d)` a deadline for the whole
exchange (all hops, their DNS checks and the body; `PinError::Timeout`), and
`.limit(n)` the decoded body cap (8 MiB by default). `send()` returns a
`PinnedResponse { status, headers, body }` for any final status;
`error_for_status()` mirrors httpx `raise_for_status`, `json()` decodes the body.
`fetch` is unchanged and now built on the same path.

Every guard of `fetch` applies: the first URL must be the constructor's origin,
every hop is re-parsed, resolved once, address-checked and pinned. Credential
headers are sent only until the first redirect to a different origin (scheme,
host, port) and never again, even back on the first origin. A body never moves
to another origin: a cross-origin 307/308 with a body is `PinError::Redirect`.
303, and 301/302 after POST, become a bodiless GET (httpx rules). Header values
are marked sensitive; `PinnedRequest`/`PinnedResponse` have no `Debug`, and header
errors (`PinError::Header`) carry no value. Nothing in the crate logs.

`Policy::allow_http_hosts` is an explicit per-hostname opt-in for plain HTTP
(Ollama and other local daemons, mock providers in the contract tests). It does
not lift address checks (a loopback daemon still needs `allow_private_hosts`),
and a redirect may use plain HTTP only to a host that also has the opt-in.
httpx discovery clients do not follow redirects; a P-009 caller that must match
that sets `Policy::max_redirects` to 0, so any 3xx is `PinError::Redirect`.
Tests: `tests/pinned_request.rs` (17).

Hardening differences from Python are recorded in `server/KNOWN_DIFFERENCES.md`.
Needs security review (SSRF, DNS rebinding, credential headers on redirects).
