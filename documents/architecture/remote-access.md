# Remote access architecture

## Provider-neutral boundary

Remote connections are persisted as adapter-scoped records. Telegram and iMessage share connection lifecycle, credential-vault ordering, pairing authorization, redaction, rate limits, gates, status, and provider-neutral adapter construction. Provider startup failures are translated to bounded transport status, and partial startup is cleaned up before status is exposed. Construction and validation flow through `RemoteAdapterRegistry` and the provider-neutral contracts in `app/remote/contracts.py`.

## iMessage trust and process boundary

The iMessage adapter is disabled by default and does not open a listening socket. The native `imsg` provider runs as a supervised JSON-RPC stdio child process. BlueBubbles is an explicit REST provider selected by connection metadata; EvoFlux never silently switches providers.

Provider DTOs and process/HTTP details remain under `app/remote/imessage/`. Generic contracts carry normalized inbound actions, safe status/capabilities, reply identifiers, and URL-addressable attachment metadata only. Credentials remain in the OS credential vault under `connection:<uuid>`.

## Testing boundary

`tests/remote/fixtures/mock_imsg_rpc.py` provides deterministic protocol and restart testing, including capability probes, send/reply/attachment payloads, persisted mock state, and watermark filtering. It does not emulate macOS Messages permissions, TCC, Apple ID/iCloud, encryption, or real phone delivery; those require a real Mac smoke test.
