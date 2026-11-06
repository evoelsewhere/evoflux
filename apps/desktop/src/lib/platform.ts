// Platform facts the UI needs before any IPC round trip.

import { isTauri } from "@tauri-apps/api/core";

const agent = typeof navigator === "undefined" ? "" : navigator.userAgent;

export const isMac = /Mac OS X|Macintosh/.test(agent);
export const isWindows = /Windows/.test(agent);
export const isLinux = !isMac && !isWindows;

/** Label of the primary modifier for shortcut hints. */
export const modKey = isMac ? "⌘" : "Ctrl";

/** Whether a keyboard event carries the platform's primary modifier. */
export function hasMod(event: KeyboardEvent | React.KeyboardEvent): boolean {
  return isMac ? event.metaKey : event.ctrlKey;
}

/**
 * Running inside the Tauri window (not the browser dev preview). Window
 * chrome — custom window controls, room for the macOS traffic lights — only
 * exists there.
 */
export const inTauri = isTauri();
