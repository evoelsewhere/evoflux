/**
 * WikiPanel — file tree + markdown editor for the agent wiki.
 *
 * The wiki lives under ``{EVOFLUX_WIKI_DIR}`` and follows the Karpathy
 * Memory v2 layout:
 *
 *   SCHEMA.md    — Dream maintainer rules
 *   INDEX.md     — dream-maintained table of contents (editable)
 *   LOG.md       — append-only Dream activity log
 *   wiki/        — curated and source-compiled Memory v2 pages
 *   imports/     — raw imported Memory v2 documents
 *   notes/       — raw note entries (read-only in the UI; deletable)
 *
 * Legacy wiki folders (topics/entities/sources/comparisons) are still shown
 * when present for compatibility.
 *
 * `WikiTree.system` is the logical bucket for root files (USER, INDEX, LOG,
 * LINT) — there is no `system/` directory on disk.
 *
 * The panel lets the user browse the tree, open a file, and save or delete it.
 * Notes are read-only in the editor (agent-written) but can be deleted.
 * The agent also edits these files through filesystem tools during conversation;
 * invalidation is handled by the team store when any write/edit/rm tool_end
 * targets a ``wiki/`` path, and by ``useTriggerDreamMutation`` after a dream
 * run completes.
 */

import { useRef, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  ArrowLeft,
  BrainCircuit,
  ChevronDown,
  ChevronRight,
  FileText,
  Folder,
  Inbox,
  Loader2,
  LockKeyhole,
  Save,
  Sparkles,
  Trash2,
  X,
} from 'lucide-react'
import { useIsMobile } from '@/hooks/use-mobile'
import { useModalFocus } from '@/hooks/useModalFocus'
import { useReducedMotion } from '@/hooks/useReducedMotion'
import { usePlatform } from '@/hooks/use-platform'
import { mediumHapticFeedback } from '@/lib/haptics'
import {
  useWikiTreeQuery,
  useWikiFileQuery,
  useWriteWikiFileMutation,
  useDeleteWikiFileMutation,
} from '@/queries'
import { useMotionPreset } from '@/lib/motion'
import { cn } from '@/lib/utils'
import type { WikiFileInfo } from '@/api/types'
import { getIntlLocale, translate } from '@/i18n'

interface WikiPanelProps {
  open: boolean
  onClose: () => void
  embedded?: boolean
}


const WIKI_LONG_PRESS_MS = 520
const WIKI_LONG_PRESS_MOVE_TOLERANCE = 10

type SectionKey =
  | 'system'
  | 'wiki'
  | 'imports'
  | 'notes'
  | 'topics'
  | 'entities'
  | 'sources'
  | 'comparisons'

type Section = {
  key: SectionKey
  label: string
  hint: string
  files: WikiFileInfo[]
}

