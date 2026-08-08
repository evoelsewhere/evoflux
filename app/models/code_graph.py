"""Code knowledge graph models.

These tables store the parsed structure of a coding workspace as a graph of
symbols (``CodeNode``) connected by relationships (``CodeEdge``).  ``CodeIndexState``
tracks per-file content hashes so the indexer can skip unchanged files on
re-index.

Search over this graph is lexical + structural only — see
``app/services/code_graph/fts_store.py`` (FTS5 virtual table, keyed by
``CodeNode.id``) — there is no vector/embedding layer.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid7

import sqlalchemy as sa
from sqlalchemy import Column, ForeignKey
from sqlmodel import Field, SQLModel

from app.models.chat import TZDateTime, _utcnow


class CodeNode(SQLModel, table=True):
    """A single symbol in the code graph (file, class, function, method, …)."""

    __tablename__: str = "code_nodes"  # type: ignore[reportIncompatibleVariableOverride]
    __table_args__ = (
        sa.Index("ix_code_nodes_workspace_file", "workspace_id", "file_path"),
        sa.Index("ix_code_nodes_workspace_name", "workspace_id", "name"),
        sa.Index("ix_code_nodes_workspace_kind", "workspace_id", "kind"),
        sa.Index(
            "ix_code_nodes_workspace_qualified_name", "workspace_id", "qualified_name"
        ),
    )

    id: UUID = Field(default_factory=uuid7, primary_key=True)
    workspace_id: UUID = Field(
        sa_column=Column(
            sa.Uuid(),
            ForeignKey("coding_workspaces.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    # file | module | class | function | method | interface | variable
    kind: str = Field(sa_column=Column(sa.String(30), nullable=False))
    name: str = Field(sa_column=Column(sa.String(255), nullable=False))
    # Dotted path within the file, e.g. "OuterClass.method". Equals ``name`` for
    # top-level symbols; equals the relative path for ``file`` nodes.
    qualified_name: str = Field(sa_column=Column(sa.String(), nullable=False))
    file_path: str = Field(sa_column=Column(sa.String(), nullable=False))
    language: str = Field(sa_column=Column(sa.String(40), nullable=False))
    line_start: int = Field(sa_column=Column(sa.Integer, nullable=False))
    line_end: int = Field(sa_column=Column(sa.Integer, nullable=False))
    signature: str | None = Field(default=None, sa_column=Column(sa.String()))
    docstring: str | None = Field(default=None, sa_column=Column(sa.Text()))
    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(TZDateTime(), nullable=False),
    )


class CodeEdge(SQLModel, table=True):
    """A directed relationship between two ``CodeNode`` rows."""

    __tablename__: str = "code_edges"  # type: ignore[reportIncompatibleVariableOverride]
    __table_args__ = (
        sa.Index("ix_code_edges_src", "workspace_id", "src_id", "kind"),
        sa.Index("ix_code_edges_dst", "workspace_id", "dst_id", "kind"),
        sa.Index("ix_code_edges_workspace_file", "workspace_id", "file_path"),
    )

    id: UUID = Field(default_factory=uuid7, primary_key=True)
    workspace_id: UUID = Field(
        sa_column=Column(
            sa.Uuid(),
            ForeignKey("coding_workspaces.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    src_id: UUID = Field(
        sa_column=Column(
            sa.Uuid(),
            ForeignKey("code_nodes.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )
    dst_id: UUID = Field(
        sa_column=Column(
            sa.Uuid(),
            ForeignKey("code_nodes.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )
    # contains | calls | inherits | implements | references | imports
    kind: str = Field(sa_column=Column(sa.String(30), nullable=False))
    # File the edge originates from — lets the indexer delete a file's edges
    # before re-inserting on incremental re-index.
    file_path: str | None = Field(default=None, sa_column=Column(sa.String()))
    line: int | None = Field(default=None, sa_column=Column(sa.Integer))
    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(TZDateTime(), nullable=False),
    )


class CodeIndexState(SQLModel, table=True):
    """Per-file indexing bookkeeping for incremental re-index."""

    __tablename__: str = "code_index_state"  # type: ignore[reportIncompatibleVariableOverride]
    __table_args__ = (
        sa.UniqueConstraint(
            "workspace_id", "file_path", name="uq_code_index_state_workspace_file"
        ),
        sa.Index("ix_code_index_state_workspace", "workspace_id"),
    )

    id: UUID = Field(default_factory=uuid7, primary_key=True)
    workspace_id: UUID = Field(
        sa_column=Column(
            sa.Uuid(),
            ForeignKey("coding_workspaces.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    file_path: str = Field(sa_column=Column(sa.String(), nullable=False))
    language: str | None = Field(default=None, sa_column=Column(sa.String(40)))
    content_hash: str = Field(sa_column=Column(sa.String(64), nullable=False))
    node_count: int = Field(
        default=0, sa_column=Column(sa.Integer, nullable=False, server_default="0")
    )
    edge_count: int = Field(
        default=0, sa_column=Column(sa.Integer, nullable=False, server_default="0")
    )
    indexed_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(TZDateTime(), nullable=False),
    )


class CodeIndexChunk(SQLModel, table=True):
    """One bounded, parser-aligned source partition used by code search."""

    __tablename__: str = "code_index_chunks"  # type: ignore[reportIncompatibleVariableOverride]
    __table_args__ = (
        sa.UniqueConstraint(
            "workspace_id", "component_key", name="uq_code_index_chunk_component"
        ),
        sa.Index("ix_code_index_chunk_workspace_file", "workspace_id", "file_path"),
        sa.Index("ix_code_index_chunk_workspace_node", "workspace_id", "node_id"),
    )

    id: UUID = Field(default_factory=uuid7, primary_key=True)
    workspace_id: UUID = Field(
        sa_column=Column(
            sa.Uuid(),
            ForeignKey("coding_workspaces.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    node_id: UUID | None = Field(
        default=None,
        sa_column=Column(sa.Uuid(), ForeignKey("code_nodes.id", ondelete="SET NULL")),
    )
    component_key: str = Field(sa_column=Column(sa.String(), nullable=False))
    file_path: str = Field(sa_column=Column(sa.String(), nullable=False))
    language: str = Field(sa_column=Column(sa.String(40), nullable=False))
    kind: str = Field(sa_column=Column(sa.String(30), nullable=False))
    name: str = Field(sa_column=Column(sa.String(255), nullable=False))
    qualified_name: str = Field(sa_column=Column(sa.String(), nullable=False))
    line_start: int = Field(sa_column=Column(sa.Integer, nullable=False))
    line_end: int = Field(sa_column=Column(sa.Integer, nullable=False))
    content: str = Field(sa_column=Column(sa.Text(), nullable=False))
    signature: str | None = Field(default=None, sa_column=Column(sa.Text()))
    docstring: str | None = Field(default=None, sa_column=Column(sa.Text()))
    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(TZDateTime(), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(TZDateTime(), nullable=False, onupdate=_utcnow),
    )


class CrossRepoEdge(SQLModel, table=True):
    """A candidate reference from one repo to a symbol in a sibling repo.

    Scoped to a ``CodingProject`` because cross-repository links only make sense
    within a project's repository set. This is not a ``CodeEdge``: candidates
    can be unresolved and carry matching provenance before a target node exists.
    Node FKs use ``SET NULL`` and ``dst_qualified_name`` stays denormalized so a
    removed target symbol can be re-attached by name on the next resolution pass.
    """

    __tablename__: str = "code_cross_repo_edges"  # type: ignore[reportIncompatibleVariableOverride]
    __table_args__ = (
        sa.Index("ix_cre_project_status", "project_id", "status"),
        sa.Index("ix_cre_project_src_ws", "project_id", "src_workspace_id"),
        sa.Index("ix_cre_project_dst_ws", "project_id", "dst_workspace_id"),
    )

    id: UUID = Field(default_factory=uuid7, primary_key=True)
    project_id: UUID = Field(
        sa_column=Column(
            sa.Uuid(),
            ForeignKey("coding_projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )

    src_workspace_id: UUID = Field(
        sa_column=Column(
            sa.Uuid(),
            ForeignKey("coding_workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )
    # SET NULL, not CASCADE — see class docstring.
    src_node_id: UUID | None = Field(
        default=None,
        sa_column=Column(sa.Uuid(), ForeignKey("code_nodes.id", ondelete="SET NULL")),
    )
    src_file_path: str = Field(sa_column=Column(sa.String(), nullable=False))
    src_line: int | None = Field(default=None, sa_column=Column(sa.Integer))

    # Raw import specifier / call target / URL string as it appeared in
    # source — the thing that needs resolving.
    raw_reference: str = Field(sa_column=Column(sa.String(), nullable=False))
    # ImportRef.name or callee name, if the extractor had one.
    dst_name_hint: str | None = Field(default=None, sa_column=Column(sa.String()))
    # imports | calls | references | inherits
    kind: str = Field(sa_column=Column(sa.String(30), nullable=False))

    # unresolved | resolved | rejected (rejected = a resolved link a user/agent
    # marked wrong — a manual override, never re-suggested by later passes).
    status: str = Field(
        default="unresolved",
        sa_column=Column(sa.String(20), nullable=False, server_default="unresolved"),
    )
    # NULL until a resolution pass touches this row. Current resolver values are
    # static path/FQN/manifest methods and deterministic lexical matching.
    # Keep the column open-ended so historical provenance remains readable.
    method: str | None = Field(default=None, sa_column=Column(sa.String(30)))
    confidence: float | None = Field(default=None)
    rationale: str | None = Field(default=None, sa_column=Column(sa.Text()))

    dst_workspace_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            sa.Uuid(), ForeignKey("coding_workspaces.id", ondelete="SET NULL")
        ),
    )
    dst_node_id: UUID | None = Field(
        default=None,
        sa_column=Column(sa.Uuid(), ForeignKey("code_nodes.id", ondelete="SET NULL")),
    )
    # Denormalized — survives dst_node_id going NULL on the target repo's next
    # reindex, so re-resolution can reattach by name instead of re-matching.
    dst_qualified_name: str | None = Field(default=None, sa_column=Column(sa.String()))

    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(TZDateTime(), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(TZDateTime(), nullable=False, onupdate=_utcnow),
    )


class CodeAmbiguousEdge(SQLModel, table=True):
    """An edge whose target name matched 2+ candidates.

    Stored so the UI and agent can surface these as "ambiguous" rather than
    silently dropping them. The ``candidate_node_ids`` field lists all possible
    target ``CodeNode.id`` values as a JSON array.
    """

    __tablename__: str = "code_ambiguous_edges"  # type: ignore[reportIncompatibleVariableOverride]
    __table_args__ = (sa.Index("ix_cae_workspace_src", "workspace_id", "src_id"),)

    id: UUID = Field(default_factory=uuid7, primary_key=True)
    workspace_id: UUID = Field(
        sa_column=Column(
            sa.Uuid(),
            ForeignKey("coding_workspaces.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    src_id: UUID = Field(
        sa_column=Column(
            sa.Uuid(),
            ForeignKey("code_nodes.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )
    dst_name: str = Field(sa_column=Column(sa.String(255), nullable=False))
    # calls | inherits | implements | references | decorated_by | uses | overrides
    kind: str = Field(sa_column=Column(sa.String(30), nullable=False))
    # JSON array of candidate CodeNode.id UUIDs.
    candidate_node_ids: str = Field(sa_column=Column(sa.Text(), nullable=False))
    file_path: str | None = Field(default=None, sa_column=Column(sa.String()))
    line: int | None = Field(default=None, sa_column=Column(sa.Integer))
    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(TZDateTime(), nullable=False),
    )
