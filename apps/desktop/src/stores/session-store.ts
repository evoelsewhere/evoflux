// Workspaces and the chats inside them, as the sidebar shows them — kept in
// the app database on this machine (see `@/lib/db`).
//
// A workspace is a folder the agent works in; chats without one live under
// "This computer". A new chat is a draft until its first prompt: it has an
// engine (and an id) but no row yet, so chats that were never used leave
// nothing behind.

import { emit, listen } from "@tauri-apps/api/event";
import { create } from "zustand";
import { db, log, type DbChat, type DbWorkspace, type TurnRecord } from "@/lib/db";
import { inTauri } from "@/lib/platform";

/** Chat rows changed in one window reach the others (a chat window records its own turns). */
const CHAT_UPDATED = "chat://updated";
const CHAT_REMOVED = "chat://removed";
const WINDOW_TOKEN = Math.random().toString(36).slice(2);
let syncing = false;

export type Workspace = DbWorkspace;

export interface SessionSummary extends Omit<DbChat, "preview" | "provider" | "model"> {
  preview?: string | null;
  provider?: string | null;
  model?: string | null;
  /** Not saved yet: no prompt was sent. */
  draft?: boolean;
}

export const UNTITLED = "New chat";
export const LOCAL_GROUP = "local";

const LAST_CHAT_KEY = "ui.lastChat";
const LOCAL_COLLAPSED_KEY = "sidebar.localCollapsed";

interface SessionStore {
  loaded: boolean;
  workspaces: Workspace[];
  /** Live (not archived) chats, drafts included. */
  sessions: SessionSummary[];
  /** Archived chats, loaded when the archive is opened. */
  archived: SessionSummary[];
  currentId: string | null;
  /** The chat that was open when the app last closed. */
  lastChatId: string | null;
  /** Workspace ids (and "local") whose chat list is collapsed. */
  collapsed: string[];

  load(): Promise<void>;
  ensureWorkspace(path: string): Promise<Workspace>;
  workspaceOf(sessionId: string | null): Workspace | null;
  removeWorkspace(id: string): Promise<string[]>;
  toggleCollapsed(groupId: string): void;

  /** Show a new, unsaved chat and make it current. */
  addDraft(id: string, workspaceId: string | null): SessionSummary;
  /** Drop an unsaved chat. */
  discardDraft(id: string): void;
  /** Save a draft on its first prompt, titled after it. */
  saveDraft(id: string, prompt: string, model?: { provider?: string; model?: string }): Promise<void>;
  select(id: string): void;
  rename(id: string, title: string): Promise<void>;
  setPinned(id: string, pinned: boolean): Promise<void>;
  setArchived(id: string, archived: boolean): Promise<void>;
  markUnread(id: string, unread: boolean): void;
  /** Save a copy of chat `id` (whole transcript) as `newId`; resolves with the copy. */
  fork(id: string, newId: string): Promise<SessionSummary | null>;
  /** Move a chat to another workspace (`null`: "This computer"). */
  move(id: string, workspaceId: string | null): Promise<void>;
  /** Save a chat a scheduled task starts: top level, in the task's folder. */
  createTaskChat(chat: { id: string; workspaceId: string | null; title: string }): Promise<SessionSummary | null>;
  /** Save a chat started by another chat's agent (nested sessions), without showing it. */
  createChild(chat: {
    id: string;
    parentChatId: string;
    workspaceId: string | null;
    title: string;
    worktreePath?: string | null;
  }): Promise<SessionSummary | null>;
  /** The worktree a chat works in, or its workspace folder again (`null`). */
  setWorktree(id: string, worktreePath: string | null): Promise<void>;
  /** Put a chat under another (`parentChatId`), or detach it (`null`). */
  setParent(id: string, parentChatId: string | null): Promise<void>;
  remove(id: string): Promise<void>;
  recordTurn(id: string, turn: TurnRecord): Promise<void>;
  loadArchived(): Promise<void>;
}

const titleFrom = (prompt: string) => prompt.replace(/\s+/g, " ").trim().slice(0, 80) || UNTITLED;

function report(action: string) {
  return (error: unknown) => log("error", "db", `${action} failed: ${String(error)}`);
}

/** Replace (or drop, with `null`) one chat in a list, keeping the sidebar order rules. */
function put(list: SessionSummary[], id: string, chat: SessionSummary | null): SessionSummary[] {
  const rest = list.filter((s) => s.id !== id);
  return chat ? [chat, ...rest] : rest;
}

