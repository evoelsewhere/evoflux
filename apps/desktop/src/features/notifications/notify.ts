// `notify()` — the one way a feature tells the user something happened.
//
// Every notification lands in the bell (the notification center). On top of
// that it is delivered on one channel, picked from where the user is:
//
//   window focused      → an in-app toast (unless `toast: false`)
//   window not focused  → an OS notification (unless `system: false`)
//
// Do not disturb, or muting the source, silences both channels; the bell still
// collects everything. See /docs/features/notifications/sdd.md at the repo root.

import { isPermissionGranted, requestPermission, sendNotification } from "@tauri-apps/plugin-notification";
import { inTauri } from "@/lib/platform";
import {
  useNotificationStore,
  type AppNotification,
  type NotificationLevel,
  type NotificationTarget,
} from "@/stores/notification-store";

export type { AppNotification, NotificationLevel, NotificationTarget };

export interface NotifyOptions {
  title: string;
  body?: string;
  level?: NotificationLevel;
  /** The feature raising it: "engine", "scheduler", "plugins", … */
  source: string;
  target?: NotificationTarget;
  /** Replace the earlier notification with this key instead of adding one. */
  key?: string;
  /** Show a toast when the window is focused. Default true. */
  toast?: boolean;
  /** Send an OS notification when the window is not focused. Default true. */
  system?: boolean;
  /** Only record it in the bell, already read (a log entry, not news). Default false. */
  quiet?: boolean;
}

const newId = () => `n-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`;

/** Whether the user is looking at the app right now. */
export const windowFocused = () => document.visibilityState === "visible" && document.hasFocus();

/** Record a notification and deliver it. Returns its id. */
export function notify(options: NotifyOptions): string {
  const store = useNotificationStore.getState();
  const notification: AppNotification = {
    id: newId(),
    level: options.level ?? "info",
    title: options.title,
    body: options.body,
    source: options.source,
    createdAt: Date.now(),
    read: options.quiet ?? false,
    target: options.target,
    key: options.key,
  };
  const muted = options.quiet || store.doNotDisturb || store.mutedSources.includes(options.source);
  const focused = windowFocused();
  store.add(notification, !muted && focused && options.toast !== false);
  if (!muted && !focused && options.system !== false) void sendSystem(notification);
  return notification.id;
}

// ── OS notifications ─────────────────────────────────────────────────────────

let permission: Promise<boolean> | null = null;

/** Ask once per run; the OS remembers the answer. */
function systemAllowed(): Promise<boolean> {
  permission ??= (async () => {
    if (inTauri) {
      if (await isPermissionGranted()) return true;
      return (await requestPermission()) === "granted";
    }
    if (typeof Notification === "undefined") return false;
    if (Notification.permission === "granted") return true;
    return (await Notification.requestPermission()) === "granted";
  })().catch(() => false);
  return permission;
}

async function sendSystem(notification: AppNotification) {
  if (!(await systemAllowed())) return;
  if (inTauri) sendNotification({ title: notification.title, body: notification.body });
  else new Notification(notification.title, { body: notification.body });
}
