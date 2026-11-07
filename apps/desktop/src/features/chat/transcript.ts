// Folds the engine's event stream into the turns the thread renders.
//
// A turn is one person message plus everything the agent did in response, as
// an ordered list of parts — reasoning, text and tool calls — in exactly the
// order the model produced them across every step of the run (the model may
// think, write, call a tool, think again, write more). Streamed blocks are
// keyed by `messageId:contentIndex`, so deltas land on the block they belong
// to; tool calls are also keyed by their call id, which is how the execution
// events find them. (The same model as DeepSeek Harness's per-step `blocks[]`.)

import { type AgentMessage, type EngineMessage } from "@/engine/protocol";

export interface TextPart {
  kind: "text";
  key: string;
  text: string;
  streaming: boolean;
}

export interface ReasoningPart {
  kind: "reasoning";
  key: string;
  text: string;
  streaming: boolean;
  startedAt: number;
  endedAt?: number;
}

/** `preparing`: the model is still writing the arguments. */
export type ToolPhase = "preparing" | "running" | "done" | "error";

export interface ToolPart {
  kind: "tool";
  key: string;
  callId: string;
  name: string;
  /** Parsed arguments once complete. */
  args: unknown;
  /** Raw argument JSON while it streams. */
  argsText: string;
  phase: ToolPhase;
  output: string;
  /** Tool-specific result data (an edit's diff, …). */
  details?: Record<string, any>;
  /** Images the result carried (a browser screenshot), as data URLs. */
  images?: string[];
  startedAt: number;
  endedAt?: number;
}

export type Part = TextPart | ReasoningPart | ToolPart;

export interface TurnMeta {
  model?: string;
  provider?: string;
  durationMs?: number;
  inputTokens?: number;
  outputTokens?: number;
  cacheRead?: number;
  cacheWrite?: number;
  cost?: number;
}

/** One of the agent's questions (`ask_user`). */
export interface Question {
  question: string;
  header?: string;
  options: { label: string; description?: string }[];
  multiSelect: boolean;
}

export interface PermissionRequest {
  requestId: string;
  toolCallId?: string;
  title: string;
  description?: string;
  options: { title: string; permission?: string }[];
  kind: string;
  /** `kind: "questions"`: the agent's questions, answered in the questions panel. */
  questions?: Question[];
}

export interface Turn {
  id: string;
  prompt: string;
  /** Pictures sent with the prompt, as data URLs. */
  images?: string[];
  /** The prompt's session entry and its parent (saved chats), for editing it. */
  entryId?: string;
  parentId?: string | null;
  parts: Part[];
  status: "running" | "done" | "error" | "aborted";
  error?: string;
  startedAt: number;
  endedAt?: number;
  meta: TurnMeta;
  permission?: PermissionRequest;
}

/** A message sent while the agent works, waiting for it to be read. */
export interface QueuedMessage {
  entryId: string;
  text: string;
  images?: string[];
  /** `steer`: read at the agent's next step; `followUp`: after it would stop. */
  deliverAs: "steer" | "followUp";
}

export interface TranscriptState {
  turns: Turn[];
  busy: boolean;
  /** Messages sent during the run that the agent has not read yet. */
  queued?: QueuedMessage[];
  /** Assistant message currently streaming, so deltas land on the right blocks. */
  streamingMessageId?: string;
  /**
   * How background subagents ended, from their reports to the chat (which
   * make no turn of their own), keyed `id:<agent id>` and `description:<…>`.
   * The `agent` call keeps the snapshot from when it started.
   */
  agentReports?: Record<string, AgentReport>;
}

export interface AgentReport {
  status: "done" | "error" | "cancelled";
  at: number;
}

/** The `<background-agent id description status>` reports in a message (crates/evo-engine/src/agent_tool.rs). */
export function agentReportsIn(text: string, at: number): Record<string, AgentReport> {
  const reports: Record<string, AgentReport> = {};
  for (const match of text.matchAll(/<background-agent id="([^"]*)" description="([^"]*)" status="([^"]*)"/g)) {
    const status = match[3] === "error" || match[3] === "cancelled" ? match[3] : "done";
    reports[`id:${match[1]}`] = { status, at };
    reports[`description:${match[2]}`] = { status, at };
  }
  return reports;
}

const withReports = (state: TranscriptState, text: string, at: number): TranscriptState => {
  const found = agentReportsIn(text, at);
  return Object.keys(found).length ? { ...state, agentReports: { ...state.agentReports, ...found } } : state;
};

