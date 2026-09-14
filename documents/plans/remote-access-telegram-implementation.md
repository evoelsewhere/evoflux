# Remote Access over Telegram Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one-tap, outbound-only phone access to a running EvoFlux installation through one user-owned Telegram bot.

**Architecture:** A connection-aware `app/remote/` core owns authorization, lifecycle, routing, projection, and ephemeral capabilities; a Telegram adapter owns only Bot API translation and polling. Two database tables hold non-secret connection/pairing metadata, while a new, independent OS-vault abstraction stores tokens by connection ID. Phone text enters the existing persisted interactive path and normalized stream events leave through an explicit redaction boundary.

**Tech Stack:** Python 3.12, FastAPI, SQLModel/Alembic, asyncio, httpx, keyring, Pydantic v2, pytest; React 19, TypeScript, TanStack Query, existing Settings primitives, Bun/Vitest.

**Spec:** [`remote-channel-telegram.md`](remote-channel-telegram.md)

## Global Constraints

- Telegram is the only v1 adapter; public storage and service contracts remain connection-aware.
- One configured connection and one paired Telegram account are allowed per installation in v1.
- Each installation uses a user-supplied personal bot token; there is no shared bot or relay.
- No inbound listener, tunnel, public URL, LAN mode, or loopback self-call is introduced.
- Tokens live only in the OS credential vault; vault failure leaves no partial configuration and has no `.env` fallback.
- Private chats only; principal ID authorizes and destination ID addresses replies.
- Messages received while EvoFlux is stopped are discarded at the next startup.
- Remote permission replies are limited to `once` and `reject`; remote access cannot widen durable policy or configuration.
- All outbound user/agent text uses explicit remote-channel redaction, defaults to `redact`, and is sent without Telegram parse mode.
- Stream observers are synchronous, bounded, and non-blocking; no network or database work runs under stream locks.
- **`app/conductor/client.py` and `app/conductor/service.py` are never modified.** Conductor is relied on externally by `evo-conductor`, including the exact public constructor signature of its existing credential wrapper; the new OS-vault abstraction (`app/core/credential_store.py`) is standalone code used only by `app/remote/`, not a refactor Conductor is migrated onto.
- Every task cites its ACs, adds focused evidence first, and leaves the application usable at its checkpoint.
- Commit all resulting changes in the repository, including unrelated pre-existing modifications already in the working tree, as a single commit once implementation is verified.

---

## File and interface map

New backend units:

- `app/core/credential_store.py` — keyed OS-vault protocol and implementation, standalone and used only by `app/remote/` (Conductor keeps its own separate implementation, untouched).
- `app/remote/contracts.py` — provider-neutral dataclasses/enums/protocols.
- `app/remote/connection_service.py` — durable connection CRUD, v1 cardinality, vault coordination.
- `app/remote/pairing.py` — deep-link capability issuance and principal binding.
- `app/remote/inbound.py` — authorization, commands, current-task selection, persisted chat admission.
- `app/remote/outbound.py` — allowlisted event projection, redaction, splitting, delivery queues.
- `app/remote/gates.py` — opaque callbacks and existing gate-service resolution.
- `app/remote/actions.py` — optional Workflow/Coding/EASD/Scheduler menus.
- `app/remote/runtime.py` — process lifecycle and per-connection adapter ownership.
- `app/remote/telegram/models.py` — bounded Pydantic payloads with `extra="ignore"`.
- `app/remote/telegram/client.py` — raw Bot API HTTP calls and error classification.
- `app/remote/telegram/adapter.py` — polling loop and normalized action translation.
- `app/api/schemas/remote.py`, `app/api/routes/remote.py` — authenticated desktop API.
- `tests/core/test_credential_store.py`, `tests/remote/`, `tests/api/routes/test_remote.py` — focused backend evidence.

New frontend units:

- `web/src/api/client/remote.ts` — typed remote Settings/connection API.
- `web/src/components/settings/RemoteAccessSettings.tsx` — setup, QR/link, pairing, status, removal.
- `web/src/__tests__/components/settings/RemoteAccessSettings.test.tsx` — primary UI states and secret handling.

Changed shared units:

