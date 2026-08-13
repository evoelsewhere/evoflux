/**
 * Drag payload shared by the session rows and the sidebar folder drop zones.
 *
 * A custom MIME type is used so a folder only accepts sessions dragged from
 * the sidebar and ignores unrelated drags (files, text, links) — the composer
 * already treats file drops as attachments.
 */

export const SESSION_DRAG_MIME = 'application/x-evoflux-session-id'
export const SESSION_FOLDER_DROP_ZONE = 'data-session-folder-drop-zone'
export const SESSION_UNFILE_DROP_ZONE = 'data-session-unfile-drop-zone'

// WebKit/WKWebView can omit custom MIME types from DataTransfer during
// dragenter/dragover (and may return an empty value on drop). Keep the id in
// memory as the authoritative fallback for drags that originate in this
// window. This also avoids accepting unrelated text/file drops as sessions.
let activeSessionDragId: string | null = null
// `undefined` means the pointer is not over a valid target; `null` is the
// intentional target for moving a session back to Recent.
let activeSessionDropTarget: string | null | undefined
let sessionDropHandled = false

export function setSessionDragPayload(event: React.DragEvent, sessionId: string): void {
  activeSessionDragId = sessionId
  activeSessionDropTarget = undefined
  sessionDropHandled = false
  try {
    event.dataTransfer.setData(SESSION_DRAG_MIME, sessionId)
  } catch {
    // Some embedded WebViews reject custom MIME types. The in-memory value
    // still lets this window's folder drop zones recognize the session.
  }
  // Some browsers refuse to start a drag without a text/plain fallback.
  event.dataTransfer.setData('text/plain', sessionId)
  event.dataTransfer.effectAllowed = 'move'
}

/** True when the in-flight drag carries a sidebar session. */
export function isSessionDrag(event: React.DragEvent): boolean {
  return activeSessionDragId !== null
    || Array.from(event.dataTransfer.types).includes(SESSION_DRAG_MIME)
}

export function readSessionDragPayload(event: React.DragEvent): string | null {
  try {
    const id = event.dataTransfer.getData(SESSION_DRAG_MIME)
    return id || activeSessionDragId
  } catch {
    return activeSessionDragId
  }
}

export function setSessionDropTarget(folderId: string | null): void {
  activeSessionDropTarget = folderId
}

export function clearSessionDropTarget(folderId: string | null): void {
  if (activeSessionDropTarget === folderId) activeSessionDropTarget = undefined
}

export function readSessionDropTarget(): string | null | undefined {
  return activeSessionDropTarget
}

export function readSessionDropTargetFromElement(
  element: Element | null,
): string | null | undefined {
  const folderZone = element?.closest<HTMLElement>(`[${SESSION_FOLDER_DROP_ZONE}]`)
  const folderId = folderZone?.getAttribute(SESSION_FOLDER_DROP_ZONE)
  if (folderId) return folderId
  return element?.closest(`[${SESSION_UNFILE_DROP_ZONE}]`) ? null : undefined
}

export function markSessionDropHandled(): void {
  sessionDropHandled = true
}

export function wasSessionDropHandled(): boolean {
  return sessionDropHandled
}

export function clearSessionDragPayload(): void {
  activeSessionDragId = null
  activeSessionDropTarget = undefined
  sessionDropHandled = false
}
