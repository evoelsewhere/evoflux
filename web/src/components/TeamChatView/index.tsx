/**
 * TeamChatView — top-level layout for the team chat route.
 *
 * Owns:
 *   - View-mode state (``agent`` / ``split``).
 *   - Side panels (``Sidebar``, ``WorkspaceFilesPanel``, ``SessionSettingsPanel``,
 *     inline task list, command palette).
 *   - The header (token totals, view toggle, panel toggles, agent tabs).
 *   - Mount-time SSE connect + session restore (carefully sequenced so
 *     ``loadSession`` runs *before* ``connectStream`` to avoid wiping
 *     replayed mid-turn state — see comment inside the init effect).
 *   - Keyboard shortcuts and the Command Palette assembly.
 *
 * Delegates:
 *   - ``SplitGrid``       — fixed n-pane grid layout (split mode).
 *   - ``useTeamCommands`` — Command Palette command list.
 *
 * Stream subscriptions are split into the smallest selectors that work
 * (one primitive per ``useTeamStore`` call) to avoid the infinite loop
 * that returning a freshly-built object on every render would trigger.
 */
import { useEffect, useMemo, useRef, useState, useCallback } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { useNavigate } from '@tanstack/react-router'
import { useQueryClient } from '@tanstack/react-query'
import { SessionSettingsPanel } from '../SessionSettingsPanel'
import { AgentView } from '../AgentView'
import { WorkspaceInfoCard } from '../WorkspaceInfoCard'
import { ProjectInfoCard } from '../ProjectInfoCard'
import { useProjectQuery } from '@/queries/useProjectsQuery'
import { CodingSidebar } from '../CodingSidebar'
import { CodingWorkspacePanel } from '../CodingWorkspacePanel'
import { CodingFileViewerPanel } from '../CodingFileViewerPanel'
import { Sidebar } from '../Sidebar'
import { CommandPalette } from '../CommandPalette'
import { WorkspaceFilesPanel } from '../WorkspaceFilesPanel'
import { WikiPanel } from '../WikiPanel'
import { SchedulerPanel } from '../SchedulerPanel'
import { SessionScheduleIndicator } from '../SessionScheduleIndicator'
import { ActivityPanel } from '../ActivityPanel'
import { BrowserViewer } from '../BrowserViewer'
import { PlanApprovalModal } from '../PlanApprovalModal'
import { PermissionApprovalModal } from '../PermissionApprovalModal'
import { AskUserQuestionModal } from '../AskUserQuestionModal'
import { MonitorView } from '../MonitorView'
import { useTodosQuery } from '@/queries/useTodosQuery'
import { useSessionChapters } from '@/hooks/useSessionChapters'
import { SessionTOC } from '@/components/SessionTOC'
import { useProvidersQuery, useRegistryQuery, useTriggerDreamMutation } from '@/queries'
import { useCommandsQuery } from '@/queries/useCommandsQuery'
import { useSnippetsQuery } from '@/queries/useSnippetsQuery'
import { renderCommand, renderSnippet, resolveApiUrl, resolveTeamSession, setSessionPermissionMode, getTeamSession } from '@/api/client'
import { useShallow } from 'zustand/react/shallow'
import { useTeamStore } from '@/stores/useTeamStore'
import { useToastStore } from '@/stores/useToastStore'
import { prependSession, prependWorkspaceSession } from '@/stores/cache-invalidation-bridge'
import { useUIStore } from '@/stores/useUIStore'
import { useKeyboardShortcuts } from '@/hooks/useKeyboardShortcuts'
import { useTeamAgentsQuery } from '@/queries/useAgentsQuery'
import { useFileRefsQuery } from '@/queries/useFileRefsQuery'
import { AlertCircle, Brain, CalendarClock, Check, ChevronDown, FolderOpen, FolderCode, Menu, Minimize2, MoreHorizontal, PanelLeft, SlidersHorizontal, X } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { useIsMobile } from '@/hooks/use-mobile'
import { usePlatform } from '@/hooks/use-platform'
import { useTauriDrag } from '@/hooks/use-tauri-drag'
import { useWorkspaceFileWatcher } from '@/hooks/useWorkspaceFileWatcher'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { isAgentRole, type AgentRole } from '@/lib/agent-roles'
import type { ActiveLoop, AgentStream, LoopTurnSummary } from '@/stores/useTeamStore'
import { AgentTopbar } from '@/components/AgentTopbar'
import { formatTokens } from '@/utils/format'
import { TaskProgressPill } from '@/components/TaskProgressPill'
import { type InputBarHandle, type SlashCommand, type SnippetCommand } from '../InputBar'
import { FloatingInputBar } from '../FloatingInputBar'
import type { AgentCapabilities as AgentCapabilitiesType, MessageAttachment, WorkspaceFileInfo } from '@/api/types'
import { SplitGrid } from './SplitGrid'
import { useTeamCommands } from './useTeamCommands'
import { VIEW_MODES, type ViewMode } from './types'
import { codingFocusId, saveLastCodingWorkspace, workspaceLabel } from '@/utils/workspace'
import { TokenMeter } from '@/components/ui/token-meter'
import { setTraySession } from '@/lib/tray'
import { parseLoopCommand } from '@/lib/parseLoopCommand'

interface TeamChatViewProps {
  sessionId?: string
  mode?: 'forge' | 'coding'
  workspace?: string | null
  codingSessionLoading?: boolean
}

type AgentStatus = AgentStream['status']

// Stable fallbacks so narrowed selectors below never return a fresh
// reference when the underlying stream field is absent.
const EMPTY_AGENT_STREAMS: Record<string, AgentStream> = {}
const EMPTY_BLOCKS: AgentStream['blocks'] = []
const EMPTY_REVERTED_MESSAGES: Array<{ role: string; content: string }> = []

async function attachmentToFile(att: MessageAttachment): Promise<File | null> {
  const url = resolveApiUrl(att.url)
  if (!url) return null
  const res = await fetch(url)
  if (!res.ok) return null
  const blob = await res.blob()
  return new File(
    [blob],
    att.original_name ?? att.filename ?? 'attachment',
    { type: att.media_type ?? blob.type },
  )
}