- `app/models/__init__.py`, `app/migrations/env.py`, `app/core/schema_version.py` — model/migration registration.
- `app/core/runtime_settings.py`, `app/api/schemas/settings.py`, `app/api/routes/settings.py` — remote outbound policy.
- `app/services/memory_stream_store.py` — synchronous global observer registry.
- `app/services/interactive_message_service.py` — channel-neutral source metadata lookup.
- `app/agent/outbound_redaction.py` — add `remote` to `OutboundChannel`.
- `app/api/app.py` — lazy optional remote startup and structured shutdown.
- Settings navigation/client exports, three Help locales, and current docs named by the spec.

---

### Task 1: Keyed OS-vault abstraction and connection-aware schema

**ACs:** AC-3, AC-4, AC-5, AC-6, AC-17

**Files:**

- Create: `app/core/credential_store.py` (standalone; Conductor is not touched or migrated onto it)
- Replace unfinished content: `app/models/remote.py`
- Replace unfinished content: `app/migrations/versions/00000064_create_remote_pairings.py`
- Modify: `app/models/__init__.py`
- Modify: `app/migrations/env.py`
- Keep/verify: `app/core/schema_version.py`
- Create: `tests/core/test_credential_store.py`
- Create: `tests/remote/test_models.py`
- Modify: `tests/core/test_alembic_migrations.py`

**Interfaces:**

- Produces `CredentialStoreProtocol.load/save/delete`, keyed by service/account at construction.
- Produces `RemoteConnection` and `RemotePairing`; later tasks import them from `app.models`.
- No network or runtime service is introduced in this task.

- [ ] **Step 1: Write vault tests that prove key isolation and secret-safe errors**

```python
def test_keyed_store_uses_supplied_service_and_account(fake_keyring):
    store = CredentialStore(service="EvoFlux Remote", account="connection:abc")
    store.save("secret")
    assert fake_keyring.saved == ("EvoFlux Remote", "connection:abc", "secret")

def test_vault_error_does_not_echo_secret(fake_keyring):
    fake_keyring.set_password.side_effect = RuntimeError("boom")
    with pytest.raises(CredentialStoreError) as exc:
        CredentialStore(service="EvoFlux Remote", account="connection:abc").save("secret")
    assert "secret" not in str(exc.value)
```

- [ ] **Step 2: Run the vault tests and confirm they fail before the abstraction exists**

```powershell
uv run pytest --no-cov -q tests/core/test_credential_store.py
```

Expected: collection/import failure for `app.core.credential_store`.

- [ ] **Step 3: Implement the generic vault as new, standalone infrastructure**

```python
class CredentialStoreProtocol(Protocol):
    def load(self) -> str | None: ...
    def save(self, credential: str) -> None: ...
    def delete(self) -> None: ...

class CredentialStore:
    def __init__(self, *, service: str, account: str) -> None: ...
    def load(self) -> str | None: ...
    def save(self, credential: str) -> None: ...
    def delete(self) -> None: ...
```

Use `keyring.get_password/set_password/delete_password`, preserve missing-entry delete behavior, and wrap all other failures in `CredentialStoreError` with fixed messages. **Do not touch Conductor.** `app/conductor/client.py` and `app/conductor/service.py` keep their own separate `CredentialStore`/`CredentialStoreError`/`CredentialStoreProtocol` definitions and parameterless constructor exactly as they are today — Conductor is relied on externally by `evo-conductor`, and this module exists purely for `app/remote/` to construct as `CredentialStore(service="EvoFlux Remote", account=f"connection:{connection_id}")`.

- [ ] **Step 4: Write model and migration tests before replacing the partial schema**

```python
def test_pairing_keeps_authorization_and_destination_separate():
    pairing = RemotePairing(
        connection_id=uuid4(), principal_id="user-1", destination_id="chat-9", label="Phone"
    )
    assert pairing.principal_id != pairing.destination_id
```

Extend migration evidence to assert head `00000064`, tables `remote_connections` and `remote_pairings`, both uniqueness constraints, connection cascade, and session `SET NULL`.

- [ ] **Step 5: Implement and register the exact models**

```python
class RemoteConnection(SQLModel, table=True):
    id: UUID
    adapter: str
    label: str
    enabled: bool
    adapter_principal_id: str
    adapter_username: str
    created_at: datetime
    updated_at: datetime

class RemotePairing(SQLModel, table=True):
    id: UUID
    connection_id: UUID
    principal_id: str
    destination_id: str
    label: str
    display: str
    active_session_id: UUID | None
    created_at: datetime
    last_seen_at: datetime
```

The migration creates both tables in dependency order. Do not retain the unfinished `channel`, `account_id`, or `revoked_at` columns from the earlier draft.

