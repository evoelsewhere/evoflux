// Side chat: questions about the active chat that never enter it.
//
// The engine owns the thread (`side_question`, crates/evo-engine/src/
// side_questions.rs): it reads the conversation so far, runs without tools,
// keeps follow-ups in order and lives in memory only. This store mirrors its
// snapshot per chat and polls while an answer streams.

import { create } from "zustand";
import { useEngineStore } from "./engine-store";

export type SideTurnStatus = "queued" | "running" | "done" | "failed" | "cancelled";

export interface SideTurn {
  requestId: string;
  question: string;
  text: string;
  status: SideTurnStatus;
  error?: string | null;
}

export interface SideThread {
  threadId?: string;
  turns: SideTurn[];
  /** Follow-ups waiting for the current answer. */
  queued: string[];
  historyTruncated?: boolean;
}

interface SideChatStore {
  /** Thread per chat id. */
  threads: Record<string, SideThread>;
  /** Last failure per chat (sending or polling). */
  errors: Record<string, string | undefined>;
  /** Draft per chat, kept while the panel is closed. */
  drafts: Record<string, string>;
  setDraft(chat: string, text: string): void;
  /** Ask (a follow-up when a thread is open). */
  ask(question: string): Promise<void>;
  /** Stop the answer being written and drop queued follow-ups. */
  stop(): Promise<void>;
  /** Forget the thread and start over. */
  clear(): Promise<void>;
  /** Read the active chat's thread now, and keep reading while an answer streams. */
  refresh(): Promise<void>;
}

const POLL_MS = 120;
const EMPTY: SideThread = { turns: [], queued: [] };

const activeChat = () => useEngineStore.getState().activeId;
const live = (thread: SideThread | undefined) =>
  !!thread && (thread.queued.length > 0 || thread.turns.some((t) => t.status === "running" || t.status === "queued"));

function toThread(snapshot: Record<string, unknown> | null | undefined): SideThread {
  if (!snapshot || !Array.isArray(snapshot.turns)) return EMPTY;
  return {
    threadId: typeof snapshot.threadId === "string" ? snapshot.threadId : undefined,
    turns: (snapshot.turns as SideTurn[]).map((t) => ({
      requestId: String(t.requestId),
      question: String(t.question ?? ""),
      text: String(t.text ?? ""),
      status: (t.status ?? "done") as SideTurnStatus,
      error: t.error ?? null,
    })),
    queued: Array.isArray(snapshot.queued) ? (snapshot.queued as string[]) : [],
    historyTruncated: snapshot.historyTruncated === true,
  };
}

const timers = new Map<string, ReturnType<typeof setTimeout>>();

export const useSideChatStore = create<SideChatStore>((set, get) => {
  const call = (op: string, question?: string) =>
    useEngineStore.getState().request<Record<string, unknown>>("side_question", question ? { op, question } : { op });

  const poll = (chat: string) => {
    if (timers.has(chat)) return;
    const tick = async () => {
      timers.delete(chat);
      // Only the chat on screen has its engine in reach of `request`.
      if (activeChat() !== chat) return;
      try {
        const thread = toThread(await call("status"));
        set((s) => ({ threads: { ...s.threads, [chat]: thread }, errors: { ...s.errors, [chat]: undefined } }));
        if (live(thread)) timers.set(chat, setTimeout(tick, POLL_MS));
      } catch (error) {
        set((s) => ({ errors: { ...s.errors, [chat]: String(error instanceof Error ? error.message : error) } }));
      }
    };
    timers.set(chat, setTimeout(tick, POLL_MS));
  };

  return {
    threads: {},
    errors: {},
    drafts: {},
    setDraft: (chat, text) => set((s) => ({ drafts: { ...s.drafts, [chat]: text } })),

    async ask(question) {
      const chat = activeChat();
      const text = question.trim();
      if (!chat || !text) return;
      // Show the question at once; the snapshot replaces it.
      const optimistic: SideTurn = { requestId: `local-${Date.now()}`, question: text, text: "", status: "queued" };
      set((s) => {
        const thread = s.threads[chat] ?? EMPTY;
        const busy = live(thread);
        return {
          threads: {
            ...s.threads,
            [chat]: busy ? { ...thread, queued: [...thread.queued, text] } : { ...thread, turns: [...thread.turns, optimistic] },
          },
          errors: { ...s.errors, [chat]: undefined },
          drafts: { ...s.drafts, [chat]: "" },
        };
      });
      try {
        await call("start", text);
      } catch (error) {
        set((s) => ({
          threads: {
            ...s.threads,
            [chat]: {
              ...(s.threads[chat] ?? EMPTY),
              turns: (s.threads[chat]?.turns ?? []).filter((t) => t.requestId !== optimistic.requestId),
            },
          },
          errors: { ...s.errors, [chat]: String(error instanceof Error ? error.message : error) },
          drafts: { ...s.drafts, [chat]: s.drafts[chat] || text },
        }));
        return;
      }
      poll(chat);
    },

    async stop() {
      const chat = activeChat();
      if (!chat) return;
      await call("cancel").catch(() => undefined);
      void get().refresh();
    },

    async clear() {
      const chat = activeChat();
      if (!chat) return;
      await call("clear").catch(() => undefined);
      set((s) => ({ threads: { ...s.threads, [chat]: EMPTY }, errors: { ...s.errors, [chat]: undefined } }));
    },

    async refresh() {
      const chat = activeChat();
      if (!chat || useEngineStore.getState().status !== "ready") return;
      try {
        const thread = toThread(await call("status"));
        set((s) => ({ threads: { ...s.threads, [chat]: thread } }));
        if (live(thread)) poll(chat);
      } catch {
        // An older engine without side chat; the panel says so when asking fails.
      }
    },
  };
});

export const sideThreadOf = (chat: string | null) => (chat && useSideChatStore.getState().threads[chat]) || EMPTY;
export { EMPTY as EMPTY_SIDE_THREAD };
