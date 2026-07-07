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
import { ChevronRight, Sparkles } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'

import { cn } from '@/lib/utils'
import { splitSections } from '@/utils/thinking'

interface ThinkingProps {
  content: string
  isStreaming?: boolean
}

export function Thinking({ content, isStreaming }: ThinkingProps) {
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

  // ── Collapsed pill ──────────────────────────────────────────────
  // A single, quiet line — no card, no border, just faded text.
  // Clicking toggles the full content below.
  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="group/my-2 flex items-center gap-1.5 py-0.5 text-[11px] leading-none text-(--color-text-subtle) opacity-50 transition-opacity hover:opacity-80"
        aria-expanded={false}
      >
        <Sparkles
          size={11}
          className="shrink-0 text-(--accent-purple) opacity-60"
          aria-hidden="true"
        />
        <span className="italic">
          {isStreaming
            ? 'Thinking…'
            : charCount > 0
              ? `Thought · ${charCount.toLocaleString()} chars`
              : 'Thinking'}
        </span>
        <ChevronRight
          size={10}
          className="shrink-0 text-(--color-text-subtle) opacity-0 transition-all group-hover/my-2:opacity-60"
          aria-hidden="true"
        />
      </button>
    )
  }

  // ── Expanded / streaming ────────────────────────────────────────
  // Content rendered at low opacity for the ghosted/faded effect.
  // No heavy border — just a faint left accent line to anchor the block.
  return (
    <div className="my-2 min-w-0">
      {/* Toggle row — minimal, same style as collapsed */}
      <button
        type="button"
        onClick={() => setOpen(false)}
        className="group/my-2 flex items-center gap-1.5 py-0.5 text-[11px] leading-none text-(--color-text-subtle) opacity-50 transition-opacity hover:opacity-80"
        aria-expanded={true}
      >
        <Sparkles
          size={11}
          className={cn(
            'shrink-0 text-(--accent-purple) opacity-60',
            isStreaming && 'animate-pulse',
          )}
          aria-hidden="true"
        />
        <span className="italic">
          {isStreaming ? 'Thinking…' : 'Thinking'}
        </span>
        <ChevronRight
          size={10}
          className="shrink-0 rotate-90 text-(--color-text-subtle) opacity-0 transition-all group-hover/my-2:opacity-60"
          aria-hidden="true"
        />
      </button>

      {/* Ghosted content — low opacity, faint left border */}
      <div
        ref={contentRef}
        className={cn(
          'ml-2 max-h-60 overflow-y-auto border-l border-(--color-border) pl-3',
          // Streaming: very faded (watermark feel). Finalized: slightly more readable.
          isStreaming ? 'opacity-40' : 'opacity-60',
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
    </div>
  )
}