export const initialTranscript: TranscriptState = { turns: [], busy: false };

let counter = 0;
const localId = (prefix: string) => `${prefix}-${Date.now().toString(36)}-${++counter}`;

/** The reply text of a turn (every text block, in order). */
export function turnReply(turn: Turn): string {
  return turn.parts
    .filter((part): part is TextPart => part.kind === "text")
    .map((part) => part.text)
    .filter(Boolean)
    .join("\n\n");
}

function updateCurrent(state: TranscriptState, update: (turn: Turn) => Turn): TranscriptState {
  const last = state.turns.at(-1);
  if (!last) return state;
  return { ...state, turns: [...state.turns.slice(0, -1), update(last)] };
}

function toolOutput(result: any): string {
  if (result == null) return "";
  if (typeof result === "string") return result;
  const content = Array.isArray(result.content) ? result.content : [];
  const text = content
    .filter((part: any) => part?.type === "text")
    .map((part: any) => part.text)
    .join("\n");
  return text || (result.content === undefined ? JSON.stringify(result, null, 2) : "");
}

/** Image blocks of a tool result, as data URLs. */
function toolImages(result: any): string[] | undefined {
  const content = Array.isArray(result?.content) ? result.content : [];
  const images = content
    .filter((part: any) => part?.type === "image" && typeof part.data === "string")
    .map((part: any) => `data:${part.mimeType || part.mime_type || "image/png"};base64,${part.data}`);
  return images.length ? images : undefined;
}

function upsert(turn: Turn, key: string, create: () => Part, change: (part: Part) => Part): Turn {
  const index = turn.parts.findIndex((part) => part.key === key);
  if (index === -1) return { ...turn, parts: [...turn.parts, change(create())] };
  const parts = turn.parts.slice();
  parts[index] = change(parts[index]);
  return { ...turn, parts };
}

function findTool(turn: Turn, callId: string): number {
  return turn.parts.findIndex((part) => part.kind === "tool" && part.callId === callId);
}

/** Close every still-streaming text or reasoning block (a new channel began, or the step ended). */
function settleBlocks(turn: Turn, now: number, except?: string): Turn {
  let changed = false;
  const parts = turn.parts.map((part) => {
    if (part.key === except) return part;
    if (part.kind === "reasoning" && part.streaming) {
      changed = true;
      return { ...part, streaming: false, endedAt: now };
    }
    if (part.kind === "text" && part.streaming) {
      changed = true;
      return { ...part, streaming: false };
    }
    return part;
  });
  return changed ? { ...turn, parts } : turn;
}

/** Add a tool's own usage (a subagent's) to the turn, keeping its model. */
function applyToolUsage(turn: Turn, usage: any): Turn {
  if (!usage || typeof usage !== "object") return turn;
  return applyUsage(turn, { usage } as AgentMessage & Record<string, any>);
}

function applyUsage(turn: Turn, message: AgentMessage & Record<string, any>): Turn {
  const usage = message.usage as any;
  return {
    ...turn,
    meta: {
      ...turn.meta,
      model: message.model ?? turn.meta.model,
      provider: message.provider ?? turn.meta.provider,
      inputTokens: (turn.meta.inputTokens ?? 0) + (usage?.input ?? 0),
      outputTokens: (turn.meta.outputTokens ?? 0) + (usage?.output ?? 0),
      cacheRead: (turn.meta.cacheRead ?? 0) + (usage?.cacheRead ?? 0),
      cacheWrite: (turn.meta.cacheWrite ?? 0) + (usage?.cacheWrite ?? 0),
      cost: (turn.meta.cost ?? 0) + (usage?.cost?.total ?? 0),
    },
  };
}

function permissionFrom(message: EngineMessage): PermissionRequest {
  const ui = (message.ui ?? {}) as Record<string, any>;
  const options = Array.isArray(ui.options)
    ? ui.options.map((o: any) => ({ title: String(o?.title ?? o), permission: o?.permission }))
    : [];
  const questions: Question[] | undefined =
    ui.kind === "questions" && Array.isArray(ui.questions)
      ? ui.questions.map((q: any) => ({
          question: String(q?.question ?? ""),
          header: q?.header ? String(q.header) : undefined,
          options: Array.isArray(q?.options)
            ? q.options.map((o: any) => ({ label: String(o?.label ?? o), description: o?.description ? String(o.description) : undefined }))
            : [],
          multiSelect: Boolean(q?.multi_select ?? q?.multiSelect),
        }))
      : undefined;
  return {
    requestId: message.requestId,
    toolCallId: message.toolCallId ?? undefined,
    title: ui.title ?? ui.question ?? ui.message ?? "The agent needs your input",
    description: ui.description ?? ui.detail ?? undefined,
    options: options.length || questions ? options : [{ title: "Allow" }, { title: "Deny" }],
    kind: ui.kind ?? "confirm",
    questions,
  };
}

