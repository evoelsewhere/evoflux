// Back / forward through the chats opened in this window, like a browser.
//
// Every change of the current chat is recorded, except the ones made by going
// back or forward. Chats that no longer exist (an untouched "New chat" is
// discarded when you leave it) are skipped.

import { create } from "zustand";
import { useEngineStore } from "@/stores/engine-store";
import { useSessionStore } from "@/stores/session-store";

const MAX_ENTRIES = 100;

interface HistoryStore {
  entries: string[];
  index: number;
  back(): void;
  forward(): void;
}

let navigating = false;

const exists = (id: string) => useSessionStore.getState().sessions.some((s) => s.id === id);

/** The nearest entry from `index` in direction `step` whose chat still exists. */
function target(entries: string[], index: number, step: 1 | -1): number {
  for (let i = index + step; i >= 0 && i < entries.length; i += step) {
    if (exists(entries[i]) && entries[i] !== entries[index]) return i;
  }
  return -1;
}

export const useHistoryStore = create<HistoryStore>((set, get) => {
  const go = (step: 1 | -1) => {
    const { entries, index } = get();
    const next = target(entries, index, step);
    if (next < 0) return;
    navigating = true;
    set({ index: next });
    void useEngineStore
      .getState()
      .selectSession(entries[next])
      .finally(() => {
        navigating = false;
      });
  };
  return {
    entries: [],
    index: -1,
    back: () => go(-1),
    forward: () => go(1),
  };
});

export const canGoBack = (s: HistoryStore) => target(s.entries, s.index, -1) >= 0;
export const canGoForward = (s: HistoryStore) => target(s.entries, s.index, 1) >= 0;

// Record the chat shown at startup, then every switch that is not a back/forward.
{
  const current = useSessionStore.getState().currentId;
  if (current) useHistoryStore.setState({ entries: [current], index: 0 });
}
useSessionStore.subscribe((state, previous) => {
  if (navigating || !state.currentId || state.currentId === previous.currentId) return;
  const { entries, index } = useHistoryStore.getState();
  // A new visit drops the forward entries, as in a browser.
  const next = [...entries.slice(0, index + 1), state.currentId].slice(-MAX_ENTRIES);
  useHistoryStore.setState({ entries: next, index: next.length - 1 });
});