export const useSessionStore = create<SessionStore>()((set, get) => {
  /** Apply a saved row to whichever list it belongs in, and tell the other windows. */
  const apply = (chat: DbChat | null | undefined, share = true) => {
    if (!chat) return;
    if (share && inTauri) void emit(CHAT_UPDATED, { from: WINDOW_TOKEN, chat }).catch(() => undefined);
    set((s) => {
      const row: SessionSummary = { ...chat };
      return chat.archivedAt
        ? { sessions: put(s.sessions, chat.id, null), archived: put(s.archived, chat.id, row) }
        : {
            sessions: s.sessions.some((x) => x.id === chat.id)
              ? s.sessions.map((x) => (x.id === chat.id ? row : x))
              : [row, ...s.sessions],
            archived: put(s.archived, chat.id, null),
          };
    });
  };

  return {
    loaded: false,
    workspaces: [],
    sessions: [],
    archived: [],
    currentId: null,
    lastChatId: null,
    collapsed: [],

    async load() {
      if (inTauri && !syncing) {
        syncing = true;
        void listen<{ from: string; chat: DbChat }>(CHAT_UPDATED, ({ payload }) => {
          if (payload.from !== WINDOW_TOKEN) apply(payload.chat, false);
        });
        void listen<{ from: string; id: string }>(CHAT_REMOVED, ({ payload }) => {
          if (payload.from === WINDOW_TOKEN) return;
          set((s) => ({ sessions: put(s.sessions, payload.id, null), archived: put(s.archived, payload.id, null) }));
        });
      }
      const [workspaces, chats, settings] = await Promise.all([db.workspaces(), db.chats(false), db.settings()]);
      const collapsed = workspaces.filter((w) => w.collapsed).map((w) => w.id);
      if (settings[LOCAL_COLLAPSED_KEY] === true) collapsed.push(LOCAL_GROUP);
      const last = typeof settings[LAST_CHAT_KEY] === "string" ? (settings[LAST_CHAT_KEY] as string) : null;
      set({
        loaded: true,
        workspaces,
        sessions: chats,
        collapsed,
        lastChatId: chats.some((c) => c.id === last) ? last : null,
      });
    },

    async ensureWorkspace(path) {
      const workspace = await db.ensureWorkspace(path);
      set((s) => ({
        workspaces: s.workspaces.some((w) => w.id === workspace.id)
          ? s.workspaces.map((w) => (w.id === workspace.id ? workspace : w))
          : [...s.workspaces, workspace].sort((a, b) => a.name.localeCompare(b.name)),
      }));
      return workspace;
    },

    workspaceOf(sessionId) {
      const session = get().sessions.find((s) => s.id === sessionId) ?? get().archived.find((s) => s.id === sessionId);
      return get().workspaces.find((w) => w.id === session?.workspaceId) ?? null;
    },

    async removeWorkspace(id) {
      const removed = await db.removeWorkspace(id);
      set((s) => ({
        workspaces: s.workspaces.filter((w) => w.id !== id),
        sessions: s.sessions.filter((session) => session.workspaceId !== id),
        archived: s.archived.filter((session) => session.workspaceId !== id),
      }));
      return removed;
    },

    toggleCollapsed(groupId) {
      const collapsed = !get().collapsed.includes(groupId);
      set((s) => ({ collapsed: collapsed ? [...s.collapsed, groupId] : s.collapsed.filter((g) => g !== groupId) }));
      const saved =
        groupId === LOCAL_GROUP ? db.setSetting(LOCAL_COLLAPSED_KEY, collapsed) : db.setWorkspaceCollapsed(groupId, collapsed);
      saved.catch(report("saving the sidebar"));
    },

    addDraft(id, workspaceId) {
      const now = Date.now();
      const draft: SessionSummary = {
        id,
        workspaceId,
        title: UNTITLED,
        titleSource: "auto",
        pinned: false,
        unread: false,
        archivedAt: null,
        turnCount: 0,
        costUsd: 0,
        tokens: 0,
        createdAt: now,
        updatedAt: now,
        parentChatId: null,
        origin: "user",
        worktreePath: null,
        draft: true,
      };
      set((s) => ({
        sessions: [draft, ...s.sessions],
        currentId: id,
        collapsed: s.collapsed.filter((g) => g !== (workspaceId ?? LOCAL_GROUP)),
      }));
      return draft;
    },

    discardDraft(id) {
      set((s) => ({ sessions: s.sessions.filter((x) => !(x.id === id && x.draft)) }));
    },

    async saveDraft(id, prompt, model) {
      const draft = get().sessions.find((s) => s.id === id);
      if (!draft?.draft) return;
      // Show the title at once; the row follows.
      set((s) => ({
        sessions: s.sessions.map((x) => (x.id === id ? { ...x, title: titleFrom(prompt), updatedAt: Date.now() } : x)),
      }));
      const chat = await db
        .createChat({ id, workspaceId: draft.workspaceId, title: titleFrom(prompt), provider: model?.provider, model: model?.model })
        .catch((error) => {
          report("saving the chat")(error);
          return null;
        });
      if (chat) {
        apply(chat);
        set((s) => ({ sessions: s.sessions.map((x) => (x.id === id ? { ...x, draft: undefined } : x)) }));
        void db.setSetting(LAST_CHAT_KEY, id).catch(() => undefined);
      }
    },

    select(id) {
      set({ currentId: id });
      const chat = get().sessions.find((s) => s.id === id);
      if (chat && !chat.draft) {
        void db.setSetting(LAST_CHAT_KEY, id).catch(() => undefined);
        if (chat.unread) get().markUnread(id, false);
      }
    },

    async rename(id, title) {
      const clean = title.replace(/\s+/g, " ").trim().slice(0, 120);
      if (!clean) return;
      const chat = get().sessions.find((s) => s.id === id);
      if (chat?.draft) return;
      set((s) => ({ sessions: s.sessions.map((x) => (x.id === id ? { ...x, title: clean, titleSource: "user" } : x)) }));
      apply(await db.updateChat(id, { title: clean }).catch(report("renaming the chat")) ?? null);
    },

    async setPinned(id, pinned) {
      set((s) => ({ sessions: s.sessions.map((x) => (x.id === id ? { ...x, pinned } : x)) }));
      apply(await db.updateChat(id, { pinned }).catch(report("pinning the chat")) ?? null);
    },

    async setArchived(id, archived) {
      apply(await db.updateChat(id, { archived }).catch(report("archiving the chat")) ?? null);
    },

    markUnread(id, unread) {
      set((s) => ({
        sessions: s.sessions.map((x) => (x.id === id ? { ...x, unread } : x)),
      }));
      if (!get().sessions.find((s) => s.id === id)?.draft) {
        void db.updateChat(id, { unread }).catch(report("marking the chat"));
      }
    },

    async fork(id, newId) {
      const source = get().sessions.find((s) => s.id === id) ?? get().archived.find((s) => s.id === id);
      if (!source || source.draft) return null;
      const chat = await db.forkChat(id, newId, `${source.title} (fork)`).catch((error) => {
        report("forking the chat")(error);
        return null;
      });
      apply(chat);
      return chat;
    },

    async move(id, workspaceId) {
      const chat = get().sessions.find((s) => s.id === id);
      if (!chat || chat.draft || chat.workspaceId === workspaceId) return;
      set((s) => ({ sessions: s.sessions.map((x) => (x.id === id ? { ...x, workspaceId } : x)) }));
      apply(await db.moveChat(id, workspaceId).catch(report("moving the chat")) ?? null);
    },

    async createTaskChat({ id, workspaceId, title }) {
      const chat = await db.createChat({ id, workspaceId, title: titleFrom(title) }).catch((error) => {
        report("saving the scheduled chat")(error);
        return null;
      });
      apply(chat);
      return chat;
    },

    async createChild({ id, parentChatId, workspaceId, title, worktreePath = null }) {
      const chat = await db
        .createChat({ id, parentChatId, workspaceId, title: titleFrom(title), origin: "agent", worktreePath })
        .catch((error) => {
          report("saving the nested chat")(error);
          return null;
        });
      apply(chat);
      return chat;
    },

    async setWorktree(id, worktreePath) {
      set((s) => ({ sessions: s.sessions.map((x) => (x.id === id ? { ...x, worktreePath } : x)) }));
      apply(await db.setWorktree(id, worktreePath).catch(report("saving the chat's worktree")) ?? null);
    },

    async setParent(id, parentChatId) {
      set((s) => ({ sessions: s.sessions.map((x) => (x.id === id ? { ...x, parentChatId } : x)) }));
      apply(await db.setParent(id, parentChatId).catch(report("linking the chat")) ?? null);
    },

    async remove(id) {
      const chat = get().sessions.find((s) => s.id === id) ?? get().archived.find((s) => s.id === id);
      set((s) => ({ sessions: put(s.sessions, id, null), archived: put(s.archived, id, null) }));
      if (chat && !chat.draft) {
        await db.deleteChat(id).catch(report("deleting the chat"));
        if (inTauri) void emit(CHAT_REMOVED, { from: WINDOW_TOKEN, id }).catch(() => undefined);
      }
    },

    async recordTurn(id, turn) {
      if (get().sessions.find((s) => s.id === id)?.draft) return;
      apply(await db.recordTurn(id, turn).catch(report("saving the turn")) ?? null);
    },

    async loadArchived() {
      const archived = await db.chats(true).catch(() => []);
      set({ archived });
    },
  };
});

// Development: a new copy of this module would start with no chats while the
// engine store still holds the old one. Reload the window instead.
if (import.meta.hot) import.meta.hot.accept(() => window.location.reload());
