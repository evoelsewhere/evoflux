import * as React from "react";
import { BellIcon, BellOffIcon, CheckCheckIcon, ListXIcon, XIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTitle, PopoverTrigger } from "@/components/ui/popover";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { unreadCount, useNotificationStore, type AppNotification } from "@/stores/notification-store";
import { NotificationIcon, timeAgo } from "./notification-icon";
import { openNotification } from "./open-target";

function ToolbarButton({
  label,
  onClick,
  pressed,
  disabled,
  children,
}: {
  label: string;
  onClick(): void;
  pressed?: boolean;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label={label}
            aria-pressed={pressed}
            disabled={disabled}
            onClick={onClick}
            className={cn("size-7 text-muted-foreground", pressed && "bg-accent text-foreground")}
          />
        }
      >
        {children}
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  );
}

function NotificationRow({ notification, now }: { notification: AppNotification; now: number }) {
  const remove = useNotificationStore((s) => s.remove);
  return (
    <li className="group/row relative">
      <button
        type="button"
        onClick={() => openNotification(notification)}
        className="flex w-full items-start gap-3 rounded-lg px-3 py-2.5 text-left transition-colors hover:bg-accent focus-visible:bg-accent focus-visible:outline-none"
      >
        <NotificationIcon level={notification.level} className="mt-0.5" />
        <span className="flex min-w-0 flex-1 flex-col gap-0.5 pr-5">
          <span className={cn("truncate text-[13px] leading-5", !notification.read && "font-medium")}>
            {notification.title}
          </span>
          {notification.body && (
            <span className="line-clamp-2 text-xs leading-4 text-muted-foreground">{notification.body}</span>
          )}
          <span className="text-[11px] leading-4 text-muted-foreground">
            <span className="capitalize">{notification.source}</span> · {timeAgo(notification.createdAt, now)}
          </span>
        </span>
      </button>
      {!notification.read && (
        <span
          aria-label="Unread"
          className="absolute top-3.5 right-3 size-1.5 rounded-full bg-brand group-hover/row:hidden"
        />
      )}
      <button
        type="button"
        aria-label={`Remove ${notification.title}`}
        onClick={() => remove(notification.id)}
        className="absolute top-2 right-1.5 hidden size-6 items-center justify-center rounded-md text-muted-foreground group-hover/row:flex hover:bg-foreground/10 hover:text-foreground focus-visible:flex"
      >
        <XIcon className="size-3.5" />
      </button>
    </li>
  );
}

const startOfToday = () => new Date().setHours(0, 0, 0, 0);

/**
 * The bell in the title bar and its notification center: everything the app
 * told the user, newest first, with Do not disturb. Opening it does not mark
 * anything read; opening a notification does.
 */
export function NotificationCenter() {
  const notifications = useNotificationStore((s) => s.notifications);
  const doNotDisturb = useNotificationStore((s) => s.doNotDisturb);
  const unread = useNotificationStore(unreadCount);
  const { markAllRead, clear, setDoNotDisturb } = useNotificationStore.getState();
  const [filter, setFilter] = React.useState<"all" | "unread">("all");
  const [open, setOpen] = React.useState(false);
  // Relative times ("5m") are read from the clock on each render while open.
  const now = Date.now();

  const shown = filter === "unread" ? notifications.filter((n) => !n.read) : notifications;
  const today = startOfToday();
  const groups = [
    { label: "Today", items: shown.filter((n) => n.createdAt >= today) },
    { label: "Earlier", items: shown.filter((n) => n.createdAt < today) },
  ].filter((g) => g.items.length > 0);

  const label = unread > 0 ? `Notifications, ${unread} unread` : "Notifications";

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <Tooltip>
        <TooltipTrigger
          render={
            <PopoverTrigger
              render={
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label={label}
                  className="no-drag relative text-muted-foreground data-popup-open:bg-accent data-popup-open:text-foreground"
                />
              }
            />
          }
        >
          {doNotDisturb ? <BellOffIcon /> : <BellIcon />}
          {unread > 0 && (
            <span className="absolute top-0.5 right-0.5 flex h-3.5 min-w-3.5 items-center justify-center rounded-full bg-brand px-1 text-[9px] leading-none font-semibold text-brand-foreground tabular-nums">
              {unread > 9 ? "9+" : unread}
            </span>
          )}
        </TooltipTrigger>
        <TooltipContent>{doNotDisturb ? "Notifications (Do not disturb)" : "Notifications"}</TooltipContent>
      </Tooltip>

      <PopoverContent align="end" className="flex w-[min(24rem,calc(100vw-1.5rem))] flex-col">
        <div className="flex items-center gap-1 border-b border-border/60 py-1.5 pr-1.5 pl-3">
          <PopoverTitle className="flex-1">Notifications</PopoverTitle>
          <ToolbarButton
            label={doNotDisturb ? "Turn off Do not disturb" : "Do not disturb"}
            pressed={doNotDisturb}
            onClick={() => setDoNotDisturb(!doNotDisturb)}
          >
            <BellOffIcon />
          </ToolbarButton>
          <ToolbarButton label="Mark all as read" onClick={markAllRead} disabled={unread === 0}>
            <CheckCheckIcon />
          </ToolbarButton>
          <ToolbarButton label="Clear all" onClick={clear} disabled={notifications.length === 0}>
            <ListXIcon />
          </ToolbarButton>
        </div>

        <div className="flex gap-1 px-3 pt-2" role="tablist" aria-label="Filter">
          {(["all", "unread"] as const).map((value) => (
            <button
              key={value}
              type="button"
              role="tab"
              aria-selected={filter === value}
              onClick={() => setFilter(value)}
              className={cn(
                "rounded-md px-2 py-0.5 text-xs transition-colors",
                filter === value ? "bg-accent text-foreground" : "text-muted-foreground hover:text-foreground",
              )}
            >
              {value === "all" ? "All" : `Unread${unread ? ` · ${unread}` : ""}`}
            </button>
          ))}
        </div>

        {doNotDisturb && (
          <p className="mx-3 mt-2 rounded-md bg-muted px-2.5 py-1.5 text-xs text-muted-foreground">
            Do not disturb is on — no toasts or system notifications.
          </p>
        )}

        <div className="max-h-[min(28rem,65vh)] overflow-y-auto px-1.5 pt-1 pb-1.5">
          {groups.length === 0 ? (
            <div className="flex flex-col items-center gap-2 px-6 py-10 text-center">
              <BellIcon className="size-5 text-muted-foreground" />
              <p className="text-sm font-medium">{filter === "unread" ? "No unread notifications" : "You're all caught up"}</p>
              <p className="text-xs text-muted-foreground">Finished runs, approvals and engine problems show up here.</p>
            </div>
          ) : (
            groups.map((group) => (
              <section key={group.label} aria-label={group.label}>
                <h3 className="px-3 pt-2 pb-1 text-[11px] font-medium text-muted-foreground">{group.label}</h3>
                <ul>
                  {group.items.map((n) => (
                    <NotificationRow key={n.id} notification={n} now={now} />
                  ))}
                </ul>
              </section>
            ))
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}