export function WikiPanel({ open, onClose, embedded = false }: WikiPanelProps) {
  const isMobile = useIsMobile()
  const prefersReducedMotion = useReducedMotion()
  const preset = useMotionPreset()
  const { data: tree, isLoading, isError } = useWikiTreeQuery(true)
  const [selectedPath, setSelectedPath] = useState<string | null>(null)
  const [mobilePane, setMobilePane] = useState<'tree' | 'editor'>('tree')
  useModalFocus(open && !embedded, onClose)

  const handleSelect = (path: string) => {
    setSelectedPath(path)
    if (isMobile) setMobilePane('editor')
  }

  const handleBack = () => {
    setMobilePane('tree')
    setSelectedPath(null)
  }

  const rootFiles = tree?.system ?? []
  const rawSections: Section[] = [
    {
      key: 'wiki',
      label: 'Knowledge',
      hint: 'Curated pages agents can recall',
      files: tree?.wiki ?? [],
    },
    {
      key: 'imports',
      label: 'Imports',
      hint: 'Original imported documents',
      files: tree?.imports ?? [],
    },
    {
      key: 'notes',
      label: 'Inbox',
      hint: 'Notes waiting for Dream synthesis',
      files: tree?.notes ?? [],
    },
    {
      key: 'topics',
      label: 'Legacy topics',
      hint: 'Legacy concept pages',
      files: tree?.topics ?? [],
    },
    {
      key: 'entities',
      label: 'Legacy entities',
      hint: 'Legacy people, tools, organisations, products',
      files: tree?.entities ?? [],
    },
    {
      key: 'sources',
      label: 'Legacy sources',
      hint: 'Legacy source summaries',
      files: tree?.sources ?? [],
    },
    {
      key: 'comparisons',
      label: 'Legacy comparisons',
      hint: 'Legacy X-vs-Y pages',
      files: tree?.comparisons ?? [],
    },
  ]
  const sections = rawSections.filter(
    (s) => s.key === 'wiki' || s.key === 'notes' || s.files.length > 0,
  )
  const curatedCount = (tree?.wiki.length ?? 0)
    + (tree?.topics.length ?? 0)
    + (tree?.entities.length ?? 0)
    + (tree?.sources.length ?? 0)
    + (tree?.comparisons.length ?? 0)
  const pendingCount = tree?.notes.length ?? 0

  return (
    <AnimatePresence>
      {open && (
        <>
          {!embedded && <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="fixed inset-0 z-(--z-overlay) bg-(--color-overlay)"
          />}

          <motion.div
            initial={embedded ? false : prefersReducedMotion ? { opacity: 0 } : { opacity: 0, scale: 0.97, y: 8 * preset.distance }}
            animate={embedded ? undefined : prefersReducedMotion ? { opacity: 1 } : { opacity: 1, scale: 1, y: 0 }}
            exit={embedded ? undefined : prefersReducedMotion ? { opacity: 0 } : { opacity: 0, scale: 0.97, y: 8 * preset.distance }}
            transition={preset.spring}
            className={cn(
              'flex flex-col overflow-hidden border-(--color-border) bg-(--bg-page)',
              embedded
                ? 'relative h-full w-full'
                : 'fixed inset-x-0 bottom-0 top-[env(safe-area-inset-top,0px)] z-(--z-modal) shadow-2xl sm:left-1/2 sm:top-1/2 sm:inset-auto sm:h-[min(90vh,860px)] sm:w-[min(90vw,1180px)] sm:-translate-x-1/2 sm:-translate-y-1/2 sm:rounded-lg sm:border',
            )}
            role={embedded ? 'region' : 'dialog'}
            aria-modal={embedded ? undefined : 'true'}
            aria-label="Memory"
            data-modal-focus={embedded ? undefined : 'true'}
          >
            <header className="flex min-h-16 items-center justify-between gap-3 border-b border-(--color-border) bg-(--bg-sidebar)/55 px-4 py-3">
              <div className="flex min-w-0 items-center gap-3">
                {isMobile && mobilePane === 'editor' && (
                  <button
                    onClick={handleBack}
                    className="flex size-9 shrink-0 items-center justify-center rounded-lg text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
                    aria-label="Back to file list"
                  >
                    <ArrowLeft size={16} />
                  </button>
                )}
                <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-(--color-accent-soft) text-(--color-accent)">
                  <BrainCircuit size={17} aria-hidden="true" />
                </div>
                <div className="min-w-0">
                  <h2 className="font-heading text-sm font-semibold text-(--color-text)">Memory</h2>
                  <p className="truncate text-xs text-(--color-text-muted)">
                    Long-term knowledge shared across conversations
                  </p>
                </div>
              </div>
              <div className="flex shrink-0 items-center gap-1.5">
                {!isLoading && !isError && (
                  <div className="hidden items-center gap-1.5 sm:flex">
                    <span className="rounded-full bg-(--color-accent-soft) px-2 py-1 font-mono text-[10px] tabular-nums text-(--color-accent)">
                      {curatedCount} pages
                    </span>
                    <span className="rounded-full bg-(--bg-key) px-2 py-1 font-mono text-[10px] tabular-nums text-(--color-text-muted)">
                      {pendingCount} pending
                    </span>
                  </div>
                )}
                <button
                  onClick={onClose}
                  className="flex size-8 items-center justify-center rounded-lg text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
                  aria-label="Close Memory panel"
                >
                  <X size={16} />
                </button>
              </div>
            </header>

            {isMobile ? (
              <div className="flex min-h-0 flex-1 flex-col">
                {mobilePane === 'tree' ? (
                  <nav className="flex-1 overflow-y-auto bg-(--bg-sidebar)/45 px-2 py-3">
                    <TreeContent
                      isLoading={isLoading}
                      isError={isError}
                      rootFiles={rootFiles}
                      sections={sections}
                      selectedPath={selectedPath}
                      onSelect={handleSelect}
                    />
                  </nav>
                ) : (
                  <div className="min-w-0 flex-1">
                    {selectedPath ? (
                      <WikiEditor
                        key={selectedPath}
                        path={selectedPath}
                        onDeleted={handleBack}
                      />
                    ) : (
                      <EmptyState />
                    )}
                  </div>
                )}
              </div>
            ) : (
              <div className="flex min-h-0 flex-1">
                <nav className="w-[248px] shrink-0 overflow-y-auto border-r border-(--color-border) bg-(--bg-sidebar)/45 px-2 py-3">
                  <TreeContent
                    isLoading={isLoading}
                    isError={isError}
                    rootFiles={rootFiles}
                    sections={sections}
                    selectedPath={selectedPath}
                    onSelect={handleSelect}
                  />
                </nav>
                <div className="min-w-0 flex-1">
                  {selectedPath ? (
                    <WikiEditor
                      key={selectedPath}
                      path={selectedPath}
                      onDeleted={() => setSelectedPath(null)}
                    />
                  ) : (
                    <EmptyState />
                  )}
                </div>
              </div>
            )}
          </motion.div>
        </>
      )}
    </AnimatePresence>
  )
}

