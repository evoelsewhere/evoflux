// The app's notifications: what the bell lists, plus the toasts on screen.
//
// Features do not write here directly — they call `notify()` from
// `@/features/notifications/notify`, which also decides whether a toast or an
// OS notification goes out. See /docs/features/notifications/sdd.md at the repo root.

import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { CustomizeSection, PanelId, SettingsSection } from "@/stores/ui-store";

export type NotificationLevel = "info" | "success" | "warning" | "error";

/** Where clicking a notification takes the user. Plain data, so it survives a restart. */
export type NotificationTarget =
  | { type: "session"; id: string }
  | { type: "panel"; id: PanelId }
  | { type: "settings"; section?: SettingsSection }
  | { type: "customize"; section?: CustomizeSection }
  | { type: "url"; href: string };

export interface AppNotification {
  id: string;
  level: NotificationLevel;
  title: string;
  body?: string;
  /** The feature that raised it ("engine", "scheduler", …): shown as a label, used to filter and mute. */
  source: string;
  createdAt: number;
  read: boolean;
  target?: NotificationTarget;
  /**
   * Replaces an earlier notification with the same key instead of adding
   * another ("engine:exit", "scheduler:job-42"). The replacement is unread again.
   */
  key?: string;
}

/** Notifications kept in the bell; the oldest go first. */
export const MAX_NOTIFICATIONS = 200;

interface NotificationStore {
  notifications: AppNotification[];
  /** Ids of notifications shown as toasts right now (not persisted). */
  toasts: string[];
  /** Mutes toasts and OS notifications; the bell still collects everything. */
  doNotDisturb: boolean;
  /** Sources whose toasts and OS notifications are muted. */
  mutedSources: string[];

  add(notification: AppNotification, toast: boolean): void;
  markRead(id: string): void;
  markAllRead(): void;
  remove(id: string): void;
  clear(): void;
  dismissToast(id: string): void;
  setDoNotDisturb(on: boolean): void;
  setSourceMuted(source: string, muted: boolean): void;
}

export const useNotificationStore = create<NotificationStore>()(
  persist(
    (set) => ({
      notifications: [],
      toasts: [],
      doNotDisturb: false,
      mutedSources: [],

      add: (notification, toast) =>
        set((s) => {
          const replaced = notification.key ? s.notifications.find((n) => n.key === notification.key) : undefined;
          const rest = replaced ? s.notifications.filter((n) => n.id !== replaced.id) : s.notifications;
          return {
            notifications: [notification, ...rest].slice(0, MAX_NOTIFICATIONS),
            toasts: [
              ...(toast ? [notification.id] : []),
              ...s.toasts.filter((id) => id !== replaced?.id),
            ],
          };
        }),
      markRead: (id) =>
        set((s) => ({ notifications: s.notifications.map((n) => (n.id === id ? { ...n, read: true } : n)) })),
      markAllRead: () => set((s) => ({ notifications: s.notifications.map((n) => (n.read ? n : { ...n, read: true })) })),
      remove: (id) =>
        set((s) => ({
          notifications: s.notifications.filter((n) => n.id !== id),
          toasts: s.toasts.filter((t) => t !== id),
        })),
      clear: () => set({ notifications: [], toasts: [] }),
      dismissToast: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t !== id) })),
      setDoNotDisturb: (doNotDisturb) => set({ doNotDisturb }),
      setSourceMuted: (source, muted) =>
        set((s) => ({
          mutedSources: muted
            ? [...new Set([...s.mutedSources, source])]
            : s.mutedSources.filter((m) => m !== source),
        })),
    }),
    {
      name: "evo.notifications",
      partialize: (s) => ({
        notifications: s.notifications,
        doNotDisturb: s.doNotDisturb,
        mutedSources: s.mutedSources,
      }),
    },
  ),
);

export const unreadCount = (s: { notifications: AppNotification[] }) => s.notifications.filter((n) => !n.read).length;