const newText = (key: string): TextPart => ({ kind: "text", key, text: "", streaming: true });
const newReasoning = (key: string, now: number): ReasoningPart => ({
  kind: "reasoning",
  key,
  text: "",
  streaming: true,
  startedAt: now,
});
const newTool = (key: string, callId: string, name: string, now: number): ToolPart => ({
  kind: "tool",
  key,
  callId,
  name,
  args: undefined,
  argsText: "",
  phase: "preparing",
  output: "",
  startedAt: now,
});

/** Reconcile a finished assistant message's content with the streamed blocks. */
function finishMessage(turn: Turn, messageId: string, message: AgentMessage & Record<string, any>, now: number): Turn {
  const content = Array.isArray(message.content) ? message.content : [];
  let next = turn;
  content.forEach((block: any, index: number) => {
    const key = `${messageId}:${index}`;
    if (block?.type === "text" && typeof block.text === "string" && block.text) {
      next = upsert(next, key, () => newText(key), (part) => ({ ...(part as TextPart), text: block.text, streaming: false }));
    } else if (block?.type === "thinking" && typeof block.thinking === "string" && block.thinking) {
      next = upsert(
        next,
        key,
        () => newReasoning(key, now),
        (part) => ({ ...(part as ReasoningPart), text: block.thinking, streaming: false, endedAt: (part as ReasoningPart).endedAt ?? now }),
      );
    } else if (block?.type === "toolCall" && block.id) {
      const existing = findTool(next, block.id);
      const toolKey = existing === -1 ? key : next.parts[existing].key;
      next = upsert(
        next,
        toolKey,
        () => newTool(toolKey, block.id, block.name ?? "tool", now),
        (part) => ({ ...(part as ToolPart), name: block.name ?? (part as ToolPart).name, args: block.arguments ?? (part as ToolPart).args }),
      );
    }
  });
  return settleBlocks(next, now);
}

export type TranscriptAction =
  | { type: "reset" }
  | { type: "prompt"; text: string; images?: string[] }
  | { type: "queued"; item: QueuedMessage }
  /** Drop a waiting message (`null`: all of them). */
  | { type: "unqueued"; entryId: string | null }
  | { type: "fail"; error: string }
  | { type: "permission-answered" }
  | { type: "engine"; message: EngineMessage }
  /** A background subagent's latest snapshot, for the call that started it (any turn). */
  | { type: "agent-progress"; callId: string; child: Record<string, unknown> }
  /** Usage of background subagents whose reports this turn delivers. */
  | { type: "extra-usage"; usage: unknown };

/**
 * How a run ended. `agent_settled` says so (`outcome`, `aborted`, `error`);
 * `agent_end`, which usually comes first, carries only the run's messages, so
 * its last assistant message's `stopReason` tells: a run stopped while a tool
 * ran ends with an `aborted` assistant message.
 */
export function runEnd(message: EngineMessage): { aborted: boolean; failed: boolean; error?: string } {
  const messages: AgentMessage[] = Array.isArray(message.messages) ? message.messages : [];
  const last = [...messages].reverse().find((m) => m?.role === "assistant") as (AgentMessage & Record<string, any>) | undefined;
  const aborted = message.aborted === true || message.outcome === "aborted" || last?.stopReason === "aborted";
  const error =
    message.error ?? (last?.stopReason === "error" ? (last.errorMessage ?? "The model returned an error") : undefined);
  const failed = message.outcome === "failed" || (!!error && !aborted);
  return { aborted, failed, error: error == null ? undefined : String(error) };
}

