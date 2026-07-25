/**
 * Thinking — collapsible inline reasoning trace.
 *
 * Renders reasoning content (OpenAI /responses, MiMo reasoning_content,
 * Anthropic extended thinking, etc.) as a faded, ghosted block that
 * doesn't compete with the main response.
 *
 * Design language (GitHub Copilot-inspired):
 *   • Collapsed  — a single muted line: "Thinking…" with a subtle chevron.
 *                   No border, no background card — just quiet text.
 *   • Streaming  — content visible at low opacity (≈0.45) so it reads
 *                   like a watermark behind the agent's real output.
 *   • Finalized  — collapsed by default; clicking reveals full content at
 *                   slightly higher opacity (≈0.65) for readability.
 */
import { ChevronRight } from 'lucide-react'
import { AnimatePresence, motion } from 'framer-motion'
import { useEffect, useMemo, useRef, useState } from 'react'

import { ThinkingDots } from '@/components/motion/ThinkingDots'
import { panelTransition, useMotionPreset } from '@/lib/motion'
import { cn } from '@/lib/utils'
import { splitSections } from '@/utils/thinking'

interface ThinkingProps {
  content: string
  isStreaming?: boolean
}

export function Thinking({ content, isStreaming }: ThinkingProps) {
  const preset = useMotionPreset()
  const [open, setOpen] = useState(true)
  const contentRef = useRef<HTMLDivElement>(null)

  // Auto-collapse once streaming finishes.
  useEffect(() => {
    if (!isStreaming && open) setOpen(false)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isStreaming])

  // Auto-scroll to bottom during streaming.
  useEffect(() => {
    if (isStreaming && contentRef.current) {
      contentRef.current.scrollTop = contentRef.current.scrollHeight
    }
  }, [content, isStreaming])

  // Only parse sections while open — keep collapsed updates cheap.
  const sections = useMemo(
    () => (open ? splitSections(content) : []),
    [content, open],
  )

  const charCount = content.length

  const label = isStreaming
    ? 'Thinking'
    : charCount > 0
      ? `Thought · ${charCount.toLocaleString()} chars`
      : 'Thinking'

  return (
    <div className="my-2 min-w-0">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="group/my-2 flex items-center gap-1.5 py-0.5 text-[11px] leading-none text-(--color-text-subtle) opacity-75 transition-opacity hover:opacity-100"
        aria-expanded={open}
      >
        <ChevronRight
          size={10}
          className={cn(
            'shrink-0 text-(--color-text-subtle) opacity-0 transition-transform duration-(--motion-fast) group-hover/my-2:opacity-60',
            open && 'rotate-90',
          )}
          aria-hidden="true"
        />
        <span className="italic">{label}</span>
        {isStreaming && <ThinkingDots className="text-(--color-text-subtle)" />}
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            key="thinking-body"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={panelTransition(preset)}
            className="overflow-hidden"
          >
            <div
              ref={contentRef}
              className={cn(
                'ml-2 max-h-60 overflow-y-auto border-l border-(--color-border) pl-3',
                isStreaming ? 'opacity-60' : 'opacity-80',
              )}
            >
              <div className="min-w-0 space-y-1.5 font-mono text-[11px] leading-relaxed text-(--color-text-muted) [overflow-wrap:anywhere]">
                {sections.map((s, i) => (
                  <div key={i} className="min-w-0">
                    {s.header && (
                      <p className="mb-0.5 break-words text-[11px] font-medium text-(--color-text-subtle) [overflow-wrap:anywhere]">
                        {s.header}
                      </p>
                    )}
                    {s.body && (
                      <p className="whitespace-pre-wrap break-words [overflow-wrap:anywhere]">
                        {s.body}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
