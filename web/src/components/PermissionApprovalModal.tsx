import { useState } from 'react'
import { ShieldAlert, ShieldCheck, ShieldX } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'

import { replyPermissionRequest } from '@/api/client'
import { useTeamStore } from '@/stores/useTeamStore'
import { useMotionPreset } from '@/lib/motion'
import { cn } from '@/lib/utils'

const TOOL_ICON_MAP: Record<string, string> = {
  shell: '💻',
  python: '🐍',
  bg: '⚙️',
  rm: '🗑️',
  edit: '✏️',
  write: '📝',
  patch: '🩹',
  browser: '🌐',
}

export function PermissionApprovalModal() {
  const permissionRequest = useTeamStore((s) => s.permissionRequest)
  const sessionId = useTeamStore((s) => s.sessionId)
  const preset = useMotionPreset()
  const [replying, setReplying] = useState(false)

  const handleReply = async (reply: 'once' | 'always' | 'reject') => {
    if (!permissionRequest || !sessionId) return
    setReplying(true)
    try {
      await replyPermissionRequest(sessionId, permissionRequest.requestId, reply)
    } catch {
      // Ignore — "not found or already resolved" means the backend already
      // handled it (e.g. auto-allow mode). We still close the modal below.
    } finally {
      setReplying(false)
      useTeamStore.setState({ permissionRequest: null })
    }
  }

  return (
    <AnimatePresence>
      {permissionRequest && (
        <motion.div
          key={permissionRequest.requestId}
          initial={{ opacity: 0, y: 6 * preset.distance }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: 6 * preset.distance }}
          transition={preset.spring}
          className="mx-auto w-full max-w-3xl px-4 pb-2"
        >
          <div className="rounded-xl border border-(--color-warning)/35 bg-(--bg-page) shadow-sm overflow-hidden">
            {/* Top bar */}
            <div className="flex items-center gap-2 border-b border-(--color-border) bg-(--color-warning)/5 px-4 py-2.5">
              <ShieldAlert size={14} className="shrink-0 text-(--color-warning)" aria-hidden="true" />
              <span className="text-xs font-semibold text-(--color-text)">Permission required</span>
              <span className="text-xs text-(--color-text-muted)">— agent wants to run:</span>
              <span className="ml-0.5 rounded bg-(--bg-key) px-1.5 py-0.5 font-mono text-xs text-(--color-text)">
                {permissionRequest.tool}
              </span>
              {TOOL_ICON_MAP[permissionRequest.tool] && (
                <span aria-hidden="true" className="text-xs">
                  {TOOL_ICON_MAP[permissionRequest.tool]}
                </span>
              )}
            </div>

            {/* Patterns + actions row */}
            <div className="flex items-center gap-3 px-4 py-2.5 flex-wrap">
              {/* Patterns */}
              <div className="flex-1 min-w-0">
                {permissionRequest.patterns.length > 0 ? (
                  <div className="flex flex-wrap gap-1">
                    {permissionRequest.patterns.map((p, i) => (
                      <span
                        key={i}
                        className="break-all rounded bg-(--bg-key) px-1.5 py-0.5 font-mono text-xs text-(--color-text-muted)"
                      >
                        {p}
                      </span>
                    ))}
                  </div>
                ) : (
                  <span className="text-xs italic text-(--color-text-subtle)">no arguments</span>
                )}
              </div>

              {/* Action buttons */}
              <div className="flex shrink-0 items-center gap-1.5">
                <button
                  disabled={replying}
                  onClick={() => handleReply('reject')}
                  className={cn(
                    'flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-xs font-medium transition-colors',
                    'text-red-600 hover:bg-red-500/10 dark:text-red-400',
                    replying && 'pointer-events-none opacity-50',
                  )}
                >
                  <ShieldX size={12} aria-hidden="true" />
                  Reject
                </button>
                <button
                  disabled={replying}
                  onClick={() => handleReply('once')}
                  className={cn(
                    'flex items-center gap-1 rounded-lg border border-(--color-border) px-2.5 py-1.5 text-xs font-medium transition-colors',
                    'bg-(--bg-card) text-(--color-text) hover:bg-(--bg-key)',
                    replying && 'pointer-events-none opacity-50',
                  )}
                >
                  Allow once
                </button>
                <button
                  disabled={replying}
                  onClick={() => handleReply('always')}
                  className={cn(
                    'flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-xs font-medium transition-colors',
                    'bg-(--color-primary) text-white hover:opacity-90',
                    replying && 'pointer-events-none opacity-50',
                  )}
                >
                  <ShieldCheck size={12} aria-hidden="true" />
                  {replying ? 'Allowing…' : 'Always allow'}
                </button>
              </div>
            </div>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
