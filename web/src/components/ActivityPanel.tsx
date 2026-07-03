/**
 * ActivityPanel — chronological feed of cross-agent team events.
 *
 * Shows agent spawns, messages, handoffs, status changes, and turn
 * completions as a compact timeline in a slide-over panel.
 */

import { useRef, useEffect } from 'react'
import { ArrowRightLeft, CheckCircle2, LogIn, LogOut, Mail, AlertTriangle, CircleDot } from 'lucide-react'
import { useTeamStore, type ActivityItem } from '@/stores/useTeamStore'
import { ScrollArea } from '@/components/ui/scroll-area'

function kindIcon(kind: ActivityItem['kind']) {
  const size = 14
  switch (kind) {
    case 'spawn':   return <LogIn size={size} className="text-(--color-success)" />
    case 'dismiss': return <LogOut size={size} className="text-(--color-text-muted)" />
    case 'inbox':   return <Mail size={size} className="text-(--color-text-2)" />
    case 'handoff': return <ArrowRightLeft size={size} className="text-(--color-accent)" />
    case 'status':  return <AlertTriangle size={size} className="text-(--color-warning, orange)" />
    case 'done':    return <CheckCircle2 size={size} className="text-(--color-success)" />
    default:        return <CircleDot size={size} className="text-(--color-text-muted)" />
  }
}

function formatTime(date: Date): string {
  return date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function ActivityRow({ item }: { item: ActivityItem }) {
  return (
    <div className="flex items-start gap-2 px-3 py-1.5 text-xs hover:bg-(--bg-hover)">
      <span className="mt-0.5 shrink-0">{kindIcon(item.kind)}</span>
      <div className="min-w-0 flex-1">
        <p className="truncate text-(--color-text)">{item.label}</p>
        {typeof item.artifact?.summary === 'string' && (
          <p className="mt-0.5 truncate text-(--color-text-muted)">
            {item.artifact.summary}
          </p>
        )}
      </div>
      <span className="shrink-0 font-mono text-xs text-(--color-text-subtle)">
        {formatTime(item.timestamp)}
      </span>
    </div>
  )
}

export function ActivityPanel() {
  const activityLog = useTeamStore((s) => s.activityLog)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [activityLog.length])

  if (activityLog.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-xs text-(--color-text-muted)">
        No activity yet
      </div>
    )
  }

  return (
    <ScrollArea className="h-full">
      <div className="divide-y divide-(--color-border)/50">
        {activityLog.map((item) => (
          <ActivityRow key={item.id} item={item} />
        ))}
        <div ref={bottomRef} />
      </div>
    </ScrollArea>
  )
}
