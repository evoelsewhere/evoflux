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
 *   • Streaming  — expanded by default so the live trace stays visible.
 *   • Finalized  — automatically collapses when streaming finishes.
 */
import { ChevronRight } from 'lucide-react'
import { AnimatePresence, motion } from 'framer-motion'
import { useEffect, useMemo, useRef, useState } from 'react'

import { ActivityStatus } from '@/components/motion/ActivityStatus'
import { panelTransition, useMotionPreset } from '@/lib/motion'
import { cn } from '@/lib/utils'
import { splitSections } from '@/utils/thinking'
import { getIntlLocale } from '@/i18n'

interface ThinkingProps {
  content: string
  isStreaming?: boolean
}

export function Thinking({ content, isStreaming }: ThinkingProps) {
  const preset = useMotionPreset()
  const [open, setOpen] = useState(Boolean(isStreaming))
  const contentRef = useRef<HTMLDivElement>(null)

  // Follow the stream lifecycle by default: reveal live reasoning, then put
  // the completed trace away. Users can still toggle it manually afterward.
  useEffect(() => {
    setOpen(Boolean(isStreaming))
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
      ? `Thought · ${charCount.toLocaleString(getIntlLocale())} chars`
      : 'Thinking'

  return (
    <div className="my-2 min-w-0">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="group/my-2 flex items-center gap-1.5 py-0.5 text-[11px] leading-none text-(--color-text-subtle) opacity-75 transition-opacity hover:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-(--focus-ring)"
        aria-expanded={open}
        aria-label={open ? `Collapse ${label}` : `Expand ${label}`}
      >
        <ChevronRight
          size={10}
          className={cn(
            'shrink-0 text-(--color-text-subtle) opacity-40 transition-[opacity,transform] duration-(--motion-fast) group-hover/my-2:opacity-60',
            open && 'rotate-90',
          )}
          aria-hidden="true"
        />
        {isStreaming ? (
          <ActivityStatus label={label} className="text-[11px] italic" />
        ) : (
          <span className="italic">{label}</span>
        )}
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            key="thinking-body"
            initial={preset.intensity === 'reduced' ? false : { height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={preset.intensity === 'reduced' ? undefined : { height: 0, opacity: 0 }}
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
              <div data-i18n-ignore className="min-w-0 space-y-1.5 font-mono text-[11px] leading-relaxed text-(--color-text-muted) [overflow-wrap:anywhere]">
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
