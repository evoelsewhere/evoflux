/**
 * Drag payload shared by the session rows and the sidebar folder drop zones.
 *
 * A custom MIME type is used so a folder only accepts sessions dragged from
 * the sidebar and ignores unrelated drags (files, text, links) — the composer
 * already treats file drops as attachments.
 */

export const SESSION_DRAG_MIME = 'application/x-evoflux-session-id'

export function setSessionDragPayload(event: React.DragEvent, sessionId: string): void {
  event.dataTransfer.setData(SESSION_DRAG_MIME, sessionId)
  // Some browsers refuse to start a drag without a text/plain fallback.
  event.dataTransfer.setData('text/plain', sessionId)
  event.dataTransfer.effectAllowed = 'move'
}

/** True when the in-flight drag carries a sidebar session. */
export function isSessionDrag(event: React.DragEvent): boolean {
  return Array.from(event.dataTransfer.types).includes(SESSION_DRAG_MIME)
}

export function readSessionDragPayload(event: React.DragEvent): string | null {
  const id = event.dataTransfer.getData(SESSION_DRAG_MIME)
  return id || null
}