export function TeamChatView({ sessionId, mode = 'forge', workspace = null, codingSessionLoading = false }: TeamChatViewProps) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const isMobile = useIsMobile()
  const { isMacOverlay, os } = usePlatform()
  // Manual drag pattern: a mousedown handler that only starts a drag
  // when the user pressed on the bare header, not on a child button.
  // The hook returns `{}` outside Tauri so the spread is a no-op in
  // browsers. See ``useTauriDrag`` for details.
  const dragHandlers = useTauriDrag()
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false)
  const inputRef = useRef<InputBarHandle>(null)
  const mainColumnRef = useRef<HTMLDivElement>(null)
  const mobileSidebarSwipeStartRef = useRef<{ x: number; y: number } | null>(null)
  const mobileActionsSwipeStartRef = useRef<{ x: number; y: number } | null>(null)
  const [showFilesPanel, setShowFilesPanel] = useState(false)
  const [codingPanel, setCodingPanel] = useState<null | 'changed' | 'files'>(null)
  const [codingFileViewer, setCodingFileViewer] = useState<WorkspaceFileInfo | null>(null)
  // Coding-mode sidebar is expanded by default so it's always visible on entry.
  const [codingSidebarCollapsed, setCodingSidebarCollapsed] = useState(false)
  const [openWorkspaceDialogKey, setOpenWorkspaceDialogKey] = useState(0)
  const [showTodos, setShowTodos] = useState(false)
  const [showActivity, setShowActivity] = useState(false)
  const [permissionMode, setPermissionMode] = useState<import('@/api/types').PermissionMode>('auto')
  const [showMobileActions, setShowMobileActions] = useState(false)
  const [showPalette, setShowPalette] = useState(false)
  const [fileRefsEnabled, setFileRefsEnabled] = useState(false)
  const [viewMode, setViewMode] = useState<ViewMode>('agent')

  // On mobile, always force agent view — split/monitor require a wide screen.
  // Also close any desktop-only panels when shrinking to mobile.
  const effectiveViewMode: ViewMode = isMobile ? 'agent' : viewMode
  useEffect(() => {
    setCodingFileViewer(null)
  }, [workspace])

  useEffect(() => {
    if (isMobile) {
      useUIStore.getState().closeAgentCapabilities()
      setShowFilesPanel(false)
    }
  }, [isMobile])

  const connectStream  = useTeamStore((s) => s.connectStream)
  const loadTeamStatus = useTeamStore((s) => s.loadTeamStatus)
  const loadSession    = useTeamStore((s) => s.loadSession)
  const sendMessage    = useTeamStore((s) => s.sendMessage)
  const continueTeam   = useTeamStore((s) => s.continueTeam)
  const beginResolvedSession = useTeamStore((s) => s.beginResolvedSession)
  const consumeResolvedSessionReady = useTeamStore((s) => s.consumeResolvedSessionReady)
  const cycleActiveAgent = useTeamStore((s) => s.cycleActiveAgent)
  const setActiveAgent   = useTeamStore((s) => s.setActiveAgent)
  const setSessionModelSettings = useTeamStore((s) => s.setSessionModelSettings)
  const setupRequired = useTeamStore((s) => s.setupRequired)
  const dismissSetupRequired = useTeamStore((s) => s.dismissSetupRequired)

  const dreamMutation = useTriggerDreamMutation()
  const pushToast = useToastStore((s) => s.push)

  const activeAgent    = useTeamStore((s) => s.activeAgent)
  const agentNames     = useTeamStore((s) => s.agentNames)
  const isTeamWorking  = useTeamStore((s) => s.isTeamWorking)
  const isContinuing   = useTeamStore((s) => s.isContinuing)
  const sessionIdState = useTeamStore((s) => s.sessionId)
  const projectIdState = useTeamStore((s) => s.projectId)
  // A project session isn't "in" any one repo — chat-level UI (empty state,
  // composer placeholder) must reflect the project, not the primary repo
  // path (`workspace`) the backend happens to derive for the agent's cwd.
  const activeProjectQuery = useProjectQuery(projectIdState)
  const activeProject = activeProjectQuery.data ?? null
  // Single source of truth for "what is this coding session about" wherever
  // the UI needs a short identity label (tray, mobile header, action sheet,
  // composer placeholder) — project name when project-scoped, else the repo.
  const codingIdentityLabel =
    mode === 'coding' && workspace
      ? projectIdState
        ? activeProject?.name ?? 'Project…'
        : workspaceLabel(workspace)
      : null
  const sessionTitle   = useTeamStore((s) => s.sessionTitle)
  const sessionModel   = useTeamStore((s) => s.sessionModel)
  const sessionThinkingLevel = useTeamStore((s) => s.sessionThinkingLevel)
  const sessionFastMode = useTeamStore((s) => s.sessionFastMode)
  const leadName       = useTeamStore((s) => s.leadName)
  const activeLoop     = useTeamStore((s) => s.activeLoop)
  const isConnected    = useTeamStore((s) => s.isConnected)
  const isSessionLoading = useTeamStore((s) => s.isSessionLoading)
  const promptSuggestions = useTeamStore((s) => s.promptSuggestions)

  // Utility modal state lives in useUIStore so only one can be open at a time.
  const wikiOpen = useUIStore((s) => s.wikiOpen)
  const schedulerOpen = useUIStore((s) => s.schedulerOpen)
  const agentCapabilitiesOpen = useUIStore((s) => s.agentCapabilitiesOpen)
  const browserOpen = useUIStore((s) => s.browserOpen)
  const toggleWiki = useUIStore((s) => s.toggleWiki)
  const toggleScheduler = useUIStore((s) => s.toggleScheduler)
  const toggleAgentCapabilities = useUIStore((s) => s.toggleAgentCapabilities)
  const closeWiki = useUIStore((s) => s.closeWiki)
  const closeScheduler = useUIStore((s) => s.closeScheduler)
  const closeAgentCapabilities = useUIStore((s) => s.closeAgentCapabilities)
  const closeBrowser = useUIStore((s) => s.closeBrowser)

  // Subscribe to active-agent stream fields directly to avoid recomputing on
  // every other agent's tick.
  const activeBlocks        = useTeamStore((s) => s.activeAgent ? s.agentStreams[s.activeAgent]?.blocks : undefined)
  const activeCurrentBlocks = useTeamStore((s) => s.activeAgent ? s.agentStreams[s.activeAgent]?.currentBlocks : undefined)
  const activeStatus        = useTeamStore((s) => s.activeAgent ? s.agentStreams[s.activeAgent]?.status : undefined)
  const activeLastError     = useTeamStore((s) => s.activeAgent ? s.agentStreams[s.activeAgent]?.lastError : undefined)
  const hasActiveStream     = useTeamStore((s) => Boolean(s.activeAgent && s.agentStreams[s.activeAgent]))

  // Per-purpose narrowed subscriptions — the full ``agentStreams`` map gets a
  // new reference on every streamed token, so subscribing to it wholesale
  // re-rendered this entire shell per SSE event. ``useShallow`` keeps the
  // derived array/object identities stable while statuses are unchanged.
  const splitAgentNames = useTeamStore(useShallow(
    (s) => s.agentNames.filter((name) => s.agentStreams[name]?.status !== 'offline'),
  ))
  const agentStatuses = useTeamStore(useShallow((s) => {
    const statuses: Record<string, AgentStatus | undefined> = {}
    for (const name of s.agentNames) statuses[name] = s.agentStreams[name]?.status
    return statuses
  }))
  // Only monitor/split views render every agent's stream — gate the
  // whole-map subscription on the view mode so the default agent view
  // stops re-rendering this shell on every token of every agent.
  const gridAgentStreams = useTeamStore((s) =>
    effectiveViewMode === 'split' || effectiveViewMode === 'monitor' ? s.agentStreams : null,
  )
  // Finalized lead blocks only change on turn boundaries — not per token.
  const leadBlocks = useTeamStore((s) => (s.leadName ? s.agentStreams[s.leadName]?.blocks : undefined))
  const leadRevertedCount = useTeamStore((s) => (s.leadName ? s.agentStreams[s.leadName]?.revertedCount ?? 0 : 0))
  const leadRevertedMessages = useTeamStore(
    (s) => (s.leadName ? s.agentStreams[s.leadName]?.revertedMessages ?? EMPTY_REVERTED_MESSAGES : EMPTY_REVERTED_MESSAGES),
  )
  const historyPrompts = useMemo(() => {
    if (!leadBlocks) return []
    return [...leadBlocks]
      .reverse()
      .filter((block) => block.type === 'user' && block.content.trim())
      .map((block) => block.content)
  }, [leadBlocks])

  const { data: todosData } = useTodosQuery(sessionIdState)
  const todos = todosData?.todos ?? []
  const prevTodosLen = useRef(todos.length)
  useEffect(() => {
    if (prevTodosLen.current === 0 && todos.length > 0) setShowTodos(true)
    if (todos.length === 0) setShowTodos(false)
    prevTodosLen.current = todos.length
  }, [todos.length])
  const { data: chapters = [] } = useSessionChapters(sessionIdState)
  const providersQ = useProvidersQuery()
  const hasConfiguredModelProvider = providersQ.data?.providers.some(
    (provider) => provider.kind !== 'local' && provider.is_configured,
  ) ?? true

  // Lead capabilities — used to drive composer affordances (slash menu).
  const agentWorkspace = mode === 'coding' ? workspace : null
  const hasCodingWorkspace = mode !== 'coding' || Boolean(workspace)
  const isCodingSessionLoading = mode === 'coding' && codingSessionLoading

  // Watch workspace for external file changes (other editors, git, etc.)
  useWorkspaceFileWatcher(agentWorkspace)
  const { data: teamAgentsData, isLoading: teamAgentsLoading } = useTeamAgentsQuery(agentWorkspace, hasCodingWorkspace)
  const leadAgent = teamAgentsData?.agents?.find((a) => a.is_lead)
  const leadCapabilities: AgentCapabilitiesType | undefined = leadAgent?.capabilities
  const selectedModel = sessionModel ?? ''
  const summaryTriggerTokens = leadAgent?.summary_trigger_tokens
  const selectedThinkingLevel = sessionThinkingLevel ?? ''

  // When the user selects a session model override, derive capabilities from
  // the model registry so file-upload affordances match the selected model.
  // Also used as fallback when the team hasn't started yet (leadCapabilities
  // is undefined) but we know which model will be used.
  const registryQ = useRegistryQuery()
  const effectiveCapabilities: AgentCapabilitiesType | undefined = useMemo(() => {
    const modelToLookup = sessionModel || (leadCapabilities ? null : leadAgent?.model)
    if (!modelToLookup || !registryQ.data) return leadCapabilities
    const entry = registryQ.data.models.find((m) => m.id === modelToLookup)
    if (!entry) return leadCapabilities
    return {
      input: {
        vision: entry.vision,
        document_text: leadCapabilities?.input.document_text ?? true,
        audio: entry.input_audio ?? false,
        video: entry.input_video ?? false,
      },
      output: {
        text: leadCapabilities?.output.text ?? true,
        image: entry.output_image,
        audio: leadCapabilities?.output.audio ?? false,
      },
    }
  }, [sessionModel, registryQ.data, leadCapabilities, leadAgent?.model])

  // Workspace file/folder list for the InputBar's @-mention picker. Fetched
  // lazily — the query is keyed on workspace/session so coding and normal
  // modes don't share cache entries.
  const { refs: fileRefs } = useFileRefsQuery({
    mode,
    sessionId: sessionIdState,
    workspace,
    enabled: fileRefsEnabled && (mode === 'coding' ? Boolean(workspace) : Boolean(sessionIdState)),
  })

  // Sum tokens — four primitive selectors, no new object returned (avoids infinite loop).
  const totalPrompt     = useTeamStore((s) => Object.values(s.agentStreams).reduce((n, st) => n + st.usage.promptTokens, 0))
  const totalCompletion = useTeamStore((s) => Object.values(s.agentStreams).reduce((n, st) => n + st.usage.completionTokens, 0))
  const totalCached     = useTeamStore((s) => Object.values(s.agentStreams).reduce((n, st) => n + st.usage.cachedTokens, 0))
  const totalAll        = useTeamStore((s) => Object.values(s.agentStreams).reduce((n, st) => n + st.usage.totalTokens, 0))
  // Live context-window occupancy = latest-turn input (+ cached), which is what
  // the summarization threshold actually compares against. Cumulative
  // totalTokens grows with completion tokens across turns and would falsely
  // push the budget bar toward 100% on long sessions.
  const contextUsed = totalPrompt + totalCached
  const headerTokens = totalAll > 0
    ? {
        input: totalPrompt,
        output: totalCompletion,
        cached: totalCached,
        trigger: summaryTriggerTokens,
        pulsing: isTeamWorking,
      }
    : undefined

  const abortRef = useRef<AbortController | null>(null)

  // ── Init / reconnect ───────────────────────────────────────────────────────

  useEffect(() => {
    if (hasCodingWorkspace) loadTeamStatus(agentWorkspace)
    if (isCodingSessionLoading) return
    if (!sessionId) return
    const store = useTeamStore.getState()
    if (store.sessionId === sessionId && store.isConnected) return

    // Reset (not just re-point) on every genuine switch — a bare
    // `setState({ sessionId })` left `isConnected`/`agentStreams` holding
    // the PREVIOUS session's data, so the skeleton below (gated on
    // `sessionId && !isConnected`) never got a chance to render: the old
    // session's stale messages kept showing with no loading feedback while
    // `loadSession` fetched the new one in the background.
    beginResolvedSession(sessionId, { mode, workspace: agentWorkspace })

    // Clear the composer when switching sessions. The InputBar holds its
    // draft text and pending files in local state, so without an explicit
    // reset session A's typed-but-unsent message bleeds into session B.
    inputRef.current?.setValue('')
    inputRef.current?.setFiles([])

    // Order matters: load prior-turn history FIRST, then open the SSE.
    //
    // Before this ordering, `connectStream()` started SSE replay (which
    // writes synthetic thinking/message events into `currentBlocks`)
    // while `loadSession()` was still inflight. When `loadSession`
    // resolved it unconditionally set `currentBlocks = []`, wiping the
    // replayed state. On mid-turn refresh the UI looked blank until the
    // next live chunk arrived — often until `done`.
    //
    // Awaiting the DB read first means `loadSession` has already committed
    // `blocks` and emptied `currentBlocks` by the time any SSE event is
    // dispatched, so replay + live events accumulate cleanly.
    let cancelled = false
    ;(async () => {
      if (!consumeResolvedSessionReady(sessionId, agentWorkspace)) {
        await loadSession(sessionId, agentWorkspace)
      }
      if (cancelled) return
      const controller = connectStream()
      if (controller) abortRef.current = controller
    })()

    return () => {
      cancelled = true
      abortRef.current?.abort()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, agentWorkspace, hasCodingWorkspace, isCodingSessionLoading])

  useEffect(() => {
    if (!sessionId) return

    const resumeStream = () => {
      const state = useTeamStore.getState()
      if (state.sessionId !== sessionId) return
      if (state._workspace !== agentWorkspace) return
      if (state.isConnected && !state._unloading) return

      useTeamStore.setState({ _unloading: false })
      if (state.isTeamWorking) {
        void loadSession(sessionId, agentWorkspace).then(() => {
          const current = useTeamStore.getState()
          if (current.sessionId !== sessionId || current._workspace !== agentWorkspace) return
          abortRef.current = connectStream()
        })
      } else {
        abortRef.current = connectStream()
      }
    }

    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') resumeStream()
    }

    window.addEventListener('pageshow', resumeStream)
    document.addEventListener('visibilitychange', handleVisibilityChange)
    return () => {
      window.removeEventListener('pageshow', resumeStream)
      document.removeEventListener('visibilitychange', handleVisibilityChange)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, agentWorkspace])

  // ── Commands / shortcuts ───────────────────────────────────────────────────

  const isEmptyIdleSession = useCallback(() => useTeamStore.getState().isEmptyIdleSession(), [])

  const handleNewSession = useCallback(() => {
    if (isEmptyIdleSession()) return
    abortRef.current?.abort()
    abortRef.current = null
    inputRef.current?.setValue('')
    inputRef.current?.setFiles([])
    ;(async () => {
      try {
        const sessionOptions = {
          mode,
          workspace: mode === 'coding' ? workspace : null,
          model: sessionIdState ? sessionModel : null,
          thinkingLevel: sessionIdState ? sessionThinkingLevel : null,
        }
        beginResolvedSession(null, sessionOptions)
        const session = await resolveTeamSession({
          ...sessionOptions,
          create: true,
        })
        beginResolvedSession(session.id, {
          mode,
          workspace: session.workspace ?? workspace,
          model: session.model ?? sessionModel,
          thinkingLevel: session.thinking_level ?? sessionThinkingLevel,
          skipInitialRestore: session.created,
        })
        if (session.created) {
          prependSession(queryClient, session)
        }
        if (mode === 'coding' && workspace) {
          if (session.created) prependWorkspaceSession(queryClient, workspace, session)
          saveLastCodingWorkspace(workspace)
          const focusId = codingFocusId({ project_id: session.project_id, workspace: session.workspace ?? workspace })
          navigate(
            focusId
              ? { to: '/coding/$focusId/$sessionId', params: { focusId, sessionId: session.id } }
              : { to: '/coding' },
          )
        } else {
          navigate({ to: '/$sessionId', params: { sessionId: session.id } })
        }
      } catch (err) {
        useTeamStore.setState((state) => {
          state.error = err instanceof Error ? err.message : 'Failed to create session'
        })
      }
    })()
  }, [beginResolvedSession, isEmptyIdleSession, mode, navigate, queryClient, sessionIdState, sessionModel, sessionThinkingLevel, workspace])

  const handleWorkspaceFiles = useCallback(() => {
    if (mode === 'coding') {
      if (workspace) {
        if (isMobile) setMobileSidebarOpen(false)
        setCodingPanel((value) => {
          const next = value === null ? 'changed' : null
          if (next === null) setCodingFileViewer(null)
          return next
        })
      } else {
        setCodingSidebarCollapsed(false)
        setOpenWorkspaceDialogKey((value) => value + 1)
      }
      return
    }
    if (sessionIdState) setShowFilesPanel((value) => !value)
  }, [isMobile, mode, workspace, sessionIdState])

  const handlePermissionModeChange = useCallback(async (newMode: import('@/api/types').PermissionMode) => {
    setPermissionMode(newMode)
    if (sessionIdState) {
      try {
        await setSessionPermissionMode(sessionIdState, newMode)
      } catch {
        // non-fatal: in-memory mode is already updated; DB sync failed silently
      }
    }
  }, [sessionIdState])

  const handleCodingSidebarToggle = useCallback(() => {
    if (isMobile) {
      setCodingPanel(null)
      setCodingFileViewer(null)
      setMobileSidebarOpen((value) => !value)
      return
    }
    setCodingSidebarCollapsed((value) => !value)
  }, [isMobile])

  const handleOpenWorkspaceDialog = useCallback(() => {
    setCodingSidebarCollapsed(false)
    setOpenWorkspaceDialogKey((value) => value + 1)
  }, [])

  const handleDreamRun = useCallback(() => {
    dreamMutation.mutate(undefined, {
      onSuccess: (result) => {
        if (result.skipped) {
          pushToast({
            tone: 'info',
            title: 'Dream skipped',
            description: `${result.skipped}. ${result.remaining} pending.`,
          })
          return
        }
        const { sessions_processed, notes_processed, remaining } = result
        const processed = sessions_processed + notes_processed
        pushToast({
          tone: 'success',
          title: 'Dream complete',
          description: processed > 0
            ? `${processed} item${processed !== 1 ? 's' : ''} processed. ${remaining} remaining.`
            : `Nothing to process.`,
        })
      },
      onError: (err) => {
        pushToast({
          tone: 'error',
          title: 'Dream failed',
          description: err instanceof Error ? err.message : String(err),
        })
      },
    })
  }, [dreamMutation, pushToast])

  // Focus the chat input. Callable directly (shortcut / Command Palette)
  // or indirectly via `window.dispatchEvent(new CustomEvent('focus-chat-input'))`
  // — the latter decouples future callers (buttons elsewhere, other views)
  // from this component's ref.
  const focusInput = useCallback(() => {
    inputRef.current?.focus()
  }, [])

  useEffect(() => {
    const handler = () => focusInput()
    window.addEventListener('focus-chat-input', handler)
    return () => window.removeEventListener('focus-chat-input', handler)
  }, [focusInput])

  useEffect(() => {
    if (isMobile || showPalette || (mode === 'coding' && (!workspace || isCodingSessionLoading))) return

    const isEditableElement = (target: EventTarget | null) => {
      if (!(target instanceof HTMLElement)) return false
      if (target.isContentEditable) return true
      return target.closest('input, textarea, select, [contenteditable="true"]') !== null
    }

    const handler = (e: KeyboardEvent) => {
      if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey) return
      if (e.key.length !== 1 || e.key.trim().length === 0) return
      if (isEditableElement(e.target)) return
      e.preventDefault()
      inputRef.current?.focus()
      inputRef.current?.insertText(e.key)
    }

    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [isCodingSessionLoading, isMobile, mode, showPalette, workspace])

  const handleAddFileComment = useCallback((path: string, startLine: number, endLine: number) => {
    const ref = startLine === endLine ? `@${path}#L${startLine}` : `@${path}#L${startLine}-L${endLine}`
    inputRef.current?.appendValue(`${ref} `)
    inputRef.current?.focus()
  }, [])

  /** Editor context menu → Chat: user requests an action on selected code */
  const handleSendToChat = useCallback((action: string, code: string, path: string, startLine: number, endLine: number) => {
    const lineRef = startLine === endLine ? `L${startLine}` : `L${startLine}-L${endLine}`
    const prefix = action === 'explain'
      ? `Explain this code from \`${path}#${lineRef}\`:\n`
      : action === 'refactor'
        ? `Refactor this code from \`${path}#${lineRef}\`:\n`
        : action === 'fix'
          ? `Fix this code from \`${path}#${lineRef}\`:\n`
          : `@${path}#${lineRef}\n`
    inputRef.current?.setValue(`${prefix}\`\`\`\n${code}\n\`\`\`\n`)
    inputRef.current?.focus()
  }, [])

  const handleCodingFileSelect = useCallback((file: WorkspaceFileInfo | null) => {
    setCodingFileViewer(file)
    if (isMobile && file) setCodingPanel(null)
  }, [isMobile])

  // Restore a queued message's text into the composer (fired by the
  // X button on PendingMessageQueue). Overwrites any current draft —
  // matches the /undo restore semantics above.
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<{ content?: string }>).detail
      const content = detail?.content ?? ''
      inputRef.current?.setValue(content)
      inputRef.current?.focus()
    }
    window.addEventListener('queue:restore-draft', handler)
    return () => window.removeEventListener('queue:restore-draft', handler)
  }, [])

  // Restore permission mode from the session's persisted value whenever the
  // active session changes (e.g. on load or navigation).
  useEffect(() => {
    if (!sessionIdState) return
    let cancelled = false
    getTeamSession(sessionIdState)
      .then((session) => {
        if (!cancelled && session.permission_mode) {
          setPermissionMode(session.permission_mode as import('@/api/types').PermissionMode)
        }
      })
      .catch(() => {/* non-fatal */})
    return () => { cancelled = true }
  }, [sessionIdState])

  // Push the active session/workspace label to the desktop tray. The
  // command is a no-op outside Tauri so this is safe to fire from the
  // web build too.
  //
  // Label priority — the tray reflects *liveness first*, then identity:
  //   - team currently responding → ``"Working: <ws-or-title>"``
  //     (falls back to ``"Working…"`` when no title yet — e.g. the
  //     team is generating the first message of a brand-new chat)
  //   - coding mode with workspace → ``"Coding: <ws>"``
  //   - chat with server-named session → ``"Chat: <title>"``
  //   - everything else → empty (tray shows ``No active session``)
  useEffect(() => {
    let label = ''
    const identity = codingIdentityLabel ?? sessionTitle ?? ''
    if (isTeamWorking) {
      label = identity ? `Working: ${identity}` : 'Working…'
    } else if (codingIdentityLabel) {
      label = `Coding: ${codingIdentityLabel}`
    } else if (sessionTitle) {
      label = `Chat: ${sessionTitle}`
    }
    void setTraySession(label)
  }, [codingIdentityLabel, sessionTitle, isTeamWorking])

  // Shell shortcut: start a message with `!` to run the rest as a shell command.
  // Slash commands for the input bar (type / to trigger).
  // Built-ins execute immediately on pick; user-defined commands are inserted
  // into the textarea (``keepInputOpen``) so the user can append
  // ``$ARGUMENTS`` before submitting.
  const commandsQ = useCommandsQuery(agentWorkspace)
  const snippetsQ = useSnippetsQuery(mode === 'coding' ? agentWorkspace : null)
  const userCommandNames = useMemo(
    () => new Set<string>((commandsQ.data?.commands ?? []).map((c) => c.name)),
    [commandsQ.data],
  )
  const slashCommands: SlashCommand[] = [
    { id: 'stop', label: 'Stop', description: 'Stop all working agents' },
    { id: 'continue', label: 'Continue', description: 'Continue the last assistant response' },
    { id: 'compact', label: 'Compact', description: 'Summarize and compact this session' },
    { id: 'shell', label: 'Shell', description: 'Run a shell command (prefix your command with !)' },
    { id: 'undo', label: 'Undo', description: 'Undo the previous message' },
    { id: 'redo', label: 'Redo', description: 'Restore all undone messages back to the live tip' },
    { id: 'new', label: 'New Chat', description: 'Start a fresh team conversation' },
    { id: 'init', label: 'Init', description: 'Create or update AGENTS.md for this project' },
    ...(mode === 'coding'
      ? [
          { id: 'loop', label: 'loop <prompt>', displayName: 'loop', insertText: 'loop', description: 'Start a coding loop', keepInputOpen: true },
          { id: 'loop:set', label: 'loop:set <limit>', displayName: 'loop:set', insertText: 'loop:set', description: 'Set coding loop budget: 5, 10, 20, or 50', keepInputOpen: true },
          { id: 'loop:pause', label: 'loop:pause', displayName: 'loop:pause', description: 'Pause the active coding loop' },
          { id: 'loop:resume', label: 'loop:resume', displayName: 'loop:resume', description: 'Resume the paused coding loop' },
          { id: 'loop:stop', label: 'loop:stop', displayName: 'loop:stop', description: 'Stop the active coding loop' },
          { id: 'loop:status', label: 'loop:status', displayName: 'loop:status', description: 'Show loop status and history' },
          { id: 'loop:config', label: 'loop:config <key=value>', displayName: 'loop:config', insertText: 'loop:config', description: 'Set loop config: goal, verify, evolve, budget, threshold, errors, delay', keepInputOpen: true },
        ]
      : []),
    ...(commandsQ.data?.commands ?? []).map((c) => {
      const displayName = c.name.replace('/', ':')
      return {
        id: c.name,
        label: displayName,
        displayName,
        insertText: displayName,
        description: c.description || `Custom command (${c.source})`,
        category: 'command',
        keepInputOpen: true,
      }
    }),
  ]

  const snippetCommands: SnippetCommand[] = (snippetsQ.data?.snippets ?? []).map((item) => ({
    id: item.name,
    label: item.name.replace('/', ':'),
    description: item.description || `Snippet (${item.source})`,
    category: 'snippet',
  }))

  const handleSnippetCommand = useCallback(async (id: string) => {
    if (!agentWorkspace) return null
    try {
      const res = await renderSnippet(id, agentWorkspace)
      return res.content
    } catch (err) {
      pushToast({
        tone: 'error',
        title: `Failed to render #${id.replace('/', ':')}`,
        description: (err as Error).message,
      })
      return null
    }
  }, [agentWorkspace, pushToast])

  const runLoopCommand = useCallback(async (command: string, prompt?: string) => {
    const current = useTeamStore.getState()
    await current.sendLoopCommand(command, prompt, {
      mode,
      workspace,
      model: current.sessionId ? selectedModel || null : null,
      thinkingLevel: current.sessionId ? selectedThinkingLevel || null : null,
      fastMode: current.sessionFastMode,
    })
  }, [mode, workspace, selectedModel, selectedThinkingLevel])

  const handleSlashCommand = useCallback((id: string) => {
    switch (id) {
      case 'stop':
        useTeamStore.getState().stopTeam()
        break
      case 'continue':
        useTeamStore.getState().continueTeam()
        break
      case 'compact':
        useTeamStore.getState().compactTeam()
        break
      case 'shell':
        inputRef.current?.setValue('! ')
        inputRef.current?.focus()
        break
      case 'undo':
        void useTeamStore.getState().undoTeam().then(async (response) => {
          const message = response?.message
          if (!message || message.role !== 'user' || message.is_summary) return
          inputRef.current?.setValue(message.content ?? '')
          const attachments = message.attachments ?? []
          const files = (
            await Promise.all(attachments.map((att) => attachmentToFile(att)))
          ).filter((file): file is File => file !== null)
          inputRef.current?.setFiles(files)
          inputRef.current?.focus()
        })
        break
      case 'redo':
        void useTeamStore.getState().redoTeam().then(() => {
          inputRef.current?.setValue('')
          inputRef.current?.setFiles([])
        })
        break
      case 'new':
        handleNewSession()
        break
      case 'loop:pause':
      case 'loop:resume':
      case 'loop:stop':
        void runLoopCommand(`/${id}`).then(() => {
          const verb = id.slice('loop:'.length)
          pushToast({ tone: 'success', title: verb === 'stop' ? 'Loop stopped' : `Loop ${verb}d` })
        })
        break
      case 'loop:status':
        void runLoopCommand('/loop:status')
        break
      case 'loop:config':
        // For config, we need the full command with args from the input
        // The id is just 'loop:config', actual args come from the input field
        void runLoopCommand('/loop:config')
        break
      case 'init':
        // Prompt body lives on the backend so it can be tweaked without a
        // web rebuild and stays the single source of truth.
        void renderCommand('init', '', agentWorkspace)
          .then((res) =>
            useTeamStore.getState().sendMessage(res.content, undefined, {
              mode,
              workspace: agentWorkspace,
            }),
          )
          .catch((err: Error) =>
            pushToast({
              tone: 'error',
              title: 'Failed to start /init',
              description: err.message,
            }),
          )
        break
    }
  }, [handleNewSession, runLoopCommand, mode, agentWorkspace, pushToast])

  const tryHandleBuiltinLoopCommand = useCallback(async (content: string): Promise<boolean> => {
    const parsed = parseLoopCommand(content)
    switch (parsed.kind) {
      case 'none':
        return false
      case 'unknown_subcommand':
        return false
      case 'start_missing_prompt':
        pushToast({
          tone: 'error',
          title: '/loop needs a prompt',
          description: 'Type the prompt after /loop, e.g. "/loop just say hi".',
        })
        return true
      case 'set_invalid_limit':
        pushToast({
          tone: 'error',
          title: '/loop:set needs a valid limit',
          description: 'Use one of: 5, 10, 20, or 50.',
        })
        return true
      case 'start':
        await runLoopCommand(content, parsed.prompt)
        return true
      case 'set':
        await runLoopCommand(`/loop:set ${parsed.limit}`)
        pushToast({ tone: 'success', title: `Loop budget set to ${parsed.limit}` })
        return true
      case 'pause':
      case 'resume':
      case 'stop':
        await runLoopCommand(`/loop:${parsed.kind}`)
        pushToast({ tone: 'success', title: parsed.kind === 'stop' ? 'Loop stopped' : `Loop ${parsed.kind}d` })
        return true
      case 'status':
        await runLoopCommand('/loop:status')
        return true
      case 'config':
        await runLoopCommand(content)
        return true
    }
  }, [pushToast, runLoopCommand])

  /** If *content* starts with a known user-defined command, render server-side
   *  and return the expanded body; otherwise return *content* unchanged. */
  const expandUserCommand = useCallback(
    async (content: string): Promise<string> => {
      if (!content.startsWith('/')) return content
      if (content.startsWith('/loop:') || content.startsWith('/loop ')) return content
      // The command name may include slashes (nested folders), so we
      // greedily match the longest known prefix instead of splitting on
      // the first space. Tokens are separated by whitespace.
      const rest = content.slice(1)
      // Try progressively shorter prefixes — start with the full first
      // line, peel back to the longest known command name.
      const firstLine = rest.split('\n', 1)[0]
      const tokens = firstLine.split(' ')
      for (let n = tokens.length; n > 0; n--) {
        const candidate = tokens.slice(0, n).join(' ').trim()
        const commandName = candidate.replace(':', '/')
        if (userCommandNames.has(commandName)) {
          const argsHead = tokens.slice(n).join(' ')
          const restOfMessage = rest.slice(firstLine.length)
          const args = (argsHead + restOfMessage).trim()
          try {
            const res = await renderCommand(commandName, args, agentWorkspace)
            return res.content
          } catch (err) {
            pushToast({
              tone: 'error',
              title: `Failed to render /${candidate}`,
              description: (err as Error).message,
            })
            return content
          }
        }
      }
      return content
    },
    [userCommandNames, agentWorkspace, pushToast],
  )

  const cycleViewMode = useCallback(() => {
    setViewMode((v) => {
      const idx = VIEW_MODES.indexOf(v)
      return VIEW_MODES[(idx + 1) % VIEW_MODES.length]
    })
  }, [])

  const closeMobileActionsMenu = useCallback(() => setShowMobileActions(false), [])

  const commands = useTeamCommands({
    viewMode,
    cycleViewMode,
    setViewMode,
    toggleAgentCapabilities,
    setShowTodos,
    handleWorkspaceFiles,
    handleCodingSidebarToggle,
    mode,
    handleNewSession,
    handleDreamRun,
    agentNames,
    leadName,
    cycleActiveAgent,
    setActiveAgent,
    navigate,
  })
  const paletteCommands = commands

  useKeyboardShortcuts({
    n: handleNewSession,
    v: isMobile ? undefined : cycleViewMode,
    a: toggleAgentCapabilities,
    f: handleWorkspaceFiles,
    t: () => { if (sessionIdState) setShowTodos((v) => !v) },
    p: isMobile ? undefined : () => setShowPalette((v) => !v),
    b: mode === 'coding' ? handleCodingSidebarToggle : undefined,
    // Ctrl+M / Ctrl+S — open the wiki / scheduler drawers (state in useUIStore).
    m: toggleWiki,
    s: toggleScheduler,
    // Ctrl+I — focus the chat input (dispatched via CustomEvent so future
    // callers don't need a ref to the input).
    'i': () => window.dispatchEvent(new CustomEvent('focus-chat-input')),
  })

  // Tab / Shift+Tab — cycle the active agent in the store (agent view tabs
  // and split-mode pane focus both follow store activeAgent).
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key !== 'Tab' || e.ctrlKey || e.metaKey) return
      e.preventDefault()
      cycleActiveAgent(e.shiftKey ? 'prev' : 'next')
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [cycleActiveAgent])

  const handleMobileSidebarSwipeStart = useCallback((event: React.TouchEvent<HTMLDivElement>) => {
    if ((os !== 'ios' && os !== 'android') || !isMobile || mobileSidebarOpen) return
    const touch = event.touches[0]
    if (!touch || touch.clientX > 24) return
    mobileSidebarSwipeStartRef.current = { x: touch.clientX, y: touch.clientY }
  }, [isMobile, mobileSidebarOpen, os])

  const handleMobileSidebarSwipeMove = useCallback((event: React.TouchEvent<HTMLDivElement>) => {
    const start = mobileSidebarSwipeStartRef.current
    if (!start || (os !== 'ios' && os !== 'android') || !isMobile || mobileSidebarOpen) return
    const touch = event.touches[0]
    if (!touch) return
    const deltaX = touch.clientX - start.x
    const deltaY = touch.clientY - start.y
    if (deltaX > 56 && Math.abs(deltaY) < 36) {
      if (mode === 'coding') {
        setCodingPanel(null)
        setCodingFileViewer(null)
      }
      setMobileSidebarOpen(true)
      mobileSidebarSwipeStartRef.current = null
    }
  }, [isMobile, mobileSidebarOpen, mode, os])

  const handleMobileSidebarSwipeEnd = useCallback(() => {
    mobileSidebarSwipeStartRef.current = null
  }, [])

  const handleMobileActionsSwipeStart = useCallback((event: React.TouchEvent<HTMLDivElement>) => {
    if ((os !== 'ios' && os !== 'android') || !isMobile || showMobileActions) return
    const touch = event.touches[0]
    if (!touch || window.innerWidth - touch.clientX > 24) return
    mobileActionsSwipeStartRef.current = { x: touch.clientX, y: touch.clientY }
  }, [isMobile, os, showMobileActions])

  const handleMobileActionsSwipeMove = useCallback((event: React.TouchEvent<HTMLDivElement>) => {
    const start = mobileActionsSwipeStartRef.current
    if (!start || (os !== 'ios' && os !== 'android') || !isMobile || showMobileActions) return
    const touch = event.touches[0]
    if (!touch) return
    const deltaX = touch.clientX - start.x
    const deltaY = touch.clientY - start.y
    if (deltaX < -56 && Math.abs(deltaY) < 36) {
      setShowMobileActions(true)
      mobileActionsSwipeStartRef.current = null
    }
  }, [isMobile, os, showMobileActions])

  const handleMobileActionsSwipeEnd = useCallback(() => {
    mobileActionsSwipeStartRef.current = null
  }, [])

  const loopLabel = activeLoop
    ? `${activeLoop.paused ? 'Loop paused' : activeLoop.prompt ? 'Loop active' : 'Loop ready'}${activeLoop.prompt ? `: "${activeLoop.prompt}"` : ''}`
    : null
  const loopProgressParts = activeLoop
    ? [
        `${activeLoop.used}/${activeLoop.limit}`,
        activeLoop.totalTokensUsed ? `${formatTokens(activeLoop.totalTokensUsed)} tokens` : null,
      ].filter(Boolean)
    : null
  const loopProgress = loopProgressParts ? loopProgressParts.join(' | ') : null
  const loopGoal = activeLoop?.goal ?? null
  const loopNoProgress = activeLoop?.noProgressWarning ?? false
  const loopRecentTurns = activeLoop?.turnHistory?.slice(-2) ?? []

  // While `loadSession` fetches history, the reset store has an (empty)
  // stream for the lead, so the AgentView branch would win and render its
  // empty state — a misleading blank chat / workspace card with no loading
  // feedback. Show the skeleton instead until either history commits or
  // live content arrives (never blank an already-visible transcript on the
  // tab-refocus reload path).
  const showHistorySkeleton =
    !!sessionId &&
    isSessionLoading &&
    (activeBlocks?.length ?? 0) === 0 &&
    (activeCurrentBlocks?.length ?? 0) === 0
  const historySkeleton = (
    <div className="relative flex min-h-0 flex-1 flex-col overflow-hidden" aria-hidden="true">
      <div className="flex-1 overflow-hidden">
        <div className="mx-auto max-w-3xl space-y-8 px-4 py-6">
          <div className="flex justify-end">
            <div className="h-9 w-44 animate-pulse rounded-2xl bg-(--bg-key)" />
          </div>
          <div className="space-y-2.5">
            <div className="h-3.5 w-3/4 animate-pulse rounded-lg bg-(--bg-key)" />
            <div className="h-3.5 w-full animate-pulse rounded-lg bg-(--bg-key)" />
            <div className="h-3.5 w-2/3 animate-pulse rounded-lg bg-(--bg-key)" />
            <div className="mt-1 h-3.5 w-5/6 animate-pulse rounded-lg bg-(--bg-key)" />
          </div>
          <div className="flex justify-end">
            <div className="h-9 w-32 animate-pulse rounded-2xl bg-(--bg-key)" />
          </div>
          <div className="space-y-2.5">
            <div className="h-3.5 w-1/2 animate-pulse rounded-lg bg-(--bg-key)" />
            <div className="h-3.5 w-5/6 animate-pulse rounded-lg bg-(--bg-key)" />
            <div className="h-3.5 w-3/4 animate-pulse rounded-lg bg-(--bg-key)" />
          </div>
        </div>
      </div>
    </div>
  )

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    // h-dvh handles iOS Safari's dynamic toolbar.
    <div
      className="mobile-safe-shell mobile-viewport flex h-dvh flex-col bg-(--bg-page) md:flex-row md:gap-0.5 md:p-1"
      onTouchStart={(event) => {
        handleMobileSidebarSwipeStart(event)
        handleMobileActionsSwipeStart(event)
      }}
      onTouchMove={(event) => {
        handleMobileSidebarSwipeMove(event)
        handleMobileActionsSwipeMove(event)
      }}
      onTouchEnd={() => {
        handleMobileSidebarSwipeEnd()
        handleMobileActionsSwipeEnd()
      }}
      onTouchCancel={() => {
        handleMobileSidebarSwipeEnd()
        handleMobileActionsSwipeEnd()
      }}
    >
      {/* Sidebar — full height on desktop. Both sidebars stay mounted to avoid
          remount jitter on mode switch; CSS hides the inactive one. */}
      {!isMobile && (
        <>
          <div className={mode !== 'coding' ? 'contents' : 'hidden'}>
            <Sidebar
              currentSessionId={sessionIdState || undefined}
              onCommandPalette={() => setShowPalette(true)}
              onNewChat={handleNewSession}
              mode={mode}
              mobileOpen={false}
              onMobileClose={() => {}}
            />
          </div>
          <div className={mode === 'coding' ? 'contents' : 'hidden'}>
            <CodingSidebar
              currentSessionId={sessionIdState || undefined}
              workspace={workspace}
              onCollapse={() => setCodingSidebarCollapsed(true)}
              openWorkspaceDialogKey={openWorkspaceDialogKey}
              onCommandPalette={() => setShowPalette(true)}
              desktopCollapsed={codingSidebarCollapsed}
              mobileOpen={false}
              onMobileClose={() => {}}
            />
          </div>
        </>
      )}

      {/* Sidebar toggle — positioned between sidebar and main content on desktop */}
      {!isMobile && (
        <div className="flex shrink-0 flex-col items-center pt-2">
          <button
            type="button"
            onClick={() => {
              if (mode === 'coding') {
                handleCodingSidebarToggle()
              } else {
                window.dispatchEvent(new KeyboardEvent('keydown', { key: 'b', ctrlKey: true, metaKey: false, bubbles: true }))
              }
            }}
            aria-label="Toggle sidebar"
            title="Toggle sidebar (Ctrl+B)"
            className="flex h-8 w-8 items-center justify-center rounded-md text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
          >
            <PanelLeft size={15} aria-hidden="true" />
          </button>
        </div>
      )}

      {/* Right column — header + main content */}
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
      {/* Header */}
      <header
        {...dragHandlers}
        className={`mobile-safe-header relative z-20 flex shrink-0 items-center gap-1.5 px-1.5 py-1.5 ${
          isMacOverlay && isMobile ? 'select-none' : ''
        }`}
        style={
          isMacOverlay && isMobile
            ? { paddingLeft: 'calc(var(--spacing-mac-traffic-inset) + 6px)' }
            : undefined
        }
      >
          {/* Mobile only — hamburger + title */}
          {isMobile && (
            <div className="flex flex-1 shrink-0 items-center gap-1.5">
              <button
                type="button"
                onClick={() => {
                  if (mode === 'coding') {
                    handleCodingSidebarToggle()
                  } else {
                    setMobileSidebarOpen(true)
                  }
                }}
                aria-label="Toggle sidebar"
                title="Toggle sidebar (Ctrl+B)"
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
              >
                <Menu size={15} aria-hidden="true" />
              </button>
              <div className="min-w-0 text-sm font-semibold text-(--color-text)">
                <div className="truncate">{codingIdentityLabel ?? (sessionTitle || 'EvoFlux')}</div>
                {activeAgent && <div className="truncate font-mono text-xs font-normal text-(--color-text-muted)">{activeAgent}</div>}
              </div>
            </div>
          )}

          {/* LEFT — agent switcher + loop status (desktop only) */}
          <div className="flex min-w-0 flex-1 items-center gap-2 overflow-visible">
            {effectiveViewMode === 'agent' && activeAgent && !isMobile && (
              <ActiveAgentSwitcher
                activeAgent={activeAgent}
                agents={agentNames}
                statuses={agentStatuses}
                onSelect={setActiveAgent}
              />
            )}
            {!isMobile && activeLoop && loopLabel && loopProgress && (
              <LoopStatusPill
                label={loopLabel}
                progress={loopProgress}
                compact={false}
                goal={loopGoal}
                noProgressWarning={loopNoProgress}
                recentTurns={loopRecentTurns}
              />
            )}
            {!isMobile && mode === 'coding' && (
              <TaskProgressPill
                isWorking={isTeamWorking}
                chapters={chapters}
              />
            )}
            {effectiveViewMode === 'split' && (
              <span className="text-xs text-(--color-text-muted)">
                Split · {splitAgentNames.length} agents
              </span>
            )}
          </div>

          {/* RIGHT — action cluster */}
          <div className="flex shrink-0 items-center gap-0.5">
          {isMobile ? (
            <>
              {headerTokens && (
                <TokenMeter
                  input={headerTokens.input}
                  output={headerTokens.output}
                  cached={headerTokens.cached}
                  trigger={headerTokens.trigger}
                  pulsing={headerTokens.pulsing}
                  className="mr-0.5"
                />
              )}
              <MobileHeaderAction
                Icon={FolderOpen}
                label={mode === 'coding' ? 'Workspace files' : 'Session files'}
                onClick={mode === 'coding'
                  ? workspace ? handleWorkspaceFiles : undefined
                  : sessionIdState ? () => setShowFilesPanel((v) => !v) : undefined}
                active={mode === 'coding' ? codingPanel !== null : showFilesPanel}
                disabled={mode === 'coding' ? !workspace : !sessionIdState}
              />
              <MobileHeaderAction
                Icon={SlidersHorizontal}
                label="Agent settings"
                onClick={toggleAgentCapabilities}
                active={agentCapabilitiesOpen}
              />
              <MobileChatActions
                open={showMobileActions}
                onOpenChange={setShowMobileActions}
                codingIdentityLabel={codingIdentityLabel}
                activeAgent={activeAgent}
                agents={agentNames}
                statuses={agentStatuses}
                onSelectAgent={setActiveAgent}
                onWiki={() => { toggleWiki(); closeMobileActionsMenu() }}
                onScheduler={() => { toggleScheduler(); closeMobileActionsMenu() }}
                onCompact={() => { useTeamStore.getState().compactTeam(); closeMobileActionsMenu() }}
                activeLoop={activeLoop}
              />
            </>
          ) : (
            <>
            <SessionTOC sessionId={sessionIdState} />
            <AgentTopbar
              isMobile={false}
              tokens={headerTokens}
              contextBudget={contextUsed > 0 ? { used: contextUsed, max: summaryTriggerTokens } : undefined}
              dreamRunning={dreamMutation.isPending}
              viewMode={viewMode}
              onViewModeChange={setViewMode}
              agentsAction={{
                Icon: SlidersHorizontal,
                onClick: toggleAgentCapabilities,
                title: 'Session model settings (Ctrl+A)',
                ariaLabel: 'Session model settings',
                className: agentCapabilitiesOpen ? 'mr-2 bg-(--bg-key) text-(--color-text)' : 'mr-2',
              }}
              extraActions={
                <SessionScheduleIndicator
                  sessionId={sessionIdState}
                  onOpenScheduler={toggleScheduler}
                />
              }
            />
            </>
          )}
          </div>
      </header>

      {/* Body — main content column. On mobile the Sidebar is
          position:fixed (overlay drawer), rendered here for z-stacking. */}
      <div className="flex min-h-0 flex-1 overflow-hidden">
        {/* Mobile sidebar overlay. Both sidebars stay mounted; CSS hides inactive one. */}
        {isMobile && (
          <>
            <div className={mode !== 'coding' ? 'contents' : 'hidden'}>
              <Sidebar
                currentSessionId={sessionIdState || undefined}
                onCommandPalette={() => setShowPalette(true)}
                onNewChat={handleNewSession}
                mode={mode}
                mobileOpen={mobileSidebarOpen}
                onMobileClose={() => setMobileSidebarOpen(false)}
              />
            </div>
            <div className={mode === 'coding' ? 'contents' : 'hidden'}>
              <CodingSidebar
                currentSessionId={sessionIdState || undefined}
                workspace={workspace}
                onCollapse={() => setCodingSidebarCollapsed(true)}
                openWorkspaceDialogKey={openWorkspaceDialogKey}
                onCommandPalette={() => setShowPalette(true)}
                desktopCollapsed={codingSidebarCollapsed}
                mobileOpen={mobileSidebarOpen}
                onMobileClose={() => setMobileSidebarOpen(false)}
              />
            </div>
          </>
        )}

        <main id="main" ref={mainColumnRef} className="relative flex min-w-0 flex-1 flex-col overflow-hidden rounded-[10px] bg-(--bg-page) shadow-sm">
        {setupRequired && (
          <div className="mx-3 mt-3 flex flex-col gap-3 rounded-xl border border-(--accent-blue)/35 bg-(--accent-blue-soft) p-3 text-sm text-(--color-text) shadow-sm sm:flex-row sm:items-center sm:justify-between">
            <div className="flex min-w-0 gap-3">
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-(--accent-blue)" aria-hidden="true" />
              <div className="min-w-0">
                <p className="font-medium">Configure a provider to start chatting</p>
                <p className="mt-0.5 text-xs text-(--color-text-muted)">{setupRequired.message}</p>
              </div>
            </div>
            <div className="flex shrink-0 items-center gap-2 self-start sm:self-center">
              <Button
                size="sm"
                onClick={() => useUIStore.getState().openSettings('providers')}
              >
                Open Providers
              </Button>
              <button
                type="button"
                className="flex h-9 w-9 items-center justify-center rounded-md text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text) md:h-8 md:w-8"
                onClick={dismissSetupRequired}
                aria-label="Dismiss provider setup notice"
              >
                <X size={14} aria-hidden="true" />
              </button>
            </div>
          </div>
        )}
        {!setupRequired && !hasConfiguredModelProvider && (
          <div className="mx-3 mt-3 flex flex-col gap-3 rounded-xl border border-(--color-border) bg-(--bg-card) p-3 text-sm text-(--color-text) shadow-sm sm:flex-row sm:items-center sm:justify-between">
            <div className="flex min-w-0 gap-3">
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-(--color-accent)" aria-hidden="true" />
              <div className="min-w-0">
                <p className="font-medium">No model provider configured</p>
                <p className="mt-0.5 text-xs text-(--color-text-muted)">Connect a provider once, then EvoFlux can seed and run the default team.</p>
              </div>
            </div>
            <Button size="sm" onClick={() => useUIStore.getState().openSettings('providers')}>
              Open Providers
            </Button>
          </div>
        )}
        {/* Content area */}
        {effectiveViewMode === 'monitor' ? (
          <MonitorView
            agentNames={agentNames}
            leadName={leadName}
            agentStreams={gridAgentStreams ?? EMPTY_AGENT_STREAMS}
          />
        ) : effectiveViewMode === 'split' && splitAgentNames.length > 0 ? (
          <div className="min-h-0 flex-1 p-3">
            <SplitGrid
              agentNames={splitAgentNames}
              leadName={leadName}
              agentStreams={gridAgentStreams ?? EMPTY_AGENT_STREAMS}
              todos={todos}
              isContinuing={isContinuing}
              onContinue={continueTeam}
            />
          </div>
        ) : isCodingSessionLoading ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-3 px-6 text-center">
            <div className="h-8 w-8 animate-spin rounded-full border-2 border-(--color-border) border-t-(--color-accent)" />
            <div>
              <h2 className="text-sm font-medium text-(--color-text)">Opening coding session…</h2>
              <p className="mt-1 text-xs text-(--color-text-muted)">Loading the saved workspace for this session.</p>
            </div>
          </div>
        ) : mode === 'coding' && workspace && teamAgentsLoading ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-3 px-6 text-center">
            <div className="h-8 w-8 animate-spin rounded-full border-2 border-(--color-border) border-t-(--color-accent)" />
            <div>
              <h2 className="text-sm font-medium text-(--color-text)">Opening coding workspace…</h2>
              <p className="mt-1 text-xs text-(--color-text-muted)">Preparing agents for {workspace}</p>
            </div>
          </div>
        ) : mode === 'coding' && !workspace ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-4 px-6 text-center">
            <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-(--bg-key) text-(--color-accent)">
              <FolderCode size={24} />
            </div>
            <div>
              <h2 className="text-base font-medium text-(--color-text)">No workspace attached</h2>
              <p className="mt-1 max-w-sm text-sm text-(--color-text-muted)">
                Choose a local project folder from the sidebar to start a coding session.
              </p>
            </div>
            <Button type="button" onClick={handleOpenWorkspaceDialog}>
              Open workspace
            </Button>
          </div>
        ) : showHistorySkeleton ? (
          historySkeleton
        ) : activeAgent && hasActiveStream ? (
          <AgentView
            blocks={activeBlocks ?? EMPTY_BLOCKS}
            currentBlocks={activeCurrentBlocks ?? EMPTY_BLOCKS}
            isWorking={activeStatus === 'working'}
            isError={activeStatus === 'error'}
            lastError={activeLastError}
            isContinuing={isContinuing && activeAgent === leadName}
            onContinue={activeAgent === leadName ? continueTeam : undefined}
            suggestions={activeAgent === leadName ? promptSuggestions : null}
            chapters={activeAgent === leadName ? chapters : undefined}
            onSuggestion={(text) => {
              useTeamStore.setState({ promptSuggestions: null })
              inputRef.current?.setValue(text)
              inputRef.current?.focus()
            }}
            emptyState={
              mode === 'coding' && workspace ? (
                <div className="flex flex-col items-center justify-center py-16">
                  {projectIdState ? (
                    activeProject && <ProjectInfoCard project={activeProject} />
                  ) : (
                    <WorkspaceInfoCard workspace={workspace} />
                  )}
                </div>
              ) : undefined
            }
          />
        ) : mode === 'coding' && workspace ? (
          <div className="flex flex-1 flex-col items-center justify-center py-16">
            {projectIdState ? (
              activeProject && <ProjectInfoCard project={activeProject} />
            ) : (
              <WorkspaceInfoCard workspace={workspace} />
            )}
          </div>
        ) : sessionId && !isConnected ? (
          historySkeleton
        ) : null}

        <PermissionApprovalModal />
        <AskUserQuestionModal />
        {(mode !== 'coding' || workspace) && (
          <FloatingInputBar
            ref={inputRef}
            boundsRef={mainColumnRef}
            onSubmit={async (content, files) => {
              if (mode === 'coding' && (await tryHandleBuiltinLoopCommand(content))) return
              const shell = content.startsWith('!')
              const command = shell ? content.slice(1).trim() : content
              const expanded = shell ? `!${command}` : await expandUserCommand(content)
              const current = useTeamStore.getState()
              sendMessage(expanded, files, {
                mode,
                workspace,
                model: current.sessionId ? selectedModel || null : null,
                thinkingLevel: current.sessionId ? selectedThinkingLevel || null : null,
                fastMode: current.sessionFastMode,
                shell,
              })
            }}
            onStop={() => useTeamStore.getState().stopTeam()}
            onSlashCommand={handleSlashCommand}
            onSnippetCommand={handleSnippetCommand}
            slashCommands={slashCommands}
            snippetCommands={snippetCommands}
            historyPrompts={historyPrompts}
            fileRefs={fileRefs}
            onFileRefsNeeded={() => setFileRefsEnabled(true)}
            isStreaming={isTeamWorking}
            disabled={mode === 'coding' && isCodingSessionLoading}
            placeholder={
              dreamMutation.isPending
                ? 'Dream is running…'
                : isTeamWorking
                  ? 'Team working… type to interrupt'
                  : codingIdentityLabel
                    ? `Coding in ${codingIdentityLabel}`
                    : 'Message the team…'
            }
            capabilities={effectiveCapabilities}
            revertedCount={leadRevertedCount}
            revertedMessages={leadRevertedMessages}
            onRedo={() => { void useTeamStore.getState().redoTeam() }}
            sessionModel={sessionModel}
            defaultModel={leadAgent?.model ?? null}
            sessionThinkingLevel={sessionThinkingLevel}
            sessionFastMode={sessionFastMode}
            onSessionModelSettingsChange={setSessionModelSettings}
            agentNames={agentNames}
            agentWorkspace={agentWorkspace}
            todos={todos}
            todosOpen={showTodos}
            onTodosOpenChange={setShowTodos}
            sessionId={sessionIdState}
            onWiki={toggleWiki}
            wikiActive={wikiOpen}
            onFiles={
              mode === 'coding'
                ? workspace ? handleWorkspaceFiles : undefined
                : () => setShowFilesPanel((v) => !v)
            }
            filesDisabled={mode !== 'coding' && !sessionIdState}
            onActivity={() => setShowActivity((v) => !v)}
            activityActive={showActivity}
            permissionMode={permissionMode}
            onPermissionModeChange={handlePermissionModeChange}
          />
        )}
        </main>
        <AnimatePresence>
          {showActivity && (
            <motion.aside
              key="activity-panel"
              initial={{ width: 0, opacity: 0 }}
              animate={{ width: 280, opacity: 1 }}
              exit={{ width: 0, opacity: 0 }}
              transition={{ duration: 0.15 }}
              className="flex h-full shrink-0 flex-col overflow-hidden border-l border-(--color-border) bg-(--bg-page)"
            >
              <div className="flex items-center justify-between border-b border-(--color-border) px-3 py-2">
                <span className="text-xs font-semibold text-(--color-text-2)">Activity</span>
                <button
                  onClick={() => setShowActivity(false)}
                  className="flex h-5 w-5 items-center justify-center rounded-md text-(--color-text-muted) hover:text-(--color-text)"
                  aria-label="Close activity panel"
                >
                  <X size={12} />
                </button>
              </div>
              <div className="min-h-0 flex-1">
                <ActivityPanel />
              </div>
            </motion.aside>
          )}
        </AnimatePresence>
        {mode === 'coding' && workspace && codingFileViewer !== null && (
          <CodingFileViewerPanel
            workspace={codingFileViewer.sourceWorkspace ?? workspace}
            file={codingFileViewer}
            mobile={isMobile}
            onAddComment={handleAddFileComment}
            onSendToChat={handleSendToChat}
            onClose={() => setCodingFileViewer(null)}
          />
        )}
        {mode === 'coding' && workspace && codingPanel !== null && (
          <CodingWorkspacePanel
            key={codingPanel}
            workspace={workspace}
            open
            initialTab={codingPanel}
            mobile={isMobile}
            selectedFilePath={codingFileViewer?.path ?? null}
            onFileSelect={handleCodingFileSelect}
            onClose={() => {
              setCodingPanel(null)
              setCodingFileViewer(null)
            }}
            sessionId={sessionIdState}
            projectId={projectIdState}
            isWorking={isTeamWorking}
          />
        )}
        <BrowserViewer
          sessionId={sessionIdState}
          open={browserOpen}
          onClose={closeBrowser}
        />
      </div>

      <SessionSettingsPanel
        open={agentCapabilitiesOpen}
        agentNames={agentNames}
        workspace={agentWorkspace}
        sessionModel={sessionModel}
        sessionThinkingLevel={sessionThinkingLevel}
        sessionFastMode={sessionFastMode}
        onSessionModelSettingsChange={setSessionModelSettings}
        onClose={closeAgentCapabilities}
      />
      <WorkspaceFilesPanel
        open={mode !== 'coding' && showFilesPanel}
        sessionId={sessionIdState}
        onClose={() => setShowFilesPanel(false)}
      />
      <WikiPanel open={wikiOpen} onClose={closeWiki} />
      <SchedulerPanel
        open={schedulerOpen}
        onClose={closeScheduler}
        contextMode={mode}
        contextWorkspace={workspace ?? null}
      />
      <PlanApprovalModal />
      {showPalette && (
        <CommandPalette commands={paletteCommands} onClose={() => setShowPalette(false)} />
      )}
      </div>{/* end right column */}
    </div>
  )
}

