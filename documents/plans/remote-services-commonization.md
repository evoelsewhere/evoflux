# Commonization plan: remote services and adapter providers

Status: proposed

## Goal

Create one provider-neutral remote service boundary before adding more iMessage
behavior. Telegram and iMessage should be implementations of the same lifecycle,
credential, pairing, inbound, outbound, streaming, and status contracts. Adding a
future chatbot must register a provider instead of adding another branch to
`RemoteRuntime`.

## Current evidence and problems

- `app/remote/contracts.py` already defines `RemoteAdapter`, but runtime still
  constructs iMessage through a special `if connection.adapter == "imessage"`
  branch in `app/remote/runtime.py`.
- `IMessageRemoteAdapter` and `IMessageChannel` duplicate lifecycle and pairing
  concerns rather than implementing a registry-owned adapter contract.
- Provider names and strategy names are free-form strings (`imsg`,
  `bluebubbles`, `private_draft`).
- `RemoteConnectionService` still calls the Telegram-shaped `validate_token`
  API and uses `token` as the cross-provider credential field.
- iMessage adapter watermark callbacks are placeholders and are not connected
  to `RemoteConnection.inbound_watermark_at`.
- `app/remote/edit_budget.py`, `app/remote/formatting.py`, and
  `app/remote/outbound.py` already provide shared budget, card, redaction, and
  projection behavior, but new iMessage modules partially duplicate those
  responsibilities.

## Target architecture

```text
RemoteRuntime
  └── RemoteAdapterRegistry
        ├── TelegramAdapterFactory
        └── IMessageAdapterFactory
              ├── IMsgRpcProvider
              └── BlueBubblesProvider

RemoteConnectionService
  └── RemoteCredentialValidator

RemoteProjection
  └── RemoteAdapter (send/edit/callback/typing/status)
```

## Design decisions

### 1. Typed provider identity

Add a `RemoteProviderKind(StrEnum)` for provider identity. The connection
stores a nullable provider for legacy Telegram rows and defaults iMessage to
`IMSG`. Unknown provider values are rejected at API/service boundaries.

### 2. Registry-owned adapter creation

Add a registry/factory interface:

```python
class RemoteAdapterRegistry(Protocol):
    def factory_for(self, adapter: RemoteAdapterKind) -> RemoteAdapterFactory: ...
```

`RemoteRuntime` asks the registry for an adapter. It must not inspect adapter
strings, import provider implementations dynamically, or call optional methods
through `hasattr`.

### 3. One common lifecycle contract

Extend the common adapter contract with explicit pairing/configuration before
start, rather than starting an unpaired adapter and restarting it later:

```python
async def start(self, *, pairing: RemotePrincipal | None) -> None: ...
```

If changing the existing protocol is too disruptive, introduce a second
versioned protocol and adapt Telegram atomically. Do not preserve a permanent
runtime branch.

### 4. Generic credential contract

Replace the service's provider-neutral `token` concept with:

```python
RemoteCredentialInput(
    adapter=RemoteAdapterKind,
    provider=RemoteProviderKind,
    secret: str,
    endpoint_url: str | None,
)
```

Keep `token` as a deprecated Telegram API alias. Each provider validator owns
reachability/authentication checks and returns `ValidatedRemoteIdentity`; vault
write-before-DB-commit remains in the shared service.

### 5. Durable watermark ownership

Move watermark load/save into the connection service/repository boundary. The
poller accepts a repository-backed cursor object, never no-op callbacks. Cursor
advance must occur after normalized action admission and must be idempotent by
`connection_id + source_key`.

### 6. Reuse shared outbound primitives

- Use `app/remote/edit_budget.py` for live status cadence; add a generic
  `new_card` decision there instead of maintaining `IMessageLiveBudget`.
- Use `app/remote/formatting.py` for shared card content and add an adapter
  renderer only for iMessage's numbered/tapback projection.
- Use the redaction call already owned by `app/remote/outbound.py`; iMessage
  must not create a second independent redaction boundary.
- Make streaming strategy a typed capability returned by the adapter, not a
  free-form provider string.

## Execution phases

### Phase 1 — contract and registry

- Add typed provider/capability enums and generic credential input.
- Extend tests for Telegram compatibility and unknown-provider rejection.
- Add registry implementation and inject it into `RemoteRuntime`.
- Remove the direct iMessage branch from runtime.

### Phase 2 — credential and persistence

- Add provider validators for `imsg` and BlueBubbles.
- Preserve vault-before-commit and safe cleanup on failure.
- Persist provider and watermark through repository/service methods.
- Add migration upgrade/downgrade and restart/replay tests.

### Phase 3 — adapter lifecycle

- Make Telegram and iMessage implement the same pairing-aware lifecycle.
- Route inbound normalized actions through the existing remote authorization
  service.
- Route outbound messages, cards, callbacks, typing, and status through the
  common `RemoteAdapter` contract.

### Phase 4 — shared outbound behavior

- Move block chunking/strategy selection into shared remote streaming code.
- Reuse `EditBudget`, formatting, and redaction.
- Add iMessage renderer for numbered/tapback actions only.
- Add cross-adapter tests proving Telegram output remains unchanged.

### Phase 5 — product integration and E2E

- Update API schemas/client/UI for typed adapter/provider choices.
- Add provider validation and safe status/capability display.
- Run E2E with a fake provider in CI.
- Run real-device smoke test using `imsg` on macOS; keep BlueBubbles fallback
  as a separate provider scenario.

## Acceptance criteria

- Adding a new provider requires registry/validator/provider implementation,
  not a new `if adapter == ...` in runtime.
- Telegram focused tests remain green with no response-shape regression.
- No provider secret appears in rows, logs, API responses, or exception text.
- Pairing is supplied before provider polling begins.
- Restart resumes from the persisted watermark without replaying admitted
  inbound actions.
- All outbound strategies share the existing redaction and budget boundaries.
- A fake-provider E2E test covers configure → start → inbound action → agent
  handler → outbound response.
- `imsg` real-device smoke test is documented with macOS host prerequisites.

## Verification commands

```bash
uv run ruff check app/ tests/
uv run ruff format --check app/ tests/
uv run ty check app/
uv run pytest --no-cov -q
cd web && bun run lint && bun run typecheck && bun run build
```

## Non-goals

- No general third-party plugin SDK in this phase.
- No media transfer before text/card/callback semantics are stable.
- No replacement of existing Telegram API behavior.
- No silent provider fallback after a configured provider fails; fallback is an
  explicit provider selection or an explicitly documented policy.
