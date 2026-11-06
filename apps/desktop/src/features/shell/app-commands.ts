// Window and editing commands shared by the app menu and the global hotkeys.
// Inside Tauri they drive the native window; in the browser preview they fall
// back to what a page can do.

import { invoke } from "@tauri-apps/api/core";
import { getCurrentWebview } from "@tauri-apps/api/webview";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { openUrl } from "@tauri-apps/plugin-opener";
import { inTauri } from "@/lib/platform";
import { useUiStore } from "@/stores/ui-store";

export const REPOSITORY_URL = "https://github.com/evoelsewhere/evo-harness";

// ── Zoom ─────────────────────────────────────────────────────────────────────

export const ZOOM_STEPS = [0.67, 0.75, 0.8, 0.9, 1, 1.1, 1.25, 1.5, 1.75, 2];

export function applyZoom(level: number) {
  if (inTauri) {
    void getCurrentWebview().setZoom(level).catch(() => undefined);
  } else {
    document.documentElement.style.setProperty("zoom", String(level));
  }
}

export function setZoom(level: number) {
  useUiStore.getState().setZoom(level);
  applyZoom(level);
}

export function zoomBy(step: 1 | -1) {
  const current = useUiStore.getState().zoom;
  const index = ZOOM_STEPS.findIndex((z) => z >= current - 0.001);
  const at = index < 0 ? ZOOM_STEPS.length - 1 : index;
  // Between two steps, the first step in the direction of travel is the nearer one.
  const exact = Math.abs(ZOOM_STEPS[at] - current) < 0.001;
  const next = step > 0 ? (exact ? at + 1 : at) : at - 1;
  setZoom(ZOOM_STEPS[Math.max(0, Math.min(ZOOM_STEPS.length - 1, next))]);
}

export const resetZoom = () => setZoom(1);

// ── Window ───────────────────────────────────────────────────────────────────

export async function toggleFullscreen() {
  if (inTauri) {
    const window = getCurrentWindow();
    await window.setFullscreen(!(await window.isFullscreen()));
  } else if (document.fullscreenElement) {
    await document.exitFullscreen();
  } else {
    await document.documentElement.requestFullscreen();
  }
}

export function closeWindow() {
  if (inTauri) void getCurrentWindow().close();
  else window.close();
}

export const reloadWindow = () => window.location.reload();

/** Toggle the web inspector; `open` forces it open (the hotkey). */
export function toggleDevtools(open?: boolean) {
  if (inTauri) void invoke("window_devtools", { open }).catch(() => undefined);
}

export function openLink(url: string) {
  if (inTauri) void openUrl(url).catch(() => undefined);
  else window.open(url, "_blank", "noopener");
}

// ── Editing ──────────────────────────────────────────────────────────────────
//
// Opening the menu moves focus to its button, so remember the last text field
// the user was in and run the command there once the menu has closed.

let lastEditable: HTMLElement | null = null;

const isEditable = (el: Element | null): el is HTMLElement =>
  el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement || (el instanceof HTMLElement && el.isContentEditable);

if (typeof document !== "undefined") {
  document.addEventListener("focusin", (event) => {
    if (isEditable(event.target as Element)) lastEditable = event.target as HTMLElement;
  });
}

export type EditCommand = "undo" | "redo" | "cut" | "copy" | "paste" | "selectAll";

export function runEditCommand(command: EditCommand) {
  // After the menu's close has handed focus back to its trigger.
  window.setTimeout(async () => {
    const target = lastEditable?.isConnected ? lastEditable : null;
    if (command === "copy" && !target) {
      // Copy the page selection (a reply, say) when no field was in use.
      document.execCommand("copy");
      return;
    }
    if (!target) return;
    target.focus();
    if (command === "paste") {
      const text = await navigator.clipboard.readText().catch(() => "");
      if (text) document.execCommand("insertText", false, text);
      return;
    }
    document.execCommand(command);
  }, 80);
}