// ─── Loop status ────────────────────────────────────────────────────────────

function LoopStatusPill({
  label,
  progress,
  compact,
  goal,
  noProgressWarning,
  recentTurns,
}: {
  label: string
  progress: string
  compact: boolean
  goal?: string | null
  noProgressWarning?: boolean
  recentTurns?: LoopTurnSummary[]
}) {
  const titleParts = [label, progress, goal ? `Goal: ${goal}` : null].filter(Boolean)
  return (
    <div
      className="mx-1 flex max-w-[46vw] shrink-0 items-center gap-1 rounded-full border border-(--color-border) bg-(--bg-card) px-2 py-1 text-xs text-(--color-text) shadow-sm md:max-w-sm"
      title={titleParts.join(' · ')}
    >
      <span className="min-w-0 truncate font-medium">
        {compact ? 'Loop' : label}
      </span>
      {noProgressWarning && (
        <span className="shrink-0 text-(--color-warning)" title="No progress detected">⚠</span>
      )}
      {recentTurns && recentTurns.length > 0 && (
        <span className="flex shrink-0 gap-0.5">
          {recentTurns.map((t) => (
            <span
              key={t.iteration}
              className={t.success === true ? 'text-green-500' : t.success === false ? 'text-red-500' : 'text-(--color-text-muted)'}
              title={t.error ?? `Turn ${t.iteration}`}
            >
              {t.success === true ? '✓' : t.success === false ? '✗' : '…'}
            </span>
          ))}
        </span>
      )}
      <span className="shrink-0 font-mono text-xs text-(--color-text-muted)">{progress}</span>
    </div>
  )
}

