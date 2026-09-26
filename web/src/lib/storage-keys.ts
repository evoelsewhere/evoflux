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
  locale: 'oa-locale',
  accessKey: 'EvoFlux.accessKey',
  lastRoute: 'oa-last-route',
  pinnedSessions: 'oa.pinnedSessions',
  /** Version of the exact Office renderer whose install offer the user hid. */
  officeRuntimeOfferHidden: 'oa.officeRuntime.offerHidden',
  /** "false" stops documents an agent creates from opening their preview. */
  autoOpenGeneratedDocuments: 'oa.documents.autoOpenGenerated',
  modeRoutes: {
    work: 'oa-last-route-work',
    coding: 'oa-last-route-coding',
  },
  /** Read-only migration keys from mode names used by older releases. */
  legacyModeRoutes: {
    work: 'oa-last-route-forge',
  },

  sidebar: {
    width: 'oa.sidebar.width',
    collapsed: 'oa-sidebar-collapsed',
    codingWidth: 'oa.codingSidebar.width',
  },

  /** Resizable panel widths (useResizableWidth / SidePanel storageKey props). */
  panels: {
    activity: 'oa.activityPanel.width',
    changes: 'oa.changesPanel.width',
    changeSet: 'oa.changeSetPanel.width',
    terminal: 'oa.terminalPanel.width',
    codingWorkspace: 'oa.codingWorkspacePanel.width',
    codingWorkspacePicker: 'oa.codingWorkspacePicker.width',
    codingFileViewer: 'oa.codingFileViewer.width',
    plan: 'planPanelWidth',
    workspace: 'workspace-panel-width',
    workspaceTree: 'workspace-tree-width',
    codingWorkspaceTree: 'oa.codingWorkspace.treeWidth',
    sideChat: 'oa.sideChatPanel.width',
    workbench: 'oa.workbenchPanel.width',
    workbenchMaximized: 'oa.workbenchPanel.maximized',
  },

  workspaceFiles: {
    treeVisible: 'oa.workspaceFiles.treeVisible',
    codingTreeVisible: 'oa.codingWorkspace.treeVisible',
  },

  /** Coding workspace list + last-used pointers (utils/workspace.ts). */
  coding: {
    workspaces: 'oa-coding-workspaces',
    lastWorkspace: 'oa-last-coding-workspace',
    lastProject: 'oa-last-coding-project',
    lastFocus: 'oa-last-coding-focus',
    expanded: 'oa.codingSidebar.expanded',
  },

  /** Work sidebar UI state. */
  work: {
    foldersExpanded: 'oa.workSidebar.foldersExpanded',
    recentCollapsed: 'oa.workSidebar.recentCollapsed',
    recentWorkspaceFolders: 'oa.work.recentWorkspaceFolders',
  },

  enterprise: {
    favorites: 'oa.enterprise.favorites',
  },

  desktopNotifications: {
    enabled: 'oa-desktop-notifications-enabled',
    soundEnabled: 'oa-desktop-notifications-sound-enabled',
  },

  browser: {
    preferences: 'oa.browser.preferences',
    zoomByOrigin: 'oa.browser.zoom-by-origin',
    recentSites: 'oa.browser.recent-sites',
    previewPlacement: 'oa.browser.preview-placement',
    webBridgeDefaultEnabled: 'oa.browser.webbridge-default-enabled',
  },

  computerApp: {
    previewPlacement: 'oa.computer-app.preview-placement',
    /** sessionStorage: this window's open cards, kept across a reload. */
    openCards: 'oa.computer-app.open-cards',
  },
} as const
