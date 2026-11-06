import { CircleAlertIcon, CircleCheckIcon, InfoIcon, TriangleAlertIcon } from "lucide-react";
import type { NotificationLevel } from "@/stores/notification-store";
import { cn } from "@/lib/utils";

const icons = {
  info: { Icon: InfoIcon, tone: "text-muted-foreground" },
  success: { Icon: CircleCheckIcon, tone: "text-emerald-600 dark:text-emerald-400" },
  warning: { Icon: TriangleAlertIcon, tone: "text-amber-600 dark:text-amber-400" },
  error: { Icon: CircleAlertIcon, tone: "text-destructive" },
} satisfies Record<NotificationLevel, unknown>;

export function NotificationIcon({ level, className }: { level: NotificationLevel; className?: string }) {
  const { Icon, tone } = icons[level];
  return <Icon aria-hidden className={cn("size-4 shrink-0", tone, className)} />;
}

/** "now", "5m", "3h", "2d", then the date. */
export function timeAgo(at: number, now = Date.now()): string {
  const seconds = Math.max(0, Math.round((now - at) / 1000));
  if (seconds < 45) return "now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h`;
  const days = Math.round(hours / 24);
  if (days < 7) return `${days}d`;
  return new Date(at).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
