"""Graph semantics — DAG checks and the Phase-1 sequential walk (plan §6.3).

Pure functions over a small mutable :class:`GraphState`; the runner (M3)
drives these, but everything here is unit-testable without a session:

- A node is READY when every incoming edge is *resolved* (fired, or dead)
  and at least one fired. Entry nodes are ready at start.
- A node whose incoming edges are ALL dead is SKIPPED, and its outgoing
  edges become dead (cascades).
- Unconditional edges fire when their source succeeds; ``when:`` edges
  fire when the gate answer / switch value matches. A gate/switch whose
  answer matches no outgoing edge simply ends that branch gracefully.
- Execution picks ONE ready node at a time, in topological order —
  branches interleave sequentially and deterministically.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.workflow.models import DefinitionError, WorkflowDefinition


def validate_dag(definition: WorkflowDefinition) -> list[str]:
    """Cycle + reachability checks (plan §4.4). Returns errors."""
    errors: list[str] = []
    order = topological_order(definition)
    if order is None:
        errors.append("the graph contains a cycle.")
        return errors

    entries = definition.entry_nodes()
    if not entries:
        errors.append("the graph has no entry node (every node has an incoming edge).")
        return errors

    reachable: set[str] = set()
    frontier = list(entries)
    adjacency: dict[str, list[str]] = {}
    for edge in definition.edges:
        adjacency.setdefault(edge.from_, []).append(edge.to)
    while frontier:
        current = frontier.pop()
        if current in reachable:
            continue
        reachable.add(current)
        frontier.extend(adjacency.get(current, []))
    for node in definition.nodes:
        if node.id not in reachable:
            errors.append(f"node '{node.id}' is unreachable from any entry node.")
    return errors


def topological_order(definition: WorkflowDefinition) -> list[str] | None:
    """Kahn's algorithm; None when the graph has a cycle. Ties broken by
    the order nodes appear in the file, so the sequential walk is stable
    and matches what the author sees."""
    file_order = {node.id: i for i, node in enumerate(definition.nodes)}
    indegree: dict[str, int] = {node.id: 0 for node in definition.nodes}
    adjacency: dict[str, list[str]] = {node.id: [] for node in definition.nodes}
    for edge in definition.edges:
        indegree[edge.to] += 1
        adjacency[edge.from_].append(edge.to)

    ready = sorted(
        (node_id for node_id, deg in indegree.items() if deg == 0),
        key=lambda node_id: file_order[node_id],
    )
    order: list[str] = []
    while ready:
        current = ready.pop(0)
        order.append(current)
        for child in adjacency[current]:
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
        ready.sort(key=lambda node_id: file_order[node_id])
    if len(order) != len(definition.nodes):
        return None
    return order


# ── runtime state ─────────────────────────────────────────────────────────────

#: Node statuses used by the walk.
PENDING = "pending"
RUNNING = "running"
SUCCEEDED = "succeeded"
FAILED = "failed"
SKIPPED = "skipped"


@dataclass
class GraphState:
    definition: WorkflowDefinition
    order: list[str]
    node_status: dict[str, str] = field(default_factory=dict)
    fired_edges: set[tuple[str, str]] = field(default_factory=set)
    dead_edges: set[tuple[str, str]] = field(default_factory=set)

    @classmethod
    def create(cls, definition: WorkflowDefinition) -> "GraphState":
        order = topological_order(definition)
        if order is None:  # pragma: no cover — validated at save
            raise DefinitionError(["the graph contains a cycle."])
        return cls(
            definition=definition,
            order=order,
            node_status={node.id: PENDING for node in definition.nodes},
        )

    # -- queries --------------------------------------------------------------
    def incoming(self, node_id: str):
        return [e for e in self.definition.edges if e.to == node_id]

    def outgoing(self, node_id: str):
        return [e for e in self.definition.edges if e.from_ == node_id]

    def is_ready(self, node_id: str) -> bool:
        if self.node_status[node_id] != PENDING:
            return False
        incoming = self.incoming(node_id)
        if not incoming:
            return True
        fired = 0
        for edge in incoming:
            key = (edge.from_, edge.to)
            if key in self.fired_edges:
                fired += 1
            elif key not in self.dead_edges:
                return False  # unresolved edge — wait
        return fired >= 1

    def next_ready(self) -> str | None:
        """First ready node in topological order — the ONE node the
        sequential walk executes next. Also propagates skips so a node
        whose branches all died never blocks the walk."""
        self._propagate_skips()
        for node_id in self.order:
            if self.is_ready(node_id):
                return node_id
        return None

    def is_finished(self) -> bool:
        return self.next_ready() is None and RUNNING not in self.node_status.values()

    # -- transitions ----------------------------------------------------------
    def mark_running(self, node_id: str) -> None:
        self.node_status[node_id] = RUNNING

    def mark_succeeded(self, node_id: str, *, answer: str | None = None) -> None:
        """Fire outgoing edges. For gate/switch, *answer* picks which
        ``when:`` edges fire; everything else fires all unconditional
        edges. Non-matching edges become dead."""
        self.node_status[node_id] = SUCCEEDED
        node = next(n for n in self.definition.nodes if n.id == node_id)
        outgoing = self.outgoing(node_id)
        if node.kind in ("gate", "switch"):
            matched = False
            default_edge = None
            for edge in outgoing:
                key = (edge.from_, edge.to)
                if edge.when == "*":
                    default_edge = edge
                    continue
                if answer is not None and edge.when == answer:
                    self.fired_edges.add(key)
                    matched = True
                else:
                    self.dead_edges.add(key)
            if default_edge is not None:
                key = (default_edge.from_, default_edge.to)
                if matched:
                    self.dead_edges.add(key)
                else:
                    self.fired_edges.add(key)
            # no match anywhere → all outgoing dead → branch ends gracefully
        else:
            for edge in outgoing:
                self.fired_edges.add((edge.from_, edge.to))

    def mark_failed(self, node_id: str) -> None:
        """Failure fails the execution: everything not yet terminal is
        skipped (plan §6.3 — no on_error/retry in v1)."""
        self.node_status[node_id] = FAILED
        for other, status in self.node_status.items():
            if status in (PENDING, RUNNING) and other != node_id:
                self.node_status[other] = SKIPPED

    # -- internals ------------------------------------------------------------
    def _propagate_skips(self) -> None:
        changed = True
        while changed:
            changed = False
            for node in self.definition.nodes:
                if self.node_status[node.id] != PENDING:
                    continue
                incoming = self.incoming(node.id)
                if not incoming:
                    continue
                keys = [(e.from_, e.to) for e in incoming]
                if all(key in self.dead_edges for key in keys):
                    self.node_status[node.id] = SKIPPED
                    for edge in self.outgoing(node.id):
                        self.dead_edges.add((edge.from_, edge.to))
                    changed = True