function applyEngine(state: TranscriptState, message: EngineMessage, now: number): TranscriptState {
  switch (message.type) {
    case "agent_start":
      return { ...state, busy: true };
    case "agent_end":
    case "agent_settled": {
      const { aborted, failed, error } = runEnd(message);
      const next = updateCurrent(state, (turn) => {
        if (turn.status !== "running") {
          // `agent_end` closed the turn as done; the settlement knows better.
          // Not a `compact` run's: it has no turn, and its outcome is not the last turn's.
          if (message.type === "agent_settled" && message.compact !== true && turn.status === "done" && (aborted || failed)) {
            return {
              ...turn,
              status: aborted ? "aborted" : "error",
              error: failed ? (error ?? turn.error ?? "The run failed") : turn.error,
            };
          }
          return turn;
        }
        const settled = settleBlocks(turn, now);
        return {
          ...settled,
          status: aborted ? "aborted" : failed ? "error" : "done",
          error: failed ? (error ?? turn.error ?? "The run failed") : turn.error,
          endedAt: now,
          meta: { ...turn.meta, durationMs: now - turn.startedAt },
          // A call still open when the run ends was interrupted.
          parts: settled.parts.map((part) =>
            part.kind === "tool" && (part.phase === "running" || part.phase === "preparing")
              ? { ...part, phase: "error" as const, endedAt: now, output: part.output || "Stopped before it finished." }
              : part,
          ),
        };
      });
      return { ...next, busy: false, streamingMessageId: undefined };
    }
    case "message_start": {
      const msg = message.message as AgentMessage | undefined;
      if (msg?.role === "user") return userMessageStarted(state, msg, now);
      if (msg?.role !== "assistant") return state;
      return { ...state, streamingMessageId: message.messageId ?? localId("message") };
    }
    case "message_update": {
      const event = message.assistantMessageEvent ?? {};
      const type: string = event.type ?? message.eventType ?? "";
      const index: number = event.contentIndex ?? message.contentIndex ?? 0;
      const messageId = message.messageId ?? state.streamingMessageId ?? "message";
      const key = `${messageId}:${index}`;
      const delta: string = event.delta ?? message.delta ?? "";
      return updateCurrent(state, (turn) => {
        switch (type) {
          case "text_start":
          case "text_delta":
            return upsert(settleBlocks(turn, now, key), key, () => newText(key), (part) => ({
              ...(part as TextPart),
              text: (part as TextPart).text + (type === "text_delta" ? delta : ""),
              streaming: true,
            }));
          case "thinking_start":
          case "thinking_delta":
            return upsert(settleBlocks(turn, now, key), key, () => newReasoning(key, now), (part) => ({
              ...(part as ReasoningPart),
              text: (part as ReasoningPart).text + (type === "thinking_delta" ? delta : ""),
              streaming: true,
            }));
          case "text_end":
          case "thinking_end":
            return settleBlocks(turn, now);
          case "toolcall_start":
          case "toolcall_delta": {
            const partial = event.partial?.content?.[index] ?? message.message?.content?.[index];
            const callId: string = event.id ?? partial?.id ?? key;
            const name: string = event.toolName ?? partial?.name ?? "tool";
            const existing = callId ? findTool(turn, callId) : -1;
            const toolKey = existing === -1 ? key : turn.parts[existing].key;
            return upsert(settleBlocks(turn, now), toolKey, () => newTool(toolKey, callId, name, now), (part) => ({
              ...(part as ToolPart),
              callId: (part as ToolPart).callId === toolKey && callId !== key ? callId : (part as ToolPart).callId,
              name: name !== "tool" ? name : (part as ToolPart).name,
              argsText: (part as ToolPart).argsText + (type === "toolcall_delta" ? delta : ""),
            }));
          }
          case "toolcall_end": {
            const call = event.toolCall;
            if (!call?.id) return turn;
            const existing = findTool(turn, call.id);
            const toolKey = existing === -1 ? key : turn.parts[existing].key;
            return upsert(turn, toolKey, () => newTool(toolKey, call.id, call.name, now), (part) => ({
              ...(part as ToolPart),
              callId: call.id,
              name: call.name ?? (part as ToolPart).name,
              args: call.arguments,
            }));
          }
          default:
            return turn;
        }
      });
    }
    case "message_end": {
      const msg = message.message as (AgentMessage & Record<string, any>) | undefined;
      if (msg?.role !== "assistant") return state;
      const messageId = message.messageId ?? state.streamingMessageId ?? localId("message");
      const next = updateCurrent(state, (turn) => {
        let updated = applyUsage(finishMessage(turn, messageId, msg, now), msg);
        if (msg.stopReason === "error") updated = { ...updated, error: msg.errorMessage ?? "The model returned an error" };
        return updated;
      });
      return { ...next, streamingMessageId: undefined };
    }
    case "tool_execution_start":
      return updateCurrent(state, (turn) => {
        const settled = settleBlocks(turn, now);
        const index = findTool(settled, message.toolCallId);
        const key = index === -1 ? `call:${message.toolCallId}` : settled.parts[index].key;
        return upsert(settled, key, () => newTool(key, message.toolCallId, message.toolName, now), (part) => ({
          ...(part as ToolPart),
          name: message.toolName ?? (part as ToolPart).name,
          args: message.args ?? (part as ToolPart).args,
          phase: "running",
        }));
      });
    case "tool_execution_update":
    case "tool_execution_end": {
      const done = message.type === "tool_execution_end";
      const result = done ? message.result : message.partialResult;
      return updateCurrent(state, (turn) => {
        const index = findTool(turn, message.toolCallId);
        if (index === -1) return turn;
        const parts = turn.parts.slice();
        const part = parts[index] as ToolPart;
        parts[index] = {
          ...part,
          phase: done ? (message.isError ? "error" : "done") : part.phase,
          output: toolOutput(result) || part.output,
          images: toolImages(result) ?? part.images,
          details: (result && typeof result === "object" && result.details) || part.details,
          endedAt: done ? now : part.endedAt,
        };
        // A subagent's tokens and cost count toward the turn.
        return done ? applyToolUsage({ ...turn, parts }, result?.usage) : { ...turn, parts };
      });
    }
    case "ui_dialog_request":
      return updateCurrent(state, (turn) => ({ ...turn, permission: permissionFrom(message) }));
    case "ui_dialog_closed":
      return updateCurrent(state, (turn) =>
        turn.permission?.requestId === message.requestId ? { ...turn, permission: undefined } : turn,
      );
    default:
      return state;
  }
}

