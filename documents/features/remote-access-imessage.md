# Remote access — iMessage channel

Status: **Implemented behind an explicit provider selection** — requires a user-owned Mac running `imsg` for the native provider, or a configured BlueBubbles server as the explicit fallback.

## Overview

EvoFlux can expose the existing remote-access workflow through iMessage without changing Telegram behavior. The iMessage adapter is disabled until explicitly configured and uses the same pairing, authorization, redaction, rate-limit, gate, completion, and audit boundaries as the Telegram adapter.

## Providers

- `imsg` is the primary provider and communicates through line-delimited JSON-RPC over stdio.
- `bluebubbles` is an explicit REST fallback. EvoFlux never silently switches providers.
- Provider credentials are stored in the OS credential vault under `connection:<uuid>`; raw credentials are never returned by the API or stored in application tables.

## Setup

1. Open Settings → Remote access.
2. Select `iMessage`.
3. Select `imsg` for a reachable Mac host or `BlueBubbles` for a configured BlueBubbles endpoint.
4. Enter the provider credential and endpoint when required.
5. Validate and enable the connection.
6. Complete pairing with the configured phone identity.

BlueBubbles requires an endpoint URL and credential. Native `imsg` requires the provider process to be reachable and authorized by macOS Messages. Capability and health information is safe metadata only; provider payloads, credentials, and message history are not exposed.

## Runtime behavior

The adapter starts the provider before capability probing, restores pairing before inbound polling, and persists an inbound receipt watermark. Provider startup failures become safe transport status and partial startup is cleaned up rather than leaking provider exceptions. On restart, messages at or before the watermark are not replayed. Outbound messages pass through the common remote redaction boundary and may carry a provider-neutral reply target and URL-addressable attachment metadata.

## Security and trust boundaries

- iMessage remains disabled by default and does not open an inbound listening socket.
- Provider-specific RPC/HTTP DTOs stay behind `app/remote/imessage/`.
- Generic remote contracts carry only normalized actions, safe status, reply identifiers, and attachment metadata.
- macOS Messages/TCC, Apple ID state, and phone delivery require a real Mac and cannot be proven by the protocol mock.

## Verification

Protocol and channel tests can use `tests/remote/fixtures/mock_imsg_rpc.py`, including process restart and persisted mock state. A real-device smoke test remains required for macOS permissions, provider reachability, pairing, phone delivery, and recovery.
