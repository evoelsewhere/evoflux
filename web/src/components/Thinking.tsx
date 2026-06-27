/**
 * Thinking — collapsible inline reasoning trace.
 *
 * Reasoning streams from providers like OpenAI's ``/responses`` API or
 * MiMo's ``reasoning_content`` field. When the block is still streaming
 * it stays open; once finalized it collapses by default with a summary
 * label showing the block is a thinking trace.
 */
import { ChevronRight, Brain } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { cn } from '@/lib/utils'
import { splitSections } from '@/utils/thinking'

interface ThinkingProps {
  content: string
  isStreaming?: boolean
}

export function Thinking({ content, isStreaming }: ThinkingProps) {
  const [open, setOpen] = useState(true)
  const contentRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!isStreaming && open) {
      setOpen(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isStreaming])

  useEffect(() => {
    if (isStreaming && contentRef.current) {
      contentRef.current.scrollTop = contentRef.current.scrollHeight
    }
  }, [content, isStreaming])

  const sections = splitSections(content)
  const charCount = content.length
  const label = charCount > 0
    ? `Thinking · ${charCount.toLocaleString()} chars`
    : 'Thinking'

  return (
    <div className="my-2 min-w-0 overflow-hidden rounded-lg border border-(--color-border) bg-(--bg-card)">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full min-h-11 items-center gap-2 px-3 py-2 text-left text-xs font-medium text-(--color-text-muted) transition-colors hover:bg-(--bg-key) md:min-h-0"
        aria-expanded={open}
      >
        <Brain size={13} className="shrink-0 text-(--accent-purple)" aria-hidden="true" />
        <span className="flex-1 truncate">{label}</span>
        {isStreaming && (
          <span className="inline-flex items-center gap-1 text-xs text-(--accent-purple)">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-(--accent-purple)" />
            streaming
          </span>
        )}
        <ChevronRight
          size={13}
          className={cn(
            'shrink-0 transition-transform duration-150',
            open && 'rotate-90',
          )}
          aria-hidden="true"
        />
      </button>
      {open && (
        <div
          ref={contentRef}
          className="max-h-80 overflow-y-auto border-t border-(--color-border) px-3 py-2"
        >
          <div className="min-w-0 space-y-2 font-mono text-xs leading-relaxed text-(--color-text-2) [overflow-wrap:anywhere]">
            {sections.map((s, i) => (
              <div key={i} className="min-w-0">
                {s.header && (
                  <p className="mb-1 break-words font-semibold text-(--color-text) [overflow-wrap:anywhere]">{s.header}</p>
                )}
                {s.body && <p className="whitespace-pre-wrap break-words [overflow-wrap:anywhere]">{s.body}</p>}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
