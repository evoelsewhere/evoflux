import { useEffect, useId, useRef, useState } from 'react'
import { Check, ChevronDown, CircleAlert, Hand, ShieldCheck, type LucideIcon } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { PermissionMode } from '@/api/types'

interface ModeDef {
  id: PermissionMode
  label: string
  description: string
  icon: LucideIcon
  /**
   * Full access has to be visible without opening the menu — the mode that
   * stops asking must never pass for one of the others.
   */
  unguarded?: boolean
}

const UNGUARDED_TONE = 'text-(--color-warning)'

// Digits 1–3 pick a mode while the list is open, in this order.
const MODES: ModeDef[] = [
  {
    id: 'ask',
    label: 'Ask for approval',
    description: 'Always asks before editing files, running commands or taking other actions.',
    icon: Hand,
  },
  {
    id: 'auto',
    label: 'Approve for me',
    description: 'Only asks for actions detected as potentially unsafe.',
    icon: ShieldCheck,
  },
  {
    id: 'bypass',
    label: 'Full access',
    description: 'Runs every action without asking. Only the sandbox still applies.',
    icon: CircleAlert,
    unguarded: true,
  },
]

// Sessions default to auto; an unknown mode falls back to it.
const DEFAULT_INDEX = MODES.findIndex((m) => m.id === 'auto')

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
  const current = currentIndex >= 0 ? MODES[currentIndex] : MODES[DEFAULT_INDEX]

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
    setActiveIndex(currentIndex >= 0 ? currentIndex : DEFAULT_INDEX)
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
          'hover:bg-(--bg-key) active:translate-y-px focus-visible:bg-(--bg-key) focus-visible:ring-1 focus-visible:ring-(--color-border-strong)',
          current.unguarded ? UNGUARDED_TONE : 'text-(--color-text-muted) hover:text-(--color-text)',
          open && 'bg-(--bg-key)',
          disabled && 'cursor-default opacity-50',
        )}
      >
        <current.icon size={14} aria-hidden="true" className="shrink-0" />
        <span className="composer-mode-label truncate">{current.label}</span>
        <ChevronDown
          size={10}
          aria-hidden="true"
          className={cn('composer-mode-chevron shrink-0 transition-transform', open && 'rotate-180')}
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
                'grid w-full grid-cols-[16px_minmax(0,1fr)_14px] items-start gap-2.5 rounded-md px-2 py-2 text-left outline-none transition-colors',
                activeIndex === index && 'bg-(--bg-key)',
                m.unguarded ? UNGUARDED_TONE : 'text-(--color-text)',
              )}
            >
              <m.icon
                size={15}
                aria-hidden="true"
                className={cn('mt-0.5', !m.unguarded && 'text-(--color-text-muted)')}
              />
              <span className="min-w-0 flex-1">
                <span className="block text-xs font-medium">{m.label}</span>
                {/* Wraps rather than truncating. The clipped half used to be
                    the half that mattered — what a mode still asks about, and
                    what Full access gives up. */}
                <span
                  className={cn(
                    'block text-[11px] leading-4 text-pretty',
                    m.unguarded ? 'opacity-80' : 'text-(--color-text-subtle)',
                  )}
                >
                  {m.description}
                </span>
              </span>
              <Check
                size={14}
                aria-hidden="true"
                className={cn('mt-0.5', mode === m.id ? 'opacity-100' : 'opacity-0')}
              />
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