export function transcriptReducer(state: TranscriptState, action: TranscriptAction): TranscriptState {
  const now = Date.now();
  switch (action.type) {
    case "reset":
      return initialTranscript;
    case "prompt":
      return {
        ...state,
        busy: true,
        turns: [
          ...state.turns,
          {
            id: localId("turn"),
            prompt: action.text,
            images: action.images?.length ? action.images : undefined,
            parts: [],
            status: "running",
            startedAt: now,
            meta: {},
          },
        ],
      };
    case "queued":
      return { ...state, queued: [...(state.queued ?? []), action.item] };
    case "unqueued":
      return {
        ...state,
        queued: action.entryId === null ? [] : (state.queued ?? []).filter((item) => item.entryId !== action.entryId),
      };
    case "fail":
      return {
        ...updateCurrent(state, (turn) => ({ ...turn, status: "error", error: action.error, endedAt: now })),
        busy: false,
      };
    case "permission-answered":
      return updateCurrent(state, (turn) => ({ ...turn, permission: undefined }));
    case "engine":
      return applyEngine(state, action.message, now);
    case "agent-progress": {
      const index = state.turns.findIndex((turn) => findTool(turn, action.callId) !== -1);
      if (index === -1) return state;
      const turns = state.turns.slice();
      const turn = turns[index];
      const parts = turn.parts.slice();
      const at = findTool(turn, action.callId);
      const part = parts[at] as ToolPart;
      parts[at] = { ...part, details: { ...(part.details ?? {}), child: action.child } };
      turns[index] = { ...turn, parts };
      return { ...state, turns };
    }
    case "extra-usage":
      return updateCurrent(state, (turn) => applyToolUsage(turn, action.usage));
  }
}

/** Messages about background subagents (crates/evo-engine/src/agent_tool.rs `NOTE_TAG`). */
export const BACKGROUND_NOTE = "<background-agent";
/** A note from a nested session to the chat that started it. */
export const SESSION_NOTE = "<nested-session";
/** A message or question from another agent (crates/evo-engine/src/mesh_tools.rs), or the wake that reads it. */
export const MAIL_NOTE = "<mail";
export const isBackgroundNote = (text: string) => {
  const start = text.trimStart();
  return start.startsWith(BACKGROUND_NOTE) || start.startsWith(SESSION_NOTE) || start.startsWith(MAIL_NOTE);
};

// ── Restoring a saved chat ─────────────────────────────────────────────────────

/**
 * A prompt as the person typed it: a `/name args` the engine expanded into a
 * `<skill name="…">…</skill>` block is shown as `/name args` again.
 */
