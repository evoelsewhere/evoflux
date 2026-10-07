import { useEffect, useState } from 'react'
import { useNavigate } from '@tanstack/react-router'
import {
  AlertTriangle,
  Bell,
  Check,
  CircleHelp,
  ShieldCheck,
  Sparkles,
} from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  Popover,
  PopoverContent,
  PopoverTitle,
  PopoverTrigger,
} from '@/components/ui/popover'
import {
  listInboxNotifications,
  markAllInboxNotificationsRead,
  markInboxNotificationRead,
  subscribeToInboxNotifications,
  type InboxNotification,
} from '@/lib/notification-inbox'
import { routeForActivation } from '@/lib/notification-activation'

function kindLabel(kind: InboxNotification['kind']): string {
  switch (kind) {
    case 'question_asked': return 'Needs your input'
    case 'permission_asked': return 'Needs your approval'
    case 'agent_not_configured': return 'Agent setup'
    case 'terminal_error': return 'Terminal error'
    case 'goal_blocked': return 'Goal blocked'
    case 'background_done': return 'Background task'
    case 'reminder_fired': return 'Reminder'
    case 'assistant_done': return 'Assistant finished'
    case 'import_sync': return 'Import sync'
  }
}

function KindIcon({ kind }: { kind: InboxNotification['kind'] }) {
  const Icon = kind === 'question_asked'
    ? CircleHelp
    : kind === 'permission_asked'
      ? ShieldCheck
      : kind === 'terminal_error' || kind === 'goal_blocked'
        ? AlertTriangle
        : kind === 'agent_not_configured'
          ? Sparkles
          : Bell
  return <Icon size={14} aria-hidden="true" />
}

function timestampLabel(timestamp: number): string {
  return new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit' }).format(timestamp)
}

export function NotificationInboxButton({ align = 'end' }: { align?: 'start' | 'end' } = {}) {
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [items, setItems] = useState<InboxNotification[]>(() => listInboxNotifications())
  const unreadCount = items.reduce((count, item) => count + Number(item.readAt === null), 0)

  useEffect(() => subscribeToInboxNotifications(() => setItems(listInboxNotifications())), [])

  const openNotification = (item: InboxNotification) => {
    markInboxNotificationRead(item.id)
    setItems(listInboxNotifications())
    if (!item.activation) return
    setOpen(false)
    void navigate(routeForActivation(item.activation))
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        render={
          <button
            type="button"
            className="relative flex h-7 w-8 shrink-0 items-center justify-center rounded-lg text-(--color-text-muted) outline-none transition-colors hover:bg-(--bg-key) hover:text-(--color-text) focus-visible:ring-2 focus-visible:ring-(--focus-ring) data-[popup-open]:bg-(--bg-key) data-[popup-open]:text-(--color-text)"
            aria-label={unreadCount > 0 ? `Notifications, ${unreadCount} unread` : 'Notifications'}
            aria-haspopup="dialog"
            title="Notifications"
            data-no-drag
          />
        }
      >
        <Bell size={15} aria-hidden="true" />
        {unreadCount > 0 && (
          <span className="absolute -right-1 -top-1 flex min-h-4 min-w-4 items-center justify-center rounded-full bg-(--color-accent) px-1 text-[9px] font-semibold leading-none text-white shadow-sm">
            {unreadCount > 99 ? '99+' : unreadCount}
          </span>
        )}
      </PopoverTrigger>
      <PopoverContent
        align={align}
        side="bottom"
        sideOffset={8}
        collisionPadding={12}
        className="w-[min(23rem,calc(100vw-1rem))] gap-0 overflow-hidden rounded-xl border-(--color-border) bg-(--bg-card) p-0 shadow-(--shadow-popover)"
      >
        <div className="flex items-center justify-between gap-3 border-b border-(--color-border) px-4 py-3">
          <div className="min-w-0">
            <PopoverTitle className="text-sm font-semibold">Notifications</PopoverTitle>
            <p className="mt-0.5 text-xs text-(--color-text-muted)">
              {unreadCount ? `${unreadCount} unread` : 'You are all caught up'}
            </p>
          </div>
          {unreadCount > 0 && (
            <Button
              type="button"
              size="sm"
              variant="ghost"
              className="h-7 shrink-0 px-2 text-xs"
              onClick={markAllInboxNotificationsRead}
            >
              <Check size={13} aria-hidden="true" />
              Mark all read
            </Button>
          )}
        </div>

        {items.length === 0 ? (
          <div className="px-5 py-9 text-center">
            <Bell size={19} className="mx-auto text-(--color-text-subtle)" aria-hidden="true" />
            <p className="mt-2 text-sm font-medium text-(--color-text)">No notifications yet</p>
            <p className="mt-1 text-xs text-(--color-text-muted)">New desktop notifications will show up here.</p>
          </div>
        ) : (
          <ul className="max-h-[min(26rem,65vh)] overflow-y-auto py-1">
            {items.map((item) => {
              const unread = item.readAt === null
              return (
                <li key={item.id}>
                  <button
                    type="button"
                    onClick={() => openNotification(item)}
                    className={`group flex w-full gap-3 border-l-2 px-3 py-3 text-left transition-colors hover:bg-(--bg-key) ${unread
                      ? 'border-l-(--color-accent) bg-(--color-accent)/8'
                      : 'border-l-transparent'
                    }`}
                    aria-label={`${unread ? 'Unread. ' : ''}${kindLabel(item.kind)}: ${item.title}`}
                  >
                    <span className={`mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-lg ${unread
                      ? 'bg-(--color-accent)/15 text-(--color-accent)'
                      : 'bg-(--bg-key) text-(--color-text-muted)'
                    }`}>
                      <KindIcon kind={item.kind} />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="flex items-start justify-between gap-2">
                        <span className={`line-clamp-2 text-[13px] leading-5 ${unread ? 'font-semibold text-(--color-text)' : 'font-medium text-(--color-text-2)'}`}>
                          {item.title}
                        </span>
                        <span className="shrink-0 pt-0.5 text-[10px] tabular-nums text-(--color-text-subtle)">
                          {timestampLabel(item.createdAt)}
                        </span>
                      </span>
                      <span className="mt-0.5 block text-[11px] font-medium text-(--color-text-muted)">
                        {kindLabel(item.kind)}
                      </span>
                      <span className="mt-1 line-clamp-2 block text-xs leading-5 text-(--color-text-muted)">
                        {item.body}
                      </span>
                    </span>
                    {unread && <span className="mt-2 size-2 shrink-0 rounded-full bg-(--color-accent)" aria-hidden="true" />}
                  </button>
                </li>
              )
            })}
          </ul>
        )}
      </PopoverContent>
    </Popover>
  )
}
