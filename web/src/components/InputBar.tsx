import { useRef, useState, useCallback, useImperativeHandle, forwardRef, useEffect, useMemo } from 'react'
import { Activity, ArrowUp, ChevronDown, File, Folder, ListTodo, Loader2, MessageCircle, Paperclip, Quote, Square, SquareCheck, Terminal, X } from 'lucide-react'
import { FilePreviewStrip } from './FilePreviewStrip'
import { findActiveMention, rankFileRefs, type FileRef } from './InputBar.mentions'
import { MentionOverlay } from './InputBar.overlay'
import { SessionPillsRow, type SessionPillsRowProps } from './SessionPillsRow'
import { ModeSelector } from './ModeSelector'
import { TodosList } from './TodosList'
import { cn } from '@/lib/utils'
import type { AgentCapabilities, TodoItem } from '@/api/types'
import { useIsMobile } from '@/hooks/use-mobile'

// Re-export the public type so callers can import ``FileRef`` from this module
// alongside the component. (The helper ``findActiveMention`` is imported from
// './InputBar.mentions' directly to keep this file free of non-component
// runtime exports — react-refresh requirement.)
export type { FileRef } from './InputBar.mentions'

// ── Slash commands ──────────────────────────────────────────────────────────

export interface SlashCommand {
  id: string
  label: string
  description: string
  /**
   * When true, picking this command from the menu inserts ``/<id> `` into
   * the textarea and leaves the caret after the trailing space — for
   * commands that take free-form arguments the user still needs to type
   * (e.g. backend-discovered commands with ``$ARGUMENTS``). The default
   * is the legacy behaviour: the input is cleared and the parent's
   * ``onSlashCommand`` runs immediately.
   */
  keepInputOpen?: boolean
  /**
   * Optional visual category tag displayed in a small badge to the right of
   * the description (e.g. ``"skill"`` or ``"command"``). Use this to visually
   * distinguish different kinds of slash entries without adding a separate
   * separator row for every group.
   */
  category?: string
  /** Text shown after the leading slash in the picker. Defaults to ``id``. */
  displayName?: string
  /** Text inserted after the leading slash when ``keepInputOpen`` is true. Defaults to ``id``. */
  insertText?: string
  /** Only show this entry once the slash query starts with this prefix. */
  filterPrefix?: string
  /** Hide this launcher once its submenu prefix has been completed. */
  hideAfterPrefix?: string
  /** Whether selection appends a trailing space. Defaults to true. */
  appendSpace?: boolean
  /**
   * When ``true`` this entry is rendered as a non-interactive section header
   * (a label row). Set ``id`` to something unique but non-actionable and
   * leave ``description`` blank. Keyboard navigation skips these rows.
   */
  isSeparator?: boolean
}

export interface SnippetCommand {
  id: string
  label: string
  description: string
  category?: string
}

interface InputBarProps {
  /** Return false to reject the send and preserve the current draft. */
  onSubmit: (message: string, files?: File[]) => boolean | void | Promise<boolean | void>
  onStop?: () => void
  onSlashCommand?: (id: string) => void
  onSnippetCommand?: (id: string) => Promise<string | null> | string | null
  slashCommands?: SlashCommand[]
  snippetCommands?: SnippetCommand[]
  /**
   * Workspace files/folders the user can reference with `@`. When the list is
   * empty (or omitted) the picker stays dormant — the `@` character behaves as
   * plain text.
   */
  fileRefs?: FileRef[]
  onFileRefsNeeded?: () => void
  isStreaming?: boolean
  disabled?: boolean
  /** Whether this composer can submit file attachments. Defaults to true. */
  attachmentsEnabled?: boolean
  placeholder?: string
  autoFocus?: boolean
  capabilities?: AgentCapabilities
  /**
   * When true, the component renders only the inner rounded pill (no
   * top border, no background row chrome). A parent wrapper is expected
   * to provide positioning, and backdrop. Used by
   * `FloatingInputBar` for the draggable variant.
   */
  floating?: boolean
  /**
   * When true, file previews render below the input container instead of
   * above it. Used by `FloatingInputBar` when the panel is near the top
   * edge of its bounds so previews stay visible.
   */
  filesBelow?: boolean
  /**
   * Optional render-prop for a drag handle rendered anchored to the top
   * edge of the input pill (not the outer wrapper). This keeps the handle
   * pinned to the input regardless of whether file previews are rendered
   * above or below. Used by `FloatingInputBar`.
   */
  renderDragHandle?: () => React.ReactNode
  /**
   * When true, render the slim collapsed action strip instead of the full
   * pill. The strip keeps file, voice, chat, and send/stop controls visible.
   * Clicking the chat affordance calls `onUnminimize` so the parent can swap
   * back to the full variant and focus the textarea.
   */
  minimized?: boolean
  /** Called when the user clicks the collapsed bar to expand it. */
  onUnminimize?: () => void
  /** Forwarded to the textarea so the parent can drive minimize-on-blur. */
  onFocus?: () => void
  /**
   * Fired when the textarea blurs. ``canMinimize`` is ``false`` when the
   * input has uncommitted content (text or attachments) the user would
   * lose visual access to if the bar collapsed; the parent should keep
   * the bar expanded in that case.
   */
  onBlur?: (canMinimize: boolean) => void
  /**
   * Called whenever uncommitted content (text or attachments) appears or
   * disappears. The parent uses this to keep the bar expanded when the
   * user adds files via the minimized strip's attach button — without
   * this signal, dropping a file while collapsed would leave the bar
   * collapsed and the new file invisible.
   */
  onHasContentChange?: (hasContent: boolean) => void
  /** Newest-first prompt history supplied by the parent, e.g. loaded chat history. */
  historyPrompts?: string[]
  /** Session model settings — when provided, renders SessionPillsRow above the textarea. */
  sessionModel?: string | null
  defaultModel?: string | null
  sessionThinkingLevel?: string | null
  sessionFastMode?: boolean
  onSessionModelSettingsChange?: SessionPillsRowProps['onSessionModelSettingsChange']
  agentNames?: string[]
  agentWorkspace?: string | null
  /** Roster mode for the workspace team ('coding'). */
  agentMode?: 'coding' | null
  /**
   * Composer-anchored task popover. ``todosOpen`` controls visibility and
   * ``onTodosOpenChange`` is fired by the progress pill above the input card.
   */
  todos?: TodoItem[]
  todosOpen?: boolean
  onTodosOpenChange?: (open: boolean) => void
  sessionId?: string | null
  onWiki?: () => void
  wikiActive?: boolean
  onActivity?: () => void
  activityActive?: boolean
  /** Optional mode-specific control rendered with the composer's left actions. */
  workspaceSelector?: React.ReactNode
  permissionMode?: import('@/api/types').PermissionMode
  onPermissionModeChange?: (mode: import('@/api/types').PermissionMode) => void
}

export interface InputBarHandle {
  focus: () => void
  setValue: (text: string) => void
  appendValue: (text: string) => void
  insertText: (text: string) => void
  setFiles: (files: File[]) => void
  setQuoteContext: (text: string | null) => void
}

const CHAR_WARN_THRESHOLD = 500

function findActiveSnippet(text: string, caret: number) {
  const hash = text.lastIndexOf('#', Math.max(0, caret - 1))
  if (hash === -1) return null
  const token = text.slice(hash + 1, caret)
  if (/\s/.test(token)) return null
  return { start: hash, end: caret, query: token.toLowerCase() }
}

