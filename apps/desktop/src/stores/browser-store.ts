// In-app browser: tabs (each a native child webview, src-tauri/src/browser.rs),
// which one shows, and where. The side panel's browser view reports the area
// the page should cover; the active tab is shown there only while the
// Browser tool is visible and nothing (a menu, a dialog) lies over it.

import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { create } from "zustand";
import { persist } from "zustand/middleware";
import { inTauri } from "@/lib/platform";
import { useUiStore } from "./ui-store";

export interface BrowserTab {
  /** The child webview's label. */
  id: string;
  url: string;
  title: string;
  loading: boolean;
}

export interface Bounds {
  x: number;
  y: number;
  width: number;
  height: number;
}

interface BrowserStore {
  tabs: BrowserTab[];
  activeId: string | null;
  /** Where pages show, in window logical pixels; `null` while the view is not mounted. */
  bounds: Bounds | null;
  /** A menu or dialog covers the page area: hide the native view meanwhile. */
  covered: boolean;
  /** Recently visited URLs, newest first (for the start page). */
  history: string[];
  error: string | null;
  /** Open `url` in a new tab (shown); resolves to its id. */
  newTab(url: string, options?: { background?: boolean }): Promise<string | null>;
  closeTab(id: string): void;
  select(id: string): void;
  navigate(id: string, input: string): Promise<void>;
  go(id: string, action: "back" | "forward" | "reload" | "stop"): void;
  setBounds(bounds: Bounds | null): void;
  setCovered(covered: boolean): void;
  /** Resolve once `id` finishes loading (or after `timeoutMs`). */
  waitForLoad(id: string, timeoutMs?: number): Promise<void>;
}

const HISTORY_MAX = 12;
const loadWaiters = new Map<string, Array<() => void>>();

/** Whether the Browser tool is the visible side panel tool. */
const browserShown = () => {
  const ui = useUiStore.getState();
  return ui.rightPanelOpen && ui.activePanel === "browser";
};

export const useBrowserStore = create<BrowserStore>()(
  persist(
    (set, get) => {
      const patch = (id: string, change: Partial<BrowserTab>) =>
        set((s) => ({ tabs: s.tabs.map((t) => (t.id === id ? { ...t, ...change } : t)) }));

      return {
        tabs: [],
        activeId: null,
        bounds: null,
        covered: false,
        history: [],
        error: null,

        async newTab(url, options = {}) {
          if (!inTauri) return null;
          const bounds = get().bounds ?? { x: 0, y: 0, width: 800, height: 600 };
          try {
            const id = await invoke<string>("browser_create", { url, ...bounds, visible: false });
            set((s) => ({
              tabs: [...s.tabs, { id, url, title: "", loading: true }],
              activeId: options.background && s.activeId ? s.activeId : id,
              error: null,
            }));
            sync();
            return id;
          } catch (error) {
            set({ error: String(error) });
            return null;
          }
        },

        closeTab(id) {
          void invoke("browser_close", { tab: id }).catch(() => undefined);
          set((s) => {
            const index = s.tabs.findIndex((t) => t.id === id);
            const tabs = s.tabs.filter((t) => t.id !== id);
            const activeId = s.activeId === id ? (tabs[Math.min(index, tabs.length - 1)]?.id ?? null) : s.activeId;
            return { tabs, activeId };
          });
          sync();
        },

        select(id) {
          set({ activeId: id });
          sync(true);
        },

        async navigate(id, input) {
          try {
            const url = await invoke<string>("browser_navigate", { tab: id, url: input });
            patch(id, { url, loading: true });
            set({ error: null });
          } catch (error) {
            set({ error: String(error) });
          }
        },

        go(id, action) {
          void invoke("browser_history", { tab: id, action }).catch(() => undefined);
        },

        setBounds(bounds) {
          const current = get().bounds;
          if (
            bounds &&
            current &&
            Math.abs(bounds.x - current.x) < 0.5 &&
            Math.abs(bounds.y - current.y) < 0.5 &&
            Math.abs(bounds.width - current.width) < 0.5 &&
            Math.abs(bounds.height - current.height) < 0.5
          )
            return;
          set({ bounds });
          sync();
        },

        setCovered(covered) {
          if (covered === get().covered) return;
          set({ covered });
          sync();
        },

        waitForLoad(id, timeoutMs = 15000) {
          const tab = get().tabs.find((t) => t.id === id);
          if (!tab?.loading) return Promise.resolve();
          return new Promise((resolve) => {
            const done = () => {
              clearTimeout(timer);
              resolve();
            };
            const timer = setTimeout(done, timeoutMs);
            loadWaiters.set(id, [...(loadWaiters.get(id) ?? []), done]);
          });
        },
      };
    },
    {
      name: "evo.browser",
      partialize: (state) => ({ history: state.history }),
    },
  ),
);

