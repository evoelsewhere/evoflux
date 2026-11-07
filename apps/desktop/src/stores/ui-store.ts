// View state that is not owned by the engine.

import { create } from "zustand";
import { persist } from "zustand/middleware";

export type PanelId = "terminal" | "browser" | "files" | "side-chat" | "memory";
/** Panels that exist; a saved tab for any other (Plugins moved to Customize, Scheduler to its page) is dropped. */
const PANEL_IDS: readonly string[] = ["terminal", "browser", "files", "side-chat", "memory"];
export type ApprovalMode = "ask" | "auto-edits" | "auto";
export type SettingsSection = "general" | "appearance" | "providers" | "office" | "engine" | "sandbox" | "logs" | "about";
export type CustomizeSection = "instructions" | "skills" | "agents" | "connectors" | "plugins" | "hooks" | "languages";

export const SIDEBAR_WIDTH = { min: 220, default: 272, max: 420 } as const;
export const SIDE_PANEL_WIDTH = { min: 300, default: 440 } as const;

interface UiStore {
  sidebarOpen: boolean;
  sidebarWidth: number;
  sidePanelWidth: number;
  rightPanelOpen: boolean;
  /**
   * The chat summary card (changes, task, progress) pinned beside the thread,
   * where it fits next to the messages (`summaryFits`). Where it does not, the
   * toolbar opens it as an overlay instead (`summaryPeek`, not saved).
   */
  summaryOpen: boolean;
  summaryFits: boolean;
  summaryPeek: boolean;
  toggleSummary(open?: boolean): void;
  setSummaryFits(fits: boolean): void;
  setSummaryPeek(peek: boolean): void;
  /** Tools open as tabs in the side panel, in tab order. */
  openTabs: PanelId[];
  /** The visible tab; `null` shows the tool launcher. */
  activePanel: PanelId | null;
  commandOpen: boolean;
  /** The settings page replaces the sidebar and main column while open. */
  settingsOpen: boolean;
  settingsSection: SettingsSection;
  /** Connectors (pool keys) switched off per chat, from the composer's + menu. */
  chatConnectorsOff: Record<string, string[]>;
  setChatConnectorOff(chat: string, key: string, off: boolean): void;
  /** Customize (skills, agents, …) replaces the main column while open. */
  customizeOpen: boolean;
  /** The Scheduler page (sidebar → Scheduler) shows instead of the chat. */
  schedulerOpen: boolean;
  openScheduler(): void;
  /** The Usage page (sidebar → Usage) shows instead of the chat. */
  usageOpen: boolean;
  openUsage(): void;
  customizeSection: CustomizeSection;
  openCustomize(section?: CustomizeSection): void;
  closeCustomize(): void;
  approval: ApprovalMode;
  /** `provider/id` keys shown at the top of the model menu, in a stable order. */
  pinnedModels: string[];
  /** Page zoom (1 = 100%). */
  zoom: number;
  /** The app "Open in" used last; the toolbar's one-click target. */
  openInApp: string | null;
  setOpenInApp(id: string): void;
  /** Agents may start nested sessions without asking (otherwise they propose). */
  autoStartSessions: boolean;
  setAutoStartSessions(on: boolean): void;
  /** What became of each proposed session: started (with its id) or dismissed. */
  proposals: Record<string, { status: "started" | "dismissed"; sessionId?: string }>;
  settleProposal(id: string, outcome: { status: "started" | "dismissed"; sessionId?: string }): void;
  /** Worktrees whose changes were applied or discarded, by path. */
  settledWorktrees: Record<string, "applied" | "discarded">;
  settleWorktree(path: string, outcome: "applied" | "discarded"): void;
  setZoom(zoom: number): void;
  setSidebarOpen(open: boolean): void;
  setSidebarWidth(width: number): void;
  setSidePanelWidth(width: number): void;
  toggleRightPanel(open?: boolean): void;
  /** Open `panel` as a tab (or focus it); `null` shows the launcher. */
  openPanel(panel: PanelId | null): void;
  closeTab(panel: PanelId): void;
  /** Close every tab but `panel`, which becomes the visible one. */
  closeOtherTabs(panel: PanelId): void;
  closeAllTabs(): void;
  /** Show the next (`1`) or previous (`-1`) tab, wrapping around. */
  cycleTab(step: 1 | -1): void;
  setCommandOpen(open: boolean): void;
  /** Open the settings page, on `section` when given. */
  openSettings(section?: SettingsSection): void;
  closeSettings(): void;
  setApproval(mode: ApprovalMode): void;
  setPinnedModels(keys: string[]): void;
}

export const PINNED_MODELS_MAX = 4;

const clampWidth = (width: number) => Math.round(Math.min(SIDEBAR_WIDTH.max, Math.max(SIDEBAR_WIDTH.min, width)));

