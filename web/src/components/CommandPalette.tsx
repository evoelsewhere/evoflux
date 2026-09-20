/**
 * CommandPalette — Ctrl+P search overlay for the whole application.
 *
 * Two sources feed one list. `commands` holds the actions the app can perform
 * (pure data, matched locally on label, description, group and keywords).
 * `searchCommands` is the asynchronous content search — sessions, messages,
 * Memory, projects, scheduled tasks, agents, skills and, in a Coding
 * workspace, repository files and symbols. Each command carries a label,
 * description, optional shortcut hint and an action callback. Activated and
 * dismissed from the parent via the `onClose` prop.
 */

import { useState, useRef, useEffect, useCallback, useMemo } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Search, CornerDownLeft } from 'lucide-react'
import { useProximityTracker, useProximityIntensity } from '@/hooks/useProximity'
import { useModalFocus } from '@/hooks/useModalFocus'
import { useReducedMotion } from '@/hooks/useReducedMotion'
import { reducedMotionTransition, useMotionPreset } from '@/lib/motion'
import { usePlatform } from '@/hooks/use-platform'
import { useIsMobile } from '@/hooks/use-mobile'
import { useI18n } from '@/i18n'
import { formatShortcutLabel } from '@/lib/keyboard-shortcuts'

export interface Command {
  id: string
  label: string
  description?: string
  /** Right-aligned trailing note — a result's date, never an action. */
  meta?: string
  shortcut?: string
  /** Optional category for grouping */
  group?: string
  keywords?: string[]
  action: () => void
}

interface CommandPaletteProps {
  commands: Command[]
  searchCommands?: (query: string, signal: AbortSignal) => Promise<Command[]>
  onClose: () => void
}