function MobileLoopStatusCard({ activeLoop }: { activeLoop: ActiveLoop }) {
  const state = activeLoop.paused ? 'Paused' : activeLoop.prompt ? 'Active' : 'Ready'
  const progressParts = [
    `${activeLoop.used}/${activeLoop.limit}`,
    activeLoop.totalTokensUsed ? `${formatTokens(activeLoop.totalTokensUsed)} tokens` : null,
  ].filter(Boolean)
  const recentTurns = activeLoop.turnHistory?.slice(-3) ?? []
  return (
    <div className="mb-1 rounded-md border border-(--color-border) bg-(--bg-card) px-2 py-2 text-sm">
      <div className="flex items-center justify-between gap-2">
        <span className="font-medium text-(--color-text)">Loop {state.toLowerCase()}</span>
        <span className="font-mono text-xs text-(--color-text-muted)">{progressParts.join(' | ')}</span>
      </div>
      {activeLoop.goal && (
        <p className="mt-1 text-xs text-(--color-text-muted)" title={activeLoop.goal}>
          Goal: {activeLoop.goal}{activeLoop.goalMet ? ' ✓' : ''}
        </p>
      )}
      {activeLoop.noProgressWarning && (
        <p className="mt-1 text-xs text-(--color-warning)">⚠ No progress detected</p>
      )}
      {recentTurns.length > 0 && (
        <div className="mt-1 flex gap-1">
          {recentTurns.map((t) => (
            <span
              key={t.iteration}
              className={`font-mono text-xs ${t.success === true ? 'text-green-500' : t.success === false ? 'text-red-500' : 'text-(--color-text-muted)'}`}
              title={t.error ?? `Turn ${t.iteration}`}
            >
              {t.success === true ? '✓' : t.success === false ? '✗' : '…'}
              {t.iteration}
            </span>
          ))}
        </div>
      )}
      {activeLoop.prompt && (
        <p className="mt-1 line-clamp-2 text-xs text-(--color-text-muted)" title={activeLoop.prompt}>
          {activeLoop.prompt}
        </p>
      )}
    </div>
  )
}