// ── Tree helpers ─────────────────────────────────────────────────────────────

function TreeContent({
  isLoading,
  isError,
  rootFiles,
  sections,
  selectedPath,
  onSelect,
}: {
  isLoading: boolean
  isError: boolean
  rootFiles: WikiFileInfo[]
  sections: Section[]
  selectedPath: string | null
  onSelect: (path: string) => void
}) {
  if (isLoading) {
    return (
      <div className="px-2 py-6 text-center text-xs text-(--color-text-subtle)">
        <Loader2 size={14} className="mx-auto animate-spin" />
      </div>
    )
  }
  if (isError) {
    return <p className="px-2 py-4 text-xs text-(--color-error)">Failed to load Memory</p>
  }
  return (
    <div className="select-none py-1 text-xs">
      {rootFiles.length > 0 && (
        <div className="mb-2">
          <p className="px-2 pb-1.5 text-[10px] font-semibold tracking-[0.08em] text-(--color-text-subtle) uppercase">
            System
          </p>
          {rootFiles.map((file) => (
            <WikiFileRow
              key={file.path}
              file={file}
              depth={0}
              selectedPath={selectedPath}
              onSelect={onSelect}
            />
          ))}
        </div>
      )}
      {sections.map((section) => (
        <WikiSection
          key={section.key}
          section={section}
          selectedPath={selectedPath}
          onSelect={onSelect}
        />
      ))}
    </div>
  )
}