export function CommandPalette({ commands, searchCommands, onClose }: CommandPaletteProps) {
  const { t } = useI18n()
  const [query, setQuery] = useState('')
  const [activeIdx, setActiveIdx] = useState(0)
  const [remoteCommands, setRemoteCommands] = useState<Command[]>([])
  const [searching, setSearching] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLDivElement>(null)
  const mouseY = useProximityTracker(listRef)
  const prefersReducedMotion = useReducedMotion()
  const preset = useMotionPreset()
  const isMobile = useIsMobile()
  const { isTauri, os } = usePlatform()
  const isTauriMobile = isMobile && isTauri && (os === 'ios' || os === 'android')
  useModalFocus(true, onClose)

  // Focus input on open
  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  // Filter commands by query — memoised so the reference only changes when query changes
  const localizedCommands = useMemo(() => commands.map((command) => ({
    ...command,
    label: t(command.label),
    description: command.description ? t(command.description) : undefined,
    group: command.group ? t(command.group) : undefined,
  })), [commands, t])

  useEffect(() => {
    const normalized = query.trim()
    if (!searchCommands || normalized.length < 2) {
      setRemoteCommands([]) // eslint-disable-line react-hooks/set-state-in-effect -- query reset owns remote results
      setSearching(false)
      return
    }
    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      setSearching(true)
      void searchCommands(normalized, controller.signal)
        .then((items) => {
          if (!controller.signal.aborted) setRemoteCommands(items)
        })
        .catch(() => {
          if (!controller.signal.aborted) setRemoteCommands([])
        })
        .finally(() => {
          if (!controller.signal.aborted) setSearching(false)
        })
    }, 180)
    return () => {
      window.clearTimeout(timer)
      controller.abort()
    }
  }, [query, searchCommands])

  const filtered = useMemo(() => {
    const local = query.trim()
      ? localizedCommands.filter((cmd) => {
        const q = query.toLowerCase()
        return (
          cmd.label.toLowerCase().includes(q) ||
          cmd.description?.toLowerCase().includes(q) ||
          cmd.group?.toLowerCase().includes(q) ||
          cmd.keywords?.some((keyword) => keyword.toLowerCase().includes(q))
        )
      })
      : localizedCommands
    const byId = new Map<string, Command>(
      local.map((command) => [command.id, command]),
    )
    // Remote rows carry user content in label/description — never translated —
    // but their group header is app chrome and follows the UI locale.
    for (const command of remoteCommands) {
      byId.set(command.id, {
        ...command,
        group: command.group ? t(command.group) : undefined,
      })
    }
    return [...byId.values()]
  }, [localizedCommands, query, remoteCommands, t])

  // A late result set can be shorter than the one the user was arrowing
  // through, which used to leave the highlight past the end — no visible
  // selection, and Enter doing nothing. Clamp on the way out instead.
  const activeIndex = filtered.length > 0 ? Math.min(activeIdx, filtered.length - 1) : 0

  // Scroll active item into view
  useEffect(() => {
    const el = listRef.current?.querySelector(`[data-idx="${activeIndex}"]`) as HTMLElement | null
    el?.scrollIntoView({ block: 'nearest' })
  }, [activeIndex])

  const run = useCallback(
    (cmd: Command) => {
      onClose()
      cmd.action()
    },
    [onClose],
  )

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      onClose()
      return
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActiveIdx(Math.min(activeIndex + 1, filtered.length - 1))
      return
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActiveIdx(Math.max(activeIndex - 1, 0))
      return
    }
    if (e.key === 'Enter') {
      e.preventDefault()
      const cmd = filtered[activeIndex]
      if (cmd) run(cmd)
      return
    }
  }

  // Group commands for display
  const groups = new Map<string, Command[]>()
  for (const cmd of filtered) {
    const g = cmd.group ?? ''
    if (!groups.has(g)) groups.set(g, [])
    groups.get(g)!.push(cmd)
  }

  // Flat list with group headers for rendering (track absolute index)
  type Row = { type: 'header'; label: string } | { type: 'cmd'; cmd: Command; idx: number }
  const rows: Row[] = []
  let absIdx = 0
  for (const [group, cmds] of groups.entries()) {
    if (group) rows.push({ type: 'header', label: group })
    for (const cmd of cmds) {
      rows.push({ type: 'cmd', cmd, idx: absIdx++ })
    }
  }

  return (
    <AnimatePresence>
      <motion.div
        key="backdrop"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className={`fixed inset-0 z-(--z-modal) flex items-start justify-center bg-(--color-overlay) px-3 backdrop-blur-sm sm:px-0 sm:pt-[15vh] ${isTauriMobile ? 'pt-[max(5rem,calc(env(safe-area-inset-top)+3.5rem))]' : 'pt-4'}`}
        onClick={onClose}
      >
        <motion.div
          key="panel"
          initial={prefersReducedMotion ? { opacity: 0 } : { opacity: 0, scale: 0.97, y: -8 * preset.distance }}
          animate={prefersReducedMotion ? { opacity: 1 } : { opacity: 1, scale: 1, y: 0 }}
          exit={prefersReducedMotion ? { opacity: 0 } : { opacity: 0, scale: 0.97, y: -8 * preset.distance }}
          transition={reducedMotionTransition(Boolean(prefersReducedMotion), preset.spring)}
          onClick={(e) => e.stopPropagation()}
          /* Wider than a command-only palette needed: rows now carry message
             excerpts and repository paths, which read badly at 28rem. */
          className="flex w-full max-w-md flex-col overflow-hidden rounded-2xl border border-(--color-border) bg-(--bg-card) shadow-2xl sm:max-w-2xl"
          role="dialog"
          aria-modal="true"
          aria-label="Command palette"
          data-modal-focus="true"
          onKeyDown={handleKeyDown}
        >
          {/* Search input */}
          <div className="flex items-center gap-3 border-b border-(--color-border) px-4 py-3">
            <Search size={15} className="shrink-0 text-(--color-text-muted)" />
            <input
              ref={inputRef}
              value={query}
              onChange={(e) => {
                setQuery(e.target.value)
                setActiveIdx(0)
              }}
              placeholder="Search sessions, messages, files, settings…"
              className="flex-1 bg-transparent text-sm text-(--color-text) placeholder-(--color-text-muted) outline-none"
              aria-label="Search everything"
            />
            {query && (
              <button
                onClick={() => {
                  setQuery('')
                  setActiveIdx(0)
                }}
                className="text-xs text-(--color-text-muted) hover:text-(--color-text-2)"
              >
                Clear
              </button>
            )}
          </div>

          {/* Command list */}
          <div
            ref={listRef}
            aria-busy={searching}
            className="max-h-80 overflow-y-auto py-1.5 sm:max-h-[26rem]"
          >
            {filtered.length === 0 ? (
              searching ? (
                <SearchSkeleton count={5} still={Boolean(prefersReducedMotion)} />
              ) : (
                <p className="px-4 py-6 text-center text-sm text-(--color-text-muted)">
                  Nothing matches "{query}"
                </p>
              )
            ) : (
              rows.map((row, i) => {
                if (row.type === 'header') {
                  return (
                    <p
                      key={`h-${i}`}
                      className="px-4 pb-1 pt-3 text-xs font-semibold uppercase tracking-widest text-(--color-text-muted)"
                    >
                      {row.label}
                    </p>
                  )
                }
                const isActive = row.idx === activeIndex
                return (
                  <CommandRow
                    key={row.cmd.id}
                    cmd={row.cmd}
                    idx={row.idx}
                    isActive={isActive}
                    mouseY={mouseY}
                    onRun={run}
                    onActivate={setActiveIdx}
                  />
                )
              })
            )}
            {/* Results are already on screen but more are still coming. */}
            {filtered.length > 0 && searching && (
              <SearchSkeleton count={2} still={Boolean(prefersReducedMotion)} />
            )}
          </div>

          {/* Footer hint */}
          <div className="flex items-center gap-2 border-t border-(--color-border) px-4 py-2">
            <kbd className="rounded-xs border border-(--color-border) bg-(--bg-page) px-1 py-0.5 font-mono text-xs text-(--color-text-muted)">↑↓</kbd>
            <span className="text-xs text-(--color-text-muted)">navigate</span>
            <kbd className="rounded-xs border border-(--color-border) bg-(--bg-page) px-1 py-0.5 font-mono text-xs text-(--color-text-muted)">↵</kbd>
            <span className="text-xs text-(--color-text-muted)">run</span>
            <kbd className="rounded-xs border border-(--color-border) bg-(--bg-page) px-1 py-0.5 font-mono text-xs text-(--color-text-muted)">Esc</kbd>
            <span className="text-xs text-(--color-text-muted)">close</span>
            {searching && <span className="ml-auto text-xs text-(--color-accent)">Searching…</span>}
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  )
}