- [ ] **Step 6: Run focused schema tests and confirm Conductor is untouched**

```powershell
uv run pytest --no-cov -q tests/core/test_credential_store.py tests/remote/test_models.py tests/core/test_alembic_migrations.py tests/conductor/test_client_service.py
uv run ruff check app/core/credential_store.py app/models/remote.py tests/core/test_credential_store.py tests/remote/test_models.py
uv run ty check app/
git diff --stat -- app/conductor
```

Expected: all tests pass; the last command prints no output, proving `app/conductor/` has no diff.

---

### Task 2: Remote settings, core contracts, and durable connection service

**ACs:** AC-3, AC-4, AC-5, AC-6, AC-23, AC-32, AC-34

**Files:**

- Create: `app/remote/__init__.py`
- Create: `app/remote/contracts.py`
- Create: `app/remote/connection_service.py`
- Modify: `app/core/runtime_settings.py`
- Modify: `app/api/schemas/settings.py`
- Modify: `app/api/routes/settings.py`
- Modify: `app/agent/outbound_redaction.py`
- Create: `tests/remote/test_connection_service.py`
- Modify: `tests/api/test_settings_routes.py`
- Modify: `tests/agent/test_outbound_redaction.py`

**Interfaces:**

- Produces `RemoteSettings(outbound_data_policy="redact", outbound_pii_policy="standard")`.
- Produces `RemoteConnectionService.create/update_token/set_enabled/remove/list/get`.
- Consumes a `RemoteAdapterFactory.validate_token(adapter, token)` protocol so tests never call Telegram.
- Produces `OutboundChannel` value `remote` for Tasks 6–11.

- [ ] **Step 1: Write failing settings and connection-transaction tests**

Cover default redaction, settings round trip, one-connection `409` domain error, token validation before vault save, vault failure rollback, different-bot replacement invalidating pairing, same-bot replacement retaining it, and removal deleting the vault value.

```python
async def test_create_rolls_back_when_vault_save_fails(session, service):
    service.credentials.save.side_effect = CredentialStoreError("vault unavailable")
    with pytest.raises(RemoteCredentialError):
        await service.create_connection(session, token="bot-token", label="My phone")
    assert (await session.exec(select(RemoteConnection))).all() == []
```

- [ ] **Step 2: Run the focused failures**

```powershell
uv run pytest --no-cov -q tests/remote/test_connection_service.py tests/api/test_settings_routes.py -k "remote or outbound"
```

- [ ] **Step 3: Define provider-neutral contracts**

```python
class RemoteAdapterKind(StrEnum):
    TELEGRAM = "telegram"

@dataclass(frozen=True)
class ValidatedRemoteIdentity:
    adapter: RemoteAdapterKind
    principal_id: str
    username: str

class RemoteAdapterFactory(Protocol):
    async def validate_token(self, adapter: RemoteAdapterKind, token: str) -> ValidatedRemoteIdentity: ...
```

Also define bounded enums for lifecycle state, safe error class, inbound action kind, outbound priority, and immutable principal/message/button values. External payload types do not escape adapter modules.

- [ ] **Step 4: Implement settings and connection coordination**

Add `RemoteSettings` to `RuntimeSettings`; add exact GET/PUT schemas/routes at `/api/settings/remote`. Construct vault accounts as `connection:<uuid>`. Do not persist the token or a fingerprint. Keep DB transactions free of vault and network calls by validating first, storing the vault value, then committing metadata with compensating vault deletion on commit failure.

- [ ] **Step 5: Run focused checks**

```powershell
uv run pytest --no-cov -q tests/remote/test_connection_service.py tests/api/test_settings_routes.py tests/agent/test_outbound_redaction.py
uv run ruff check app/remote app/core/runtime_settings.py app/api/routes/settings.py app/api/schemas/settings.py app/agent/outbound_redaction.py tests/remote
```

---

### Task 3: Telegram Bot API client and adapter lifecycle

**ACs:** AC-1, AC-6, AC-11, AC-12, AC-13, AC-24, AC-34

**Files:**

- Create: `app/remote/telegram/__init__.py`
- Create: `app/remote/telegram/models.py`
- Create: `app/remote/telegram/client.py`
- Create: `app/remote/telegram/adapter.py`
- Create: `tests/remote/telegram/test_client.py`
- Create: `tests/remote/telegram/test_adapter.py`

**Interfaces:**

