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
import {
  Search, X, Command as CommandIcon, MessageSquare, MessagesSquare, Plus,
  Compass, PanelsTopLeft, Users, Settings, GitBranch, FileText, FileClock,
  Code2, TriangleAlert, Sparkles, Brain, FolderKanban, FolderGit2,
  CalendarClock, type LucideIcon,
} from 'lucide-react'
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
  /** Leading glyph; falls back to the icon of the command's group. */
  icon?: LucideIcon
  action: () => void
}

/**
 * Leading glyph per group, keyed by the untranslated group name the command
 * sources use (`useTeamCommands`, `useGlobalSearch`).
 */
const GROUP_ICONS: Record<string, LucideIcon> = {
  Team: Plus,
  View: PanelsTopLeft,
  Agents: Users,
  Navigation: Compass,
  Settings,
  Git: GitBranch,
  Chats: MessageSquare,
  'Mentioned in chats': MessagesSquare,
  Memory: Brain,
  Projects: FolderKanban,
  Repositories: FolderGit2,
  'Scheduled tasks': CalendarClock,
  Skills: Sparkles,
  Files: FileText,
  'Recent files': FileClock,
  Code: Code2,
  Problems: TriangleAlert,
}

type PaletteCommand = Command & { glyph: LucideIcon }

function withGlyph(command: Command): PaletteCommand {
  return {
    ...command,
    glyph: command.icon ?? (command.group ? GROUP_ICONS[command.group] : undefined) ?? CommandIcon,
  }
}

