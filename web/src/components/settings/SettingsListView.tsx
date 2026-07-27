/**
 * SettingsListView — the list surface shared by Agents, Skills and MCP.
 *
 * It composes the same `SettingsPage` frame as the form pages, so a list and
 * a form feel like one product: sticky header with the primary action, one
 * sentence of context, then a single grouped surface of hairline rows.
 *
 *   ┌─────────────────────────────────────────────┐
 *   │ ⚙ Agents                        [+ New …]   │  ← sticky header
 *   ├─────────────────────────────────────────────┤
 *   │ short description sentence                  │
 *   │ [tabs slot] [bulk-action slot]              │
 *   │ ┌ 🔎 Filter …                    6 items ─┐ │
 *   │ ├─ ▌ name       description             ─┤ │  ← active row
 *   │ ├─   name       description             ─┤ │
 *   │ └─────────────────────────────────────────┘ │
 *   └─────────────────────────────────────────────┘
 *
 * The view is purely presentational — callers produce the `rows` array,
 * including any per-row actions.
 */
import { AlertCircle, Plus, Search, type LucideIcon } from 'lucide-react'
import { useId, useMemo, useState, type ReactNode } from 'react'
import { motion } from 'framer-motion'

import { SettingsGroup, SettingsPage } from '@/components/settings/SettingsLayout'
import { SettingsAsyncBoundary } from '@/components/settings/SettingsLoading'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useSettingsNavigate } from '@/contexts/SettingsContext'
import { fadeRise, staggerDelay, useListEnterIndex, useMotionPreset } from '@/lib/motion'
import { cn } from '@/lib/utils'

// ─── Types ─────────────────────────────────────────────────────────────────

export interface ListViewRow {
  /** Stable key per row. */
  key: string
  /** Route target. Omit for non-clickable group rows. */
  to?: string
  /** Path params for parameterised routes (e.g. `{ name }`). */
  params?: Record<string, string>
  /** Whether the row is selected in the URL (controls highlight). */
  active?: boolean
  /** Render as a non-clickable group header. */
  kind?: 'item' | 'group'
  /** Main label of the row. */
  title: string
  /** Optional secondary inline tag (e.g. role badge). */
  badge?: string
  /** Short description rendered below the title. */
  description?: string
  /** File path or other monospace meta line shown under the description. */
  meta?: string
  /** Validation error message. When set, an error icon is shown next to the title. */
  invalidReason?: string
  /** Optional trailing content (e.g. status dot). */
  trailing?: ReactNode
  /**
   * Selection checkbox shown before the title. Omit both to render no
   * checkbox at all (the default — most list pages don't need selection).
   */
  selected?: boolean
  onToggleSelect?: () => void
}

type NewRoute =
  | '/settings/agents/new'
  | '/settings/skills/new'
  | '/settings/mcp/new'

export interface SettingsListViewProps {
  title: string
  /** Icon for the page header. */
  icon: LucideIcon
  lede: string
  /** Route for the primary "+ New" CTA. */
  newTo: NewRoute
  newLabel: string
  newAction?: ReactNode
  /** Placeholder for the filter input. */
  filterPlaceholder: string
  /** Optional tab strip rendered above the filter input. */
  tabs?: ReactNode
  /** Optional content rendered between the tabs and the list (e.g. a bulk-action bar). */
  headerExtra?: ReactNode
  rows: ListViewRow[]
  isLoading: boolean
  isFetching?: boolean
  isError: boolean
  error?: unknown
  onRetry?: () => void
  /** Empty-state body when there are no rows at all (before filtering). */
  emptyTitle: string
  emptyBody: string
}

// ─── View ──────────────────────────────────────────────────────────────────

export function SettingsListView({
  title,
  icon,
  lede,
  newTo,
  newLabel,
  newAction,
  filterPlaceholder,
  tabs,
  headerExtra,
  rows,
  isLoading,
  isFetching = false,
  isError,
  error,
  onRetry,
  emptyTitle,
  emptyBody,
}: SettingsListViewProps) {
  const filterId = useId()
  const [query, setQuery] = useState('')

  const filtered = useMemo(() => {
    const t = query.trim().toLowerCase()
    if (!t) return rows
    return rows.filter(
      (r) =>
        r.title.toLowerCase().includes(t) ||
        (r.description ?? '').toLowerCase().includes(t) ||
        (r.meta ?? '').toLowerCase().includes(t),
    )
  }, [rows, query])

  const total = rows.filter((row) => row.kind !== 'group').length
  const countLabel = total === 1 ? '1 item' : `${total} items`
  const visibleItemKeys = useMemo(
    () => filtered.filter((row) => row.kind !== 'group').map((row) => row.key),
    [filtered],
  )
  const enterIndex = useListEnterIndex(visibleItemKeys, 12)

  return (
    <SettingsPage
      icon={icon}
      title={title}
      lede={lede}
      size="wide"
      actions={newAction ?? <NewButton to={newTo} label={newLabel} />}
    >
      <SettingsAsyncBoundary
        loading={isLoading || isFetching}
        hasData={!isLoading && !isError}
        error={isError ? (error ?? new Error(`Failed to load ${title.toLowerCase()}.`)) : undefined}
        variant="list"
        loadingLabel={`Loading ${title.toLowerCase()}`}
        errorTitle={`Failed to load ${title.toLowerCase()}`}
        onRetry={onRetry}
      >
        {(tabs || headerExtra) && (
          <div className="space-y-3">
            {tabs}
            {headerExtra}
          </div>
        )}

        {total === 0 && (
          <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed border-(--color-border) bg-(--bg-card)/55 px-4 py-12 text-center">
            <p className="text-sm font-medium text-(--color-text)">{emptyTitle}</p>
            <p className="max-w-md text-xs leading-relaxed text-(--color-text-muted)">{emptyBody}</p>
            <NewButton to={newTo} label={newLabel} />
          </div>
        )}

        {total > 0 && (
        <SettingsGroup className="divide-y-0 shadow-[0_12px_36px_rgba(0,0,0,0.035)]" stagger={false}>
          <div className="flex h-10 items-center gap-2 border-b border-(--color-border-subtle) px-3">
            <Search size={13} className="shrink-0 text-(--color-text-muted)" aria-hidden="true" />
            <label htmlFor={filterId} className="sr-only">
              {filterPlaceholder}
            </label>
            <Input
              id={filterId}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={filterPlaceholder}
              aria-label={filterPlaceholder}
              className="h-full flex-1 border-0 bg-transparent px-0 text-sm shadow-none focus:ring-0 focus-visible:ring-0"
            />
            <span className="shrink-0 font-mono text-xs tabular-nums text-(--color-text-muted)">
              {query.trim() ? `${filtered.filter((r) => r.kind !== 'group').length} / ${total}` : countLabel}
            </span>
          </div>

          {filtered.length === 0 ? (
            <p className="px-4 py-10 text-center text-sm text-(--color-text-muted)">
              No matches for &ldquo;{query}&rdquo;.
            </p>
          ) : (
            <ul>
              {filtered.map((row) => (
                <ListRow
                  key={row.key}
                  row={row}
                  enterIndex={row.kind === 'group' ? undefined : enterIndex(row.key)}
                />
              ))}
            </ul>
          )}
          </SettingsGroup>
        )}
      </SettingsAsyncBoundary>
    </SettingsPage>
  )
}