- Produces `TelegramClient.get_me/delete_webhook/get_updates/send_text/edit_text/answer_callback/set_commands`.
- Produces `TelegramAdapter.start/stop` and normalized inbound callback delivery.
- Consumes a token and callbacks; owns `httpx.AsyncClient`, offsets, polling, and Bot API error classification.

- [ ] **Step 1: Write client translation and safe-error tests**

Mock `httpx.MockTransport` for successful `getMe`, `getUpdates`, send/edit/ack, invalid-token `401`, conflict `409`, `429` with `parameters.retry_after`, chat `403`, malformed response, and transport failure. Assert exception strings never contain the request URL because it embeds the token.

- [ ] **Step 2: Run the client tests and verify failure**

```powershell
uv run pytest --no-cov -q tests/remote/telegram/test_client.py
```

- [ ] **Step 3: Implement bounded external payloads and the client**

```python
class TelegramResponse(BaseModel, Generic[T]):
    model_config = ConfigDict(extra="ignore")
    ok: bool
    result: T | None = None
    error_code: int | None = None
    description: str | None = None
    parameters: TelegramResponseParameters | None = None
```

Build requests without logging full URLs, omit `parse_mode`, enforce the 1–64 byte callback payload contract before send, and translate failures to safe internal error classes.

- [ ] **Step 4: Write poll lifecycle tests with injected clock/jitter**

Prove webhook deletion uses `drop_pending_updates=True`; only `message` and `callback_query` are requested; updates are ordered; accepted update offsets advance; conflict/rate-limit/transport backoff follows policy; stop interrupts long poll/backoff promptly; duplicate start/stop is safe.

- [ ] **Step 5: Implement the adapter state machine**

```python
class TelegramAdapter:
    async def start(self, on_action: Callable[[RemoteInboundAction], Awaitable[Admission]]) -> None: ...
    async def stop(self) -> None: ...
    def status(self) -> RemoteAdapterStatus: ...
```

Use an `asyncio.Event` for interruptible waits and a single owner task for polling. Never retry `invalid_token` until token replacement or explicit restart.

- [ ] **Step 6: Run adapter checks**

```powershell
uv run pytest --no-cov -q tests/remote/telegram
uv run ruff check app/remote/telegram tests/remote/telegram
uv run ty check app/
```

---

### Task 4: One-tap pairing and principal authorization

**ACs:** AC-7, AC-8, AC-9, AC-10

**Files:**

- Create: `app/remote/pairing.py`
- Create: `tests/remote/test_pairing.py`

**Interfaces:**

- Produces `PairingService.issue_link/consume/unpair/authorize`.
- Consumes connection metadata and normalized `RemotePrincipal`.
- Issues opaque base64url tokens and returns `PairingLink(url, qr_payload, expires_at)`.

- [ ] **Step 1: Write pairing capability tests**

```python
def test_issued_token_is_url_safe_bounded_and_single_use(pairing_service):
    link = pairing_service.issue_link(connection)
    token = parse_qs(urlparse(link.url).query)["start"][0]
    assert re.fullmatch(r"[A-Za-z0-9_-]{22,64}", token)
    assert pairing_service.consume(token, principal)
    assert not pairing_service.consume(token, principal)
```

Add expiry, private-chat, bot sender, wrong connection, one-pairing limit, separate destination, per-principal/global rate limit, silence decision, and immediate token invalidation cases.

- [ ] **Step 2: Run and confirm focused failures**

```powershell
uv run pytest --no-cov -q tests/remote/test_pairing.py
```

- [ ] **Step 3: Implement in-memory pairing tokens and durable binding**

Use `secrets.token_urlsafe(16)` or stronger, a ten-minute monotonic expiry, constant-time token comparison where lookup does not already provide equivalent protection, and fixed refusal results that expose no connection state. Persist principal/destination only after every check passes.

- [ ] **Step 4: Run pairing checks**

```powershell
uv run pytest --no-cov -q tests/remote/test_pairing.py tests/remote/test_connection_service.py
uv run ruff check app/remote/pairing.py tests/remote/test_pairing.py
```

---

### Task 5: Desktop API and lazy runtime lifecycle

**ACs:** AC-1, AC-2, AC-3, AC-5, AC-7, AC-10, AC-12, AC-13, AC-33, AC-34

**Progress:** Complete.

**Files:**