/** Row-shaped placeholders while a search is in flight. */
const SKELETON_WIDTHS = ['72%', '54%', '83%', '61%', '46%']

function SearchSkeleton({ count, still }: { count: number; still: boolean }) {
  return (
    <div aria-hidden="true" data-testid="palette-skeleton">
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="flex flex-col gap-2 px-4 py-3">
          {/* Two bars per row, matching a result's label and description. */}
          <div
            className={`h-3.5 rounded-xs bg-(--bg-key) ${still ? '' : 'animate-pulse'}`}
            style={{ width: SKELETON_WIDTHS[i % SKELETON_WIDTHS.length] }}
          />
          <div
            className={`h-2.5 w-1/4 rounded-xs bg-(--bg-key) ${still ? '' : 'animate-pulse'}`}
          />
        </div>
      ))}
    </div>
  )
}

interface CommandRowProps {
  cmd: Command
  idx: number
  isActive: boolean
  mouseY: number | null
  onRun: (cmd: Command) => void
  onActivate: (idx: number) => void
}

/**
 * Single command row with proximity fade. The keyboard-driven `activeIdx`
 * still owns the dominant `accent-subtle` background; proximity adds a
 * softer `accent-dim` layer on nearby non-active rows so the cursor's
 * position is readable before `onMouseEnter` fires.
 *
 * Layering mirrors SessionRow in Sidebar: proximity is an absolute sibling
 * behind the button (`-z-10`, `isolation: isolate` on wrapper), so the
 * button's own `hover:bg-*` class can still paint on top without being
 * overridden by an inline style on the same element.
 */
function CommandRow({ cmd, idx, isActive, mouseY, onRun, onActivate }: CommandRowProps) {
  const { ref, intensity } = useProximityIntensity(mouseY)
  const showProximity = !isActive && intensity > 0

  return (
    <div ref={ref as React.RefObject<HTMLDivElement>} className="relative isolate">
      {showProximity && (
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 -z-10"
          style={{
            backgroundColor: `color-mix(in srgb, var(--bg-key) ${intensity * 100}%, transparent)`,
          }}
        />
      )}
      <button
        data-idx={idx}
        onClick={() => onRun(cmd)}
        onMouseEnter={() => onActivate(idx)}
        className={`flex w-full items-center gap-3 px-4 py-2.5 text-left transition-colors ${
          isActive
            ? 'bg-(--bg-key) text-(--color-text)'
            : 'text-(--color-text-2) hover:bg-(--bg-key)'
        }`}
      >
        <div className="min-w-0 flex-1">
          {/* Content rows carry whole message excerpts — keep every row one
              line so the list stays scannable. */}
          <span className="block truncate text-sm font-medium">{cmd.label}</span>
          {cmd.description && (
            <span className="block truncate text-xs text-(--color-text-muted)">
              {cmd.description}
            </span>
          )}
        </div>
        {cmd.meta && (
          // Least important column: a phone-width row keeps the label instead.
          <span className="hidden shrink-0 text-[11px] leading-none text-(--color-text-subtle) sm:block">
            {cmd.meta}
          </span>
        )}
        {cmd.shortcut && (
          <kbd className="shrink-0 rounded-xs border border-(--color-border) bg-(--bg-page) px-1.5 py-1 font-sans text-[11px] font-medium leading-none tracking-normal text-(--color-text-muted)">
            {formatShortcutLabel(cmd.shortcut)}
          </kbd>
        )}
        {isActive && (
          <CornerDownLeft size={12} className="shrink-0 text-(--color-text-muted)" />
        )}
      </button>
    </div>
  )
}