function WikiSection({
  section,
  selectedPath,
  onSelect,
}: {
  section: Section
  selectedPath: string | null
  onSelect: (path: string) => void
}) {
  const preset = useMotionPreset()
  const [isExpanded, setIsExpanded] = useState(section.key !== 'imports')
  const childCount = section.files.length

  return (
    <div className="mb-0.5">
      <button
        type="button"
        onClick={() => setIsExpanded((value) => !value)}
        className="group flex h-9 w-full items-center gap-1.5 rounded-lg px-2 text-left text-xs text-(--color-text-2) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
        aria-expanded={isExpanded}
        title={section.hint}
      >
        {isExpanded ? (
          <ChevronDown size={13} className="shrink-0 text-(--color-text-subtle)" aria-hidden="true" />
        ) : (
          <ChevronRight size={13} className="shrink-0 text-(--color-text-subtle)" aria-hidden="true" />
        )}
        <Folder size={13} className="shrink-0 text-(--color-text-subtle)" aria-hidden="true" />
        <span className="min-w-0 flex-1 truncate font-semibold">{section.label}</span>
        {childCount > 0 && (
          <span className="min-w-5 rounded-full bg-(--bg-key) px-1.5 py-0.5 text-center font-mono text-[10px] tabular-nums text-(--color-text-subtle)">
            {childCount}
          </span>
        )}
      </button>
      <AnimatePresence initial={false}>
        {isExpanded && (
          <motion.div
            key="wiki-section-children"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={preset.transition}
            className="overflow-hidden pb-1"
          >
            {section.files.length === 0 ? (
              <p className="h-7 truncate py-1.5 pl-9 pr-2 text-[11px] italic text-(--color-text-subtle)">
                Nothing here yet
              </p>
            ) : (
              section.files.map((file) => (
                <WikiFileRow
                  key={file.path}
                  file={file}
                  depth={1}
                  selectedPath={selectedPath}
                  onSelect={onSelect}
                />
              ))
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

function WikiFileRow({
  file,
  depth,
  selectedPath,
  onSelect,
}: {
  file: WikiFileInfo
  depth: number
  selectedPath: string | null
  onSelect: (path: string) => void
}) {
  const isMobile = useIsMobile()
  const { isTauri, os } = usePlatform()
  const isTauriMobile = isTauri && (os === 'ios' || os === 'android')
  const [actionsPoint, setActionsPoint] = useState<{ x: number; y: number } | null>(null)
  const longPressTimerRef = useRef<number | null>(null)
  const longPressStartRef = useRef<{ x: number; y: number } | null>(null)
  const name = file.path.split('/').pop() ?? file.path
  const isActive = file.path === selectedPath

  const clearLongPress = () => {
    if (longPressTimerRef.current !== null) window.clearTimeout(longPressTimerRef.current)
    longPressTimerRef.current = null
    longPressStartRef.current = null
  }

  const copyPath = async () => {
    await navigator.clipboard.writeText(file.path)
  }

  return (
    <>
    <button
      type="button"
      onClick={() => onSelect(file.path)}
      onContextMenu={(event) => {
        if (isTauriMobile) return
        event.preventDefault()
        setActionsPoint({ x: event.clientX, y: event.clientY })
      }}
      onPointerDown={(event) => {
        if (!isMobile || !isTauriMobile || event.pointerType === 'mouse') return
        longPressStartRef.current = { x: event.clientX, y: event.clientY }
        longPressTimerRef.current = window.setTimeout(() => {
          longPressTimerRef.current = null
          longPressStartRef.current = null
          mediumHapticFeedback()
          setActionsPoint({ x: event.clientX, y: event.clientY })
        }, WIKI_LONG_PRESS_MS)
      }}
      onPointerMove={(event) => {
        const start = longPressStartRef.current
        if (!start) return
        if (
          Math.abs(event.clientX - start.x) > WIKI_LONG_PRESS_MOVE_TOLERANCE ||
          Math.abs(event.clientY - start.y) > WIKI_LONG_PRESS_MOVE_TOLERANCE
        ) {
          clearLongPress()
        }
      }}
      onPointerUp={clearLongPress}
      onPointerCancel={clearLongPress}
      onPointerLeave={clearLongPress}
      className={cn(
        'group flex h-8 w-full items-center gap-1.5 rounded-lg px-1.5 text-left text-xs transition-colors',
        isActive
          ? 'bg-(--color-accent-soft) font-medium text-(--color-accent)'
          : 'text-(--color-text-2) hover:bg-(--bg-key) hover:text-(--color-text)',
      )}
      style={{ paddingLeft: `${depth * 16 + 6}px` }}
      title={file.description || file.path}
    >
      <FileText
        size={13}
        className={cn(
          'shrink-0',
          isActive ? 'text-(--color-accent)' : 'text-(--color-text-subtle) group-hover:text-(--color-text-2)',
        )}
        aria-hidden="true"
      />
      <span className="min-w-0 flex-1 truncate font-mono text-[11px]">{name}</span>
    </button>
    {actionsPoint && (
      <div
        className="fixed inset-0 z-(--z-lightbox)"
        onClick={() => setActionsPoint(null)}
        onContextMenu={(event) => {
          event.preventDefault()
          setActionsPoint(null)
        }}
      >
        <div
          role="menu"
          aria-label={`Actions for ${name}`}
          className="fixed min-w-44 rounded-lg border border-(--color-border) bg-(--bg-card) p-1 text-sm text-(--color-text) shadow-xl"
          style={{ left: actionsPoint.x, top: actionsPoint.y }}
          onClick={(event) => event.stopPropagation()}
        >
          <button
            type="button"
            role="menuitem"
            className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left hover:bg-(--bg-key) focus-visible:bg-(--bg-key) focus-visible:outline-none"
            onClick={() => {
              setActionsPoint(null)
              onSelect(file.path)
            }}
          >
            <FileText size={14} aria-hidden="true" />
            Open
          </button>
          <button
            type="button"
            role="menuitem"
            className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left hover:bg-(--bg-key) focus-visible:bg-(--bg-key) focus-visible:outline-none"
            onClick={() => {
              setActionsPoint(null)
              void copyPath()
            }}
          >
            <FileText size={14} aria-hidden="true" />
            Copy path
          </button>
        </div>
      </div>
    )}
    </>
  )
}

// ── Editor ───────────────────────────────────────────────────────────────────

function WikiEditor({
  path,
  onDeleted,
}: {
  path: string
  onDeleted: () => void
}) {
  const { data: file, isLoading, isError } = useWikiFileQuery(path)
  const writeMutation = useWriteWikiFileMutation()
  const deleteMutation = useDeleteWikiFileMutation()

  const textareaRef = useRef<HTMLTextAreaElement | null>(null)
  const [dirty, setDirty] = useState(false)
  // `charCount` tracks live edits only — when null, we derive the display
  // count from `file.content.length` so an empty buffer correctly shows 0
  // (instead of incorrectly falling back to the original file length).
  const [charCount, setCharCount] = useState<number | null>(null)

  // Raw Memory v2 inputs are read-only in the editor; curated/source pages remain editable.
  const isReadOnly = path.startsWith('notes/') || path.startsWith('imports/')
  // Root files cannot be deleted — backend enforces this too.
  const isDeletable = path !== 'USER.md' && path !== 'INDEX.md' && path !== 'SCHEMA.md'

  const getDraft = (): string => textareaRef.current?.value ?? file?.content ?? ''

  const handleSave = () => {
    if (!dirty || isReadOnly) return
    writeMutation.mutate(
      { path, content: getDraft() },
      { onSuccess: () => setDirty(false) },
    )
  }

  const handleDelete = () => {
    if (!confirm(translate('Delete Memory file "{0}"? This cannot be undone.', [path]))) return
    deleteMutation.mutate(path, { onSuccess: onDeleted })
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (!isReadOnly && (e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
      e.preventDefault()
      handleSave()
    }
  }

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center text-(--color-text-subtle)">
        <Loader2 size={16} className="animate-spin" />
      </div>
    )
  }
  if (isError || !file) {
    return (
      <div className="flex h-full items-center justify-center px-4 text-center text-xs text-(--color-error)">
        Failed to load {path}
      </div>
    )
  }

  const displayChars = charCount ?? file.content.length

  return (
    <div className="flex h-full flex-col">
      <div className="flex min-h-14 items-center justify-between gap-3 border-b border-(--color-border) bg-(--bg-card) px-4 py-2.5">
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 items-center gap-2">
            <div className="truncate font-mono text-xs font-medium text-(--color-text)">{path}</div>
            {isReadOnly && (
              <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-(--bg-key) px-2 py-0.5 text-[10px] font-medium text-(--color-text-muted)">
                <LockKeyhole size={10} aria-hidden="true" />
                Source
              </span>
            )}
          </div>
          {file.description && (
            <div className="mt-0.5 truncate text-[11px] text-(--color-text-muted)">
              {file.description}
            </div>
          )}
        </div>
        <div className="ml-2 flex items-center gap-1">
          {!isReadOnly && (
            <button
              onClick={handleSave}
              disabled={!dirty || writeMutation.isPending}
              className={cn(
                'flex h-8 items-center gap-1.5 rounded-lg px-2.5 text-xs font-medium transition-[background-color,color,opacity]',
                dirty
                  ? 'bg-(--color-accent) text-(--color-text-on-accent) hover:opacity-90'
                  : 'cursor-not-allowed text-(--color-text-subtle)',
              )}
              title="Save (Ctrl/⌘ S)"
            >
              {writeMutation.isPending ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
              Save
            </button>
          )}
          {isDeletable && (
            <button
              onClick={handleDelete}
              disabled={deleteMutation.isPending}
              className="flex h-8 items-center gap-1.5 rounded-lg px-2.5 text-xs font-medium text-(--color-error) transition-colors hover:bg-(--color-error-subtle)"
              title="Delete file"
            >
              <Trash2 size={12} />
              Delete
            </button>
          )}
        </div>
      </div>

      {writeMutation.isError && (
        <div className="border-b border-(--color-border) bg-(--color-error-subtle) px-4 py-2 text-xs text-(--color-error)">
          {(writeMutation.error as Error).message}
        </div>
      )}

      <textarea
        ref={textareaRef}
        defaultValue={file.content}
        readOnly={isReadOnly}
        onInput={(e) => {
          if (isReadOnly) return
          const v = (e.target as HTMLTextAreaElement).value
          setCharCount(v.length)
          if (!dirty) setDirty(true)
        }}
        onKeyDown={handleKeyDown}
        spellCheck={false}
        className={cn(
          'min-h-0 flex-1 resize-none p-5 font-mono text-[13px] leading-6 text-(--color-text) focus:outline-none',
          isReadOnly
            ? 'cursor-default bg-(--bg-muted)/45 text-(--color-text-muted)'
            : 'bg-(--bg-page)',
        )}
        placeholder={
          isReadOnly ? '' :
          path === 'INDEX.md' ? '# Index\n\n- [topic](topics/topic.md) — description\n' :
          'Frontmatter recommended:\n---\ndescription: …\n---\n\n'
        }
      />

      <div className="flex items-center justify-between border-t border-(--color-border) bg-(--bg-card) px-4 py-2 font-mono text-[10px] text-(--color-text-subtle)">
        <span className="tabular-nums">{displayChars.toLocaleString(getIntlLocale())} chars</span>
        {isReadOnly ? (
          <span className="italic">read-only</span>
        ) : dirty ? (
          <span className="text-(--color-accent)">unsaved</span>
        ) : (
          <span>saved</span>
        )}
      </div>
    </div>
  )
}

// ── Empty state ──────────────────────────────────────────────────────────────

function EmptyState() {
  return (
    <div className="flex h-full items-center justify-center overflow-y-auto px-6 py-8">
      <div className="w-full max-w-sm text-center">
        <div className="mx-auto flex size-12 items-center justify-center rounded-2xl bg-(--color-accent-soft) text-(--color-accent)">
          <BrainCircuit size={22} aria-hidden="true" />
        </div>
        <p className="mt-4 font-heading text-base font-semibold text-(--color-text)">
          Your long-term Memory
        </p>
        <p className="mx-auto mt-1.5 max-w-xs text-xs leading-relaxed text-(--color-text-muted)">
          Select a page to review the knowledge agents can carry into future conversations.
        </p>
        <div className="mt-5 grid gap-2 text-left">
          <div className="flex items-start gap-2.5 rounded-lg border border-(--color-border) bg-(--bg-card) p-3">
            <Inbox size={14} className="mt-0.5 shrink-0 text-(--color-text-muted)" aria-hidden="true" />
            <div>
              <p className="text-xs font-medium text-(--color-text)">Inbox captures evidence</p>
              <p className="mt-0.5 text-[11px] leading-relaxed text-(--color-text-subtle)">
                Notes and imports stay unchanged until they are synthesized.
              </p>
            </div>
          </div>
          <div className="flex items-start gap-2.5 rounded-lg border border-(--color-border) bg-(--bg-card) p-3">
            <Sparkles size={14} className="mt-0.5 shrink-0 text-(--color-accent)" aria-hidden="true" />
            <div>
              <p className="text-xs font-medium text-(--color-text)">Dream builds knowledge</p>
              <p className="mt-0.5 text-[11px] leading-relaxed text-(--color-text-subtle)">
                Curated pages preserve sources while removing repetition.
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