- Create: `app/api/schemas/remote.py`
- Create: `app/api/routes/remote.py`
- Create: `app/remote/runtime.py`
- Modify: `app/api/app.py`
- Create: `tests/api/routes/test_remote.py`
- Create: `tests/remote/test_runtime.py`

**Interfaces:**

- Produces the authenticated routes listed in the specification.
- Produces singleton `remote_runtime.start/stop/reconcile_connection/status`.
- Consumes connection, pairing, vault, and adapter services from Tasks 1–4.

- [x] **Step 1: Write route/auth/secret-shape tests**

Cover zero-or-one list, create, patch enable/label, token replacement, remove, pairing-link issue, pairing read/revoke, status, second-connection `409`, invalid UUID, missing resource, desktop auth, and OpenAPI absence of returned token fields.

- [x] **Step 2: Write disabled-lifespan and shutdown tests**

```python
async def test_disabled_start_does_not_import_telegram(monkeypatch):
    sys.modules.pop("app.remote.telegram.adapter", None)
    await remote_runtime.start()
    assert "app.remote.telegram.adapter" not in sys.modules
```

Prove optional startup failure does not fail health readiness and shutdown stops the remote runtime after pending optional startup completes.

- [x] **Step 3: Implement thin routes and lazy runtime construction**

Routes validate HTTP shape and call services; they do not call Telegram directly. Import `app.remote.telegram.adapter` inside the enabled connection factory only. Add remote startup beside other optional services and explicit shutdown beside Conductor/Scheduler cleanup.

- [x] **Step 4: Run route and lifecycle evidence**

```powershell
$env:EVOFLUX_DESKTOP_TOKEN=$null
uv run pytest --no-cov -q tests/api/routes/test_remote.py tests/remote/test_runtime.py tests/api/test_app_lifespan.py
uv run ruff check app/api/routes/remote.py app/api/schemas/remote.py app/remote/runtime.py app/api/app.py tests/api/routes/test_remote.py tests/remote/test_runtime.py
```

---

### Task 6: Natural-language ingress and current-task behavior

**ACs:** AC-14, AC-15, AC-16, AC-17, AC-18, AC-29

**Progress:** Complete.

**Files:**

- Create: `app/remote/inbound.py`
- Modify: `app/services/interactive_message_service.py`
- Modify: `app/services/chat_service.py` (channel-source delivery compatibility only)
- Create: `tests/remote/test_inbound.py`
- Modify: `tests/services/test_interactive_message_service.py`
- Modify or create: `tests/services/test_chat_service.py`

**Interfaces:**

- Produces `RemoteInboundService.handle_text/new_task/continue_task/stop_current`.
- Consumes `PairingService.authorize`, `create_chat_session`, `resolve_team_for_session`, `submit_persisted_interactive_message`, and existing interrupt behavior.
- Generalizes persisted source metadata from `webbridge_source` to channel-neutral `interactive_source` while reading legacy metadata for compatibility, including the shared delivered-state helper used by immediate and queued delivery.

- [x] **Step 1: Write channel-neutral idempotency compatibility tests**

Persist one `interactive_source` message and prove lookup/dedup; retain a regression that legacy `webbridge_source` rows still deduplicate WebBridge retries.

- [x] **Step 2: Write inbound behavior tests**

Cover first plain text creating a top-level Work session with provenance tags; subsequent text using the current session; queued/pending/accepted status; duplicate update effect-once; deleted current session recovery; **New task** clearing without deletion; **Continue this task** selecting only top-level Work/Coding; refusal of team-member, Side Chat, and internal sessions; `/stop` interrupting only the current live turn.

- [x] **Step 3: Run failures**

```powershell
uv run pytest --no-cov -q tests/services/test_interactive_message_service.py tests/services/test_chat_service.py tests/remote/test_inbound.py
```

- [x] **Step 4: Implement the channel-neutral source record**

```python
message_extra = {
    "interactive_source": {
        "channel": "remote",
        "adapter": "telegram",
        "connection_id": str(action.connection_id),
        "key": action.source_key,
        "request_hash": request_hash,
        "state": "persisted",
    }
}
```

Do not make HTTP self-calls. Reuse existing team/session defaults and message locking.

- [x] **Step 5: Run ingress evidence**

```powershell
uv run pytest --no-cov -q tests/services/test_interactive_message_service.py tests/services/test_chat_service.py tests/remote/test_inbound.py
uv run ruff check app/remote/inbound.py app/services/interactive_message_service.py app/services/chat_service.py tests/remote/test_inbound.py
```

---