const KBD_CLASS =
  'inline-flex h-5 min-w-5 items-center justify-center rounded-[5px] border border-(--color-border) bg-(--bg-page) px-1.5 font-sans text-[11px] font-medium leading-none text-(--color-text-muted)'

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
    ...withGlyph(command),
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
    const byId = new Map<string, PaletteCommand>(
      local.map((command) => [command.id, command]),
    )
    // Remote rows carry user content in label/description — never translated —
    // but their group header is app chrome and follows the UI locale.
    for (const command of remoteCommands) {
      byId.set(command.id, {
        ...withGlyph(command),
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
  const groups = new Map<string, PaletteCommand[]>()
  for (const cmd of filtered) {
    const g = cmd.group ?? ''
    if (!groups.has(g)) groups.set(g, [])
    groups.get(g)!.push(cmd)
  }

  // Flat list with group headers for rendering (track absolute index)
  type Row = { type: 'header'; label: string } | { type: 'cmd'; cmd: PaletteCommand; idx: number }
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
        /* A light dim, not a heavy blur: the app behind should stay legible
           as context, and a frosted page made the panel's edges vanish. */
        className={`fixed inset-0 z-(--z-modal) flex items-start justify-center bg-black/25 px-3 backdrop-blur-[2px] sm:px-0 sm:pt-[14vh] dark:bg-black/45 ${isTauriMobile ? 'pt-[max(5rem,calc(env(safe-area-inset-top)+3.5rem))]' : 'pt-4'}`}
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
             excerpts and repository paths, which read badly at 28rem. The
             surface is opaque — a translucent card over a blurred page read
             as washed-out grey on grey. */
          className="flex w-full max-w-md flex-col overflow-hidden rounded-xl border border-(--color-border) bg-(--bg-card) shadow-(--shadow-popover) sm:max-w-[40rem]"
          role="dialog"
          aria-modal="true"
          aria-label="Command palette"
          data-modal-focus="true"
          onKeyDown={handleKeyDown}
        >
          {/* Search input */}
          <div className="flex h-13 items-center gap-3 border-b border-(--color-border-subtle) px-4">
            <Search size={17} className="shrink-0 text-(--color-text-muted)" />
            <input
              ref={inputRef}
              value={query}
              onChange={(e) => {
                setQuery(e.target.value)
                setActiveIdx(0)
              }}
              placeholder="Search sessions, messages, files, settings…"
              className="h-full flex-1 bg-transparent text-[15px] text-(--color-text) placeholder-(--color-text-muted) outline-none"
              aria-label="Search everything"
            />
            {query ? (
              <button
                type="button"
                onClick={() => {
                  setQuery('')
                  setActiveIdx(0)
                  inputRef.current?.focus()
                }}
                className="flex size-6 shrink-0 items-center justify-center rounded-md text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
                aria-label="Clear"
              >
                <X size={14} />
              </button>
            ) : (
              <kbd className={`${KBD_CLASS} shrink-0`}>Esc</kbd>
            )}
          </div>

          {/* Command list */}
          <div
            ref={listRef}
            aria-busy={searching}
            className="max-h-80 overflow-y-auto overscroll-contain p-1.5 [scrollbar-width:thin] sm:max-h-[26rem]"
          >
            {filtered.length === 0 ? (
              searching ? (
                <SearchSkeleton count={5} still={Boolean(prefersReducedMotion)} />
              ) : (
                <div className="flex flex-col items-center gap-2 px-4 py-10 text-center">
                  <Search size={20} className="text-(--color-text-subtle)" />
                  <p className="text-sm text-(--color-text-muted)">
                    Nothing matches "{query}"
                  </p>
                </div>
              )
            ) : (
              rows.map((row, i) => {
                if (row.type === 'header') {
                  return (
                    <p
                      key={`h-${i}`}
                      className={`px-2.5 pb-1.5 text-[11px] font-medium text-(--color-text-subtle) ${i === 0 ? 'pt-1.5' : 'pt-3'}`}
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
          <div className="flex h-9 items-center gap-4 border-t border-(--color-border-subtle) bg-(--bg-page)/60 px-4 text-[11px] text-(--color-text-muted)">
            <span className="flex items-center gap-1.5">
              <kbd className={KBD_CLASS}>↑</kbd>
              <kbd className={KBD_CLASS}>↓</kbd>
              <span>navigate</span>
            </span>
            <span className="flex items-center gap-1.5">
              <kbd className={KBD_CLASS}>↵</kbd>
              <span>run</span>
            </span>
            <span className="ml-auto">
              {searching ? (
                <span className="text-(--color-accent)">Searching…</span>
              ) : (
                query.trim() && filtered.length > 0 && t('{0} results', [filtered.length])
              )}
            </span>
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
        <div key={i} className="flex min-h-11 items-center gap-3 px-2.5 py-1.5">
          {/* Glyph tile plus two bars, matching a result row's shape. */}
          <div className={`size-7 shrink-0 rounded-md bg-(--bg-key) ${still ? '' : 'animate-pulse'}`} />
          <div className="flex min-w-0 flex-1 flex-col gap-1.5">
            <div
              className={`h-3 rounded-xs bg-(--bg-key) ${still ? '' : 'animate-pulse'}`}
              style={{ width: SKELETON_WIDTHS[i % SKELETON_WIDTHS.length] }}
            />
            <div
              className={`h-2.5 w-1/4 rounded-xs bg-(--bg-key) ${still ? '' : 'animate-pulse'}`}
            />
          </div>
        </div>
      ))}
    </div>
  )
}

interface CommandRowProps {
  cmd: PaletteCommand
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
  const Glyph = cmd.glyph

  return (
    <div ref={ref as React.RefObject<HTMLDivElement>} className="relative isolate">
      {showProximity && (
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 -z-10 rounded-lg"
          style={{
            backgroundColor: `color-mix(in srgb, var(--bg-key) ${intensity * 60}%, transparent)`,
          }}
        />
      )}
      <button
        type="button"
        data-idx={idx}
        onClick={() => onRun(cmd)}
        onMouseEnter={() => onActivate(idx)}
        className={`flex min-h-11 w-full items-center gap-3 rounded-lg px-2.5 py-1.5 text-left transition-colors ${
          isActive
            ? 'bg-(--bg-key) text-(--color-text)'
            : 'text-(--color-text-2)'
        }`}
      >
        <span
          aria-hidden
          className={`flex size-7 shrink-0 items-center justify-center rounded-md border transition-colors ${
            isActive
              ? 'border-(--color-border) bg-(--bg-card) text-(--color-text)'
              : 'border-(--color-border-subtle) bg-(--bg-page) text-(--color-text-muted)'
          }`}
        >
          <Glyph size={14} strokeWidth={1.75} />
        </span>
        <div className="min-w-0 flex-1">
          {/* Content rows carry whole message excerpts — keep every line
              truncated so the list stays scannable. */}
          <span className="block truncate text-[13px] font-medium leading-5 text-(--color-text)">{cmd.label}</span>
          {cmd.description && (
            <span className="block truncate text-xs leading-4 text-(--color-text-muted)">
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
          <kbd className={`${KBD_CLASS} shrink-0`}>
            {formatShortcutLabel(cmd.shortcut)}
          </kbd>
        )}
      </button>
    </div>
  )
}
