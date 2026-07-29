/**
 * SchedulerPanel — modal overlay for managing scheduled tasks.
 *
 * Mirrors MemoryPanel structure: fixed overlay with right-sliding drawer,
 * backdrop click to close, and X close button.
 */

import { useEffect, useMemo, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { X, Clock, Play, Pause, Trash2, Plus, Loader2, AlertCircle, CalendarClock, Zap, ArrowLeft, Pencil, FolderOpen, ChevronRight } from 'lucide-react'
import { cn } from '@/lib/utils'
import { DateTimePicker } from '@/components/ui/date-time-picker'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { SegmentedControl } from '@/components/ui/segmented-control'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import {
  useScheduledTasksQuery,
  useCreateScheduledTaskMutation,
  useUpdateScheduledTaskMutation,
  useDeleteScheduledTaskMutation,
  usePauseScheduledTaskMutation,
  useResumeScheduledTaskMutation,
  useTriggerScheduledTaskMutation,
} from '@/queries'
import type { ScheduledTaskResponse, ScheduledTaskCreate, ScheduledTaskMode } from '@/api/types'
import { formatRelativeDate, formatInTimezone, wallClockToISO, isoToWallClock } from '@/utils/format'
import { useModalFocus } from '@/hooks/useModalFocus'
import { loadCodingWorkspaceEntries, workspaceLabel } from '@/utils/workspace'
import { useReducedMotion } from '@/hooks/useReducedMotion'
import { fadeRise, staggerDelay, useListEnterIndex, useMotionPreset } from '@/lib/motion'

interface SchedulerPanelProps {
  open: boolean
  onClose: () => void
  embedded?: boolean
  /** Routing target inherited from the surrounding chat view. When the
   *  scheduler is opened inside a coding workspace, the Create form
   *  pre-fills mode='coding' + that workspace. Edit forms always start
   *  from the task's own stored mode/workspace. */
  contextMode?: ScheduledTaskMode
  contextWorkspace?: string | null
}

// ── Shared utility ──────────────────────────────────────────────────────────

// Form fields sit on a bg-(--bg-card) panel; the shared <Input>/<Textarea>/
// <SelectTrigger> primitives default to bg-transparent which leaves them
// indistinguishable from the parent. Give them an explicit fillable surface
// so the controls read as inputs.
const FIELD_CLASS = 'bg-(--bg-page)'

// Inline className for SelectContent — the global default (`bg-popover`)
// resolves to `--bg-card`, the same surface as this drawer, so the dropdown
// looks like an outlined frame floating on the same paper. Use the page
// surface for clear contrast and soften the border.
const SELECT_CONTENT_CLASS = 'bg-(--bg-page) border-(--color-border-strong)'

// Status dot colour mapping
const STATUS_DOT: Record<string, string> = {
  pending: 'bg-(--color-text-subtle)',
  running: 'bg-(--color-accent) animate-pulse',
  paused: 'bg-(--color-warning)',
  completed: 'bg-(--color-success)',
  failed: 'bg-(--color-error)',
}

// Three-option segmented control used for "Schedule type". The shared Tabs
// primitive inverts in light mode (track = bg-key which is darker than the
// active bg-background = bg-page), so we render a flat row of buttons that
// match the rest of this drawer's surfaces.

// ── Session ID select ────────────────────────────────────────────────────────

type SessionMode = 'new' | 'auto' | 'custom'

function resolveSessionMode(value: string | null | undefined): SessionMode {
  if (!value) return 'new'
  if (value === 'auto') return 'auto'
  return 'custom'
}

function SessionIdField({
  value,
  onChange,
}: {
  value: string | null | undefined
  onChange: (v: string | null) => void
}) {
  const mode = resolveSessionMode(value)

  const handleModeChange = (next: SessionMode) => {
    if (next === 'new') onChange(null)
    else if (next === 'auto') onChange('auto')
    else onChange('')          // open custom input with empty string
  }

  return (
    <div>
      <label className="block text-sm font-medium text-(--color-text)">Session</label>
      <Select value={mode} onValueChange={(v) => handleModeChange(v as SessionMode)}>
        <SelectTrigger className={cn('mt-1 w-full', FIELD_CLASS)}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent className={SELECT_CONTENT_CLASS}>
          <SelectItem value="new">New session each run</SelectItem>
          <SelectItem value="auto">Auto — persistent per task</SelectItem>
          <SelectItem value="custom">Custom UUID…</SelectItem>
        </SelectContent>
      </Select>
      {mode === 'custom' && (
        <Input
          className={cn('mt-2', FIELD_CLASS)}
          value={value ?? ''}
          onChange={(e) => onChange(e.target.value || null)}
          placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
          spellCheck={false}
        />
      )}
      <p className="mt-1 text-xs text-(--color-text-muted)">
        {mode === 'new' && 'Creates a fresh session each time the task fires.'}
        {mode === 'auto' && 'Reuses the same session across all runs of this task.'}
        {mode === 'custom' && 'Continues a specific existing session by UUID.'}
      </p>
    </div>
  )
}

function formatScheduleLabel(task: Pick<ScheduledTaskResponse, 'schedule_type' | 'at_datetime' | 'every_seconds' | 'cron_expression' | 'timezone'>): string {
  if (task.schedule_type === 'at' && task.at_datetime) {
    // Render in the task's saved timezone, not the browser's — otherwise
    // a task scheduled for "9 AM in New York" displays a different time
    // when viewed from a Vietnam-based browser.
    return `at ${formatInTimezone(task.at_datetime, task.timezone)}`
  }
  if (task.schedule_type === 'every' && task.every_seconds) {
    const mins = Math.floor(task.every_seconds / 60)
    const secs = task.every_seconds % 60
    if (mins > 0 && secs === 0) return `every ${mins}m`
    if (mins === 0) return `every ${secs}s`
    return `every ${mins}m ${secs}s`
  }
  if (task.schedule_type === 'cron' && task.cron_expression) {
    return `cron: ${task.cron_expression}`
  }
  return 'unknown schedule'
}

// ── Mode / workspace shared bits ────────────────────────────────────────────

function ModeBadge({ task }: { task: Pick<ScheduledTaskResponse, 'mode' | 'workspace'> }) {
  if (task.mode === 'coding' && task.workspace) {
    return (
      <span
        className="inline-flex max-w-full items-center gap-1 truncate rounded-md bg-(--bg-key) px-2 py-0.5 text-xs text-(--color-text-2) ring-1 ring-(--color-border-strong)"
        title={task.workspace}
      >
        <FolderOpen size={10} className="shrink-0" />
        <span className="truncate">coding · {workspaceLabel(task.workspace)}</span>
      </span>
    )
  }
  return (
    <span className="inline-flex items-center rounded-md bg-(--bg-key) px-2 py-0.5 text-xs text-(--color-text-2) ring-1 ring-(--color-border-strong)">
      normal
    </span>
  )
}

/**
 * Mode toggle + workspace input — shared between Create and Edit forms.
 *
 * Workspace control:
 *   - When the caller has a context workspace (scheduler opened inside a
 *     coding chat), the input pre-fills with that path. The user can still
 *     edit it or switch modes.
 *   - Saved coding workspaces from localStorage are surfaced as quick-pick
 *     suggestions via a small `<Select>` next to the path input.
 */
/**
 * Internal subcomponent — exported solely for unit testing the mode/workspace
 * toggle contract. Not part of the public ``SchedulerPanel`` API; do not
 * consume from other modules.
 */
export function ModeWorkspaceFields({
  mode,
  workspace,
  onChange,
}: {
  mode: ScheduledTaskMode
  workspace: string | null
  /** Emits both fields together so the parent applies them in a single
   *  setState — preventing the stale-snapshot bug where switching
   *  ``coding → normal`` would clear the workspace but leave ``mode``
   *  unchanged (two sequential setState calls on the same snapshot). */
  onChange: (next: { mode: ScheduledTaskMode; workspace: string | null }) => void
}) {
  const savedWorkspaces = useMemo(() => {
    const paths = loadCodingWorkspaceEntries().map((entry) => entry.path)
    if (workspace && !paths.includes(workspace)) paths.push(workspace)
    return paths.sort()
  }, [workspace])

  const modeOptions: { key: ScheduledTaskMode; label: string }[] = [
    { key: 'forge', label: 'Forge' },
    { key: 'coding', label: 'Coding' },
  ]

  return (
    <div>
      <label className="block text-sm font-medium text-(--color-text)">Routing</label>
      <div
        role="radiogroup"
        aria-label="Task mode"
        // ``inline-flex`` so two short labels ("Forge" / "Coding") do not
        // sprawl across the full form width.
        className="mt-2 inline-flex gap-1 rounded-md border border-(--color-border) bg-(--bg-page) p-1"
      >
        {modeOptions.map((opt) => {
          const active = mode === opt.key
          return (
            <button
              key={opt.key}
              type="button"
              role="radio"
              aria-checked={active}
              onClick={() => {
                onChange({
                  mode: opt.key,
                  // Drop the workspace when leaving coding mode; preserve it
                  // when staying on coding so the user does not lose their
                  // typed-in path by tapping the active tab.
                  workspace: opt.key === 'coding' ? workspace : null,
                })
              }}
              className={
                'rounded-sm px-3 py-1 text-xs font-medium transition-colors ' +
                (active
                  ? 'bg-(--bg-card) text-(--color-text) shadow-sm ring-1 ring-(--color-border-strong)'
                  : 'text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text-2)')
              }
            >
              {opt.label}
            </button>
          )
        })}
      </div>
      <p className="mt-1 text-xs text-(--color-text-muted)">
        {mode === 'forge'
          ? 'Delivers to the default team lead.'
          : 'Delivers to the lead of the coding team for the workspace below.'}
      </p>

      {mode === 'coding' && (
        <div className="mt-3">
          <label className="block text-sm font-medium text-(--color-text)">Workspace</label>
          <Select
            value={workspace ?? ''}
            onValueChange={(v) => onChange({ mode, workspace: v || null })}
          >
            <SelectTrigger
              className={`mt-1 w-full ${FIELD_CLASS}`}
              aria-label="Select workspace"
            >
              <SelectValue>
                {workspace ? workspaceLabel(workspace) : 'Select a saved workspace…'}
              </SelectValue>
            </SelectTrigger>
            <SelectContent className={SELECT_CONTENT_CLASS}>
              {savedWorkspaces.map((path) => (
                <SelectItem key={path} value={path}>
                  {workspaceLabel(path)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <p className="mt-1 text-xs text-(--color-text-muted)">
            Workspaces come from saved coding workspaces.
          </p>
        </div>
      )}
    </div>
  )
}

// ── Panel root ──────────────────────────────────────────────────────────────

export function SchedulerPanel({
  open,
  onClose,
  embedded = false,
  contextMode = 'forge',
  contextWorkspace = null,
}: SchedulerPanelProps) {
  const prefersReducedMotion = useReducedMotion()
  const preset = useMotionPreset()

  // Single-pane navigation for all screen sizes
  const [pane, setPane] = useState<'list' | 'detail' | 'create'>('list')
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')

  const tasksQuery = useScheduledTasksQuery()
  useModalFocus(open && !embedded, onClose)

  useEffect(() => {
    if (open) tasksQuery.refetch()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  // Reset to list on close
  useEffect(() => {
    if (!open) { setPane('list'); setSelectedTaskId(null); setSearchQuery('') }
  }, [open])

  const tasks = tasksQuery.data?.tasks ?? []
  const filteredTasks = tasks.filter((task) => {
    const q = searchQuery.toLowerCase()
    if (!q) return true
    return (
      task.name.toLowerCase().includes(q) ||
      task.mode.toLowerCase().includes(q) ||
      (task.workspace ?? '').toLowerCase().includes(q)
    )
  })
  const selectedTask = selectedTaskId ? tasks.find((t) => t.id === selectedTaskId) : null
  const taskEnterIndex = useListEnterIndex(filteredTasks.map((t) => t.id))

  const handleSelectTask = (id: string) => { setSelectedTaskId(id); setPane('detail') }
  const handleBackToList = () => { setPane('list'); setSelectedTaskId(null) }
  const handleTaskDeleted = (id: string) => { if (selectedTaskId === id) handleBackToList() }

  return (
    <AnimatePresence>
      {open && (
        <>
          {/* Backdrop */}
          {!embedded && <motion.div
            key="backdrop"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="fixed inset-0 z-(--z-overlay) bg-(--color-overlay)"
          />}

          {/* Right-side drawer */}
          <motion.aside
            key="drawer"
            initial={embedded ? false : prefersReducedMotion ? { opacity: 0 } : { x: '100%', opacity: 0 }}
            animate={embedded ? undefined : prefersReducedMotion ? { opacity: 1 } : { x: 0, opacity: 1 }}
            exit={embedded ? undefined : prefersReducedMotion ? { opacity: 0 } : { x: '100%', opacity: 0 }}
            transition={preset.spring}
            className={cn(
              'flex flex-col overflow-hidden border-l border-(--color-border) bg-(--bg-page)',
              embedded
                ? 'relative h-full w-full'
                : 'fixed bottom-0 right-0 top-[env(safe-area-inset-top,0px)] z-(--z-modal) w-full shadow-2xl sm:w-[460px]',
            )}
            role={embedded ? 'region' : 'dialog'}
            aria-modal={embedded ? undefined : 'true'}
            aria-label="Scheduled tasks"
            data-modal-focus={embedded ? undefined : 'true'}
          >
            {/* ── Header ── */}
            <header className="flex shrink-0 items-center gap-2 border-b border-(--color-border) px-4 py-3">
              {pane !== 'list' && (
                <button
                  onClick={handleBackToList}
                  className="rounded-xs p-1 text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
                  aria-label="Back to task list"
                >
                  <ArrowLeft size={16} />
                </button>
              )}
              <CalendarClock size={16} className="shrink-0 text-(--color-accent)" />
              <div className="min-w-0 flex-1">
                <h2 className="text-sm font-semibold text-(--color-text)">
                  {pane === 'create' ? 'New Task' : pane === 'detail' ? (selectedTask?.name ?? 'Task') : 'Scheduled Tasks'}
                </h2>
                {pane === 'list' && (
                  <p className="text-xs text-(--color-text-subtle)">
                    {tasks.length === 0 ? 'No tasks yet' : `${tasks.length} task${tasks.length !== 1 ? 's' : ''}`}
                  </p>
                )}
              </div>
              {pane === 'list' && (
                <button
                  onClick={() => setPane('create')}
                  className="flex items-center gap-1 rounded-md border border-(--color-border) px-2.5 py-1.5 text-xs font-medium text-(--color-text-muted) transition-colors hover:border-(--color-border-strong) hover:text-(--color-text)"
                  aria-label="New scheduled task"
                >
                  <Plus size={13} aria-hidden="true" />
                  New
                </button>
              )}
              <button
                onClick={onClose}
                className="rounded-xs p-1 text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
                aria-label="Close scheduler panel"
                title="Close (Esc)"
              >
                <X size={16} />
              </button>
            </header>

            {/* ── Body ── */}
            <AnimatePresence mode="wait" initial={false}>
              {pane === 'list' && (
                <motion.div
                  key="list"
                  initial={prefersReducedMotion ? { opacity: 0 } : { x: -20 * preset.distance, opacity: 0 }}
                  animate={prefersReducedMotion ? { opacity: 1 } : { x: 0, opacity: 1 }}
                  exit={prefersReducedMotion ? { opacity: 0 } : { x: -20 * preset.distance, opacity: 0 }}
                  transition={preset.spring}
                  className="flex flex-1 flex-col overflow-hidden"
                >
                  {/* Search */}
                  <div className="border-b border-(--color-border) px-3 py-2">
                    <Input
                      className={cn(FIELD_CLASS, 'h-8 text-sm')}
                      placeholder="Search tasks…"
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                    />
                  </div>

                  {/* List */}
                  <div className="flex-1 overflow-y-auto">
                    {tasksQuery.isLoading ? (
                      <div className="flex items-center justify-center p-8">
                        <Loader2 size={18} className="animate-spin text-(--color-text-muted)" />
                      </div>
                    ) : tasksQuery.isError ? (
                      <div className="flex flex-col items-center justify-center gap-2 p-10 text-center">
                        <AlertCircle size={18} className="text-(--color-error)" />
                        <p className="text-sm text-(--color-text-muted)">Failed to load tasks</p>
                      </div>
                    ) : filteredTasks.length === 0 ? (
                      <div className="flex flex-col items-center justify-center gap-3 p-10 text-center">
                        <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-(--bg-key) text-(--color-text-muted)">
                          <Clock size={18} />
                        </span>
                        <div>
                          <p className="text-sm font-medium text-(--color-text)">
                            {searchQuery ? 'No matching tasks' : 'No scheduled tasks'}
                          </p>
                          <p className="mt-0.5 text-xs text-(--color-text-subtle)">
                            {searchQuery ? 'Try a different search' : 'Click "New" to create one'}
                          </p>
                        </div>
                      </div>
                    ) : (
                      <div className="py-1">
                        {filteredTasks.map((task) => (
                          <TaskRow
                            key={task.id}
                            task={task}
                            isSelected={selectedTaskId === task.id}
                            enterIndex={taskEnterIndex(task.id)}
                            onSelect={() => handleSelectTask(task.id)}
                          />
                        ))}
                      </div>
                    )}
                  </div>
                </motion.div>
              )}

              {pane === 'detail' && selectedTask && (
                <motion.div
                  key={`detail-${selectedTask.id}`}
                  initial={prefersReducedMotion ? { opacity: 0 } : { x: 20 * preset.distance, opacity: 0 }}
                  animate={prefersReducedMotion ? { opacity: 1 } : { x: 0, opacity: 1 }}
                  exit={prefersReducedMotion ? { opacity: 0 } : { x: 20 * preset.distance, opacity: 0 }}
                  transition={preset.spring}
                  className="flex flex-1 flex-col overflow-hidden"
                >
                  <TaskDetailView
                    task={selectedTask}
                    onClose={handleBackToList}
                    onDeleted={() => handleTaskDeleted(selectedTask.id)}
                  />
                </motion.div>
              )}

              {pane === 'create' && (
                <motion.div
                  key="create"
                  initial={prefersReducedMotion ? { opacity: 0 } : { x: 20 * preset.distance, opacity: 0 }}
                  animate={prefersReducedMotion ? { opacity: 1 } : { x: 0, opacity: 1 }}
                  exit={prefersReducedMotion ? { opacity: 0 } : { x: 20 * preset.distance, opacity: 0 }}
                  transition={preset.spring}
                  className="flex flex-1 flex-col overflow-hidden"
                >
                  <CreateTaskForm
                    contextMode={contextMode}
                    contextWorkspace={contextWorkspace}
                    onSuccess={handleBackToList}
                  />
                </motion.div>
              )}
            </AnimatePresence>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  )
}

// ── Task row (session-list style) ───────────────────────────────────────────

function TaskRow({
  task,
  isSelected,
  enterIndex,
  onSelect,
}: {
  task: ScheduledTaskResponse
  isSelected: boolean
  enterIndex?: number
  onSelect: () => void
}) {
  const preset = useMotionPreset()
  const enter = enterIndex !== undefined ? fadeRise(preset, 6) : null
  const dot = STATUS_DOT[task.status] ?? STATUS_DOT.pending
  const row = (
    <button
      onClick={onSelect}
      className={cn(
        'group flex w-full items-center gap-3 px-4 py-2.5 text-left transition-colors',
        isSelected ? 'bg-(--bg-key)' : 'hover:bg-(--bg-key)/60',
      )}
    >
      {/* Status dot */}
      <span className={cn('h-2 w-2 shrink-0 rounded-full', dot)} />

      {/* Main text */}
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-(--color-text)">{task.name}</p>
        <p className="mt-0.5 truncate text-xs text-(--color-text-muted)">
          {formatScheduleLabel(task)}
          {task.next_fire_at ? ` · ${formatRelativeDate(task.next_fire_at)}` : ''}
        </p>
      </div>

      {/* Mode badge */}
      <ModeBadge task={task} />

      {/* Chevron */}
      <ChevronRight size={14} className="shrink-0 text-(--color-text-subtle) transition-transform group-hover:translate-x-0.5 group-hover:text-(--color-text-muted)" />
    </button>
  )

  if (!enter || enterIndex === undefined) return row

  return (
    <motion.div
      initial={enter.initial}
      animate={enter.animate}
      transition={{ ...enter.transition, delay: staggerDelay(preset, enterIndex) }}
    >
      {row}
    </motion.div>
  )
}

// ── Create task form ────────────────────────────────────────────────────────

function CreateTaskForm({
  contextMode,
  contextWorkspace,
  onSuccess,
}: {
  contextMode: ScheduledTaskMode
  contextWorkspace: string | null
  onSuccess: () => void
}) {
  const localTz = Intl.DateTimeFormat().resolvedOptions().timeZone
  const initialMode: ScheduledTaskMode = contextMode
  const initialWorkspace: string | null =
    contextMode === 'coding' ? contextWorkspace : null
  const [formData, setFormData] = useState<ScheduledTaskCreate>({
    name: '',
    mode: initialMode,
    workspace: initialWorkspace,
    schedule_type: 'every',
    every_seconds: 3600,
    timezone: localTz,
    prompt: '',
    enabled: true,
  })
  const [error, setError] = useState<string | null>(null)

  const createMutation = useCreateScheduledTaskMutation()

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)

    const mode: ScheduledTaskMode = formData.mode ?? 'forge'
    const workspace = formData.workspace ?? null

    if (!formData.name.trim()) { setError('Task name is required'); return }
    if (mode === 'coding' && !workspace?.trim()) {
      setError('Workspace is required for coding mode'); return
    }
    if (!formData.prompt.trim()) { setError('Prompt is required'); return }
    if (formData.schedule_type === 'at' && !formData.at_datetime) {
      setError('Date/time is required for "at" schedule'); return
    }
    if (formData.schedule_type === 'every' && (!formData.every_seconds || formData.every_seconds <= 0)) {
      setError('Interval must be greater than 0'); return
    }
    if (formData.schedule_type === 'cron' && !formData.cron_expression?.trim()) {
      setError('Cron expression is required'); return
    }

    // Strip fields that don't belong to the active schedule_type.
    // The backend Pydantic validator rejects any extra schedule fields
    // (e.g. every_seconds present when schedule_type='at').
    //
    // For 'at' schedules, DateTimePicker emits a NAIVE wall-clock string
    // ("yyyy-MM-dd'T'HH:mm"). We must combine it with the user-supplied
    // `timezone` before sending — otherwise the backend treats the wall
    // clock as UTC and the task fires at the wrong hour.
    const tz = formData.timezone || localTz
    const atIso = formData.at_datetime ? wallClockToISO(formData.at_datetime, tz) : undefined
    const payload: ScheduledTaskCreate = {
      name: formData.name.trim(),
      mode,
      workspace: mode === 'coding' ? workspace!.trim() : null,
      schedule_type: formData.schedule_type,
      timezone: tz,
      prompt: formData.prompt.trim(),
      session_id: formData.session_id,
      enabled: formData.enabled,
      ...(formData.schedule_type === 'at'    ? { at_datetime: atIso }                          : {}),
      ...(formData.schedule_type === 'every' ? { every_seconds: formData.every_seconds }       : {}),
      ...(formData.schedule_type === 'cron'  ? { cron_expression: formData.cron_expression }   : {}),
    }

    createMutation.mutate(payload, {
      onSuccess: () => {
        setFormData({
          name: '',
          mode: initialMode,
          workspace: initialWorkspace,
          schedule_type: 'every',
          every_seconds: 3600,
          timezone: localTz,
          prompt: '',
          enabled: true,
        })
        onSuccess()
      },
      onError: (err) => {
        setError(err instanceof Error ? err.message : 'Failed to create task')
      },
    })
  }

  return (
    <div className="flex flex-col overflow-hidden">
      {/* Form */}
      <form onSubmit={handleSubmit} className="flex flex-1 flex-col overflow-y-auto px-4 py-4">
        <div className="space-y-4">
          {/* Name */}
          <div>
            <label className="block text-sm font-medium text-(--color-text)">Task Name</label>
            <Input
              className={`mt-1 ${FIELD_CLASS}`}
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              placeholder="e.g., Daily Report"
            />
          </div>

          {/* Routing — mode + workspace (mode is auto-injected into the
              schedule_task tool when fired; here the user sets where the
              task should route once the timer fires). */}
          <ModeWorkspaceFields
            mode={formData.mode ?? 'forge'}
            workspace={formData.workspace ?? null}
            onChange={(next) =>
              setFormData((prev) => ({
                ...prev,
                mode: next.mode,
                workspace: next.workspace,
              }))
            }
          />

          {/* Schedule Type */}
          <div>
            <label className="block text-sm font-medium text-(--color-text)">Schedule Type</label>
            <SegmentedControl
              layoutId="scheduler-schedule-type-create"
              ariaLabel="Schedule type"
              className="mt-2"
              value={formData.schedule_type}
              onChange={(v) => setFormData({ ...formData, schedule_type: v })}
              options={[
                { value: 'every', label: 'Every' },
                { value: 'cron', label: 'Cron' },
                { value: 'at', label: 'At' },
              ]}
            />
          </div>

          {/* Schedule value (conditional) */}
          {formData.schedule_type === 'at' && (
            <div>
              <div className="flex items-end gap-2">
                <div className="flex-1">
                  <label className="block text-sm font-medium text-(--color-text)">Date & Time</label>
                  <div className="mt-1">
                    <DateTimePicker
                      value={formData.at_datetime ?? ''}
                      onChange={(v) => setFormData({ ...formData, at_datetime: v })}
                      triggerClassName="bg-(--bg-page) hover:bg-(--bg-page)"
                    />
                  </div>
                </div>
                <div className="w-44 shrink-0">
                  <label className="block text-sm font-medium text-(--color-text)">Timezone</label>
                  <Input
                    className={`mt-1 ${FIELD_CLASS}`}
                    value={formData.timezone}
                    onChange={(e) => setFormData({ ...formData, timezone: e.target.value })}
                    placeholder={localTz}
                  />
                </div>
              </div>
              <p className="mt-1 text-xs text-(--color-text-muted)">IANA timezone (e.g., America/New_York)</p>
            </div>
          )}

          {formData.schedule_type === 'every' && (
            <div>
              <label className="block text-sm font-medium text-(--color-text)">Interval (seconds)</label>
              <Input
                // Numeric value rarely exceeds 6 digits — constrain to ~9rem
                // so the input does not stretch across the full form width.
                className={`mt-1 w-36 ${FIELD_CLASS}`}
                type="number"
                min="1"
                value={formData.every_seconds ?? 3600}
                onChange={(e) =>
                  setFormData({ ...formData, every_seconds: parseInt(e.target.value) || 0 })
                }
              />
              <p className="mt-1 text-xs text-(--color-text-muted)">e.g., 3600 = 1 hour, 86400 = 1 day</p>
            </div>
          )}

          {formData.schedule_type === 'cron' && (
            <div>
              <div className="flex items-end gap-2">
                <div className="flex-1">
                  <label className="block text-sm font-medium text-(--color-text)">Cron Expression</label>
                  <Input
                    className={`mt-1 ${FIELD_CLASS}`}
                    value={formData.cron_expression ?? ''}
                    onChange={(e) => setFormData({ ...formData, cron_expression: e.target.value })}
                    placeholder="e.g., 0 9 * * MON-FRI"
                  />
                </div>
                <div className="w-44 shrink-0">
                  <label className="block text-sm font-medium text-(--color-text)">Timezone</label>
                  <Input
                    className={`mt-1 ${FIELD_CLASS}`}
                    value={formData.timezone}
                    onChange={(e) => setFormData({ ...formData, timezone: e.target.value })}
                    placeholder={localTz}
                  />
                </div>
              </div>
              <p className="mt-1 text-xs text-(--color-text-muted)">IANA timezone (e.g., America/New_York)</p>
            </div>
          )}

          {/* Prompt */}
          <div>
            <label className="block text-sm font-medium text-(--color-text)">Prompt</label>
            <Textarea
              className={`mt-1 ${FIELD_CLASS}`}
              value={formData.prompt}
              onChange={(e) => setFormData({ ...formData, prompt: e.target.value })}
              placeholder="Message to deliver to the team lead when the task fires."
              rows={4}
            />
          </div>

          {/* Session */}
          <SessionIdField
            value={formData.session_id}
            onChange={(v) => setFormData({ ...formData, session_id: v })}
          />

          {/* Error message */}
          {error && (
            <div className="flex gap-2 rounded-lg border border-(--color-error) bg-(--color-error-subtle) p-3">
              <AlertCircle size={16} className="shrink-0 text-(--color-error)" />
              <p className="text-sm text-(--color-error)">{error}</p>
            </div>
          )}
        </div>

        {/* Submit */}
        <Button
          type="submit"
          disabled={createMutation.isPending}
          className="mt-6 w-full"
        >
          {createMutation.isPending ? (
            <>
              <Loader2 size={14} className="animate-spin" />
              Creating…
            </>
          ) : (
            <>
              <Plus size={14} />
              Create Task
            </>
          )}
        </Button>
      </form>
    </div>
  )
}

// ── Task detail view ────────────────────────────────────────────────────────

function TaskDetailView({
  task,
  onDeleted,
}: {
  task: ScheduledTaskResponse
  onClose: () => void
  onDeleted: () => void
}) {
  const deleteMutation = useDeleteScheduledTaskMutation()
  const pauseMutation = usePauseScheduledTaskMutation()
  const resumeMutation = useResumeScheduledTaskMutation()
  const triggerMutation = useTriggerScheduledTaskMutation()

  const triggerTask = () => triggerMutation.mutate(task.id)
  const togglePaused = () => {
    if (task.status === 'paused') resumeMutation.mutate(task.id)
    else pauseMutation.mutate(task.id)
  }
  const deleteTask = () => {
    if (confirm(`Delete task "${task.name}"?`)) {
      deleteMutation.mutate(task.id, { onSuccess: onDeleted })
    }
  }
  const [editing, setEditing] = useState(false)

  if (editing) {
    return (
      <EditTaskForm
        task={task}
        onSuccess={() => setEditing(false)}
        onCancel={() => setEditing(false)}
      />
    )
  }

  const dot = STATUS_DOT[task.status] ?? STATUS_DOT.pending

  return (
    <div className="flex flex-col overflow-hidden">
      {/* Sub-header: task name + action buttons */}
      <div className="border-b border-(--color-border) px-4 py-3">
        <div className="flex items-center gap-3">
          <span className={cn('h-2.5 w-2.5 shrink-0 rounded-full', dot)} />
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-semibold text-(--color-text)">{task.name}</p>
            <p className="mt-0.5 truncate text-xs text-(--color-text-muted)">{formatScheduleLabel(task)}</p>
          </div>
          {/* Quick action buttons */}
          <div className="flex shrink-0 items-center gap-1">
            <button
              onClick={triggerTask}
              disabled={triggerMutation.isPending}
              className="rounded-xs p-1.5 text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text) disabled:opacity-40"
              title="Trigger now"
            >
              {triggerMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : <Zap size={14} />}
            </button>
            <button
              onClick={togglePaused}
              disabled={pauseMutation.isPending || resumeMutation.isPending}
              className="rounded-xs p-1.5 text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text) disabled:opacity-40"
              title={task.status === 'paused' ? 'Resume' : 'Pause'}
            >
              {(pauseMutation.isPending || resumeMutation.isPending)
                ? <Loader2 size={14} className="animate-spin" />
                : task.status === 'paused' ? <Play size={14} /> : <Pause size={14} />}
            </button>
            <button
              onClick={() => setEditing(true)}
              className="rounded-xs p-1.5 text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
              title="Edit task"
            >
              <Pencil size={14} />
            </button>
            <button
              onClick={deleteTask}
              disabled={deleteMutation.isPending}
              className="rounded-xs p-1.5 text-(--color-text-muted) transition-colors hover:bg-(--color-error-subtle) hover:text-(--color-error) disabled:opacity-40"
              title="Delete task"
            >
              {deleteMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
            </button>
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto">
        <section className="px-4 py-4">
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-widest text-(--color-text-muted)">
            Status
          </h3>
          <div className="space-y-1.5">
            <DetailRow label="Current">
              <span className={cn('text-sm font-medium capitalize', {
                'text-(--color-text-muted)': task.status === 'pending',
                'text-(--color-accent)': task.status === 'running',
                'text-(--color-warning)': task.status === 'paused',
                'text-(--color-success)': task.status === 'completed',
                'text-(--color-error)': task.status === 'failed',
              })}>{task.status}</span>
            </DetailRow>
            <DetailRow label="Enabled">
              <span className="text-sm text-(--color-text)">{task.enabled ? 'Yes' : 'No'}</span>
            </DetailRow>
            <DetailRow label="Run Count">
              <span className="text-sm text-(--color-text)">{task.run_count}</span>
            </DetailRow>
          </div>
        </section>

        <section className="border-t border-(--color-border) px-4 py-4">
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-widest text-(--color-text-muted)">
            Schedule
          </h3>
          <div className="space-y-1.5">
            <DetailRow label="Type">
              <span className="text-sm text-(--color-text) capitalize">{task.schedule_type}</span>
            </DetailRow>
            {task.schedule_type === 'at' && task.at_datetime && (
              <DetailRow label="Date/Time">
                <span className="text-sm text-(--color-text)">
                  {formatInTimezone(task.at_datetime, task.timezone)}
                </span>
              </DetailRow>
            )}
            {task.schedule_type === 'every' && task.every_seconds && (
              <DetailRow label="Interval">
                <span className="text-sm text-(--color-text)">{task.every_seconds}s</span>
              </DetailRow>
            )}
            {task.schedule_type === 'cron' && task.cron_expression && (
              <DetailRow label="Expression">
                <span className="text-sm text-(--color-text)">{task.cron_expression}</span>
              </DetailRow>
            )}
            <DetailRow label="Timezone">
              <span className="text-sm text-(--color-text)">{task.timezone}</span>
            </DetailRow>
          </div>
        </section>

        <section className="border-t border-(--color-border) px-4 py-4">
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-widest text-(--color-text-muted)">
            Configuration
          </h3>
          <div className="space-y-3">
            <div>
              <span className="text-xs text-(--color-text-muted)">Routing</span>
              <p className="mt-1 rounded-md border border-(--color-border) bg-(--bg-page) px-3 py-2 text-sm text-(--color-text)">
                {task.mode === 'coding' ? (
                  <>
                    Coding team
                    {task.workspace && (
                      <span className="ml-1 font-mono text-xs text-(--color-text-muted)">
                        · {task.workspace}
                      </span>
                    )}
                  </>
                ) : (
                  'Default team lead'
                )}
              </p>
            </div>
            <div>
              <span className="text-xs text-(--color-text-muted)">Prompt</span>
              <p className="mt-1 rounded-md border border-(--color-border) bg-(--bg-page) px-3 py-2 text-sm leading-relaxed text-(--color-text) whitespace-pre-wrap">
                {task.prompt}
              </p>
            </div>
            {task.session_id && (
              <div>
                <span className="text-xs text-(--color-text-muted)">Session ID</span>
                <p className="mt-1 rounded-md border border-(--color-border) bg-(--bg-page) px-3 py-2 font-mono text-xs text-(--color-text) break-all">
                  {task.session_id}
                </p>
              </div>
            )}
          </div>
        </section>

        <section className="border-t border-(--color-border) px-4 py-4">
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-widest text-(--color-text-muted)">
            Run History
          </h3>
          <div className="space-y-1.5">
            {task.last_run_at && (
              <DetailRow label="Last Run">
                <span className="text-sm text-(--color-text)">
                  {formatRelativeDate(task.last_run_at)}
                </span>
              </DetailRow>
            )}
            {task.next_fire_at && (
              <DetailRow label="Next Fire">
                <span className="text-sm text-(--color-text)">
                  {formatRelativeDate(task.next_fire_at)}
                </span>
              </DetailRow>
            )}
            {!task.last_run_at && !task.next_fire_at && !task.last_error && (
              <p className="text-xs italic text-(--color-text-muted)">No runs yet.</p>
            )}
            {task.last_error && (
              <div className="pt-1">
                <span className="text-xs text-(--color-text-muted)">Last Error</span>
                <p className="mt-1 rounded-md border border-(--color-error) bg-(--color-error-subtle) px-3 py-2 text-xs text-(--color-error) whitespace-pre-wrap">
                  {task.last_error}
                </p>
              </div>
            )}
          </div>
        </section>

        <section className="border-t border-(--color-border) px-4 py-3">
          <div className="space-y-1 text-xs text-(--color-text-muted)">
            <div>Created: {formatRelativeDate(task.created_at)}</div>
            <div>Updated: {formatRelativeDate(task.updated_at)}</div>
          </div>
        </section>
      </div>
    </div>
  )
}

// Compact label/value row used throughout the detail view.
function DetailRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-xs text-(--color-text-muted)">{label}</span>
      {children}
    </div>
  )
}

// ── Edit task form ──────────────────────────────────────────────────────────

function EditTaskForm({
  task,
  onSuccess,
  onCancel,
}: {
  task: ScheduledTaskResponse
  onSuccess: () => void
  onCancel: () => void
}) {
  const localTz = Intl.DateTimeFormat().resolvedOptions().timeZone
  // The API returns `at_datetime` as a tz-aware ISO string, but DateTimePicker
  // expects a naive wall-clock ("yyyy-MM-dd'T'HH:mm") interpreted in the
  // task's timezone. Convert back so the picker shows the correct value.
  const initialAt = task.at_datetime ? isoToWallClock(task.at_datetime, task.timezone) : undefined
  const [formData, setFormData] = useState<ScheduledTaskCreate>({
    name: task.name,
    mode: task.mode,
    workspace: task.workspace,
    schedule_type: task.schedule_type,
    at_datetime: initialAt,
    every_seconds: task.every_seconds ?? undefined,
    cron_expression: task.cron_expression ?? undefined,
    timezone: task.timezone,
    prompt: task.prompt,
    session_id: task.session_id ?? undefined,
    enabled: task.enabled,
  })
  const [error, setError] = useState<string | null>(null)

  const updateMutation = useUpdateScheduledTaskMutation()

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)

    const mode: ScheduledTaskMode = formData.mode ?? 'forge'
    const workspace = formData.workspace ?? null

    if (mode === 'coding' && !workspace?.trim()) {
      setError('Workspace is required for coding mode'); return
    }
    if (!formData.prompt.trim()) { setError('Prompt is required'); return }
    if (formData.schedule_type === 'at' && !formData.at_datetime) {
      setError('Date/time is required for "at" schedule'); return
    }
    if (formData.schedule_type === 'every' && (!formData.every_seconds || formData.every_seconds <= 0)) {
      setError('Interval must be greater than 0'); return
    }
    if (formData.schedule_type === 'cron' && !formData.cron_expression?.trim()) {
      setError('Cron expression is required'); return
    }

    // Same naive-wall-clock → tz-aware ISO conversion as CreateTaskForm.
    const tz = formData.timezone || localTz
    const atIso = formData.at_datetime ? wallClockToISO(formData.at_datetime, tz) : undefined
    const payload: Partial<ScheduledTaskCreate> = {
      mode,
      workspace: mode === 'coding' ? workspace!.trim() : null,
      schedule_type: formData.schedule_type,
      timezone: tz,
      prompt: formData.prompt.trim(),
      session_id: formData.session_id,
      enabled: formData.enabled,
      ...(formData.schedule_type === 'at'    ? { at_datetime: atIso }                          : {}),
      ...(formData.schedule_type === 'every' ? { every_seconds: formData.every_seconds }       : {}),
      ...(formData.schedule_type === 'cron'  ? { cron_expression: formData.cron_expression }   : {}),
    }

    updateMutation.mutate({ id: task.id, body: payload }, {
      onSuccess,
      onError: (err) => {
        setError(err instanceof Error ? err.message : 'Failed to update task')
      },
    })
  }

  return (
    <div className="flex flex-col overflow-hidden">
      {/* Form */}
      <form onSubmit={handleSubmit} className="flex flex-1 flex-col overflow-y-auto px-4 py-4">
        <div className="space-y-4">
          {/* Routing — mode + workspace */}
          <ModeWorkspaceFields
            mode={formData.mode ?? 'forge'}
            workspace={formData.workspace ?? null}
            onChange={(next) =>
              setFormData((prev) => ({
                ...prev,
                mode: next.mode,
                workspace: next.workspace,
              }))
            }
          />

          {/* Schedule Type */}
          <div>
            <label className="block text-sm font-medium text-(--color-text)">Schedule Type</label>
            <SegmentedControl
              layoutId="scheduler-schedule-type-edit"
              ariaLabel="Schedule type"
              className="mt-2"
              value={formData.schedule_type}
              onChange={(v) => setFormData({ ...formData, schedule_type: v })}
              options={[
                { value: 'every', label: 'Every' },
                { value: 'cron', label: 'Cron' },
                { value: 'at', label: 'At' },
              ]}
            />
          </div>

          {/* Schedule value (conditional) */}
          {formData.schedule_type === 'at' && (
            <div>
              <div className="flex items-end gap-2">
                <div className="flex-1">
                  <label className="block text-sm font-medium text-(--color-text)">Date & Time</label>
                  <div className="mt-1">
                    <DateTimePicker
                      value={formData.at_datetime ?? ''}
                      onChange={(v) => setFormData({ ...formData, at_datetime: v })}
                      triggerClassName="bg-(--bg-page) hover:bg-(--bg-page)"
                    />
                  </div>
                </div>
                <div className="w-44 shrink-0">
                  <label className="block text-sm font-medium text-(--color-text)">Timezone</label>
                  <Input
                    className={`mt-1 ${FIELD_CLASS}`}
                    value={formData.timezone}
                    onChange={(e) => setFormData({ ...formData, timezone: e.target.value })}
                    placeholder={localTz}
                  />
                </div>
              </div>
              <p className="mt-1 text-xs text-(--color-text-muted)">IANA timezone (e.g., America/New_York)</p>
            </div>
          )}

          {formData.schedule_type === 'every' && (
            <div>
              <label className="block text-sm font-medium text-(--color-text)">Interval (seconds)</label>
              <Input
                // Numeric value rarely exceeds 6 digits — constrain to ~9rem
                // so the input does not stretch across the full form width.
                className={`mt-1 w-36 ${FIELD_CLASS}`}
                type="number"
                min="1"
                value={formData.every_seconds ?? 3600}
                onChange={(e) =>
                  setFormData({ ...formData, every_seconds: parseInt(e.target.value) || 0 })
                }
              />
              <p className="mt-1 text-xs text-(--color-text-muted)">e.g., 3600 = 1 hour, 86400 = 1 day</p>
            </div>
          )}

          {formData.schedule_type === 'cron' && (
            <div>
              <div className="flex items-end gap-2">
                <div className="flex-1">
                  <label className="block text-sm font-medium text-(--color-text)">Cron Expression</label>
                  <Input
                    className={`mt-1 ${FIELD_CLASS}`}
                    value={formData.cron_expression ?? ''}
                    onChange={(e) => setFormData({ ...formData, cron_expression: e.target.value })}
                    placeholder="e.g., 0 9 * * MON-FRI"
                  />
                </div>
                <div className="w-44 shrink-0">
                  <label className="block text-sm font-medium text-(--color-text)">Timezone</label>
                  <Input
                    className={`mt-1 ${FIELD_CLASS}`}
                    value={formData.timezone}
                    onChange={(e) => setFormData({ ...formData, timezone: e.target.value })}
                    placeholder={localTz}
                  />
                </div>
              </div>
              <p className="mt-1 text-xs text-(--color-text-muted)">IANA timezone (e.g., America/New_York)</p>
            </div>
          )}

          {/* Prompt */}
          <div>
            <label className="block text-sm font-medium text-(--color-text)">Prompt</label>
            <Textarea
              className={`mt-1 ${FIELD_CLASS}`}
              value={formData.prompt}
              onChange={(e) => setFormData({ ...formData, prompt: e.target.value })}
              placeholder="Message to deliver to the team lead when the task fires."
              rows={4}
            />
          </div>

          {/* Session */}
          <SessionIdField
            value={formData.session_id}
            onChange={(v) => setFormData({ ...formData, session_id: v ?? undefined })}
          />

          {/* Error message */}
          {error && (
            <div className="flex gap-2 rounded-lg border border-(--color-error) bg-(--color-error-subtle) p-3">
              <AlertCircle size={16} className="shrink-0 text-(--color-error)" />
              <p className="text-sm text-(--color-error)">{error}</p>
            </div>
          )}
        </div>

        {/* Actions */}
        <div className="mt-6 flex gap-2">
          <Button
            type="button"
            variant="outline"
            className="flex-1"
            onClick={onCancel}
            disabled={updateMutation.isPending}
          >
            Cancel
          </Button>
          <Button
            type="submit"
            disabled={updateMutation.isPending}
            className="flex-1"
          >
            {updateMutation.isPending ? (
              <>
                <Loader2 size={14} className="animate-spin" />
                Saving…
              </>
            ) : (
              'Save Changes'
            )}
          </Button>
        </div>
      </form>
    </div>
  )
}