### Task 7: Global stream observation and safe completion delivery

**ACs:** AC-18, AC-19, AC-20, AC-21, AC-22, AC-23, AC-24, AC-34

**Files:**

- Modify: `app/services/memory_stream_store.py`
- Create: `app/remote/outbound.py`
- Create: `tests/services/test_memory_stream_observers.py`
- Create: `tests/remote/test_outbound.py`

**Interfaces:**

- Produces `register_observer(callback) -> Callable[[], None]`.
- Produces `RemoteProjection.observe`, delivery workers, redaction, completion lookup, Unicode-safe plain-text splitting, and one lifecycle-message correlation per phone-admitted turn.
- Consumes normalized `StreamEnvelope`, database session factory, and adapter send/edit methods.

- [ ] **Step 1: Write observer isolation tests**

Prove registration/unregistration, ordering, observer exception isolation, no coroutine acceptance, no await under the stream lock, and unchanged subscriber behavior with no observer.

- [ ] **Step 2: Implement the minimal synchronous observer registry**

```python
Observer = Callable[[str, StreamEnvelope], None]

def register_observer(observer: Observer) -> Callable[[], None]: ...
```

Invoke observers after state mutation and before leaving the existing lock only if the callback performs a pure `put_nowait`; alternatively snapshot observers under lock and invoke immediately after releasing it. Tests must establish the chosen ordering and non-blocking behavior.

- [ ] **Step 3: Write exhaustive projection tests**

Drive every known event family plus an unknown type. Assert only gates/replies, terminal errors, `done`, and relevant desktop notifications enqueue. Assert child/Side Chat/internal sessions are excluded, duplicate completion sources collapse, finalized assistant text is queried after `done`, missing text uses a stub, and desktop tasks emit no activity chatter.

- [ ] **Step 4: Write redaction and rendering tests**

Test task titles, gate fields, question options, plans, errors, and final text with planted secret/PII markers under `redact`, `block`, and `off`. Verify fixed block stubs, no parse mode, 4096-character provider bound, Unicode safety, and callback-free agent text.

- [ ] **Step 5: Implement bounded priority queues and delivery**

Use separate high-priority and informational queues. `observe` may only normalize bounded scalar fields and call `put_nowait`. Delivery workers perform DB lookup, explicit `protect_outbound_text(..., context=OutboundContext(channel="remote", ...))`, splitting, and Telegram sends. High-priority overflow increments a critical counter and leaves gates unresolved.

- [ ] **Step 6: Run observer/outbound evidence**

```powershell
uv run pytest --no-cov -q tests/services/test_memory_stream_observers.py tests/remote/test_outbound.py
uv run ruff check app/services/memory_stream_store.py app/remote/outbound.py tests/services/test_memory_stream_observers.py tests/remote/test_outbound.py
uv run ty check app/
```

---

### Task 8: Gate cards, callback capabilities, and race handling

**ACs:** AC-10, AC-23, AC-25, AC-26, AC-27, AC-28

**Files:**

- Create: `app/remote/gates.py`
- Create: `tests/remote/test_gates.py`

**Interfaces:**

- Produces `RemoteGateBridge.on_gate/on_reply/handle_callback`.
- Consumes existing permission/question/plan lookup and reply services directly.
- Consumes adapter `answer_callback` before any resolution and `edit_text` after it.

- [ ] **Step 1: Write all gate rendering tests**

Cover permission `once/reject` only, multi-question validated answers, plan approve/reject, every callback under 64 bytes, redacted fields, and fixed provenance headings.

- [ ] **Step 2: Write callback ordering and ownership tests**

```python
async def test_callback_is_acknowledged_before_resolution(bridge, adapter):
    await bridge.handle_callback(action)
    assert adapter.calls.index("answer_callback") < adapter.calls.index("resolve_gate")
```

Add wrong principal, destination, connection, action, expired token, restart-empty map, already-resolved gate, duplicate tap, desktop-wins race, phone-wins race, and reply-event button removal.

- [ ] **Step 3: Implement opaque capability records and service adapters**

Use random compact tokens mapped to records containing connection/principal/destination/session/request IDs, allowed action set, Telegram message reference, and expiry. Do not serialize internal IDs into callback data. Resolve via the active `PermissionService`, `AskUserService`, or `PlanApprovalService` registry.

- [ ] **Step 4: Run gate evidence**

