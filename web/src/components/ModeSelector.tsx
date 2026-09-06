import { useEffect, useId, useRef, useState } from 'react'
import { Check, ChevronDown, Shield } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { PermissionMode } from '@/api/types'

interface ModeDef {
  id: PermissionMode
  label: string
  description: string
  shortcut: number
  /**
   * How the closed trigger reads. A mode that changes what the agent is
   * allowed to do has to be visible without opening the menu — Plan mode
   * silently behaving like Plan mode is the point, and Bypass silently
   * behaving like Bypass is a hazard.
   */
  tone?: 'guarded' | 'planning' | 'unguarded'
}

const TRIGGER_TONE: Record<NonNullable<ModeDef['tone']>, string> = {
  guarded: 'text-(--color-marker-blue)',
  planning: 'text-(--color-violet)',
  unguarded: 'text-(--color-warning)',
}

const MODES: ModeDef[] = [
  {
    id: 'ask',
    label: 'Ask permissions',
    description: 'Pauses before every tool call for your approval.',
    shortcut: 1,
    tone: 'guarded',
  },
  {
    id: 'accept-edits',
    label: 'Accept edits',
    description:
      'Auto-accepts file edits. Shell and destructive operations still ask.',
    shortcut: 2,
  },
  {
    id: 'plan',
    label: 'Plan mode',
    description:
      'Records edits and shell as a plan instead of running them, until you accept it.',
    shortcut: 3,
    tone: 'planning',
  },
  {
    id: 'auto',
    label: 'Auto mode',
    description:
      'Approves every operation, but still honours deny rules and confirms irreversible actions.',
    shortcut: 4,
  },
  {
    id: 'bypass',
    label: 'Bypass permissions',
    description:
      'Runs everything unchecked — deny rules and irreversible-action confirmations do not apply.',
    shortcut: 5,
    tone: 'unguarded',
  },
]

interface ModeSelectorProps {
  mode: PermissionMode
  onModeChange: (mode: PermissionMode) => void
  disabled?: boolean
}

export function ModeSelector({ mode, onModeChange, disabled }: ModeSelectorProps) {
  const [open, setOpen] = useState(false)
  // Which row the keyboard is on. Starts on the active mode so Enter alone is
  // a no-op rather than a surprise.
  const [activeIndex, setActiveIndex] = useState(0)
  const containerRef = useRef<HTMLDivElement>(null)
  const listRef = useRef<HTMLDivElement>(null)
  const optionIdPrefix = useId()
  const optionId = (index: number) => `${optionIdPrefix}-option-${index}`

  const currentIndex = MODES.findIndex((m) => m.id === mode)
  const current = currentIndex >= 0 ? MODES[currentIndex] : MODES[3]

  // Close on outside click
  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (!containerRef.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  // Focus the list so arrows, Home/End and the digits reach it rather than the
  // composer behind it. Without this the listbox is one in name only: nothing
  // announces it, and every key it handles is also typed into whatever had
  // focus when it opened.
  useEffect(() => {
    if (open) listRef.current?.focus()
  }, [open])

  // Set on open rather than in an effect: the starting row is a function of
  // the click, not of a render that has already happened.
  const toggle = () => {
    if (disabled) return
    if (open) {
      setOpen(false)
      return
    }
    setActiveIndex(currentIndex >= 0 ? currentIndex : 3)
    setOpen(true)
  }

  const commit = (index: number) => {
    const target = MODES[index]
    if (target) onModeChange(target.id)
    setOpen(false)
  }

  const handleKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    const { key } = event
    if (key === 'Escape') {
      event.preventDefault()
      event.stopPropagation()
      setOpen(false)
      return
    }
    if (key === 'ArrowDown' || key === 'ArrowUp') {
      event.preventDefault()
      const step = key === 'ArrowDown' ? 1 : -1
      setActiveIndex((i) => (i + step + MODES.length) % MODES.length)
      return
    }
    if (key === 'Home' || key === 'End') {
      event.preventDefault()
      setActiveIndex(key === 'Home' ? 0 : MODES.length - 1)
      return
    }
    if (key === 'Enter' || key === ' ') {
      event.preventDefault()
      commit(activeIndex)
      return
    }
    if (key >= '1' && key <= String(MODES.length)) {
      // Consume it. This used to ride a document listener that never called
      // preventDefault, so picking a mode by number also typed that digit into
      // the user's unsent message.
      event.preventDefault()
      commit(Number(key) - 1)
    }
  }

  return (
    <div ref={containerRef} className="relative shrink-0">
      {/* Trigger badge — only shows when non-default OR always as compact icon */}
      <button
        type="button"
        onClick={toggle}
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
        title={`Agent permission mode: ${current.label}. ${current.description}`}
        className={cn(
          'composer-mode-trigger flex h-7 max-w-40 items-center gap-1.5 rounded-[7px] px-2 text-xs font-medium outline-none transition-[background-color,color,transform]',
          'hover:bg-(--bg-key) active:translate-y-px focus-visible:ring-2 focus-visible:ring-(--color-accent)/30',
          current.tone ? TRIGGER_TONE[current.tone] : 'text-(--color-text-muted) hover:text-(--color-text)',
          open && 'bg-(--bg-key)',
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
          ref={listRef}
          role="listbox"
          tabIndex={-1}
          aria-label="Permission mode"
          aria-activedescendant={optionId(activeIndex)}
          onKeyDown={handleKeyDown}
          className={cn(
            'absolute bottom-full right-0 z-(--z-modal) mb-2 w-[min(22rem,calc(100vw-1rem))] overflow-hidden p-1',
            'rounded-lg border border-(--color-border) bg-(--color-surface) shadow-(--shadow-popover) outline-none',
          )}
        >
          <div className="px-2 pb-1.5 pt-1 text-xs font-semibold text-(--color-text)">
            Permission mode
          </div>
          {MODES.map((m, index) => (
            <button
              key={m.id}
              id={optionId(index)}
              type="button"
              role="option"
              // Not a tab stop: the list owns focus and moves the selection
              // with aria-activedescendant, per the listbox pattern.
              tabIndex={-1}
              aria-selected={mode === m.id}
              onMouseEnter={() => setActiveIndex(index)}
              onClick={() => commit(index)}
              className={cn(
                'grid w-full grid-cols-[14px_minmax(0,1fr)_12px] items-start gap-2 rounded-md px-2 py-1.5 text-left outline-none transition-colors',
                mode === m.id && 'bg-(--bg-key)',
                activeIndex === index && 'bg-(--bg-key)',
              )}
            >
              <Check
                size={13}
                aria-hidden="true"
                className={cn(
                  'mt-0.5',
                  mode === m.id ? 'opacity-100 text-(--color-text)' : 'opacity-0',
                )}
              />
              <span className="min-w-0 flex-1">
                <span className="block text-xs font-medium text-(--color-text)">{m.label}</span>
                {/* Wraps rather than truncating. The clipped half used to be
                    the half that mattered — what a mode still asks about, and
                    what Bypass gives up. */}
                <span className="block text-[11px] leading-4 text-pretty text-(--color-text-subtle)">
                  {m.description}
                </span>
              </span>
              <span className="mt-0.5 text-right text-[10px] tabular-nums text-(--color-text-subtle)">
                {m.shortcut}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