export function typedPrompt(text: string): string {
  // Context hooks added (`<hook-context>`, crates/evo-engine/src/hooks.rs) is not what was typed.
  text = text.replace(/\n\n<hook-context>\n[\s\S]*?\n<\/hook-context>\s*$/, "");
  const match = /^<skill name="([^"]+)" location="[^"]*">[\s\S]*?\n<\/skill>(?:\n\n([\s\S]*))?$/.exec(text);
  if (!match) return text;
  return `/${match[1]}${match[2] ? ` ${match[2]}` : ""}`;
}

/**
 * A user message reached the model during a run. The prompt that started the
 * run echoes back and changes nothing; a message sent meanwhile (steered or
 * queued) ends the turn so far and starts one of its own, as in a saved chat.
 */
function userMessageStarted(state: TranscriptState, message: any, now: number): TranscriptState {
  const text = typedPrompt(userText(message));
  if (isBackgroundNote(text)) return withReports(state, text, now);
  const queued = state.queued ?? [];
  const at = queued.findIndex((item) => item.text === text);
  const current = state.turns.at(-1);
  const echo = at === -1 && current?.status === "running" && current.prompt === text && current.parts.length === 0;
  if (echo || (at === -1 && !current)) return state;
  const item = at === -1 ? undefined : queued[at];
  const rest = at === -1 ? queued : queued.filter((_, index) => index !== at);
  const turns = state.turns.map((turn, index) =>
    index === state.turns.length - 1 && turn.status === "running"
      ? { ...settleBlocks(turn, now), status: "done" as const, endedAt: now, meta: { ...turn.meta, durationMs: now - turn.startedAt } }
      : turn,
  );
  const images = item?.images ?? userImages(message);
  return {
    ...state,
    queued: rest,
    busy: true,
    streamingMessageId: undefined,
    turns: [
      ...turns,
      { id: localId("turn"), prompt: text, images, parts: [], status: "running", startedAt: now, meta: {} },
    ],
  };
}

/** The pictures of a user message, as data URLs. */
export function userImages(message: any): string[] | undefined {
  if (!Array.isArray(message?.content)) return undefined;
  const images = message.content
    .filter((part: any) => part?.type === "image" && typeof part.data === "string")
    .map((part: any) => `data:${part.mimeType || part.mime_type || "image/png"};base64,${part.data}`);
  return images.length ? images : undefined;
}

export function userText(message: any): string {
  if (typeof message?.content === "string") return message.content;
  if (!Array.isArray(message?.content)) return "";
  return message.content
    .filter((part: any) => part?.type === "text" && typeof part.text === "string")
    .map((part: any) => part.text)
    .join("\n");
}

/**
 * Rebuild the turns of a saved chat from its messages (`get_messages`), in the
 * same shape the live stream produces, so a reopened chat looks the way it did.
 */
/** Why a background agent with no report shows as stopped after a restart. */
export const LOST_AGENT =
  "Stopped: the engine running it exited (the app closed or crashed) before it finished. Start it again if its work is still needed.";

/**
 * A saved background agent's call keeps the snapshot from when it returned
 * (`status: "running"`); how it ended is in its report, a later message.
 * Apply each report to its call. With `engineStarted`, a call with no report
 * after it belongs to an engine that is gone: it was lost (the engine also
 * queues that report for the chat's next run).
 */
function settleBackgroundAgents(turns: Turn[], reports: Record<string, AgentReport>, engineStarted: boolean): Turn[] {
  return turns.map((turn) => {
    let changed = false;
    const parts = turn.parts.map((part) => {
      const child = part.kind === "tool" ? (part.details?.child as Record<string, any> | undefined) : undefined;
      if (part.kind !== "tool" || !child?.background || child.status !== "running") return part;
      const report = child.agentId ? reports[`id:${child.agentId}`] : undefined;
      // A report written before this call (an earlier run of a continued agent) is not its report.
      const own = report && report.at >= (part.endedAt ?? part.startedAt ?? 0) ? report : undefined;
      if (!own && !engineStarted) return part;
      changed = true;
      const settled = own
        ? { ...child, status: own.status, endedAt: own.at }
        : { ...child, status: "error", endedAt: child.startedAt ?? part.endedAt, error: LOST_AGENT };
      return { ...part, details: { ...part.details, child: settled } };
    });
    return changed ? { ...turn, parts } : turn;
  });
}

