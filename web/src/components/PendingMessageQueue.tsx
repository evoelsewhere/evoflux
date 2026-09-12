/**
 * PendingMessageQueue — what you have typed that the agent has not read yet.
 *
 * It belongs to the composer, not the transcript: these messages have not
 * happened in the conversation, they are still pending input. Codex draws the
 * same thing as a preview strip directly above its composer, and putting it
 * anywhere else invites reading a queued line as something the agent replied
 * to.
 *
 * Each row shows its lane, and can be moved between lanes, edited in place
 * (keeping its position in the queue) or cancelled, until the moment a turn
 * boundary claims it.
 */

import { useEffect, useRef, useState } from 'react'
import { Clock, Paperclip, X, Zap } from 'lucide-react'
import { useTeamStore } from '@/stores/useTeamStore'
import { cn } from '@/lib/utils'
import type { MessageAttachment } from '@/api/types'

const ROW_ACTION_CLASS =
  'flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text) md:h-6 md:w-6'

function attachmentLabel(attachments: MessageAttachment[]): string {
  if (attachments.length === 1) {
    return attachments[0].original_name || attachments[0].filename || '1 file'
  }
  return `${attachments.length} files`
}

function QueuedRow({
  id,
  content,
  delivery,
  attachments,
}: {
  id: string
  content: string
  delivery: 'steer' | 'queue'
  attachments?: MessageAttachment[]
}) {
  const setPendingMessageDelivery = useTeamStore((s) => s.setPendingMessageDelivery)
  const editPendingMessage = useTeamStore((s) => s.editPendingMessage)
  const removePendingMessage = useTeamStore((s) => s.removePendingMessage)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(content)
  const inputRef = useRef<HTMLTextAreaElement | null>(null)

  // Seeded on entry rather than synced by effect, so text that changes
  // underneath an open editor cannot clobber what is being typed.
  const startEditing = () => {
    setDraft(content)
    setEditing(true)
  }

  useEffect(() => {
    if (!editing) return
    const el = inputRef.current
    if (!el) return
    el.focus()
    el.setSelectionRange(el.value.length, el.value.length)
  }, [editing])

  const commit = () => {
    const next = draft.trim()
    setEditing(false)
    if (!next || next === content) {
      setDraft(content)
      return
    }
    editPendingMessage(id, next)
  }

  const steering = delivery === 'steer'
  const LaneIcon = steering ? Clock : Zap
  const laneAction = steering ? 'Hold for the next turn instead' : 'Steer this turn'

  return (
    <li className="group/row flex items-center gap-1 rounded-md px-1.5 py-0.5 transition-colors hover:bg-(--bg-key)">
      <div className="min-w-0 flex-1">
        {editing ? (
          <textarea
            ref={inputRef}
            value={draft}
            rows={Math.min(6, draft.split('\n').length || 1)}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={commit}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                commit()
              } else if (e.key === 'Escape') {
                e.preventDefault()
                setDraft(content)
                setEditing(false)
              }
            }}
            aria-label="Edit queued message"
            className="w-full resize-none rounded-sm border border-(--color-accent) bg-(--color-surface) px-2 py-1 text-sm leading-relaxed text-(--color-text) outline-none"
          />
        ) : (
          <button
            type="button"
            onClick={startEditing}
            title="Edit queued message"
            className="block w-full truncate text-left text-sm leading-relaxed text-(--color-text-2) hover:text-(--color-text)"
          >
            {content}
          </button>
        )}
        {attachments && attachments.length > 0 && (
          <span className="mt-0.5 flex items-center gap-1 text-[11px] text-(--color-text-subtle)">
            <Paperclip size={11} aria-hidden="true" />
            {attachmentLabel(attachments)}
          </span>
        )}
      </div>
      {/* Deliver it now instead of at the turn boundary. This is the whole
          reason the tray is interactive: the default is to wait, and one
          click is how an urgent correction jumps the queue. */}
      <button
        onClick={() => setPendingMessageDelivery(id, steering ? 'queue' : 'steer')}
        aria-label={laneAction}
        title={laneAction}
        className={cn(
          'flex h-7 shrink-0 items-center gap-1 rounded-md px-2 text-xs font-medium transition-colors md:h-6',
          steering
            ? 'bg-(--color-accent)/12 text-(--color-accent) hover:bg-(--color-accent)/20'
            : 'text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text)',
        )}
      >
        <LaneIcon size={13} aria-hidden="true" />
        {steering ? 'Steering' : 'Steer'}
      </button>
      <button
        onClick={() => removePendingMessage(id)}
        aria-label="Cancel queued message"
        title="Cancel queued message"
        className={ROW_ACTION_CLASS}
      >
        <X size={13} aria-hidden="true" />
      </button>
    </li>
  )
}

export function PendingMessageQueue() {
  const allMessages = useTeamStore((s) => s._pendingMessages)
  const sessionId = useTeamStore((s) => s.sessionId)
  const messages = allMessages.filter((msg) => (msg.sessionId ?? null) === sessionId)

  if (messages.length === 0) return null

  return (
    <div
      // Inside the composer card: a hairline is the only separation, so the
      // tray reads as the top of the input rather than a panel above it.
      className="w-full border-b border-(--color-border-subtle) px-2 pb-1 pt-1"
      role="group"
      aria-label={`${messages.length} message${messages.length === 1 ? '' : 's'} waiting to be delivered`}
    >
      <ul className="max-h-40 space-y-0.5 overflow-y-auto">
        {messages.map((msg) => (
          <QueuedRow
            key={msg.id}
            id={msg.id}
            content={msg.content}
            delivery={msg.delivery === 'queue' ? 'queue' : 'steer'}
            attachments={msg.attachments}
          />
        ))}
      </ul>
    </div>
  )
}
