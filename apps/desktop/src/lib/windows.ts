// Chat windows: "Open in › New window" shows one chat in a window of its own
// (src-tauri/src/window.rs). That window owns the chat's engine; the main
// window focuses it instead of showing the chat.

import { invoke } from "@tauri-apps/api/core";
import { inTauri } from "@/lib/platform";

declare global {
  interface Window {
    __EVO_CHAT_WINDOW__?: string;
  }
}

/** The chat this window shows on its own; `null` in the main window. */
export const chatWindowId: string | null = (typeof window !== "undefined" && window.__EVO_CHAT_WINDOW__) || null;

export function openChatWindow(chat: string, title: string): Promise<void> {
  return invoke("chat_window_open", { chat, title });
}

/** Focus `chat`'s window; false when it has none. */
export function focusChatWindow(chat: string): Promise<boolean> {
  if (!inTauri || chat === chatWindowId) return Promise.resolve(false);
  return invoke<boolean>("chat_window_focus", { chat }).catch(() => false);
}

export function closeChatWindow(chat: string): Promise<void> {
  if (!inTauri) return Promise.resolve();
  return invoke<void>("chat_window_close", { chat }).catch(() => undefined);
}