// ─── MobileChatActions ─────────────────────────────────────────────────────

function MobileHeaderAction({
  Icon,
  label,
  onClick,
  active = false,
  disabled = false,
  badge = 0,
}: {
  Icon: LucideIcon
  label: string
  onClick?: () => void
  active?: boolean
  disabled?: boolean
  badge?: number
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled || !onClick}
      className={`relative flex h-9 w-9 items-center justify-center rounded-md transition-colors disabled:opacity-45 ${
        active
          ? 'bg-(--bg-key) text-(--color-text)'
          : 'text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text)'
      }`}
      aria-label={label}
      title={label}
    >
      <Icon size={16} aria-hidden="true" />
      {badge > 0 && (
        <span className="absolute right-0.5 top-0.5 min-w-3.5 rounded-full bg-(--color-accent) px-1 text-center font-mono text-xs leading-3.5 text-(--bg-page)">
          {badge > 9 ? '9+' : badge}
        </span>
      )}
    </button>
  )
}

interface MobileChatActionsProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  codingIdentityLabel: string | null
  activeAgent: string | null
  agents: string[]
  statuses: Record<string, AgentStatus | undefined>
  onSelectAgent: (agent: string) => void
  onWiki: () => void
  onScheduler: () => void
  onCompact: () => void
  activeLoop: ActiveLoop | null
}

