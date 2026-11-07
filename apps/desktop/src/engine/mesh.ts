// Session mesh protocol, version 1 (docs/features/session-mesh-protocol/spec.md,
// crates/evo-protocol/src/mesh.rs). Every conversation an engine hosts — its
// session, subagents, plugin children, side questions — is a node with an
// address (`s_<session>/a_<agent>`). The engine streams `{"type":"mesh"}`
// envelopes about them at the level this window subscribed to, and answers
// mesh commands with `res` envelopes correlated by `corr`.
//
// This module holds the wire types and folds node events into the view the
// `agent` tool body renders (`ChildRun`), so subagents show live from push
// events instead of polling.

import type { ChildRun } from "@/components/ai-elements/agent-run";
import type { EngineMessage } from "./protocol";

export const MESH_VERSION = 1;

export type MeshLevel = "none" | "state" | "summary" | "full";
export type NodeKind = "session" | "agent" | "side";
export type NodeState = "proposed" | "starting" | "running" | "waiting" | "idle" | "settled" | "closed";
export type RunStatus = "done" | "failed" | "cancelled";

export interface MeshUsage {
  input: number;
  output: number;
  cacheRead: number;
  cacheWrite: number;
  totalTokens: number;
  cost: number;
}

export interface MeshNode {
  id: string;
  kind: NodeKind;
  parent?: string;
  root: string;
  depth: number;
  title: string;
  origin: "user" | "agent" | "plugin";
  state: NodeState;
  status?: RunStatus;
  reason?: string;
  caps: string[];
  usage: MeshUsage;
  startedAt: number;
  endedAt?: number;
  meta: Record<string, any>;
}

export interface ToolRow {
  callId: string;
  name: string;
  args?: Record<string, unknown>;
  phase: "running" | "done" | "error";
}

export interface MeshEnvelope extends EngineMessage {
  type: "mesh";
  v: number;
  id: string;
  kind: "cmd" | "res" | "evt" | "mail";
  op: string;
  from: string;
  to: string;
  corr?: string;
  seq: number;
  ts: number;
  body: any;
}

export const isMesh = (message: EngineMessage): message is MeshEnvelope => message.type === "mesh";

/** A command envelope from this window to an engine's router. */
export function meshCommand(id: string, from: string, op: string, body: Record<string, unknown>): MeshEnvelope {
  return { type: "mesh", v: MESH_VERSION, id, kind: "cmd", op, from, to: "hub", seq: 0, ts: Date.now(), body };
}

// ── Folding node events into the agent view ──────────────────────────────

/** What one chat's engine has told this window about its nodes. */
export interface MeshView {
  nodes: Map<string, MeshNode>;
  /** The seq of the last `node_state` applied per node: older ones (replays) are skipped. */
  stateSeq: Map<string, number>;
  /** Live tool rows and text per node (summary level). */
  activity: Map<string, { rows: ToolRow[]; text: string; turns: number; toolUses: number }>;
}

export const emptyView = (): MeshView => ({ nodes: new Map(), stateSeq: new Map(), activity: new Map() });

/** Tool rows kept per node (matches the engine's snapshot). */
const MAX_ROWS = 50;

const childStatus = (node: MeshNode): ChildRun["status"] => {
  if (node.state !== "settled" && node.state !== "closed") return "running";
  if (node.status === "done") return "done";
  if (node.status === "cancelled") return "cancelled";
  return "error";
};

/** The `agent` tool body's view of a subagent node. */
export function childRunOf(view: MeshView, address: string): ChildRun | undefined {
  const node = view.nodes.get(address);
  if (!node || node.kind !== "agent") return undefined;
  const activity = view.activity.get(address);
  const agentId = address.slice(address.lastIndexOf("/a_") + 3);
  return {
    agentId,
    background: Boolean(node.meta.background),
    agentType: node.meta.agentType,
    description: node.title,
    model: node.meta.model,
    status: childStatus(node),
    turns: activity?.turns ?? 0,
    toolUses: activity?.toolUses ?? 0,
    usage: { totalTokens: node.usage.totalTokens, cost: node.usage.cost },
    startedAt: node.startedAt,
    endedAt: node.endedAt ?? null,
    tools: activity?.rows ?? [],
    text: activity?.text ?? "",
    worktree: node.meta.worktree ?? null,
    error: node.state === "settled" && node.status !== "done" ? (node.reason ?? null) : null,
  };
}

/**
 * Apply one event envelope to `view`. Returns the address of the node whose
 * agent view changed, or undefined when nothing visible changed.
 */
export function applyMeshEvent(view: MeshView, envelope: MeshEnvelope): string | undefined {
  if (envelope.kind !== "evt") return undefined;
  const body = envelope.body ?? {};
  switch (envelope.op) {
    case "node_state": {
      const node = body.node as MeshNode;
      if (!node?.id) return undefined;
      // A replay older than what this window already applied changes nothing.
      if ((view.stateSeq.get(node.id) ?? -1) > envelope.seq) return undefined;
      view.stateSeq.set(node.id, envelope.seq);
      if (node.state === "closed") {
        // Keep the last record so a closed agent still renders as finished.
        view.nodes.set(node.id, node);
        return node.id;
      }
      // Activity accumulates across runs of a continued agent, like the
      // engine's own snapshot.
      view.nodes.set(node.id, node);
      return node.id;
    }
    case "node_activity": {
      const id = body.node as string;
      if (!view.nodes.has(id)) return undefined;
      const activity = view.activity.get(id) ?? { rows: [], text: "", turns: 0, toolUses: 0 };
      activity.turns = body.turns ?? activity.turns;
      activity.toolUses = body.toolUses ?? activity.toolUses;
      if (typeof body.text === "string") activity.text = body.text;
      // A snapshot (sent when subscribing) replaces the rows.
      if (Array.isArray(body.rows)) activity.rows = (body.rows as ToolRow[]).slice(-MAX_ROWS);
      const row = body.tool as ToolRow | undefined;
      if (row) {
        const at = activity.rows.findIndex((r) => r.callId === row.callId);
        if (at === -1) activity.rows = [...activity.rows, row].slice(-MAX_ROWS);
        else activity.rows = activity.rows.map((r, i) => (i === at ? row : r));
      }
      view.activity.set(id, { ...activity });
      return id;
    }
    case "node_usage": {
      const id = body.node as string;
      const node = view.nodes.get(id);
      if (!node || !body.self) return undefined;
      view.nodes.set(id, { ...node, usage: body.self });
      return id;
    }
    default:
      // node_report and node_event do not change the agent view (the report
      // arrives as the tool result or a queued message).
      return undefined;
  }
}
