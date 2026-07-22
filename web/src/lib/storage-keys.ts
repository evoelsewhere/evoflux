/**
 * STORAGE_KEYS — central registry of every Web Storage key the app persists
 * under (localStorage unless noted otherwise). Never rename a value: these
 * strings are persisted user state, and changing one orphans existing data.
 *
 * Pre-paint scripts: `web/public/theme-init.js` and
 * `web/public/appearance-init.js` run before the first paint and CANNOT
 * import TS — they hard-code the `oa-theme` / `oa-appearance` literals.
 * `STORAGE_KEYS.theme` / `STORAGE_KEYS.appearance` MUST stay in sync with
 * those two scripts by hand.
 */
export const STORAGE_KEYS = {
  theme: 'oa-theme',
  appearance: 'oa-appearance',
  accessKey: 'EvoFlux.accessKey',
  lastRoute: 'oa-last-route',
  lastAimProject: 'oa-last-aim-project',
  pinnedSessions: 'oa.pinnedSessions',
  /** JSON map of sessionId → true: WebBridge banner dismissed per session. */
  webbridgeBannerDismissed: 'oa.webbridgeBannerDismissed',

  sidebar: {
    width: 'oa.sidebar.width',
    collapsed: 'oa-sidebar-collapsed',
    codingWidth: 'oa.codingSidebar.width',
    aimWidth: 'oa.aimSidebar.width',
  },

  /** Resizable panel widths (useResizableWidth / SidePanel storageKey props). */
  panels: {
    activity: 'oa.activityPanel.width',
    terminal: 'oa.terminalPanel.width',
    codingWorkspace: 'oa.codingWorkspacePanel.width',
    codingFileViewer: 'oa.codingFileViewer.width',
    plan: 'planPanelWidth',
    workspace: 'workspace-panel-width',
    workspaceTree: 'workspace-tree-width',
    aimDiscussion: 'oa.aimDiscussion.width',
    aimMonitor: 'oa.aimMonitor.width',
    aimReport: 'oa.aimReport.width',
    aimUnitDetail: 'oa.aimUnitDetail.width',
    sideChat: 'oa.sideChatPanel.width',
  },

  /** Coding workspace list + last-used pointers (utils/workspace.ts). */
  coding: {
    workspaces: 'oa-coding-workspaces',
    lastWorkspace: 'oa-last-coding-workspace',
    lastFocus: 'oa-last-coding-focus',
    expanded: 'oa.codingSidebar.expanded',
  },

  /** AIM sidebar UI state. */
  aim: {
    expanded: 'oa.aimSidebar.expanded',
  },

  desktopNotifications: {
    enabled: 'oa-desktop-notifications-enabled',
    soundEnabled: 'oa-desktop-notifications-sound-enabled',
  },

  /** sessionStorage, not localStorage — ephemeral one-shot handoffs. */
  aimHandoff: {
    pipelinePrefill: 'oa-aim-pipeline-prefill',
    kbOpen: 'oa-aim-kb-open',
  },
} as const
