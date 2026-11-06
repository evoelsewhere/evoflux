import * as React from "react";
import { XIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { useNotificationStore, type AppNotification } from "@/stores/notification-store";
import { NotificationIcon } from "./notification-icon";
import { openNotification } from "./open-target";

/** How long a toast stays; errors and warnings stay longer. Hovering pauses it. */
const DURATION: Record<AppNotification["level"], number> = { info: 5000, success: 5000, warning: 8000, error: 10000 };
/** Toasts on screen at once; older ones leave the stack (they stay in the bell). */
const MAX_VISIBLE = 3;

function Toast({ notification }: { notification: AppNotification }) {
  const dismiss = useNotificationStore((s) => s.dismissToast);
  const [paused, setPaused] = React.useState(false);

  React.useEffect(() => {
    if (paused) return;
    const timer = window.setTimeout(() => dismiss(notification.id), DURATION[notification.level]);
    return () => window.clearTimeout(timer);
  }, [paused, notification.id, notification.level, dismiss]);

  return (
    <li
      role={notification.level === "error" ? "alert" : "status"}
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      onFocus={() => setPaused(true)}
      onBlur={() => setPaused(false)}
      className="group/toast pointer-events-auto relative w-[min(22rem,calc(100vw-2rem))] rounded-xl bg-popover text-popover-foreground shadow-lg ring-1 ring-foreground/5 duration-200 animate-in fade-in slide-in-from-bottom-2 dark:ring-foreground/10"
    >
      <button
        type="button"
        onClick={() => openNotification(notification)}
        className={cn(
          "flex w-full items-start gap-3 rounded-xl px-3.5 py-3 pr-9 text-left focus-visible:outline-none",
          notification.target && "cursor-pointer hover:bg-accent/40",
        )}
      >
        <NotificationIcon level={notification.level} className="mt-0.5" />
        <span className="flex min-w-0 flex-col gap-0.5">
          <span className="text-[13px] leading-5 font-medium">{notification.title}</span>
          {notification.body && (
            <span className="line-clamp-3 text-xs leading-4 text-muted-foreground">{notification.body}</span>
          )}
        </span>
      </button>
      <button
        type="button"
        aria-label="Dismiss"
        onClick={() => dismiss(notification.id)}
        className="absolute top-2.5 right-2.5 flex size-6 items-center justify-center rounded-md text-muted-foreground opacity-0 transition-opacity group-hover/toast:opacity-100 hover:bg-foreground/10 hover:text-foreground focus-visible:opacity-100"
      >
        <XIcon className="size-3.5" />
      </button>
    </li>
  );
}

/** In-app toasts, bottom right. Mount once at the app root. */
export function Toaster() {
  const toasts = useNotificationStore((s) => s.toasts);
  const notifications = useNotificationStore((s) => s.notifications);
  const shown = toasts
    .slice(0, MAX_VISIBLE)
    .map((id) => notifications.find((n) => n.id === id))
    .filter((n): n is AppNotification => !!n)
    .reverse();

  return (
    <ol
      aria-label="Notifications"
      className="pointer-events-none fixed right-4 bottom-4 z-[60] flex flex-col items-end gap-2"
    >
      {shown.map((n) => (
        <Toast key={n.id} notification={n} />
      ))}
    </ol>
  );
}
