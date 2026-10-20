/**
 * One browser per chat session, whatever is showing it.
 *
 * The PiP and the workbench browser panel used to be two independent
 * browsers — separate tab lists and separate WebViews — so the panel never
 * showed the page that was in the PiP, and closing the panel destroyed the
 * browser instead of returning it. The state now lives here, per session:
 * a surface (the PiP, or a browser tab in the workbench) is only a view
 * target — a rect and a zoom — onto the session's pages. Handing the
 * browser over is re-targeting the view; no WebView is moved, re-parented
 * or recreated.
 */

import type { Webview } from '@tauri-apps/api/webview'

import type { DirectBrowserTab } from './useDirectBrowserTabs'

export type DirectBrowserSurfaceKind = 'pip' | 'panel'

export interface DirectBrowserSurfaceSlot {
  /** `pip` for the floating preview; `panel:<workbench tab id>` for a panel. */
  id: string
  kind: DirectBrowserSurfaceKind
  visible: boolean
  /** The page this surface shows. The PiP always follows the active tab. */
  boundTabId: string | null
}

export interface DirectBrowserSession {
  sessionId: string
  tabs: DirectBrowserTab[]
  activeTabId: string | null
  webviews: Map<string, Webview>
  visibility: Map<string, boolean>
  surfaces: Map<string, DirectBrowserSurfaceSlot>
  listeners: Set<() => void>
  /** Surface currently opening a page, so two views never both do. */
  creatingBy: string | null
  /** When the last view of this session went away; null while one is shown. */
  detachedAt: number | null
}

/**
 * Sessions that keep live WebViews with no view showing them. Their pages
 * cannot be restored once closed, so a few are kept for coming back to; past
 * this the longest-detached ones are closed so a long day of chats does not
 * leave an engine process per chat running.
 */
export const MAX_DETACHED_BROWSER_SESSIONS = 3

const sessions = new Map<string, DirectBrowserSession>()

export function getDirectBrowserSession(sessionId: string): DirectBrowserSession {
  let session = sessions.get(sessionId)
  if (!session) {
    session = {
      sessionId,
      tabs: [],
      activeTabId: null,
      webviews: new Map(),
      visibility: new Map(),
      surfaces: new Map(),
      listeners: new Set(),
      creatingBy: null,
      detachedAt: null,
    }
    sessions.set(sessionId, session)
  }
  return session
}

export function subscribeDirectBrowserSession(
  sessionId: string,
  listener: () => void,
): () => void {
  const session = getDirectBrowserSession(sessionId)
  session.listeners.add(listener)
  return () => {
    session.listeners.delete(listener)
  }
}

/** Tell every surface of this session to re-render its view of the state. */
export function notifyDirectBrowserSession(sessionId: string): void {
  const session = sessions.get(sessionId)
  if (!session) return
  for (const listener of [...session.listeners]) listener()
}

export function setDirectBrowserActiveTab(
  sessionId: string,
  tabId: string | null,
): void {
  const session = getDirectBrowserSession(sessionId)
  if (session.activeTabId === tabId) return
  session.activeTabId = tabId
  notifyDirectBrowserSession(sessionId)
}

export function registerDirectBrowserSurfaceSlot(
  sessionId: string,
  slot: DirectBrowserSurfaceSlot,
): void {
  const session = getDirectBrowserSession(sessionId)
  session.surfaces.set(slot.id, { ...slot })
  session.detachedAt = null
  notifyDirectBrowserSession(sessionId)
}

export function updateDirectBrowserSurfaceSlot(
  sessionId: string,
  id: string,
  patch: Partial<Omit<DirectBrowserSurfaceSlot, 'id'>>,
): void {
  const session = sessions.get(sessionId)
  const slot = session?.surfaces.get(id)
  if (!session || !slot) return
  Object.assign(slot, patch)
  notifyDirectBrowserSession(sessionId)
}

export function unregisterDirectBrowserSurfaceSlot(
  sessionId: string,
  id: string,
): void {
  const session = sessions.get(sessionId)
  if (!session) return
  session.surfaces.delete(id)
  if (session.surfaces.size === 0) {
    session.detachedAt = Date.now()
    trimDetachedDirectBrowserSessions()
  }
  notifyDirectBrowserSession(sessionId)
}

/** Close the longest-detached sessions beyond the cap. */
export function trimDetachedDirectBrowserSessions(
  keep = MAX_DETACHED_BROWSER_SESSIONS,
): void {
  const detached = [...sessions.values()]
    .filter(
      (session) =>
        session.detachedAt !== null
        && session.surfaces.size === 0
        && session.creatingBy === null
        && session.webviews.size > 0,
    )
    .sort((a, b) => (b.detachedAt ?? 0) - (a.detachedAt ?? 0))
  for (const session of detached.slice(keep)) {
    closeSessionWebviews(session)
    notifyDirectBrowserSession(session.sessionId)
  }
}

/**
 * Which surface shows *tabId* right now. A visible panel wins over the PiP
 * so docking never fights over a WebView; a tab no surface is showing is
 * hidden and belongs to nobody.
 */
export function claimantForTab(
  session: DirectBrowserSession,
  tabId: string,
): string | null {
  for (const slot of session.surfaces.values()) {
    if (slot.kind === 'panel' && slot.visible && slot.boundTabId === tabId) {
      return slot.id
    }
  }
  const pip = [...session.surfaces.values()].find(
    (slot) => slot.kind === 'pip' && slot.visible,
  )
  if (pip && session.activeTabId === tabId) return pip.id
  return null
}

/** Panel before PiP: docking hides the preview, undocking brings it back. */
export function activeDirectBrowserSurface(
  session: DirectBrowserSession,
): DirectBrowserSurfaceSlot | null {
  const visiblePanel = [...session.surfaces.values()].find(
    (slot) => slot.kind === 'panel' && slot.visible,
  )
  if (visiblePanel) return visiblePanel
  return [...session.surfaces.values()].find((slot) => slot.kind === 'pip') ?? null
}

export function hasLiveBrowserTabs(sessionId: string): boolean {
  const session = sessions.get(sessionId)
  return Boolean(session && session.tabs.length > 0)
}

function closeSessionWebviews(session: DirectBrowserSession): void {
  for (const webview of session.webviews.values()) {
    void Promise.resolve(webview.close()).catch(() => {
      // Already gone, or no desktop shell left to close it with.
    })
  }
  session.webviews.clear()
  session.visibility.clear()
  session.tabs = []
  session.activeTabId = null
}

/**
 * Drop a session whose pages are all closed. Unmounting a surface never
 * brings the browser down — only an empty tab list does. The state object
 * keeps its identity so live surfaces referencing it stay coherent.
 */
export function disposeDirectBrowserSessionIfAbandoned(sessionId: string): void {
  const session = sessions.get(sessionId)
  if (!session || session.tabs.length > 0) return
  closeSessionWebviews(session)
}

/**
 * Explicitly closing the PiP is the one user action that may end the
 * browser — and only when no panel surface is still showing the session.
 */
export function disposeDirectBrowserSessionIfUnused(sessionId: string): void {
  const session = sessions.get(sessionId)
  if (!session) return
  for (const slot of session.surfaces.values()) {
    if (slot.kind === 'panel') return
  }
  closeSessionWebviews(session)
}

export function disposeDirectBrowserSession(sessionId: string): void {
  const session = sessions.get(sessionId)
  if (!session) return
  closeSessionWebviews(session)
  sessions.delete(sessionId)
}