function MobileChatActions({
  open,
  onOpenChange,
  codingIdentityLabel,
  activeAgent,
  agents,
  statuses,
  onSelectAgent,
  onWiki,
  onScheduler,
  onCompact,
  activeLoop,
}: MobileChatActionsProps) {
  return (
    <>
      <button
        type="button"
        data-no-drag
        onClick={() => onOpenChange(true)}
        className="mr-1 flex h-9 w-9 items-center justify-center rounded-md text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
        aria-label="Open chat actions"
        title="Chat actions"
      >
        <MoreHorizontal size={17} aria-hidden="true" />
      </button>

      <AnimatePresence>
        {open && (
          <>
            <motion.div
              key="mobile-actions-backdrop"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.18 }}
              className="mobile-safe-top fixed inset-x-0 bottom-0 z-30 bg-(--color-overlay) md:hidden"
              aria-hidden="true"
              onClick={() => onOpenChange(false)}
            />
            <motion.aside
              key="mobile-actions-drawer"
              initial={{ x: 280 }}
              animate={{ x: 0 }}
              exit={{ x: 280 }}
              transition={{ duration: 0.22, ease: [0.4, 0, 0.2, 1] }}
              className="mobile-safe-top fixed bottom-0 right-0 z-40 flex w-[min(272px,calc(100vw-2rem))] flex-col overflow-hidden border-l border-(--color-border) bg-(--bg-page) shadow-xl md:hidden"
              role="dialog"
              aria-modal="true"
              aria-label="Chat actions"
            >
              <div className="border-b border-(--color-border) px-3 py-3">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold text-(--color-text)">
                      {codingIdentityLabel ?? 'Chat actions'}
                    </p>
                    {activeAgent && (
                      <p className="mt-1 truncate font-mono text-xs text-(--color-text-muted)">Active: {activeAgent}</p>
                    )}
                  </div>
                  <button
                    type="button"
                    onClick={() => onOpenChange(false)}
                    className="rounded-md p-1.5 text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
                    aria-label="Close chat actions"
                  >
                    <X size={16} aria-hidden="true" />
                  </button>
                </div>
              </div>

              <div className="flex-1 overflow-y-auto p-2">
                {activeLoop && (
                  <>
                    <div className="px-2 py-2 text-xs font-medium text-(--color-text-muted)">Loop</div>
                    <MobileLoopStatusCard activeLoop={activeLoop} />
                  </>
                )}
                {activeAgent && agents.length > 1 && (
                  <>
                    <div className="px-2 py-2 text-xs font-medium text-(--color-text-muted)">Agents</div>
                    {agents.map((name) => (
                      <button
                        type="button"
                        key={name}
                        onClick={() => { onSelectAgent(name); onOpenChange(false) }}
                        className="flex min-h-10 w-full items-center gap-2 rounded-md px-2 text-left text-sm transition-colors hover:bg-(--bg-key)"
                      >
                        <span className={`h-2 w-2 rounded-full ${dotClassFor(name, statuses[name])}`} aria-hidden="true" />
                        <span className="min-w-0 flex-1 truncate font-mono text-xs">{name}</span>
                        {name === activeAgent && <Check size={13} className="text-(--color-accent)" aria-hidden="true" />}
                      </button>
                    ))}
                  </>
                )}

                <div className="px-2 py-2 text-xs font-medium text-(--color-text-muted)">Session</div>
                <button type="button" onClick={onWiki} className="flex min-h-10 w-full items-center gap-2 rounded-md px-2 text-left text-sm transition-colors hover:bg-(--bg-key)">
                  <Brain size={15} aria-hidden="true" />
                  <span className="flex-1">Wiki</span>
                </button>
                <button type="button" onClick={onScheduler} className="flex min-h-10 w-full items-center gap-2 rounded-md px-2 text-left text-sm transition-colors hover:bg-(--bg-key)">
                  <CalendarClock size={15} aria-hidden="true" />
                  <span className="flex-1">Scheduler</span>
                </button>
                <button type="button" onClick={onCompact} className="flex min-h-10 w-full items-center gap-2 rounded-md px-2 text-left text-sm transition-colors hover:bg-(--bg-key)">
                  <Minimize2 size={15} aria-hidden="true" />
                  <span className="flex-1">Compact context</span>
                </button>
              </div>
            </motion.aside>
          </>
        )}
      </AnimatePresence>
    </>
  )
}

