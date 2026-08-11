import { useEffect, useRef, useState } from 'react'
import { Check, ChevronDown, Shield } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { PermissionMode } from '@/api/types'

interface ModeDef {
  id: PermissionMode
  label: string
  description: string
  shortcut: number
}

const MODES: ModeDef[] = [
  {
    id: 'ask',
    label: 'Ask permissions',
    description: 'Pauses before every tool call for your approval',
    shortcut: 1,
  },
  {
    id: 'accept-edits',
    label: 'Accept edits',
    description: 'Auto-accepts file edits; asks for shell & destructive ops',
    shortcut: 2,
  },
  {
    id: 'plan',
    label: 'Plan mode',
    description: 'Plan then approve — records edits/shell until you Accept',
    shortcut: 3,
  },
  {
    id: 'auto',
    label: 'Auto mode',
    description: 'Automatically approves all operations',
    shortcut: 4,
  },
  {
    id: 'bypass',
    label: 'Bypass permissions',
    description: 'Skips all permission checks — fastest, no approval prompts',
    shortcut: 5,
  },
]

interface ModeSelectorProps {
  mode: PermissionMode
  onModeChange: (mode: PermissionMode) => void
  disabled?: boolean
}

export function ModeSelector({ mode, onModeChange, disabled }: ModeSelectorProps) {
  const [open, setOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  const current = MODES.find((m) => m.id === mode) ?? MODES[3]
  // Close on outside click
  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (!containerRef.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  // Keyboard shortcuts 1-5 when menu is open, Esc to close
  useEffect(() => {
    if (!open) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { setOpen(false); return }
      const n = parseInt(e.key)
      if (n >= 1 && n <= 5) {
        const target = MODES[n - 1]
        onModeChange(target.id)
        setOpen(false)
      }
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [open, onModeChange])

  return (
    <div ref={containerRef} className="relative shrink-0">
      {/* Trigger badge — only shows when non-default OR always as compact icon */}
      <button
        type="button"
        onClick={() => !disabled && setOpen((v) => !v)}
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
        title="Agent permission mode"
        className={cn(
          'composer-mode-trigger flex h-7 max-w-40 items-center gap-1.5 rounded-[7px] px-2 text-xs font-medium text-(--color-text-muted) outline-none transition-[background-color,color,transform]',
          'hover:bg-(--bg-key) hover:text-(--color-text) active:translate-y-px focus-visible:ring-2 focus-visible:ring-(--color-accent)/30',
          open && 'bg-(--bg-key) text-(--color-text)',
          disabled && 'cursor-default opacity-50',
        )}
      >
        <Shield size={12} aria-hidden="true" className="shrink-0" />
        <span className="composer-mode-label truncate">{current.label}</span>
        <ChevronDown
          size={10}
          aria-hidden="true"
          className={cn('shrink-0 transition-transform', open && 'rotate-180')}
        />
      </button>

      {/* Dropdown */}
      {open && (
        <div
          role="listbox"
          aria-label="Permission mode"
          className={cn(
            'absolute bottom-full right-0 z-(--z-modal) mb-2 w-[min(18rem,calc(100vw-1rem))] overflow-hidden p-1',
            'rounded-lg border border-(--color-border) bg-(--color-surface) shadow-(--shadow-popover)',
          )}
        >
          <div className="px-2 pb-1.5 pt-1 text-xs font-semibold text-(--color-text)">
            Permission mode
          </div>
          {MODES.map((m) => (
            <button
              key={m.id}
              type="button"
              role="option"
              aria-selected={mode === m.id}
              onClick={() => { onModeChange(m.id); setOpen(false) }}
              className={cn(
                'grid w-full grid-cols-[14px_minmax(0,1fr)_12px] items-center gap-2 rounded-md px-2 py-1.5 text-left outline-none transition-colors',
                'hover:bg-(--bg-key) focus-visible:bg-(--bg-key)',
                mode === m.id && 'bg-(--bg-key)',
              )}
            >
              <Check
                size={13}
                aria-hidden="true"
                className={cn(mode === m.id ? 'opacity-100 text-(--color-text)' : 'opacity-0')}
              />
              <span className="min-w-0 flex-1">
                <span className="block text-xs font-medium text-(--color-text)">{m.label}</span>
                <span className="block truncate text-[11px] leading-4 text-(--color-text-subtle)">{m.description}</span>
              </span>
              <span className="text-right text-[10px] tabular-nums text-(--color-text-subtle)">
                {m.shortcut}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