export const useUiStore = create<UiStore>()(
  persist(
    (set, get) => ({
      sidebarOpen: true,
      sidebarWidth: SIDEBAR_WIDTH.default,
      sidePanelWidth: SIDE_PANEL_WIDTH.default,
      rightPanelOpen: false,
      summaryOpen: true,
      summaryFits: true,
      summaryPeek: false,
      toggleSummary: (open) =>
        get().summaryFits
          ? set({ summaryOpen: open ?? !get().summaryOpen })
          : set({ summaryPeek: open ?? !get().summaryPeek }),
      setSummaryFits: (summaryFits) => set({ summaryFits, summaryPeek: false }),
      setSummaryPeek: (summaryPeek) => set({ summaryPeek }),
      openTabs: [],
      activePanel: null,
      commandOpen: false,
      settingsOpen: false,
      customizeOpen: false,
      schedulerOpen: false,
      openScheduler: () =>
        set({ schedulerOpen: true, usageOpen: false, customizeOpen: false, settingsOpen: false, commandOpen: false }),
      usageOpen: false,
      openUsage: () =>
        set({ usageOpen: true, schedulerOpen: false, customizeOpen: false, settingsOpen: false, commandOpen: false }),
      customizeSection: "skills",
      chatConnectorsOff: {},
      setChatConnectorOff: (chat, key, off) =>
        set((s) => {
          const current = s.chatConnectorsOff[chat] ?? [];
          const next = off ? [...new Set([...current, key])] : current.filter((k) => k !== key);
          const all = { ...s.chatConnectorsOff };
          if (next.length) all[chat] = next;
          else delete all[chat];
          return { chatConnectorsOff: all };
        }),
      settingsSection: "general",
      approval: "ask",
      pinnedModels: [],
      zoom: 1,
      openInApp: null,
      setOpenInApp: (openInApp) => set({ openInApp }),
      autoStartSessions: false,
      setAutoStartSessions: (autoStartSessions) => set({ autoStartSessions }),
      proposals: {},
      settleProposal: (id, outcome) => set((s) => ({ proposals: { ...s.proposals, [id]: outcome } })),
      settledWorktrees: {},
      settleWorktree: (path, outcome) => set((s) => ({ settledWorktrees: { ...s.settledWorktrees, [path]: outcome } })),
      setZoom: (zoom) => set({ zoom }),
      setSidebarOpen: (sidebarOpen) => set({ sidebarOpen }),
      setSidebarWidth: (width) => set({ sidebarWidth: clampWidth(width) }),
      setSidePanelWidth: (width) => set({ sidePanelWidth: Math.max(SIDE_PANEL_WIDTH.min, Math.round(width)) }),
      toggleRightPanel: (open) => set({ rightPanelOpen: open ?? !get().rightPanelOpen }),
      openPanel: (panel) =>
        set((s) => ({
          activePanel: panel,
          rightPanelOpen: true,
          openTabs: panel && !s.openTabs.includes(panel) ? [...s.openTabs, panel] : s.openTabs,
        })),
      closeTab: (panel) =>
        set((s) => {
          const index = s.openTabs.indexOf(panel);
          const openTabs = s.openTabs.filter((t) => t !== panel);
          // Closing the visible tab shows its neighbour, or the launcher when none is left.
          const activePanel =
            s.activePanel === panel ? (openTabs[Math.min(index, openTabs.length - 1)] ?? null) : s.activePanel;
          return { openTabs, activePanel };
        }),
      closeOtherTabs: (panel) => set({ openTabs: [panel], activePanel: panel }),
      closeAllTabs: () => set({ openTabs: [], activePanel: null }),
      cycleTab: (step) =>
        set((s) => {
          if (s.openTabs.length === 0) return s;
          const index = s.activePanel ? s.openTabs.indexOf(s.activePanel) : step > 0 ? -1 : 0;
          const next = (index + step + s.openTabs.length) % s.openTabs.length;
          return { activePanel: s.openTabs[next], rightPanelOpen: true };
        }),
      setCommandOpen: (commandOpen) => set({ commandOpen }),
      openSettings: (section) =>
        set((s) => ({ settingsOpen: true, settingsSection: section ?? s.settingsSection, commandOpen: false })),
      closeSettings: () => set({ settingsOpen: false }),
      openCustomize: (section) =>
        set((s) => ({
          customizeOpen: true,
          schedulerOpen: false,
          usageOpen: false,
          customizeSection: section ?? s.customizeSection,
          settingsOpen: false,
          commandOpen: false,
        })),
      // Leaves any full page (Customize, Scheduler or Usage) for the chat.
      closeCustomize: () => set({ customizeOpen: false, schedulerOpen: false, usageOpen: false }),
      setApproval: (approval) => set({ approval }),
      setPinnedModels: (keys) => set({ pinnedModels: keys.slice(0, PINNED_MODELS_MAX) }),
    }),
    {
      name: "evo.ui",
      merge: (persisted, current) => {
        const saved = (persisted ?? {}) as Partial<UiStore>;
        const openTabs = (saved.openTabs ?? current.openTabs).filter((id) => PANEL_IDS.includes(id));
        const activePanel = saved.activePanel && PANEL_IDS.includes(saved.activePanel) ? saved.activePanel : (openTabs[0] ?? null);
        return { ...current, ...saved, openTabs, activePanel };
      },
      partialize: (state) => ({
        approval: state.approval,
        pinnedModels: state.pinnedModels,
        zoom: state.zoom,
        openInApp: state.openInApp,
        autoStartSessions: state.autoStartSessions,
        proposals: state.proposals,
        settledWorktrees: state.settledWorktrees,
        rightPanelOpen: state.rightPanelOpen,
        summaryOpen: state.summaryOpen,
        sidebarOpen: state.sidebarOpen,
        sidebarWidth: state.sidebarWidth,
        sidePanelWidth: state.sidePanelWidth,
        openTabs: state.openTabs,
        chatConnectorsOff: state.chatConnectorsOff,
        activePanel: state.activePanel,
      }),
    },
  ),
);
