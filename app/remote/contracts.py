"""Provider-neutral value types and protocols for the remote-access seam.

Every value here is connection-aware (AC-4): pairings, credential keys,
inbound source keys, callback tokens, queue items, and runtime status all
carry a ``connection_id`` so a later multi-connection release does not need
to rekey anything. Nothing in this module imports an adapter-specific
(Telegram) payload type — that translation happens only inside
``app/remote/telegram/`` and never escapes it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID


class RemoteAdapterKind(StrEnum):
    """Bounded set of supported remote transports. Telegram is the only one
    shipped in v1; the enum exists so a later adapter needs no schema
    migration, only a new member."""

    TELEGRAM = "telegram"


class RemoteConnectionState(StrEnum):
    """Runtime lifecycle of one connection's adapter, per the Observability
    contract. Distinct from :class:`RemoteErrorClass`, which names the last
    *safe* error independently of the current state."""

    DISABLED = "disabled"
    STARTING = "starting"
    PAIRING = "pairing"
    POLLING = "polling"
    BACKOFF = "backoff"
    RATE_LIMITED = "rate_limited"
    USED_ELSEWHERE = "used_elsewhere"
    INVALID_TOKEN = "invalid_token"
    PHONE_UNREACHABLE = "phone_unreachable"
    CREDENTIAL_MISSING = "credential_missing"
    ERROR = "error"


class RemoteErrorClass(StrEnum):
    """Safe, bounded classification of the last adapter error. Never a raw
    provider error string — those can carry tokens or update payloads."""

    NONE = "none"
    INVALID_TOKEN = "invalid_token"
    USED_ELSEWHERE = "used_elsewhere"
    RATE_LIMITED = "rate_limited"
    TRANSPORT = "transport"
    PHONE_UNREACHABLE = "phone_unreachable"
    CREDENTIAL_MISSING = "credential_missing"
    UNKNOWN = "unknown"


class RemoteInboundActionKind(StrEnum):
    """What kind of update produced a :class:`RemoteInboundAction`."""

    TEXT = "text"
    CALLBACK = "callback"
    PAIRING_START = "pairing_start"


class RemoteOutboundPriority(StrEnum):
    """Which bounded, non-blocking queue an outbound message belongs to.

    ``HIGH`` carries gates and terminal completion notices; losing one is a
    delivery failure the status surface must report. ``INFORMATIONAL``
    carries lifecycle/admission chatter where the oldest item is dropped
    under pressure instead of blocking the producing turn.
    """

    HIGH = "high"
    INFORMATIONAL = "informational"


@dataclass(frozen=True)
class ValidatedRemoteIdentity:
    """The immutable bot identity returned by a successful ``getMe``-style
    validation, before any persistence happens."""

    adapter: RemoteAdapterKind
    principal_id: str
    username: str


class RemoteAdapterValidationError(Exception):
    """Raised by :meth:`RemoteAdapterFactory.validate_token` when the token
    does not resolve to a usable bot identity. Never carries the token."""


class RemoteAdapterFactory(Protocol):
    """Validates a credential against the adapter's identity endpoint.

    Kept as a narrow protocol so ``app/remote`` service-level code (and its
    tests) never import or call a real Telegram client — a later task
    supplies the concrete implementation.
    """

    async def validate_token(
        self, adapter: RemoteAdapterKind, token: str
    ) -> ValidatedRemoteIdentity: ...


@dataclass(frozen=True)
class RemotePrincipal:
    """One paired account. ``principal_id`` authorizes actions;
    ``destination_id`` addresses replies. They are stored and compared
    separately even though a given adapter may report matching values for a
    private chat (spec: "Connect the phone")."""

    connection_id: UUID
    principal_id: str
    destination_id: str
    #: Untrusted, adapter-reported decoration (display name/username). Never
    #: used for authorization.
    display: str = ""


@dataclass(frozen=True)
class RemoteInboundAction:
    """One normalized inbound update, already classified by the adapter.

    ``source_key`` is the inbound idempotency key (adapter + connection +
    provider update ID, AC-16) so redelivery within a process or a replay
    after a crash between admission and offset acknowledgement produces at
    most one persisted message.
    """

    connection_id: UUID
    kind: RemoteInboundActionKind
    principal: RemotePrincipal
    source_key: str
    text: str | None = None
    callback_token: str | None = None
    pairing_token: str | None = None


@dataclass(frozen=True)
class RemoteButton:
    """One inline button. ``token`` is an opaque, connection-owned,
    principal-bound capability reference — never a raw session ID, database
    ID, path, command, plan, or credential (AC-25)."""

    text: str
    token: str


@dataclass(frozen=True)
class RemoteOutboundMessage:
    """One outbound message bound for a paired destination.

    Plain text only — no parse mode, so model-authored text cannot
    manufacture links, mentions, or formatting (AC-24). ``correlation_id``
    lets the owning turn's lifecycle message be found again for editing
    instead of appending progress (AC-22).
    """

    connection_id: UUID
    destination_id: str
    text: str
    buttons: tuple[RemoteButton, ...] = field(default_factory=tuple)
    correlation_id: str | None = None
    priority: RemoteOutboundPriority = RemoteOutboundPriority.INFORMATIONAL


@dataclass(frozen=True)
class RemoteAdapterStatus:
    """Safe, diagnosable runtime status for one connection (AC-34).

    Never includes raw provider responses, credentials, or tokens.
    """

    connection_id: UUID
    state: RemoteConnectionState
    last_error_class: RemoteErrorClass = RemoteErrorClass.NONE
    last_successful_poll_at: datetime | None = None
    paired: bool = False
    phone_reachable: bool | None = None
    informational_drop_count: int = 0
    high_priority_drop_count: int = 0


class RemoteAdapter(Protocol):
    """Lifecycle and delivery surface an adapter (e.g. Telegram) implements.

    An adapter never decides EvoFlux authorization — it only starts/stops
    polling, sends/edits messages, and acknowledges callbacks. The owning
    ``RemoteService`` (a later task) is the sole authority for pairing,
    principal checks, and gate resolution.
    """

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def send(self, message: RemoteOutboundMessage) -> None: ...

    async def edit(self, message: RemoteOutboundMessage) -> None: ...

    async def answer_callback(self, callback_token: str) -> None: ...

    def status(self) -> RemoteAdapterStatus: ...


__all__ = [
    "RemoteAdapter",
    "RemoteAdapterFactory",
    "RemoteAdapterKind",
    "RemoteAdapterStatus",
    "RemoteAdapterValidationError",
    "RemoteButton",
    "RemoteConnectionState",
    "RemoteErrorClass",
    "RemoteInboundAction",
    "RemoteInboundActionKind",
    "RemoteOutboundMessage",
    "RemoteOutboundPriority",
    "RemotePrincipal",
    "ValidatedRemoteIdentity",
]
