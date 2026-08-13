import uuid
from datetime import datetime, timezone
from uuid import UUID, uuid7  # ty: ignore[unresolved-import]

import sqlalchemy as sa
from sqlalchemy import Column, DateTime, ForeignKey, JSON
import sqlalchemy.dialects.postgresql as pg
from sqlalchemy.types import TypeDecorator
from sqlmodel import Field, SQLModel

from app.core.app_mode import normalize_app_mode


def normalize_mode(mode: str) -> str:
    """Map legacy default-team mode names to canonical ``work``.

    The default mode was previously called ``normal`` and then ``forge``.
    Older UIs, persisted rows, plugins, and external API clients may still
    send either value. Accept both at input boundaries, but store and emit
    only ``work``.
    """
    return normalize_app_mode(mode)


def _utcnow() -> datetime:
    """Return the current UTC time with microsecond precision.

    Using a Python-side default (rather than ``server_default=func.now()``)
    ensures the value is set *before* the INSERT statement is issued.  This
    guarantees microsecond-level precision in all environments including
    in-memory SQLite (which only has second-level resolution for SQL ``NOW()``),
    making timestamp-based ordering reliable in fast-running tests.
    """
    return datetime.now(timezone.utc)


class TZDateTime(TypeDecorator):
    """DateTime type that always returns timezone-aware UTC datetimes.

    SQLite stores datetimes as naive strings. This decorator re-attaches
    UTC tzinfo on read so that Pydantic serializes them with a 'Z' suffix
    and downstream consumers (web UI, API clients) get correct timezone info.

    On *write* we reject naive datetimes outright. Accepting a naive value
    silently treats whatever wall-clock the caller produced as UTC, which
    has bitten us in the scheduler (see git history: a tool parsed
    ``2026-05-10T01:12:42`` from the user's local zone and we stored it
    verbatim, mis-labelled UTC on read, off by 7 hours from intent).
    Aware values are normalised to UTC for consistent storage.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(
        self, value: datetime | None, dialect: sa.Dialect
    ) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError(
                "TZDateTime received a naive datetime; callers must attach "
                "tzinfo (use the user's IANA zone or `timezone.utc`). "
                f"Got: {value!r}"
            )
        # Normalise to UTC so on-disk values are unambiguous regardless of
        # the source zone.
        return value.astimezone(timezone.utc)

    def process_result_value(
        self, value: datetime | None, dialect: sa.Dialect
    ) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


class SessionFolder(SQLModel, table=True):
    """User-created folder grouping Work-mode chat sessions.

    Folders are a pure organisation layer over ``chat_sessions``: a session
    keeps its own history and settings, only ``folder_id`` moves. When
    ``share_context`` is set the lead of every session in the folder receives
    a bounded digest of its sibling sessions (see
    ``app.services.session_folder_service.build_folder_context_block``), which
    is what makes sessions in one folder aware of each other.
    """

    __tablename__: str = "session_folders"  # type: ignore[reportIncompatibleVariableOverride]
    __table_args__ = (sa.Index("ix_session_folders_mode_sort", "mode", "sort_order"),)

    id: UUID = Field(default_factory=uuid7, primary_key=True)
    name: str = Field(sa_column=Column(sa.String(120), nullable=False))
    # Folders are scoped per app mode so a Work folder never shows up in the
    # Coding sidebar (which groups by project/workspace instead).
    mode: str = Field(
        default="work",
        sa_column=Column(sa.String(20), nullable=False, server_default="work"),
    )
    share_context: bool = Field(
        default=True,
        sa_column=Column(sa.Boolean, nullable=False, server_default=sa.true()),
    )
    sort_order: int = Field(
        default=0,
        sa_column=Column(sa.Integer, nullable=False, server_default="0"),
    )
    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(TZDateTime(), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(TZDateTime(), nullable=False, onupdate=_utcnow),
    )


class ChatSession(SQLModel, table=True):
    __tablename__: str = "chat_sessions"  # type: ignore[reportIncompatibleVariableOverride]
    __table_args__ = (
        # Me cover ORDER BY created_at listings (list_sessions_page,
        # get_latest_top_level_session filter on parent_session_id IS NULL)
        sa.Index("ix_chat_sessions_parent_created", "parent_session_id", "created_at"),
    )

    id: UUID = Field(default_factory=uuid7, primary_key=True)
    parent_session_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            sa.Uuid(),
            ForeignKey("chat_sessions.id", ondelete="CASCADE"),
            index=True,
            nullable=True,
        ),
    )
    # Top-level sessions (team leads, scheduled tasks) have parent_session_id=NULL.
    # Team-member sessions are children of their lead via parent_session_id.
    agent_name: str | None = Field(default=None, max_length=100)
    title: str | None = Field(default=None, max_length=255)
    # Set when this session was created by the scheduler; None for normal chat.
    scheduled_task_name: str | None = Field(
        default=None,
        max_length=100,
        sa_column=Column(sa.String(100), nullable=True),
    )
    mode: str = Field(
        default="work",
        max_length=20,
        sa_column=Column(sa.String(20), nullable=False, server_default="work"),
    )
    permission_mode: str = Field(
        default="auto",
        max_length=20,
        sa_column=Column(sa.String(20), nullable=False, server_default="auto"),
    )
    workspace: str | None = Field(default=None)
    project_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            sa.Uuid(),
            ForeignKey(
                "coding_projects.id",
                ondelete="SET NULL",
                name="fk_chat_sessions_project_id",
            ),
            nullable=True,
            index=True,
        ),
    )
    # Sidebar folder this session was filed under. ON DELETE SET NULL so
    # deleting a folder only un-files its sessions, never removes them.
    folder_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            sa.Uuid(),
            ForeignKey(
                "session_folders.id",
                ondelete="SET NULL",
                name="fk_chat_sessions_folder_id",
            ),
            nullable=True,
            index=True,
        ),
    )
    model: str | None = Field(default=None, max_length=255)
    thinking_level: str | None = Field(default=None, max_length=50)
    revert: dict | None = Field(
        default=None,
        sa_column=Column(
            JSON().with_variant(pg.JSONB(), "postgresql"),
            nullable=True,
        ),
    )
    # Session tags (e.g. ["webbridge"]) — set at creation by the resolve
    # endpoint, matched by tag-SET equality (order-insensitive), and used to
    # scope the lead's tool access (a "webbridge"-tagged session may only
    # drive the web through the webbridge tool). NULL = untagged session.
    # none_as_null=True: the resolve endpoint filters on SQL NULL, so an
    # untagged row must not persist as the JSON literal 'null' (the default
    # JSON-type behaviour — revert/extra have it too, but they are never
    # queried by value).
    tags: list[str] | None = Field(
        default=None,
        sa_column=Column(
            JSON(none_as_null=True).with_variant(
                pg.JSONB(none_as_null=True), "postgresql"
            ),
            nullable=True,
        ),
    )
    # Session type: "main" (default), "team_member" (existing parent_session_id
    # usage), or "side_chat" (read-only access to source_session_id context).
    session_type: str = Field(
        default="main",
        max_length=20,
        sa_column=Column(sa.String(20), nullable=False, server_default="main"),
    )
    # For side chats: reference to the main session they read from.
    # ON DELETE SET NULL so a deleted main session leaves the side chat intact
    # (it just loses source context — graceful degradation).
    source_session_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            sa.Uuid(),
            ForeignKey("chat_sessions.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )
    # Immutable source identity used to authorize an already-open side chat
    # after source_session_id is cleared by ON DELETE SET NULL. No FK by
    # design: this value must survive deletion of the source row.
    source_session_ref: UUID | None = Field(
        default=None,
        sa_column=Column(sa.Uuid(), nullable=True),
    )
    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(TZDateTime(), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(
            TZDateTime(),
            nullable=False,
            onupdate=_utcnow,
        ),
    )


class CodingWorkspace(SQLModel, table=True):
    __tablename__: str = "coding_workspaces"  # type: ignore[reportIncompatibleVariableOverride]
    __table_args__ = (
        sa.UniqueConstraint("path", name="uq_coding_workspaces_path"),
        sa.Index("ix_coding_workspaces_source_path", "source_path"),
    )

    id: UUID = Field(default_factory=uuid7, primary_key=True)
    path: str = Field(sa_column=Column(sa.String(), nullable=False))
    kind: str = Field(
        default="repo",
        max_length=20,
        sa_column=Column(sa.String(20), nullable=False, server_default="repo"),
    )
    source_path: str | None = Field(default=None)
    name: str | None = Field(default=None, max_length=255)
    managed: bool = Field(
        default=False,
        sa_column=Column(sa.Boolean, nullable=False, server_default=sa.false()),
    )
    hidden: bool = Field(
        default=False,
        sa_column=Column(sa.Boolean, nullable=False, server_default=sa.false()),
    )
    deleted_at: datetime | None = Field(default=None, sa_column=Column(TZDateTime()))
    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(TZDateTime(), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(TZDateTime(), nullable=False, onupdate=_utcnow),
    )


class GitServerConnection(SQLModel, table=True):
    """API connection used to read reviews from a Git server.

    Secret material is deliberately not stored in this table. ``token_env_var``
    points at a value in EvoFlux's config ``.env`` (or the process environment),
    while this row contains only routing metadata safe to return to the UI.
    """

    __tablename__: str = "git_server_connections"  # type: ignore[reportIncompatibleVariableOverride]
    __table_args__ = (
        sa.Index("ix_git_server_connections_host", "host"),
        sa.Index("ix_git_server_connections_workspace", "workspace_id"),
    )

    id: UUID = Field(default_factory=uuid7, primary_key=True)
    name: str = Field(sa_column=Column(sa.String(255), nullable=False))
    provider: str = Field(sa_column=Column(sa.String(40), nullable=False))
    base_url: str = Field(sa_column=Column(sa.String(2048), nullable=False))
    host: str = Field(sa_column=Column(sa.String(255), nullable=False))
    scope: str = Field(
        default="server",
        sa_column=Column(sa.String(20), nullable=False, server_default="server"),
    )
    workspace_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            sa.Uuid(),
            ForeignKey("coding_workspaces.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    token_env_var: str = Field(
        sa_column=Column(sa.String(255), nullable=False, unique=True)
    )
    username: str | None = Field(
        default=None, sa_column=Column(sa.String(255), nullable=True)
    )
    verify_ssl: bool = Field(
        default=True,
        sa_column=Column(sa.Boolean, nullable=False, server_default=sa.true()),
    )
    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(TZDateTime(), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(TZDateTime(), nullable=False, onupdate=_utcnow),
    )


class SessionMessage(SQLModel, table=True):
    __tablename__: str = "session_messages"  # type: ignore[reportIncompatibleVariableOverride]
    __table_args__ = (
        # Cover stable cursor ordering without a temporary tie-break sort.
        sa.Index(
            "ix_session_messages_session_created_id",
            "session_id",
            "created_at",
            "id",
        ),
        # Me cover is_summary lookup (get_messages_for_llm summary query)
        sa.Index("ix_session_messages_session_summary", "session_id", "is_summary"),
    )

    id: UUID = Field(default_factory=uuid7, primary_key=True)
    session_id: UUID = Field(
        sa_column=Column(
            sa.Uuid(),
            ForeignKey("chat_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )
    role: str = Field(max_length=50)
    content: str | None = Field(default=None)
    reasoning_content: str | None = Field(default=None)

    # Stores tool_calls as a list of dicts
    tool_calls: list[dict] | None = Field(
        default=None,
        sa_column=Column(JSON),
    )

    # For tool messages
    tool_call_id: str | None = Field(default=None, max_length=100)
    name: str | None = Field(default=None, max_length=100)

    # Flexible extra data (usage stats, etc.)
    # JSONB on Postgres, JSON on SQLite
    extra: dict | None = Field(
        default=None,
        sa_column=Column(
            JSON().with_variant(pg.JSONB(), "postgresql"),
        ),
    )

    # Summarization support
    # is_summary=True           → this message IS the conversation summary (assistant role)
    # exclude_from_context=True → this message exists in audit log but is not sent to LLM
    is_summary: bool = Field(
        default=False,
        sa_column=Column(sa.Boolean, nullable=False, server_default=sa.false()),
    )
    exclude_from_context: bool = Field(
        default=False,
        sa_column=Column(sa.Boolean, nullable=False, server_default=sa.false()),
    )

    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(TZDateTime(), nullable=False),
    )


class DreamLog(SQLModel, table=True):
    """Records sessions that have been processed by the dream agent."""

    __tablename__ = "dream_log"  # type: ignore[reportIncompatibleVariableOverride]

    id: int | None = Field(default=None, primary_key=True)
    session_id: uuid.UUID = Field(index=True, unique=True)
    processed_at: datetime = Field(sa_column=Column(TZDateTime, nullable=False))
    agent_name: str | None = Field(default=None)
    topics_written: str | None = Field(default=None)  # JSON array of slugs


class DreamNotesLog(SQLModel, table=True):
    """Records note files that have been processed by the dream agent."""

    __tablename__: str = "dream_notes_log"  # type: ignore[reportIncompatibleVariableOverride]

    id: int | None = Field(default=None, primary_key=True)
    filename: str = Field(index=True, unique=True)  # e.g. "2026-04-29-abc123.md"
    processed_at: datetime = Field(sa_column=Column(TZDateTime, nullable=False))


class CodingProject(SQLModel, table=True):
    """A named project grouping multiple CodingWorkspace repositories."""

    __tablename__: str = "coding_projects"  # type: ignore[reportIncompatibleVariableOverride]
    __table_args__ = (sa.Index("ix_coding_projects_created_at", "created_at"),)

    id: UUID = Field(default_factory=uuid7, primary_key=True)
    name: str = Field(sa_column=Column(sa.String(255), nullable=False))
    description: str | None = Field(
        default=None, sa_column=Column(sa.Text(), nullable=True)
    )
    settings: dict = Field(
        default_factory=dict,
        sa_column=Column(
            JSON().with_variant(pg.JSONB(), "postgresql"),
            nullable=False,
            server_default="{}",
        ),
    )
    # Coding-only discriminator for multi-repo Coding projects. Kept as a
    # column for schema compatibility; new projects should use ``"coding"``.
    kind: str = Field(
        default="coding",
        sa_column=Column(sa.String(20), nullable=False, server_default="coding"),
    )
    hidden: bool = Field(
        default=False,
        sa_column=Column(sa.Boolean, nullable=False, server_default=sa.false()),
    )
    deleted_at: datetime | None = Field(default=None, sa_column=Column(TZDateTime()))
    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(TZDateTime(), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(TZDateTime(), nullable=False, onupdate=_utcnow),
    )


class CodingProjectWorkspace(SQLModel, table=True):
    """Join table linking CodingProject to its member CodingWorkspace repos."""

    __tablename__: str = "coding_project_workspaces"  # type: ignore[reportIncompatibleVariableOverride]
    __table_args__ = (
        sa.UniqueConstraint(
            "project_id", "workspace_id", name="uq_coding_project_workspaces_pair"
        ),
        sa.Index("ix_coding_project_workspaces_project", "project_id"),
        sa.Index("ix_coding_project_workspaces_workspace", "workspace_id"),
    )

    id: UUID = Field(default_factory=uuid7, primary_key=True)
    project_id: UUID = Field(
        sa_column=Column(
            sa.Uuid(),
            ForeignKey("coding_projects.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    workspace_id: UUID = Field(
        sa_column=Column(
            sa.Uuid(),
            ForeignKey("coding_workspaces.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    display_name: str | None = Field(
        default=None, sa_column=Column(sa.String(255), nullable=True)
    )
    sort_order: int = Field(
        default=0,
        sa_column=Column(sa.Integer, nullable=False, server_default="0"),
    )
    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(TZDateTime(), nullable=False),
    )
