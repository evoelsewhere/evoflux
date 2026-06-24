"""Code knowledge graph models.

These tables store the parsed structure of a coding workspace as a graph of
symbols (``CodeNode``) connected by relationships (``CodeEdge``).  ``CodeIndexState``
tracks per-file content hashes so the indexer can skip unchanged files on
re-index.

The semantic/vector layer (sqlite-vec embeddings) is intentionally *not* part of
this module — it lands in a later phase and attaches to ``CodeNode.id`` via a
separate virtual table.
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
