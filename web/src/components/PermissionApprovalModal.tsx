import { useEffect, useRef, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'

import { replyPermissionRequest } from '@/api/client'
import { useTeamStore } from '@/stores/useTeamStore'
import { useMotionPreset } from '@/lib/motion'
import { cn } from '@/lib/utils'
import type { PermissionRequestPending } from '@/api/types'

/** The question the card asks, phrased for what the tool actually does. */
const TOOL_PROMPTS: Record<string, string> = {
  shell: 'Allow this command?',
  python: 'Allow this Python script?',
  bg: 'Allow this background process?',
  rm: 'Allow deleting these files?',
  edit: 'Allow this edit?',
  write: 'Allow writing this file?',
  patch: 'Allow this patch?',
  browser: 'Allow browser access?',
}

const KBD_CLASS =
  'hidden h-4.5 min-w-4.5 items-center justify-center rounded-[4px] border border-current/25 px-1 font-sans text-[10px] leading-none opacity-70 sm:inline-flex'

function PermissionApprovalForm({
  permissionRequest,
  sessionId,
}: {
  permissionRequest: PermissionRequestPending
  sessionId: string
}) {
  const preset = useMotionPreset()
  const [replying, setReplying] = useState(false)
  const [replyError, setReplyError] = useState<string | null>(null)
  const onceBtnRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    // Inline gate bar (not a modal dialog) — move focus to the primary
    // safe action so keyboard users aren't stranded in the composer.
    const frame = requestAnimationFrame(() => onceBtnRef.current?.focus())
    return () => cancelAnimationFrame(frame)
  }, [])

  // What "always" actually grants. The backend widens a command to its
  // family (`git commit -m x` → `git commit *`), and the dialog used to show
  // only the exact command, so the broader grant was invisible.
  const alwaysScope = (permissionRequest.alwaysPatterns ?? [])
    .filter((p) => p && !permissionRequest.patterns.includes(p))
    .join(', ')

  const handleReply = async (reply: 'once' | 'always' | 'reject') => {
    setReplying(true)
    setReplyError(null)
    try {
      const replySessionId = permissionRequest.sessionId || sessionId
      await replyPermissionRequest(replySessionId, permissionRequest.requestId, reply)
      useTeamStore.setState({ permissionRequest: null })
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to send reply. Please try again.'
      // Already resolved (other tab / interrupt / auto-allow) — dismiss.
      if (/not found|already resolved/i.test(message)) {
        useTeamStore.setState({ permissionRequest: null })
        return
      }
      // Keep the gate open on real network failures so the user can retry.
      setReplyError(message)
    } finally {
      setReplying(false)
    }
  }

  const isShell = permissionRequest.tool === 'shell' || permissionRequest.tool === 'bg'

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 * preset.distance }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: 6 * preset.distance }}
      transition={preset.spring}
      className="mx-auto w-full max-w-3xl px-4 pb-2"
    >
      <div
        className="overflow-hidden rounded-xl border border-(--color-border) bg-(--bg-card) shadow-(--shadow-depth)"
        role="region"
        aria-label="Permission required"
        onKeyDown={(e) => {
          // Rejecting is the safe direction, so Esc inside the card maps to it.
          if (e.key === 'Escape' && !replying) {
            e.preventDefault()
            void handleReply('reject')
          }
        }}
      >
        <div className="px-4 pb-3 pt-3.5">
          <div className="flex items-baseline justify-between gap-3">
            <p className="text-sm font-medium text-(--color-text)">
              {TOOL_PROMPTS[permissionRequest.tool] ?? 'Allow this action?'}
            </p>
            <span className="shrink-0 font-mono text-[11px] text-(--color-text-subtle)">
              {permissionRequest.tool}
            </span>
          </div>

          {permissionRequest.patterns.length > 0 ? (
            <div className="mt-2.5 max-h-36 overflow-auto rounded-lg border border-(--color-border-subtle) bg-(--bg-page) px-3 py-2 font-mono text-xs leading-5 whitespace-pre-wrap break-all text-(--color-text)">
              {permissionRequest.patterns.map((p, i) => (
                <div key={i}>
                  {isShell && <span className="select-none text-(--color-text-subtle)">$ </span>}
                  {p}
                </div>
              ))}
            </div>
          ) : (
            <p className="mt-1 text-xs text-(--color-text-muted)">No arguments</p>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2 border-t border-(--color-border-subtle) px-3 py-2">
          <p className="min-w-0 flex-1 px-1 text-[11px] leading-4 text-(--color-text-muted)">
            {alwaysScope ? (
              <>
                Always allow covers{' '}
                <span className="font-mono text-(--color-text-2)">{alwaysScope}</span>{' '}
                for the rest of this run.
              </>
            ) : null}
          </p>

          <div className="flex shrink-0 items-center gap-1">
            <button
              type="button"
              disabled={replying}
              onClick={() => handleReply('reject')}
              className={cn(
                'flex h-7 items-center gap-1.5 rounded-md px-2.5 text-xs font-medium text-(--color-text-muted) transition-colors',
                'hover:bg-(--bg-key) hover:text-(--color-text)',
                'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-(--focus-ring)',
                replying && 'pointer-events-none opacity-50',
              )}
            >
              Reject
              <kbd aria-hidden="true" className={KBD_CLASS}>Esc</kbd>
            </button>
            <button
              type="button"
              disabled={replying}
              onClick={() => handleReply('always')}
              className={cn(
                'flex h-7 items-center rounded-md border border-(--color-border) px-2.5 text-xs font-medium text-(--color-text) transition-colors',
                'hover:bg-(--bg-key)',
                'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-(--focus-ring)',
                replying && 'pointer-events-none opacity-50',
              )}
            >
              Always allow
            </button>
            <button
              ref={onceBtnRef}
              type="button"
              disabled={replying}
              onClick={() => handleReply('once')}
              className={cn(
                'flex h-7 items-center gap-1.5 rounded-md px-2.5 text-xs font-medium transition-colors',
                'bg-(--color-primary) text-(--color-text-on-accent) hover:opacity-90',
                'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-(--focus-ring) focus-visible:ring-offset-1 focus-visible:ring-offset-(--bg-card)',
                replying && 'pointer-events-none opacity-50',
              )}
            >
              {replying ? 'Allowing…' : 'Allow once'}
              {!replying && <kbd aria-hidden="true" className={KBD_CLASS}>↵</kbd>}
            </button>
          </div>
        </div>
        {replyError && (
          <p className="border-t border-(--color-border-subtle) px-4 py-2 text-xs text-(--color-danger)" role="alert">
            {replyError}
          </p>
        )}
      </div>
    </motion.div>
  )
}

export function PermissionApprovalModal() {
  const permissionRequest = useTeamStore((s) => s.permissionRequest)
  const sessionId = useTeamStore((s) => s.sessionId)
  const visible = Boolean(permissionRequest && sessionId)

  return (
    <AnimatePresence>
      {visible && permissionRequest && sessionId ? (
        <PermissionApprovalForm
          key={permissionRequest.requestId}
          permissionRequest={permissionRequest}
          sessionId={sessionId}
        />
      ) : null}
    </AnimatePresence>
  )
}
