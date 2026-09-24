# iMessage remote channel

Status: implemented in the local provider/integration layers; real-device validation pending a macOS Messages host.

## Included

- Provider-neutral remote adapter registration and lifecycle.
- Native `imsg` JSON-RPC stdio provider as the primary path.
- Explicit BlueBubbles REST fallback; no silent provider switching.
- OS credential-vault storage under `connection:<uuid>`.
- Adapter-scoped connection uniqueness so Telegram and iMessage can coexist.
- Durable inbound watermark and restart filtering.
- Pairing-aware authorization, shared redaction, streaming, live budgets, gates, and safe diagnostics.
- Reply targets, URL-addressable attachment metadata, and provider capability display.
- API/settings support for provider selection, endpoint validation, lifecycle controls, and safe status.

## Rollback and migration

Migrations `00000071` and `00000072` add nullable iMessage/provider metadata and advance the schema head. Existing Telegram rows remain valid. Rollback must first disable iMessage connections, remove vault entries through the service, and then use the repository migration rollback procedure; raw credentials are never recovered from the database.

## Operational notes

The protocol mock under `tests/remote/fixtures/` covers JSON-RPC, capability probing, reply/attachment payloads, polling, persisted mock state, and process restart. A real Mac is still required to validate Messages permissions, TCC, Apple ID/iCloud state, and phone delivery.