// ── Native views follow the store ────────────────────────────────────────────

let shownTab: string | null = null;

/** Show the active tab at the current bounds (or hide every tab). */
function sync(focus = false) {
  if (!inTauri) return;
  const { tabs, activeId, bounds, covered } = useBrowserStore.getState();
  const visible = browserShown() && !!bounds && !covered && bounds.width > 4 && bounds.height > 4;
  const target = visible && activeId && tabs.some((t) => t.id === activeId) ? activeId : null;
  if (shownTab && shownTab !== target) void invoke("browser_visible", { tab: shownTab, visible: false }).catch(() => undefined);
  if (target && bounds) {
    void invoke("browser_bounds", { tab: target, ...bounds })
      .then(() => invoke("browser_visible", { tab: target, visible: true, focus }))
      .catch(() => undefined);
  }
  shownTab = target;
}

useUiStore.subscribe((state, previous) => {
  if (state.rightPanelOpen !== previous.rightPanelOpen || state.activePanel !== previous.activePanel) sync();
  // Closing the Browser tool tab closes its pages.
  if (previous.openTabs.includes("browser") && !state.openTabs.includes("browser")) {
    for (const tab of useBrowserStore.getState().tabs) useBrowserStore.getState().closeTab(tab.id);
  }
});

/** Re-read a tab's title from the page (title events skip pages without one). */
async function refreshTitle(id: string) {
  const title = await invoke<unknown>("browser_eval", { tab: id, script: "document.title" }).catch(() => null);
  if (typeof title !== "string") return;
  useBrowserStore.setState((s) => ({ tabs: s.tabs.map((t) => (t.id === id ? { ...t, title } : t)) }));
}

/**
 * Take over this window's pages the store lost track of (the window reloaded,
 * or this module was hot-reloaded): they keep running in the native layer.
 * Resolves to the number of tabs adopted.
 */
export async function adoptTabs(): Promise<number> {
  if (!inTauri) return 0;
  const native = await invoke<Array<[string, string]>>("browser_list").catch(() => []);
  const known = new Set(useBrowserStore.getState().tabs.map((t) => t.id));
  const fresh = native.filter(([id]) => !known.has(id));
  if (!fresh.length) return 0;
  useBrowserStore.setState((s) => ({
    tabs: [...s.tabs, ...fresh.map(([id, url]) => ({ id, url, title: "", loading: false }))],
    activeId: s.activeId ?? fresh[fresh.length - 1][0],
  }));
  for (const [id] of fresh) void refreshTitle(id);
  sync();
  return fresh.length;
}

if (inTauri) {
  void adoptTabs();
  const unlisten = listen<{ tab: string; kind: string; url?: string; title?: string }>("browser://event", ({ payload }) => {
    const store = useBrowserStore.getState();
    const { tab, kind, url, title } = payload;
    if (!store.tabs.some((t) => t.id === tab)) return;
    const set = (change: Partial<BrowserTab>) =>
      useBrowserStore.setState((s) => ({ tabs: s.tabs.map((t) => (t.id === tab ? { ...t, ...change } : t)) }));
    if (kind === "loadStart") set({ loading: true, ...(url ? { url } : {}) });
    else if (kind === "loadEnd") {
      set({ loading: false, ...(url ? { url } : {}) });
      void refreshTitle(tab);
      for (const done of loadWaiters.get(tab) ?? []) done();
      loadWaiters.delete(tab);
      if (url && /^https?:/.test(url)) {
        useBrowserStore.setState((s) => ({
          history: [url, ...s.history.filter((h) => h !== url)].slice(0, HISTORY_MAX),
        }));
      }
    } else if (kind === "title") set({ title: title ?? "" });
    else if (kind === "newWindow" && url) void store.newTab(url);
  });
  // A hot-reloaded copy of this module must not leave the old listener behind.
  import.meta.hot?.dispose(() => {
    void unlisten.then((stop) => stop());
  });
}

/** The tab the agent acts on: the given one, else the active one. */
export function agentTab(id?: string): BrowserTab | undefined {
  const { tabs, activeId } = useBrowserStore.getState();
  return tabs.find((t) => t.id === (id || activeId));
}