```powershell
uv run pytest --no-cov -q tests/remote/test_gates.py tests/agent/test_permission.py tests/agent/test_ask_user_validation.py tests/agent/test_ask_user_sse.py tests/agent/test_plan_mode.py
uv run ruff check app/remote/gates.py tests/remote/test_gates.py
```

---

### Task 9: Secondary actions without widening owner contracts

**ACs:** AC-18, AC-25, AC-30, AC-31, AC-32

**Files:**

- Create: `app/remote/actions.py`
- Create: `tests/remote/test_actions.py`

**Interfaces:**

- Produces `/start`, `/help`, `/status`, `/new`, `/stop`, `/unpair`, and **More actions** dispatch.
- Consumes existing read/start/fire services for sessions, Coding projects, Workflows, Evo Agent Specs, and Scheduler.
- Reuses the opaque capability store from Task 8 for list choices.

- [ ] **Step 1: Write command allowlist and refusal tests**

Assert no command accepts credentials, repository paths, settings changes, permission mode, workflow approval, or arbitrary identifiers. Unknown slash commands return bounded help only to the paired principal.

- [ ] **Step 2: Write one happy and one denied path per owner**

Prove approved Workflow starts and changed hash refuses; authorized Coding project creates a task and unknown/unowned project refuses; eligible EASD action starts and blocked action preserves structured refusal; manually-triggerable schedule fires and unavailable task refuses.

- [ ] **Step 3: Implement small owner-specific adapters**

Each menu loader returns bounded `RemoteMenuItem(token, label, description)` and each action calls one existing service entry point. Do not copy owner validation into `actions.py`; translate owning exceptions into safe remote messages.

- [ ] **Step 4: Run action evidence**

```powershell
uv run pytest --no-cov -q tests/remote/test_actions.py tests/workflow tests/scheduler -k "remote or approval or trigger"
uv run ruff check app/remote/actions.py tests/remote/test_actions.py
```

---

### Task 10: Settings UI, one-tap connection, and status

**ACs:** AC-3, AC-5, AC-7, AC-10, AC-12, AC-34, AC-35, AC-36

**Files:**

- Create: `web/src/api/client/remote.ts`
- Modify: `web/src/api/types.ts`
- Modify: `web/src/api/client/settings.ts`
- Create: `web/src/components/settings/RemoteAccessSettings.tsx`
- Modify: Settings navigation/layout owning files identified during implementation
- Create: `web/src/__tests__/components/settings/RemoteAccessSettings.test.tsx`
- Modify: `web/package.json` and `web/bun.lock` only if no existing QR renderer can safely render the payload

**Interfaces:**

- Produces typed hooks/client calls for connection CRUD, pairing link, pairing state, and status.
- Consumes existing Settings overlay cards, form controls, secret inputs, confirmation dialog, and query cache conventions.

- [ ] **Step 1: Write UI tests for the primary states**

Render unconfigured, validating, vault failure, configured-disabled, connecting QR/link, paired, invalid token, used elsewhere, phone unreachable, and removal confirmation. Assert the token input clears after submit and never appears in rendered status or cached GET data.

- [ ] **Step 2: Run the tests and confirm failure**

```powershell
Set-Location web
bun test src/__tests__/components/settings/RemoteAccessSettings.test.tsx
```

- [ ] **Step 3: Implement the typed client and Settings page**

The primary copy is: EvoFlux must stay running; create a personal bot; paste its token once; select **Connect phone**; scan or open Telegram. Render the QR from the returned HTTPS payload locally, never through a remote image service. Use connection-neutral labels except where identifying Telegram as the selected adapter.

- [ ] **Step 4: Verify keyboard, focus, and narrow layout behavior**

Test labels, error announcements, tab order, QR alternative link, secret-input autocomplete, destructive removal confirmation, and mobile-width wrapping. Avoid adding a new app route; Settings remains an overlay.

- [ ] **Step 5: Run frontend evidence**

```powershell
Set-Location web
bun test src/__tests__/components/settings/RemoteAccessSettings.test.tsx
bun run lint
bun run typecheck
bun run build
```

---

### Task 11: Current documentation, Help, and operator guidance

**ACs:** AC-3, AC-11, AC-12, AC-30, AC-32, AC-35, AC-36

**Files:**

- Create: `documents/features/remote-access.md`
- Modify: `documents/features/README.md`
- Modify: `documents/features/security-and-permissions.md`
- Modify: `documents/architecture/system-overview.md`
- Modify: `documents/reference/configuration.md`
- Modify: `documents/reference/http-api.md`
- Modify: `web/src/help/locales/en.ts`
- Modify: `web/src/help/locales/vi.ts`
- Modify: `web/src/help/locales/ja.ts`

