// What clicking a notification does: go to its target and mark it read.

import { openLink } from "@/features/shell/app-commands";
import { useEngineStore } from "@/stores/engine-store";
import { useNotificationStore, type AppNotification } from "@/stores/notification-store";
import { useSessionStore } from "@/stores/session-store";
import { useUiStore } from "@/stores/ui-store";

export function openNotification(notification: AppNotification) {
  const store = useNotificationStore.getState();
  store.markRead(notification.id);
  store.dismissToast(notification.id);
  const target = notification.target;
  if (!target) return;
  const ui = useUiStore.getState();
  switch (target.type) {
    case "session":
      if (ui.settingsOpen) ui.closeSettings();
      if (useSessionStore.getState().sessions.some((s) => s.id === target.id)) {
        void useEngineStore.getState().selectSession(target.id);
      }
      break;
    case "panel":
      if (ui.settingsOpen) ui.closeSettings();
      ui.openPanel(target.id);
      break;
    case "settings":
      ui.openSettings(target.section);
      break;
    case "customize":
      ui.openCustomize(target.section);
      break;
    case "url":
      openLink(target.href);
      break;
  }
}