// ─── ActiveAgentSwitcher ───────────────────────────────────────────────────
//
// Single chip → dropdown of all members. Replaces the horizontal chip
// carousel that didn't scale past ~4 agents. ``data-no-drag`` on the
// trigger opts it out of ``useTauriDrag``'s interactive guard so the
// chip-as-trigger doesn't race the window-drag handler.

interface ActiveAgentSwitcherProps {
  activeAgent: string
  agents: string[]
  statuses: Record<string, AgentStatus | undefined>
  onSelect: (agent: string) => void
}

const DOT_BY_ROLE: Record<AgentRole, string> = {
  EvoFlux: 'bg-(--color-marker-mint)',
  executor: 'bg-(--color-marker-orange)',
  consultant: 'bg-(--color-marker-blue)',
  explorer: 'bg-(--color-text-muted)',
}

function dotClassFor(agent: string, status: AgentStatus | undefined): string {
  if (status === 'error') return 'bg-(--color-error)'
  if (status === 'working') return 'animate-pulse bg-(--color-accent)'
  if (status === 'offline') return 'bg-(--color-text-subtle) opacity-50'
  if (isAgentRole(agent)) return DOT_BY_ROLE[agent]
  return 'bg-(--color-success)'
}

function ActiveAgentSwitcher({
  activeAgent,
  agents,
  statuses,
  onSelect,
}: ActiveAgentSwitcherProps) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        data-no-drag
        className="inline-flex h-9 min-w-0 shrink items-center gap-2 rounded-md px-2 font-mono text-xs leading-none font-semibold text-(--color-text) outline-none transition-all hover:bg-(--bg-key) focus-visible:ring-2 focus-visible:ring-(--color-accent)/40 sm:h-8 sm:px-3 sm:py-0"
        aria-label={`Switch active agent (current: ${activeAgent})`}
      >
        <span
          className={`h-2 w-2 shrink-0 rounded-full ${dotClassFor(activeAgent, statuses[activeAgent])}`}
          aria-hidden="true"
        />
        <span className="min-w-0 truncate">{activeAgent}</span>
        <ChevronDown size={12} className="shrink-0 text-(--color-text-muted)" aria-hidden="true" />
      </DropdownMenuTrigger>

      {/* w-auto overrides w-(--anchor-width) so the menu sizes to its
          content rather than the (narrow) trigger. */}
      <DropdownMenuContent
        align="start"
        sideOffset={6}
        className="w-auto max-w-[min(90vw,24rem)]"
      >
        {agents.map((name) => (
          <DropdownMenuItem
            key={name}
            onClick={() => onSelect(name)}
            className="flex min-w-40 items-center gap-2 font-mono text-xs whitespace-nowrap"
          >
            <span
              className={`h-2 w-2 shrink-0 rounded-full ${dotClassFor(name, statuses[name])}`}
              aria-hidden="true"
            />
            <span>{name}</span>
            {name === activeAgent && (
              <Check size={12} className="ml-auto shrink-0 text-(--color-accent)" aria-hidden="true" />
            )}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
