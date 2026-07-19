import { useEffect, useRef, useState } from 'react'
import { Check, ChevronUp, Shield } from 'lucide-react'
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
    description: 'Agent must show a plan and get approval before executing',
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
  const isNonDefault = mode !== 'auto'

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
    <div ref={containerRef} className="relative">
      {/* Trigger badge — only shows when non-default OR always as compact icon */}
      <button
        onClick={() => !disabled && setOpen((v) => !v)}
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
        title="Agent permission mode"
        className={cn(
          'flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium transition-colors',
          'border border-(--color-border) bg-(--bg-card)',
          isNonDefault
            ? 'text-(--color-text) hover:bg-(--bg-key)'
            : 'text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text)',
          disabled && 'cursor-default opacity-50',
        )}
      >
        <Shield size={11} aria-hidden="true" className={cn(isNonDefault && 'text-(--color-primary)')} />
        <span>{current.label}</span>
        <ChevronUp
          size={10}
          aria-hidden="true"
          className={cn('transition-transform', !open && 'rotate-180')}
        />
      </button>

      {/* Dropdown */}
      {open && (
        <div
          role="listbox"
          aria-label="Permission mode"
          className={cn(
            'absolute bottom-full left-0 z-(--z-modal) mb-1 min-w-64 overflow-hidden',
            'rounded-xl border border-(--color-border) bg-(--bg-page) shadow-xl',
          )}
        >
          <div className="px-3 pt-3 pb-1 text-xs font-semibold uppercase tracking-wider text-(--color-text-muted)">
            Mode
          </div>
          {MODES.map((m) => (
            <button
              key={m.id}
              role="option"
              aria-selected={mode === m.id}
              onClick={() => { onModeChange(m.id); setOpen(false) }}
              className={cn(
                'flex w-full items-center gap-2 px-3 py-2 text-left transition-colors',
                'hover:bg-(--bg-key)',
                mode === m.id && 'bg-(--bg-key)',
              )}
            >
              <Check
                size={13}
                aria-hidden="true"
                className={cn('shrink-0', mode === m.id ? 'opacity-100 text-(--color-primary)' : 'opacity-0')}
              />
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-medium text-(--color-text)">{m.label}</span>
                <span className="block text-xs text-(--color-text-muted)">{m.description}</span>
              </span>
              <span className="shrink-0 rounded bg-(--bg-card) px-1.5 py-0.5 text-xs text-(--color-text-muted) border border-(--color-border)">
                {m.shortcut}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