export const InputBar = forwardRef<InputBarHandle, InputBarProps>(function InputBar({
  onSubmit,
  onStop,
  onSlashCommand,
  onSnippetCommand,
  slashCommands = [],
  snippetCommands = [],
  fileRefs = [],
  onFileRefsNeeded,
  isStreaming = false,
  disabled,
  attachmentsEnabled = true,
  placeholder = 'Message EvoFlux…',
  autoFocus,
  floating = false,
  filesBelow = false,
  renderDragHandle,
  minimized = false,
  onUnminimize,
  onFocus,
  onBlur,
  onHasContentChange,
  historyPrompts = [],
  sessionModel,
  defaultModel,
  sessionThinkingLevel,
  sessionFastMode,
  onSessionModelSettingsChange,
  agentNames,
  agentWorkspace,
  agentMode,
  todos,
  todosOpen = false,
  onTodosOpenChange,
  onActivity,
  activityActive,
  workspaceSelector,
  permissionMode,
  onPermissionModeChange,
  sessionId = null,
}, ref) {
  const [value, setValue] = useState('')
  const [quoteContext, setQuoteContext] = useState<string | null>(null)
  const [files, setFiles] = useState<File[]>([])
  const [slashMenuIndex, setSlashMenuIndex] = useState(0)
  const [snippetMenuIndex, setSnippetMenuIndex] = useState(0)
  const [mentionMenuIndex, setMentionMenuIndex] = useState(0)
  const [localHistory, setLocalHistory] = useState<string[]>([])
  const [historyIndex, setHistoryIndex] = useState(-1)
  const [submitting, setSubmitting] = useState(false)
  const [snippetRange, setSnippetRange] = useState<
    { start: number; end: number; query: string } | null
  >(null)
  const [shellMode, setShellMode] = useState(false)
  // The active @-mention window (positions in ``value``) — null when no
  // mention is being edited at the caret. Recomputed on every keystroke
  // and on caret-only moves (arrow keys, clicks) via ``syncMention``.
  const [mentionRange, setMentionRange] = useState<
    { start: number; end: number; query: string } | null
  >(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const dragCounterRef = useRef(0)
  const isMobile = useIsMobile()

  // Per-session composer drafts — switching sessions must not bleed text
  // or attachments into the next chat.
  type ComposerDraft = {
    value: string
    files: File[]
    quoteContext: string | null
    shellMode: boolean
  }
  const draftsRef = useRef(new Map<string, ComposerDraft>())
  const activeSessionRef = useRef<string | null>(sessionId)
  const draftSnapshotRef = useRef<ComposerDraft>({
    value: '',
    files: [],
    quoteContext: null,
    shellMode: false,
  })
  useEffect(() => {
    draftSnapshotRef.current = { value, files, quoteContext, shellMode }
  }, [value, files, quoteContext, shellMode])

  useEffect(() => {
    const prev = activeSessionRef.current
    if (prev === sessionId) return
    draftsRef.current.set(prev ?? '', draftSnapshotRef.current)
    const next = draftsRef.current.get(sessionId ?? '')
    setValue(next?.value ?? '')
    setFiles(next?.files ?? [])
    setQuoteContext(next?.quoteContext ?? null)
    setShellMode(next?.shellMode ?? false)
    setMentionRange(null)
    setSnippetRange(null)
    setHistoryIndex(-1)
    activeSessionRef.current = sessionId
  }, [sessionId])

  // Terminal → composer handoff: the AI Terminal's "Send to agent" dispatches
  // this event so selected output lands in the chat draft, without coupling
  // the terminal to the composer's internal state.
  useEffect(() => {
    const onInsert = (e: Event) => {
      const text = (e as CustomEvent<{ text?: string }>).detail?.text
      if (!text) return
      setValue((v) => (v ? `${v}\n${text}` : text))
      textareaRef.current?.focus()
    }
    window.addEventListener('evoflux:composer-insert', onInsert)
    return () => window.removeEventListener('evoflux:composer-insert', onInsert)
  }, [])

  const history = useMemo(() => {
    const seen = new Set<string>()
    const entries: string[] = []
    for (const prompt of [...localHistory, ...historyPrompts]) {
      const trimmed = prompt.trim()
      if (!trimmed || seen.has(trimmed)) continue
      seen.add(trimmed)
      entries.push(trimmed)
    }
    return entries
  }, [localHistory, historyPrompts])

  // Refresh the active mention window from the current caret position. Called
  // whenever the caret might have moved without the value changing (arrow keys,
  // click, focus from history nav). Cheap; just a left-scan from the caret.
  const syncMention = useCallback(() => {
    const el = textareaRef.current
    if (!el) return
    const caret = el.selectionStart ?? el.value.length
    const next = shellMode ? null : findActiveMention(el.value, caret)
    setSnippetRange(next || shellMode ? null : findActiveSnippet(el.value, caret))
    setMentionRange((prev) => {
      if (!prev && !next) return prev
      if (
        prev && next &&
        prev.start === next.start &&
        prev.end === next.end &&
        prev.query === next.query
      ) return prev
      return next
    })
  }, [shellMode])

  // Create blob URLs for files — memoized to avoid recreating on every render
  const blobUrls = useMemo(() => {
    const urls = new Map<number, string>()
    files.forEach((file, idx) => {
      urls.set(idx, URL.createObjectURL(file))
    })
    return urls
  }, [files])

  // Revoke blob URLs when files change or on unmount
  useEffect(() => {
    return () => {
      blobUrls.forEach((url) => URL.revokeObjectURL(url))
    }
  }, [blobUrls])

  // ``isMultiLine`` is updated as a side-effect of ``resize`` rather
  // than a separate effect, so the DOM measurement and the React
  // state stay in lock-step (one render cycle, no cascade).
  //
  // Hysteresis on the promote/demote decision:
  //   - Promote (false → true): textarea's scrollHeight exceeds one
  //     line height. Record the value length at the moment of
  //     promotion in ``promoteLengthRef``.
  //   - Demote (true → false): only when the value has no newlines
  //     AND its length is now ≤ 80% of the recorded promote-length.
  //     The 20% guard band absorbs the layout feedback loop where
  //     promoting widens the textarea (so the same content fits on
  //     one line again) which would otherwise demote → re-promote.
  const promoteLengthRef = useRef(0)
  const resize = useCallback(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    // max 5 rows ≈ 120px
    el.style.height = `${Math.min(el.scrollHeight, 120)}px`
    const computed = window.getComputedStyle(el)
    const lineHeight = parseFloat(computed.lineHeight) ||
      parseFloat(computed.fontSize) * 1.5
    const wrapped = el.scrollHeight > lineHeight * 1.4
    const currentLen = el.value.length
    const hasNewline = el.value.includes('\n')
    // isMultiLine detection kept alive so consumers that read it still work;
    // the current vertical layout does not need it for flex-order tricks.
    void wrapped; void currentLen; void hasNewline; void promoteLengthRef
  }, [])

  useImperativeHandle(ref, () => ({
    focus: () => textareaRef.current?.focus(),
    setValue: (text: string) => {
      setValue(text)
      setQuoteContext(null)
      setShellMode(false)
      setHistoryIndex(-1)
      // Programmatic value replacement invalidates any open mention picker —
      // its ``start``/``end`` indices refer to the old text.
      setMentionRange(null)
      setSnippetRange(null)
      // Trigger height recalculation after injecting text programmatically
      requestAnimationFrame(resize)
    },
    appendValue: (text: string) => {
      setValue((prev) => {
        const spacer = prev && !/\s$/.test(prev) ? ' ' : ''
        return `${prev}${spacer}${text}`
      })
      setShellMode(false)
      setHistoryIndex(-1)
      setMentionRange(null)
      setSnippetRange(null)
      requestAnimationFrame(resize)
    },
    insertText: (text: string) => {
      const el = textareaRef.current
      const shouldEnterShellMode =
        !shellMode && !quoteContext && value.length === 0 && text === '!'
      setValue((prev) => {
        const start = el?.selectionStart ?? prev.length
        const end = el?.selectionEnd ?? start
        if (shouldEnterShellMode && prev.length === 0 && start === 0 && end === 0) {
          requestAnimationFrame(resize)
          return ''
        }
        const next = prev.slice(0, start) + text + prev.slice(end)
        requestAnimationFrame(() => {
          el?.setSelectionRange(start + text.length, start + text.length)
          resize()
        })
        return next
      })
      setShellMode(shouldEnterShellMode ? true : false)
      setHistoryIndex(-1)
      setMentionRange(null)
      setSnippetRange(null)
    },
    setFiles: (nextFiles: File[]) => {
      setFiles(nextFiles)
    },
    setQuoteContext: (text: string | null) => {
      const normalized = text?.trim() || null
      setQuoteContext(normalized)
      if (normalized) setShellMode(false)
    },
  }))

  // Auto-focus the textarea whenever the bar transitions from
  // minimized → expanded. The textarea is always mounted (visibility
  // is opacity-driven, not mount-driven) so the ref is reliably
  // populated; we just need to call ``.focus()`` at the transition.
  const prevMinimizedRef = useRef(minimized)
  useEffect(() => {
    const wasMinimized = prevMinimizedRef.current
    prevMinimizedRef.current = minimized
    if (!wasMinimized || minimized) return
    // Focus on the next frame so the expanded textarea is visible first.
    const id = requestAnimationFrame(() => {
      textareaRef.current?.focus()
    })
    return () => cancelAnimationFrame(id)
  }, [minimized])

  // Plain ref now — no auto-focus-on-mount magic needed since the
  // textarea never unmounts.
  const setTextareaRef = useCallback((node: HTMLTextAreaElement | null) => {
    textareaRef.current = node
  }, [])

  const slashFilter = !shellMode && value.startsWith('/') && !value.includes(' ')
    ? value.slice(1).toLowerCase()
    : null

  const submit = useCallback(async () => {
    const trimmed = value.trim()
    const context = quoteContext?.trim() ?? ''
    if ((!trimmed && !context && files.length === 0) || disabled || submitting || slashFilter !== null) return
    const quotedContext = context
      ? context
          .split('\n')
          .map((line) => `> ${line}`)
          .join('\n')
      : ''
    const attachmentPrompt = files.length > 0 && !trimmed && !quotedContext
      ? `Please inspect the attached file${files.length === 1 ? '' : 's'}.`
      : ''
    const message = [quotedContext, trimmed, attachmentPrompt].filter(Boolean).join('\n\n')
    const submitted = shellMode ? `!${trimmed}` : message
    const submittedFiles = files
    const submittedShellMode = shellMode

    // Clear the accepted draft immediately instead of leaving it visible
    // while network/model checks run. If the parent rejects or throws, restore
    // only into still-empty fields so text typed during the request is never
    // overwritten.
    setValue('')
    setQuoteContext(null)
    setShellMode(false)
    setFiles([])
    setMentionRange(null)
    setSnippetRange(null)
    setHistoryIndex(-1)
    draftsRef.current.delete(sessionId ?? '')
    if (textareaRef.current) textareaRef.current.style.height = 'auto'

    const restoreDraft = () => {
      setValue((current) => current || value)
      setQuoteContext((current) => current ?? quoteContext)
      setShellMode((current) => current || submittedShellMode)
      setFiles((current) => current.length > 0 ? current : submittedFiles)
      requestAnimationFrame(resize)
    }

    setSubmitting(true)
    try {
      const accepted = await onSubmit(
        submitted,
        submittedFiles.length > 0 ? submittedFiles : undefined,
      )
      if (accepted === false) {
        restoreDraft()
        return
      }
    } catch {
      // The caller owns reporting; restore the draft so it can be retried.
      restoreDraft()
      return
    } finally {
      setSubmitting(false)
    }
    if (trimmed) {
      const historyEntry = shellMode ? `!${trimmed}` : trimmed
      setLocalHistory((prev) =>
        prev[0] === historyEntry ? prev : [historyEntry, ...prev].slice(0, 100),
      )
    }
  }, [
    value,
    quoteContext,
    disabled,
    onSubmit,
    files,
    shellMode,
    slashFilter,
    submitting,
    resize,
    sessionId,
  ])

  const addFile = useCallback((file: File) => {
    setFiles((prev) => [...prev, file])
  }, [])

  const removeFile = useCallback((index: number) => {
    const oldUrl = blobUrls.get(index)
    if (oldUrl) URL.revokeObjectURL(oldUrl)
    setFiles((prev) => prev.filter((_, i) => i !== index))
  }, [blobUrls])

  const handlePaste = useCallback((e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    if (!attachmentsEnabled) return
    const items = e.clipboardData?.items
    if (!items) return
    for (let i = 0; i < items.length; i++) {
      const item = items[i]
      if (item.kind === 'file') {
        const file = item.getAsFile()
        if (file) {
          e.preventDefault()
          addFile(file)
        }
      }
    }
  }, [addFile, attachmentsEnabled])

  const handleDragEnter = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    if (!attachmentsEnabled) return
    dragCounterRef.current++
  }, [attachmentsEnabled])

  const handleDragLeave = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    if (!attachmentsEnabled) return
    dragCounterRef.current--
  }, [attachmentsEnabled])

  const handleDragOver = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault()
  }, [])

  const handleDrop = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    if (!attachmentsEnabled) return
    dragCounterRef.current = 0
    const droppedFiles = e.dataTransfer?.files
    if (!droppedFiles) return
    for (let i = 0; i < droppedFiles.length; i++) {
      const file = droppedFiles[i]
      addFile(file)
    }
  }, [addFile, attachmentsEnabled])

  const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFiles = e.currentTarget.files
    if (!selectedFiles) return
    for (let i = 0; i < selectedFiles.length; i++) {
      const file = selectedFiles[i]
      addFile(file)
    }
    e.currentTarget.value = ''
  }, [addFile])

  // ── Slash command filtering ────────────────────────────────────────────────

  /**
   * ``filteredSlashCommands`` — the visible list shown in the popover.
   *
   * When a filter string is present, separator rows are only kept when at
   * least one actionable entry in their group matches (so we never render a
   * dangling header with nothing beneath it). With an empty filter string
   * (the user just typed ``/``) every entry is shown.
   *
   * Separator rows are excluded from keyboard-navigation indexing; only
   * actionable entries count as "selectable" positions.
   */
  const filteredSlashCommands = useMemo(() => {
    if (slashFilter === null || slashCommands.length === 0) return []

    const availableCommands = slashCommands.filter(
      (cmd) =>
        (!cmd.filterPrefix || slashFilter.startsWith(cmd.filterPrefix)) &&
        (!cmd.hideAfterPrefix || !slashFilter.startsWith(cmd.hideAfterPrefix)),
    )
    if (slashFilter === '') return availableCommands

    // Two-pass: first collect matching actionable ids, then walk the list
    // again keeping actionable matches AND any separator that precedes them.
    const matchedIds = new Set(
      availableCommands
        .filter(
          (cmd) =>
            !cmd.isSeparator &&
            (cmd.id.toLowerCase().includes(slashFilter) ||
              cmd.label.toLowerCase().includes(slashFilter) ||
              (cmd.displayName ?? '').toLowerCase().includes(slashFilter)),
        )
        .map((cmd) => cmd.id),
    )
    if (matchedIds.size === 0) return []

    const result: SlashCommand[] = []
    let pendingSeparator: SlashCommand | null = null
    for (const cmd of availableCommands) {
      if (cmd.isSeparator) {
        pendingSeparator = cmd
        continue
      }
      if (matchedIds.has(cmd.id)) {
        if (pendingSeparator) {
          result.push(pendingSeparator)
          pendingSeparator = null
        }
        result.push(cmd)
      }
    }
    return result
  }, [slashFilter, slashCommands])

  /** Actionable entries only — used for keyboard index arithmetic. */
  const selectableSlashCommands = useMemo(
    () => filteredSlashCommands.filter((cmd) => !cmd.isSeparator),
    [filteredSlashCommands],
  )

  const slashMenuOpen = slashFilter !== null && filteredSlashCommands.length > 0
  const slashMenuId = 'inputbar-slash-menu'
  const mentionMenuId = 'inputbar-mention-menu'
  const snippetMenuId = 'inputbar-snippet-menu'

  const filteredSnippetCommands = useMemo(() => {
    if (!snippetRange || snippetCommands.length === 0) return []
    return snippetCommands.filter((cmd) => {
      if (snippetRange.query === '') return true
      return cmd.id.toLowerCase().includes(snippetRange.query) ||
        cmd.label.toLowerCase().includes(snippetRange.query)
    })
  }, [snippetCommands, snippetRange])

  const snippetMenuOpen = snippetRange !== null && filteredSnippetCommands.length > 0
  const clampedSnippetIndex = filteredSnippetCommands.length > 0
    ? snippetMenuIndex % filteredSnippetCommands.length
    : 0

  const snippetOptionRefs = useRef<(HTMLButtonElement | null)[]>([])
  useEffect(() => {
    snippetOptionRefs.current.length = filteredSnippetCommands.length
    if (!snippetMenuOpen) return
    snippetOptionRefs.current[clampedSnippetIndex]?.scrollIntoView({ block: 'nearest' })
  }, [clampedSnippetIndex, filteredSnippetCommands, snippetMenuOpen])

  // Clamp index to valid range (handles filter changes reducing the list).
  // The index tracks position within ``selectableSlashCommands``, not the full
  // ``filteredSlashCommands`` list, so separator rows are never "focused".
  const clampedIndex = selectableSlashCommands.length > 0
    ? slashMenuIndex % selectableSlashCommands.length
    : 0

  // Refs for slash option buttons so the highlighted row stays visible when
  // the list overflows ``max-h-64``. Same pattern as the mention picker —
  // truncate to the current option count inside the effect, not during
  // render, so unmounted-but-still-recorded nulls don't accumulate.
  const slashOptionRefs = useRef<(HTMLButtonElement | null)[]>([])
  useEffect(() => {
    slashOptionRefs.current.length = selectableSlashCommands.length
    if (!slashMenuOpen) return
    const el = slashOptionRefs.current[clampedIndex]
    el?.scrollIntoView({ block: 'nearest' })
  }, [clampedIndex, slashMenuOpen, selectableSlashCommands])

  const executeSlashCommand = useCallback((cmd: SlashCommand) => {
    if (cmd.isSeparator) return
    setShellMode(false)
    if (cmd.keepInputOpen) {
      // Insert ``/<id> `` and keep the textarea focused so the user can
      // append arguments. Submission is what triggers the action — the
      // parent's onSubmit handler inspects the raw text.
      const suffix = cmd.appendSpace === false ? '' : ' '
      const next = `/${cmd.insertText ?? cmd.displayName ?? cmd.id}${suffix}`
      setValue(next)
      const el = textareaRef.current
      if (el) {
        requestAnimationFrame(() => {
          el.focus()
          el.setSelectionRange(next.length, next.length)
          resize()
        })
      }
      return
    }
    setValue('')
    if (textareaRef.current) textareaRef.current.style.height = 'auto'
    onSlashCommand?.(cmd.id)
  }, [onSlashCommand, resize])

  const insertSnippet = useCallback(async (cmd: SnippetCommand) => {
    if (!snippetRange) return
    const rendered = await onSnippetCommand?.(cmd.id)
    if (rendered == null) return
    const before = value.slice(0, snippetRange.start)
    const after = value.slice(snippetRange.end)
    const spacerBefore = before && !/\s$/.test(before) && rendered ? ' ' : ''
    const spacerAfter = after && !/^\s/.test(after) && rendered ? ' ' : ''
    const next = before + spacerBefore + rendered + spacerAfter + after
    setValue(next)
    setShellMode(false)
    setSnippetRange(null)
    setSnippetMenuIndex(0)
    const el = textareaRef.current
    if (el) {
      const caret = before.length + spacerBefore.length + rendered.length
      requestAnimationFrame(() => {
        el.focus()
        el.setSelectionRange(caret, caret)
        resize()
      })
    }
  }, [onSnippetCommand, resize, snippetRange, value])

  // ── @-mention filtering ────────────────────────────────────────────────────

  const MENTION_MAX_RESULTS = 20

  const filteredMentions = useMemo(() => {
    if (!mentionRange || fileRefs.length === 0) return [] as FileRef[]
    return rankFileRefs(fileRefs, mentionRange.query, MENTION_MAX_RESULTS)
  }, [mentionRange, fileRefs])

  const mentionMenuOpen = mentionRange !== null && filteredMentions.length > 0
  const clampedMentionIndex = filteredMentions.length > 0
    ? mentionMenuIndex % filteredMentions.length
    : 0

  // Refs for each rendered option so the highlighted one can be scrolled
  // into view when the user arrow-keys past the visible window. The array is
  // truncated to the current option count inside the effect (not during
  // render) so unmounted-but-still-recorded nulls don't accumulate.
  const mentionOptionRefs = useRef<(HTMLButtonElement | null)[]>([])
  useEffect(() => {
    mentionOptionRefs.current.length = filteredMentions.length
    if (!mentionMenuOpen) return
    const el = mentionOptionRefs.current[clampedMentionIndex]
    // ``block: 'nearest'`` only scrolls when the item is actually outside the
    // viewport, so it's a no-op for items already visible — no jitter on the
    // initial render or when the user arrows within the visible band.
    el?.scrollIntoView({ block: 'nearest' })
  }, [clampedMentionIndex, mentionMenuOpen, filteredMentions])

  /** Replace the active @-token with the selected reference plus a trailing space. */
  const insertMention = useCallback((ref: FileRef) => {
    if (!mentionRange) return
    const el = textareaRef.current
    const display = ref.type === 'directory' ? `${ref.path}/` : ref.path
    const insertion = `@${display} `
    const before = value.slice(0, mentionRange.start)
    const after = value.slice(mentionRange.end)
    const next = before + insertion + after
    setValue(next)
    setShellMode(false)
    setMentionRange(null)
    setSnippetRange(null)
    setMentionMenuIndex(0)
    // Move the caret to just after the inserted token + trailing space. The
    // textarea state lags by one render so we defer with rAF.
    if (el) {
      const caret = before.length + insertion.length
      requestAnimationFrame(() => {
        el.focus()
        el.setSelectionRange(caret, caret)
        resize()
      })
    }
  }, [mentionRange, value, resize])

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // IME composition guard: when a user is mid-composition (CJK, etc.) the
    // browser fires ``keydown`` with ``isComposing`` true for keys that drive
    // the IME (Enter commits the candidate, Arrow keys navigate it). We must
    // not hijack those — let the IME consume them. ``keyCode === 229`` is the
    // legacy fallback for browsers that don't surface ``isComposing`` on the
    // React synthetic event.
    if (e.nativeEvent.isComposing || e.keyCode === 229) return

    if (e.key === '!' && !shellMode && !quoteContext && value.length === 0) {
      e.preventDefault()
      setShellMode(true)
      setMentionRange(null)
      setSnippetRange(null)
      return
    }

    if (shellMode) {
      if (e.key === 'Backspace' && value.length === 0) {
        e.preventDefault()
        setShellMode(false)
        return
      }
      if (e.key === 'Escape') {
        e.preventDefault()
        setShellMode(false)
        return
      }
    }

    if (
      e.key === 'Backspace'
      && !shellMode
      && value.length === 0
      && quoteContext
    ) {
      e.preventDefault()
      setQuoteContext(null)
      return
    }

    // Mention menu navigation takes priority over slash navigation: a
    // composed message can contain both `/cmd` (only valid at start) and
    // `@foo` (anywhere), and the mention is the active one whenever the
    // caret is sitting inside an `@`-token.
    if (mentionMenuOpen && filteredMentions.length > 0) {
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        setMentionMenuIndex((i) => (i + 1) % filteredMentions.length)
        return
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault()
        setMentionMenuIndex((i) => (i - 1 + filteredMentions.length) % filteredMentions.length)
        return
      }
      if (e.key === 'Enter' || e.key === 'Tab') {
        e.preventDefault()
        insertMention(filteredMentions[clampedMentionIndex])
        return
      }
      if (e.key === 'Escape') {
        e.preventDefault()
        setMentionRange(null)
        return
      }
    }

    if (snippetMenuOpen && filteredSnippetCommands.length > 0) {
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        setSnippetMenuIndex((i) => (i + 1) % filteredSnippetCommands.length)
        return
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault()
        setSnippetMenuIndex((i) => (i - 1 + filteredSnippetCommands.length) % filteredSnippetCommands.length)
        return
      }
      if (e.key === 'Enter' || e.key === 'Tab') {
        e.preventDefault()
        void insertSnippet(filteredSnippetCommands[clampedSnippetIndex])
        return
      }
      if (e.key === 'Escape') {
        e.preventDefault()
        setSnippetRange(null)
        return
      }
    }

    // Slash menu navigation
    if (slashMenuOpen && selectableSlashCommands.length > 0) {
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        setSlashMenuIndex((i) => (i + 1) % selectableSlashCommands.length)
        return
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault()
        setSlashMenuIndex((i) => (i - 1 + selectableSlashCommands.length) % selectableSlashCommands.length)
        return
      }
      if (e.key === 'Enter' || e.key === 'Tab') {
        e.preventDefault()
        executeSlashCommand(selectableSlashCommands[clampedIndex])
        return
      }
      if (e.key === 'Escape') {
        e.preventDefault()
        setValue('')
        return
      }
    }

    if ((e.key === 'ArrowUp' || e.key === 'ArrowDown') && history.length > 0) {
      if (e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return
      const direction = e.key === 'ArrowUp' ? 1 : -1
      const canEnterHistory = e.key === 'ArrowUp' && value.length === 0 && historyIndex === -1
      const inHistory = historyIndex >= 0
      if (canEnterHistory || inHistory) {
        e.preventDefault()
        const nextIndex = canEnterHistory ? 0 : historyIndex + direction
        if (nextIndex < 0) {
          setHistoryIndex(-1)
          setValue('')
          setShellMode(false)
          setMentionRange(null)
          setSnippetRange(null)
          requestAnimationFrame(resize)
          return
        }
        if (nextIndex >= history.length) return
        const next = history[nextIndex]
        const shellHistoryEntry = next.startsWith('!')
        const nextValue = shellHistoryEntry ? next.slice(1) : next
        setHistoryIndex(nextIndex)
        setShellMode(shellHistoryEntry)
        setValue(nextValue)
        setMentionRange(null)
        setSnippetRange(null)
        requestAnimationFrame(() => {
          const el = textareaRef.current
          el?.setSelectionRange(nextValue.length, nextValue.length)
          resize()
        })
        return
      }
    }

    if (e.key === 'Enter' && !e.shiftKey && !isMobile) {
      e.preventDefault()
      void submit()
    }
  }

  const handleBeforeInput = (e: React.FormEvent<HTMLTextAreaElement>) => {
    if ((e.nativeEvent as InputEvent).inputType !== 'insertLineBreak') return
    if (!slashMenuOpen || selectableSlashCommands.length === 0) return

    e.preventDefault()
    executeSlashCommand(selectableSlashCommands[clampedIndex])
  }

  const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const nextValue = e.target.value
    if (!shellMode && nextValue === '!') {
      setShellMode(true)
      setValue('')
      setHistoryIndex(-1)
      setSlashMenuIndex(0)
      setSnippetMenuIndex(0)
      setMentionMenuIndex(0)
      setMentionRange(null)
      setSnippetRange(null)
      requestAnimationFrame(resize)
      return
    }
    setValue(nextValue)
    setHistoryIndex(-1)
    setSlashMenuIndex(0)
    setSnippetMenuIndex(0)
    setMentionMenuIndex(0)
    // ``selectionStart`` is already at the post-change caret position by the
    // time React fires onChange.
    const caret = e.target.selectionStart ?? nextValue.length
    const next = shellMode ? null : findActiveMention(nextValue, caret)
    if (next) onFileRefsNeeded?.()
    setMentionRange(next)
    setSnippetRange(next || shellMode ? null : findActiveSnippet(nextValue, caret))
    resize()
  }

  const hasText = value.trim().length > 0 || Boolean(quoteContext)
  const hasFiles = files.length > 0
  const canSend = (hasText || hasFiles) && !disabled && !submitting
  const canStop = isStreaming && !disabled && onStop != null
  const charCount = value.length + (quoteContext?.length ?? 0)
  const showCharCount = charCount > CHAR_WARN_THRESHOLD

  // Surface "has uncommitted content" to the parent so a minimized bar
  // can re-expand when the user attaches a file via the slim strip.
  // Edge-triggered on the boolean — not on the underlying length values —
  // so we only re-render the parent when crossing 0↔1.
  const hasContent = hasText || shellMode || hasFiles
  const lastHasContentRef = useRef(hasContent)
  useEffect(() => {
    if (lastHasContentRef.current !== hasContent) {
      lastHasContentRef.current = hasContent
      onHasContentChange?.(hasContent)
    }
  }, [hasContent, onHasContentChange])

  // Single-row, horizontally scrollable list so many attachments don't push
  // the input off-screen vertically. The strip owns its own scroll-position
  // hint (matches pencil's MultiAttachOverflow `attachmentScrollHint`).
  const filePreviewStrip = (
    <FilePreviewStrip
      files={files}
      blobUrls={blobUrls}
      onRemove={removeFile}
      filesBelow={filesBelow}
    />
  )

  const actionBtnClass = cn(
    'flex shrink-0 items-center justify-center text-(--color-text-muted) outline-none transition-[background-color,color,transform] hover:bg-(--bg-key) hover:text-(--color-text) active:translate-y-px focus-visible:ring-2 focus-visible:ring-(--color-accent)/30 disabled:cursor-not-allowed disabled:opacity-50',
    isMobile
      ? 'h-8 w-8 rounded-full border border-(--color-border) bg-(--color-surface)'
      : 'h-7 w-7 rounded-[7px] bg-transparent',
  )
  const shellBtnClass = shellMode
    ? cn(
        'flex h-8 shrink-0 items-center gap-1.5 border border-(--color-accent) bg-(--bg-key) px-3 font-mono text-xs text-(--color-text) outline-none transition-colors hover:bg-(--color-surface) focus-visible:ring-2 focus-visible:ring-(--color-accent)/30 disabled:cursor-not-allowed disabled:opacity-50',
        isMobile ? 'rounded-full' : 'rounded-[7px]',
      )
    : actionBtnClass

  const todoCount = todos?.length ?? 0
  const finishedTodoCount = todos?.filter(
    (todo) => todo.status === 'completed' || todo.status === 'cancelled',
  ).length ?? 0
  const activeTodoIndex = todos?.findIndex((todo) => todo.status === 'in_progress') ?? -1
  const pendingTodoIndex = todos?.findIndex((todo) => todo.status === 'pending') ?? -1
  const currentTodoIndex = activeTodoIndex >= 0
    ? activeTodoIndex
    : pendingTodoIndex >= 0
      ? pendingTodoIndex
      : Math.max(todoCount - 1, 0)
  const currentTodoStep = todoCount > 0 ? currentTodoIndex + 1 : 0
  const allTodosFinished = todoCount > 0 && finishedTodoCount === todoCount
  const showTodoProgress = todoCount > 0 && (!allTodosFinished || isStreaming)
  const showTodosPopover = todosOpen && showTodoProgress

  // Three states share one DOM tree: minimized, single-line, multi-line.
  // Multi-line is triggered by the slot's flex-basis:100% which wraps the
  // row so action buttons land on the line below — no DOM reordering.
  const handleExpand = () => {
    onUnminimize?.()
  }
  const stopClick = (e: React.MouseEvent) => e.stopPropagation()

  const attachEl = (
    <button
      type="button"
      onClick={(e) => { stopClick(e); fileInputRef.current?.click() }}
      disabled={disabled}
      aria-label="Attach file"
      title="Attach file (paste or drag)"
      className={actionBtnClass}
    >
      <Paperclip size={14} aria-hidden="true" />
    </button>
  )

  const chatEl = minimized ? (
    <button
      type="button"
      onClick={(e) => { stopClick(e); handleExpand() }}
      aria-label="Expand input bar"
      title="Click to write"
      className={actionBtnClass}
    >
      <MessageCircle size={14} aria-hidden="true" />
    </button>
  ) : null

  const effectivePlaceholder = shellMode
    ? 'Enter shell command... git status'
    : disabled
      ? 'Waiting for response…'
      : isStreaming
        ? 'Queue a follow-up or /stop…'
        : placeholder

  const activePopupId = mentionMenuOpen ? mentionMenuId : snippetMenuOpen ? snippetMenuId : slashMenuOpen ? slashMenuId : undefined
  const activeOptionId = mentionMenuOpen
    ? `${mentionMenuId}-option-${clampedMentionIndex}`
    : snippetMenuOpen
      ? `${snippetMenuId}-option-${clampedSnippetIndex}`
    : slashMenuOpen
      ? `${slashMenuId}-option-${clampedIndex}`
      : undefined

  const sendOrStopEl = canStop && !hasText ? (
    <button
      type="button"
      onClick={(e) => { stopClick(e); onStop?.() }}
      aria-label="Stop generation"
      className={cn(
        'flex shrink-0 items-center justify-center bg-(--color-error) text-(--color-text-on-accent) outline-none transition-[opacity,transform] hover:opacity-90 active:scale-95 focus-visible:ring-2 focus-visible:ring-(--color-error)/40',
        isMobile ? 'h-9 w-9 rounded-full' : 'h-7 w-7 rounded-[7px]',
      )}
    >
      <Square size={13} fill="currentColor" />
    </button>
  ) : (
    <button
      type="button"
      onClick={(e) => { stopClick(e); void submit() }}
      disabled={!canSend}
      aria-label="Send message"
      title={isMobile ? 'Send message' : 'Send (Enter) · New line (Shift+Enter) · Commands (/)'}
      className={cn(
        'flex shrink-0 items-center justify-center outline-none transition-[background-color,color,opacity,transform] active:scale-95 focus-visible:ring-2 focus-visible:ring-(--color-accent)/40',
        isMobile ? 'h-9 w-9 rounded-full' : 'h-7 w-7 rounded-[7px]',
        canSend
          ? 'bg-(--bg-send) text-(--color-text-on-accent) hover:opacity-90'
          : 'cursor-not-allowed bg-(--bg-key) text-(--color-text-muted) opacity-40',
      )}
    >
      {((disabled && !minimized) || submitting) ? (
        <Loader2 size={14} className="animate-spin" aria-hidden="true" />
      ) : (
        <ArrowUp size={15} aria-hidden="true" />
      )}
    </button>
  )

  const composerSkillNames = useMemo(
    () => new Set(
      slashCommands
        .filter((cmd) => cmd.category === 'skill')
        .map((cmd) => (cmd.displayName ?? cmd.id).replace(/^skill:/, '')),
    ),
    [slashCommands],
  )

  // The textarea stays mounted while minimized (opacity + pointer-events
  // toggle) so the ref stays valid and there's no remount flicker.
  const messageSlot = (
    <div
      aria-hidden={minimized}
      className={`flex w-full items-center transition-opacity duration-(--motion-fast) ${
        minimized ? 'pointer-events-none opacity-0' : 'opacity-100'
      }`}
    >
      {/* Position context for the chip overlay. ``relative`` + ``w-full``
          keep the overlay's bounding box equal to the textarea's, so
          chips line up pixel-for-pixel with the text glyphs above them.
          Intentionally not nesting the textarea's props one level deeper —
          keeps the diff against the prior version minimal. */}
      <div className="relative w-full">
      <MentionOverlay
        value={value}
        activeRange={mentionRange}
        textareaRef={textareaRef}
        fileRefs={fileRefs}
        skillNames={composerSkillNames}
      />
      <textarea
        ref={setTextareaRef}
        value={value}
        onBeforeInput={handleBeforeInput}
        onChange={handleChange}
        onKeyDown={handleKeyDown}
        // Caret-only moves (arrow keys, Home/End) don't fire onChange but
        // they can land the caret inside an existing `@token`. ``onSelect``
        // is the React-supported event that fires on selection / caret
        // moves and works in jsdom (used by our tests), so it's the
        // right hook for keeping the picker in sync.
        onSelect={syncMention}
        onClick={syncMention}
        onPaste={handlePaste}
        onFocus={(e) => {
          onFocus?.()
          if (!shellMode && findActiveMention(value, e.currentTarget.selectionStart ?? value.length)) onFileRefsNeeded?.()
        }}
        onBlur={() => {
          const canMinimize = value.trim().length === 0 && files.length === 0
          onBlur?.(canMinimize)
          // Close the picker on blur — clicks on its items use ``onMouseDown``
          // with ``preventDefault`` (see below) so they fire before the
          // textarea blurs and the menu still gets to commit its choice.
          setMentionRange(null)
        }}
        disabled={disabled || minimized}
        placeholder={minimized ? '' : effectivePlaceholder}
        rows={1}
        autoFocus={autoFocus}
        tabIndex={minimized ? -1 : 0}
        // ``p-0`` zeroes WebKit's asymmetric default textarea padding (WKWebView
        // in the macOS Tauri shell ships ~2px top + ~1px bottom that bias the
        // single-line baseline upward). ``align-middle`` keeps the textarea's
        // bounding box centred in the flex row instead of sitting on the
        // baseline of adjacent inline-block buttons. Together they make the
        // placeholder sit vertically centred against the 28px action buttons
        // both in Chrome (web build) and WKWebView (desktop build).
        //
        // ``text-transparent`` + ``caret-color`` hides the textarea's own
        // glyphs so the syntax-highlight overlay (``MentionOverlay``) is
        // the one painting visible text. The caret stays visible. The
        // placeholder is exempt from ``text-transparent`` — it's owned by
        // ``::placeholder`` and ``placeholder-(--color-text-subtle)``
        // keeps it readable.
        // ``scrollbar-none`` hides the textarea's own scrollbar. Without it,
        // the textarea grows a ~15px-wide vertical scrollbar once content
        // exceeds ``maxHeight``, which narrows its inner text-width and makes
        // it wrap a few characters earlier than the overlay mirror (which
        // has no scrollbar). The wrap-point drift is invisible while typing
        // but the native spellcheck squiggle is anchored to textarea text
        // positions, so it ends up under the wrong overlay word and drifts
        // further with every scroll. The wrapper around the overlay handles
        // overflow via the overlay's ``overflow-hidden`` + scroll sync.
        className="block w-full resize-none scrollbar-none bg-transparent p-0 align-middle text-sm leading-relaxed break-words text-transparent caret-(--color-text) placeholder-(--color-text-subtle) selection:bg-(--color-accent)/30 selection:text-(--color-text) focus:outline-none disabled:opacity-50"
        // Cap matches the ``resize()`` ceiling above so the JS-driven height
        // and the CSS limit stay in lockstep.
        style={{ maxHeight: '120px' }}
        // Spellcheck disabled: the squiggle is painted by the browser under
        // the textarea's own glyphs, but the visible text comes from the
        // overlay mirror. Even with identical font/wrap/scroll the two
        // text-layout paths drift by 1–2px, leaving the squiggle a word
        // off. Same call Discord/Slack/ChatGPT make for the same reason.
        spellCheck={false}
        aria-label={shellMode ? 'Shell command input' : 'Message input'}
        aria-expanded={mentionMenuOpen || snippetMenuOpen || slashMenuOpen}
        aria-controls={activePopupId}
        aria-activedescendant={activeOptionId}
      />
      </div>
    </div>
  )

  return (
    <div className={floating ? '' : 'bg-(--bg-page) px-4 pb-5 pt-3'}>
      <div className={floating ? 'relative' : 'relative mx-auto max-w-4xl'}>
        {!minimized && !filesBelow && files.length > 0 && (
          <div>{filePreviewStrip}</div>
        )}

        {!minimized && slashMenuOpen && (
          <div
            id={slashMenuId}
            role="listbox"
            aria-label="Slash commands"
            className="absolute bottom-full left-0 right-0 z-(--z-panel) mb-1 max-h-64 overflow-y-auto rounded-lg bg-(--color-surface)"
          >
              {filteredSlashCommands.map((cmd) => {
                if (cmd.isSeparator) {
                  return (
                    <div
                      key={cmd.id}
                      className="px-3 pt-3 pb-1 text-xs font-semibold uppercase tracking-wide text-(--color-text-muted)"
                    >
                      {cmd.label}
                    </div>
                  )
                }

                const idx = selectableSlashCommands.findIndex((item) => item.id === cmd.id)
                const active = idx === clampedIndex
                const displayName = cmd.displayName ?? cmd.id
                const colon = displayName.indexOf(':')
                const prefix = colon === -1 ? '' : displayName.slice(0, colon + 1)
                const suffix = colon === -1 ? displayName : displayName.slice(colon + 1)

                return (
                  <button
                    key={cmd.id}
                    id={`${slashMenuId}-option-${idx}`}
                    role="option"
                    aria-selected={active}
                    ref={(node) => { slashOptionRefs.current[idx] = node }}
                    onMouseDown={(e) => { e.preventDefault(); executeSlashCommand(cmd) }}
                    className={`flex w-full items-center gap-3 px-3 py-2 text-left text-sm transition-colors ${
                      active
                        ? 'bg-(--bg-key) text-(--color-text)'
                        : 'text-(--color-text-muted) hover:bg-(--bg-key)'
                    }`}
                  >
                    <span className="shrink-0 font-mono text-xs text-(--color-accent)">
                      /
                      {prefix && <span className="text-(--color-text-muted)">{prefix}</span>}
                      <span>{suffix}</span>
                    </span>
                    <span className="min-w-0 flex-1 truncate text-(--color-text-2)">
                      {cmd.description}
                    </span>
                    {cmd.category && (
                      <span className="shrink-0 rounded-md bg-(--bg-key) px-1.5 py-0.5 font-mono text-xs text-(--color-text-muted) ring-1 ring-(--color-border)">
                        {cmd.category}
                      </span>
                    )}
                  </button>
                )
              })}
          </div>
        )}

        {!minimized && snippetMenuOpen && filteredSnippetCommands.length > 0 && (
          <div
            id={snippetMenuId}
            role="listbox"
            aria-label="Snippets"
            className="absolute bottom-full left-0 right-0 z-(--z-panel) mb-1 max-h-64 overflow-y-auto rounded-lg border border-(--color-border-strong) bg-(--color-surface)"
          >
            {filteredSnippetCommands.map((cmd, idx) => {
              const active = idx === clampedSnippetIndex
              return (
                <button
                  key={cmd.id}
                  id={`${snippetMenuId}-option-${idx}`}
                  ref={(node) => { snippetOptionRefs.current[idx] = node }}
                  role="option"
                  aria-selected={active}
                  onMouseDown={(e) => { e.preventDefault(); void insertSnippet(cmd) }}
                  className={`flex w-full items-center gap-3 px-3 py-2 text-left text-sm transition-colors ${
                    active
                      ? 'bg-(--bg-key) text-(--color-text)'
                      : 'text-(--color-text-muted) hover:bg-(--bg-key)'
                  }`}
                >
                  <span className="shrink-0 font-mono text-xs text-(--color-accent)">#{cmd.label}</span>
                  <span className="min-w-0 flex-1 truncate text-(--color-text-2)">{cmd.description}</span>
                  {cmd.category && (
                    <span className="shrink-0 rounded-md bg-(--bg-key) px-1.5 py-0.5 font-mono text-xs text-(--color-text-muted) ring-1 ring-(--color-border)">
                      {cmd.category}
                    </span>
                  )}
                </button>
              )
            })}
          </div>
        )}

        {/* @-mention picker — same visual treatment as the slash menu, but
            scrollable since the workspace can contain hundreds of files. The
            list is capped to MENTION_MAX_RESULTS so the popover stays compact;
            the user narrows the list by typing. */}
        {!minimized && mentionMenuOpen && (
          <div
            id={mentionMenuId}
            role="listbox"
            aria-label="Reference workspace file"
            className="absolute bottom-full left-0 right-0 z-(--z-panel) mb-1 max-h-64 overflow-y-auto rounded-lg border border-(--color-border-strong) bg-(--color-surface)"
          >
            {filteredMentions.map((ref, idx) => {
              const isDir = ref.type === 'directory'
              // Show the basename emphasised, the parent directory dimmed.
              // For a top-level entry (no slash) the whole path is the
              // basename, so there's nothing to dim — display falls back
              // to a single span.
              const slash = ref.path.lastIndexOf('/')
              const parent = slash === -1 ? '' : ref.path.slice(0, slash + 1)
              const basename = slash === -1 ? ref.path : ref.path.slice(slash + 1)
              return (
                <button
                  key={`${ref.type}:${ref.path}`}
                  id={`${mentionMenuId}-option-${idx}`}
                  ref={(node) => { mentionOptionRefs.current[idx] = node }}
                  role="option"
                  aria-selected={idx === clampedMentionIndex}
                  // ``onMouseDown`` + ``preventDefault`` runs before the
                  // textarea's ``onBlur`` clears the picker, so the click
                  // actually reaches our handler.
                  onMouseDown={(e) => { e.preventDefault(); insertMention(ref) }}
                  className={`flex w-full items-center gap-2.5 px-3 py-2 text-left text-sm transition-colors ${
                    idx === clampedMentionIndex
                      ? 'bg-(--bg-key) text-(--color-text)'
                      : 'text-(--color-text-muted) hover:bg-(--bg-key)'
                  }`}
                >
                  {isDir ? (
                    <Folder className="size-4 shrink-0 text-(--color-accent)" aria-hidden />
                  ) : (
                    <File className="size-4 shrink-0 text-(--color-text-subtle)" aria-hidden />
                  )}
                  <span className="min-w-0 flex-1 truncate font-mono text-xs">
                    {parent && (
                      <span className="text-(--color-text-subtle)">{parent}</span>
                    )}
                    <span className="text-(--color-text)">{basename}</span>
                    {isDir && <span className="text-(--color-text-subtle)">/</span>}
                  </span>
                </button>
              )
            })}
          </div>
        )}

        {!minimized && showTodoProgress && (
          <div className="relative z-(--z-panel) mb-2 flex justify-center">
            {showTodosPopover && (
              <div className="absolute bottom-full left-1/2 mb-2 w-[min(30rem,calc(100vw-3rem))] -translate-x-1/2">
                  <div
                    id="composer-task-list"
                    className="overflow-hidden rounded-lg border border-(--color-border)/70 bg-(--bg-card)/78 shadow-lg shadow-black/10 backdrop-blur-2xl"
                  >
                    <TodosList
                      todos={todos ?? []}
                      compact
                      headerClassName="hidden"
                      listClassName="max-h-[min(30vh,12rem)] py-1 opacity-85"
                    />
                  </div>
              </div>
            )}

            <button
              type="button"
              onClick={() => onTodosOpenChange?.(!todosOpen)}
              aria-expanded={todosOpen}
              aria-controls="composer-task-list"
              className={cn(
                'flex h-9 items-center gap-2 rounded-full border border-(--color-border) bg-(--bg-card) px-3.5',
                'text-sm text-(--color-text-muted) outline-none transition-[background-color,border-color,color]',
                'hover:border-(--color-border-strong) hover:bg-(--bg-key) hover:text-(--color-text)',
                'focus-visible:ring-2 focus-visible:ring-(--color-accent)/30',
              )}
              title={todosOpen ? 'Hide task list' : 'Show task list'}
            >
              {allTodosFinished ? (
                <SquareCheck size={15} className="text-(--color-success)" aria-hidden="true" />
              ) : isStreaming ? (
                <Loader2
                  size={15}
                  className="animate-spin text-(--color-info)"
                  aria-hidden="true"
                />
              ) : (
                <ListTodo size={15} className="text-(--color-info)" aria-hidden="true" />
              )}
              <span className="tabular-nums">Step {currentTodoStep} / {todoCount}</span>
              <ChevronDown
                size={14}
                className={cn(
                  'text-(--color-text-subtle) transition-transform duration-(--motion-fast)',
                  todosOpen && 'rotate-180',
                )}
                aria-hidden="true"
              />
            </button>
          </div>
        )}

        {/* Input card — minimized: compact pill · expanded: Gemini-style card */}
        <div className={`relative ${minimized ? 'flex justify-center' : ''}`}>
          {renderDragHandle?.()}
          <div
            onDragEnter={handleDragEnter}
            onDragLeave={handleDragLeave}
            onDragOver={handleDragOver}
            onDrop={handleDrop}
            className={cn(
              'composer-input-card relative block border bg-(--color-surface) transition-[background-color,border-color] duration-(--motion-base)',
              minimized
                ? cn(
                    'w-fit border-(--color-border) p-2 hover:bg-(--bg-key)',
                    isMobile ? 'rounded-2xl' : 'rounded-[20px]',
                  )
                : cn(
                    'w-full border-(--color-border) focus-within:border-(--color-border-strong)',
                    isMobile
                      ? 'rounded-xl'
                      : 'rounded-[20px]',
                  ),
            )}
          >
            {/* ── Minimized: compact action strip ── */}
            {minimized && (
              <div onClick={handleExpand} className="flex items-center gap-2 cursor-text">
                {!shellMode && attachmentsEnabled && attachEl}
                {chatEl}
                <div className="w-0 -ml-2 min-w-0 overflow-hidden">{messageSlot}</div>
                {sendOrStopEl}
              </div>
            )}

            {/* ── Expanded: Gemini-style vertical card ── */}
            {!minimized && (
              <>
                {/* Textarea area */}
                <div className={cn('px-4 pt-3', isMobile ? 'pb-1' : 'pb-2')}>
                  {shellMode && (
                    <div className="mb-2">
                      <button
                        type="button"
                        onClick={(e) => {
                          stopClick(e)
                          setShellMode(false)
                          setMentionRange(null)
                          setSnippetRange(null)
                          requestAnimationFrame(() => textareaRef.current?.focus())
                        }}
                        disabled={disabled}
                        aria-label="Exit shell mode"
                        title="Exit shell mode (Esc)"
                        className={shellBtnClass}
                      >
                        <Terminal size={12} aria-hidden="true" />
                        <span>Shell</span>
                      </button>
                    </div>
                  )}
                  {quoteContext && (
                    <div className="mb-2 flex min-w-0 items-start gap-2 rounded-lg border border-(--color-border-subtle) bg-(--bg-key) px-2.5 py-2">
                      <Quote
                        size={13}
                        className="mt-0.5 shrink-0 text-(--color-text-muted)"
                        aria-hidden="true"
                      />
                      <div className="min-w-0 flex-1">
                        <p className="text-[11px] font-medium text-(--color-text-muted)">
                          Selected from chat
                        </p>
                        <p
                          className="mt-0.5 line-clamp-2 text-xs leading-relaxed break-words whitespace-pre-wrap text-(--color-text-2) [overflow-wrap:anywhere]"
                          title={quoteContext}
                        >
                          {quoteContext}
                        </p>
                      </div>
                      <button
                        type="button"
                        onClick={() => {
                          setQuoteContext(null)
                          textareaRef.current?.focus()
                        }}
                        aria-label="Remove selected chat context"
                        title="Remove context"
                        className="flex size-6 shrink-0 items-center justify-center rounded-md text-(--color-text-muted) outline-none transition-colors hover:bg-(--color-surface) hover:text-(--color-text) focus-visible:ring-2 focus-visible:ring-(--color-accent)/30"
                      >
                        <X size={13} aria-hidden="true" />
                      </button>
                    </div>
                  )}
                  {messageSlot}
                </div>

                {/* Bottom action bar — action buttons left · config selectors right · send. */}
                <div
                  className={cn(
                    'composer-toolbar flex min-w-0 flex-nowrap items-center gap-1.5',
                    isMobile
                      ? 'px-3 pb-3 pt-1'
                      : 'min-h-9 px-2.5 pb-2 pt-0',
                  )}
                >
                  <div className="composer-toolbar-primary flex min-w-0 items-center gap-1.5">
                    {/* Left: content & navigation actions */}
                    {!shellMode && attachmentsEnabled && attachEl}
                    {/* Wiki moved to topbar */}
                    {onActivity && (
                      <button
                        type="button"
                        onClick={(e) => { stopClick(e); onActivity() }}
                        aria-label="Team activity log"
                        title="Team activity log"
                        className={cn(actionBtnClass, activityActive && 'bg-(--bg-key) text-(--color-text)')}
                      >
                        <Activity size={14} aria-hidden="true" />
                      </button>
                    )}
                    {workspaceSelector}
                  </div>

                  {/* Right: session config selectors */}
                  <div className="composer-toolbar-secondary ml-auto flex shrink-0 items-center gap-1.5">
                    {onSessionModelSettingsChange && (
                      <SessionPillsRow
                        sessionModel={sessionModel}
                        defaultModel={defaultModel}
                        sessionThinkingLevel={sessionThinkingLevel}
                        sessionFastMode={sessionFastMode}
                        onSessionModelSettingsChange={onSessionModelSettingsChange}
                        agentNames={agentNames}
                        workspace={agentWorkspace}
                        mode={agentMode}
                      />
                    )}
                    {permissionMode && onPermissionModeChange && (
                      <ModeSelector
                        mode={permissionMode}
                        onModeChange={onPermissionModeChange}
                      />
                    )}
                    {showCharCount && (
                      <span
                        className={`shrink-0 font-mono text-xs ${
                          charCount > 2000 ? 'text-(--color-error)' : 'text-(--color-text-muted)'
                        }`}
                      >
                        {charCount}
                      </span>
                    )}
                    {sendOrStopEl}
                  </div>
                </div>
              </>
            )}
          </div>
        </div>

        {!minimized && filesBelow && files.length > 0 && (
          <div>{filePreviewStrip}</div>
        )}

        {attachmentsEnabled && (
          <input
            ref={fileInputRef}
            type="file"
            multiple
            onChange={handleFileSelect}
            className="hidden"
            aria-hidden="true"
          />
        )}
      </div>
    </div>
  )
})