**Interfaces:**

- Produces current-state documentation only after runtime behavior exists.
- Keeps this plan in `documents/plans/` as historical design rationale.

- [ ] **Step 1: Write the current feature contract from verified behavior**

Document setup, one-bot-per-computer scope, one-tap pairing, current task, automatic gates/completion, offline discard, permission limits, Telegram retention, revocation, states, source map, and focused tests. Mark the feature Optional because it needs a user-owned Telegram bot and network access.

- [ ] **Step 2: Reconcile architecture and public references**

Add the outbound remote adapter to the system topology/trust boundaries, exact `remote` settings fields, exact HTTP route family, lifecycle states, and secret masking. Link rather than duplicate long explanations.

- [ ] **Step 3: Add equivalent Help in all three locales**

Each locale must explain the same steps and warnings: EvoFlux must remain running; messages sent while stopped do not run later; bot chats leave the machine; **Allow once** is the maximum remote permission; each computer needs its own bot; revoke from Settings or `/unpair`.

- [ ] **Step 4: Validate documentation and Help consumers**

```powershell
Set-Location web
bun run lint
bun run typecheck
bun run build
Set-Location ..
rg -n "Remote access|Telegram|remote_connections|/api/remote" documents web/src/help/locales
```

Expected: current docs agree with implemented names and every local link resolves.

---

### Task 12: Cross-boundary acceptance and clean handoff

**ACs:** AC-1–AC-37

**Files:**

- Modify only files needed to fix failures caused by Tasks 1–11.
- Do not alter unrelated desktop-generated permissions or user documentation files.

**Interfaces:**

- Validates the complete path: vault → connection → one-tap pair → phone text → persisted task → gate/completion projection → callback resolution → revoke/shutdown.

- [ ] **Step 1: Add one end-to-end mocked Telegram integration test**

Use a real temporary database and fake vault/Telegram transport. Create a connection, issue/consume a pairing link, submit text, observe one persisted message, push a permission gate, resolve it by callback, persist assistant completion, observe one completion, then unpair and prove later input is refused.

- [ ] **Step 2: Run all focused remote and seam tests**

```powershell
$env:EVOFLUX_DESKTOP_TOKEN=$null
uv run pytest --no-cov -q tests/remote tests/core/test_credential_store.py tests/core/test_alembic_migrations.py tests/services/test_interactive_message_service.py tests/services/test_memory_stream_observers.py tests/api/routes/test_remote.py
```

- [ ] **Step 3: Run backend quality gates**

```powershell
uv run ruff check app/ tests/
uv run ruff format --check app/ tests/
uv run ty check app/
uv run pytest --no-cov -q
```

- [ ] **Step 4: Run frontend quality gates**

```powershell
Set-Location web
bun run lint
bun run typecheck
bun run build
Set-Location ..
```

- [ ] **Step 5: Inspect schema, privacy, and diff boundaries**

```powershell
uv run alembic heads
uv run pytest --no-cov -q tests/core/test_alembic_migrations.py
rg -n "BOT_TOKEN|api\.telegram\.org/bot|pairing_token|callback_token" app tests documents web/src
git diff --check
git status --short
```

Inspect every match so tests/examples remain synthetic and no real secret, raw update, or token-bearing URL reaches logs, diagnostics, committed fixtures, or GET responses. Confirm only the intended migration head exists and unrelated worktree changes remain untouched.

- [ ] **Step 6: Produce the AC evidence handoff, then commit everything together**

Report changed files, exact commands/results, evidence grouped by AC, any pre-existing failures, checks not run, and remaining risk. Per the user's instruction, once implementation is verified, stage and commit the full working tree — this feature's changes together with any pre-existing unrelated modifications already present — as a single commit, rather than isolating this feature into its own commit.

## Rollback

Disable the connection first to stop the poller. If code rollback is required,
remove the remote router/lifecycle hook, `app/core/credential_store.py`, and
Settings surface, unregister the stream observer, and downgrade migration
`00000064` to drop only `remote_pairings` and `remote_connections`. Conductor
is never part of this rollback since it was never modified. Existing chat
sessions and their normal messages remain intact; provenance tags on
remote-created sessions are harmless if retained or may be removed by a
bounded migration-independent cleanup.