// ─── Row ───────────────────────────────────────────────────────────────────

function NewButton({ to, label }: { to: string; label: string }) {
  const navigate = useSettingsNavigate()
  return (
    <Button size="sm" onClick={() => navigate(to)}>
      <Plus size={13} aria-hidden="true" />
      {label}
    </Button>
  )
}

function ListRow({
  row,
  enterIndex,
}: {
  row: ListViewRow
  enterIndex?: number
}) {
  const navigate = useSettingsNavigate()
  const preset = useMotionPreset()
  const enter = enterIndex !== undefined ? fadeRise(preset, 6) : null

  if (row.kind === 'group') {
    return (
      <li className="border-b border-(--color-border-subtle) bg-(--bg-key)/40 px-4 py-1.5 text-[11px] font-medium tracking-wide text-(--color-text-subtle) uppercase">
        {row.title}
      </li>
    )
  }

  const body = (
    <button
      type="button"
      onClick={() => {
        if (row.to) navigate(row.to, { params: row.params })
      }}
      aria-current={row.active ? 'page' : undefined}
      className={cn(
        'group relative flex min-h-11 w-full items-start gap-3 py-3 pr-4 pl-4 text-left transition-colors',
        'hover:bg-(--bg-key)/50',
        'focus-visible:ring-3 focus-visible:ring-inset focus-visible:ring-(--focus-ring)/40 focus-visible:outline-none',
        row.active && 'bg-(--bg-key)/70',
      )}
    >
      {/* A single marker slides to the selected row, so changing selection
          reads as one movement rather than two separate blinks. */}
      {row.active && (
        <motion.span
          layoutId="settings-list-active"
          transition={preset.spring}
          className="absolute inset-y-1 left-0 w-0.5 rounded-full bg-(--color-accent)"
          aria-hidden="true"
        />
      )}
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className={cn('truncate text-sm text-(--color-text)', row.active && 'font-medium')}>
            {row.title}
          </span>
          {row.badge && (
            <span className="rounded bg-(--bg-key) px-1.5 py-0.5 font-mono text-[10px] text-(--color-text-muted) ring-1 ring-(--color-border)">
              {row.badge}
            </span>
          )}
          {row.invalidReason && (
            <Tooltip>
              <TooltipTrigger
                render={
                  <span className="text-(--color-error)">
                    <AlertCircle size={12} aria-label="Invalid configuration" />
                  </span>
                }
              />
              <TooltipContent>{row.invalidReason}</TooltipContent>
            </Tooltip>
          )}
        </div>
        {row.description && (
          <p className="mt-0.5 line-clamp-2 text-xs leading-relaxed text-(--color-text-muted)">
            {row.description}
          </p>
        )}
        {row.meta && (
          <p className="mt-1 truncate font-mono text-[11px] text-(--color-text-subtle)">{row.meta}</p>
        )}
      </div>
      {row.trailing && <div className="shrink-0 pt-0.5">{row.trailing}</div>}
    </button>
  )

  const rowClassName = 'not-last:border-b not-last:border-(--color-border-subtle)'
  const content = row.onToggleSelect ? (
    <div className="flex items-start">
      <label className="flex h-11 shrink-0 cursor-pointer items-center pl-4">
        <Checkbox
          checked={!!row.selected}
          onCheckedChange={() => row.onToggleSelect?.()}
          aria-label={`Select ${row.title}`}
        />
      </label>
      <div className="min-w-0 flex-1">{body}</div>
    </div>
  ) : (
    body
  )

  if (!enter || enterIndex === undefined) {
    return <li className={rowClassName}>{content}</li>
  }

  return (
    <motion.li
      className={rowClassName}
      initial={enter.initial}
      animate={enter.animate}
      transition={{ ...enter.transition, delay: staggerDelay(preset, enterIndex) }}
    >
      {content}
    </motion.li>
  )
}
