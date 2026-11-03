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

Hardening differences from Python are recorded in `server/KNOWN_DIFFERENCES.md`.
Needs security review (SSRF, DNS rebinding).