export function transcriptFromMessages(
  messages: (AgentMessage & Record<string, any>)[],
  {
    running = false,
    engineStarted = false,
  }: {
    running?: boolean;
    /**
     * The chat's engine was just started: no background agent of an earlier
     * engine runs any more, so one that never reported was lost.
     */
    engineStarted?: boolean;
  } = {},
): TranscriptState {
  const turns: Turn[] = [];
  let agentReports: Record<string, AgentReport> = {};
  const replace = (turn: Turn) => {
    turns[turns.length - 1] = turn;
  };
  messages.forEach((message, index) => {
    const at = typeof message.timestamp === "number" ? message.timestamp : 0;
    if (message.role === "user") {
      const prompt = typedPrompt(userText(message));
      agentReports = { ...agentReports, ...agentReportsIn(prompt, at) };
      // A report queued for the chat's next run (a background agent's, a
      // nested session's) is read by the automated wake that follows; live it
      // makes no turn of its own (userMessageStarted), so neither does it here.
      if (isBackgroundNote(prompt) && messages[index + 1]?.role === "user") return;
      turns.push({
        id: `saved-${index}`,
        prompt,
        images: userImages(message),
        entryId: typeof message.entryId === "string" ? message.entryId : undefined,
        parentId: typeof message.parentId === "string" ? message.parentId : null,
        parts: [],
        status: "done",
        startedAt: at,
        endedAt: at,
        meta: {},
      });
      return;
    }
    if (turns.length === 0) {
      // Messages before the first prompt (a fork, a summary): an unprompted turn.
      turns.push({ id: `saved-${index}`, prompt: "", parts: [], status: "done", startedAt: at, endedAt: at, meta: {} });
    }
    const turn = turns[turns.length - 1];
    if (message.role === "assistant") {
      let next = applyUsage(finishMessage(turn, `saved-${index}`, message, at), message);
      if (message.stopReason === "error") next = { ...next, status: "error", error: message.errorMessage ?? "The model returned an error" };
      if (message.stopReason === "aborted") next = { ...next, status: "aborted" };
      replace({ ...next, endedAt: at || next.endedAt });
    } else if (message.role === "toolResult") {
      const found = findTool(turn, message.toolCallId);
      if (found === -1) return;
      const parts = turn.parts.slice();
      const part = parts[found] as ToolPart;
      parts[found] = {
        ...part,
        phase: message.isError ? "error" : "done",
        output: toolOutput(message),
        images: toolImages(message) ?? part.images,
        details: message.details ?? part.details,
        endedAt: at || part.endedAt,
      };
      replace(applyToolUsage({ ...turn, parts, endedAt: at || turn.endedAt }, (message as any).usage));
    }
  });
  for (let i = 0; i < turns.length; i++) {
    const turn = turns[i];
    // The engine still runs the last turn: its open calls are running, not stopped.
    if (running && i === turns.length - 1) {
      turns[i] = {
        ...turn,
        status: "running",
        endedAt: undefined,
        parts: turn.parts.map((part) =>
          part.kind === "tool" && part.phase === "preparing" ? { ...part, phase: "running" as const } : part,
        ),
      };
      continue;
    }
    turns[i] = {
      ...turn,
      meta: {
        ...turn.meta,
        durationMs: turn.endedAt && turn.startedAt ? Math.max(0, turn.endedAt - turn.startedAt) : undefined,
      },
      // A call with no saved result never finished.
      parts: turn.parts.map((part) =>
        part.kind === "tool" && (part.phase === "preparing" || part.phase === "running")
          ? { ...part, phase: "error" as const, output: part.output || "Stopped before it finished." }
          : part,
      ),
    };
  }
  return { turns: settleBackgroundAgents(turns, agentReports, engineStarted), busy: running, agentReports };
}

// ── Partial tool arguments ────────────────────────────────────────────────────

/**
 * Read a string field out of tool arguments that may still be streaming, so a
 * row can show the command or path before the call is dispatched.
 */
export function partialField(argsText: string, field: string): string | undefined {
  const match = new RegExp(`"${field}"\\s*:\\s*"((?:[^"\\\\]|\\\\.)*)`).exec(argsText);
  if (!match) return undefined;
  try {
    return JSON.parse(`"${match[1]}"`);
  } catch {
    // An escape cut in half: drop the dangling backslash.
    return JSON.parse(`"${match[1].replace(/\\+$/, "")}"`);
  }
}
