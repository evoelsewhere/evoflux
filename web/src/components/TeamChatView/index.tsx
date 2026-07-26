/**
 * TeamChatView — top-level layout for the team chat route.
 *
 * Owns:
 *   - View-mode state (``agent`` / ``split`` / ``monitor``).
 *   - The composition: stores/queries wiring, one sidebar per mode, the
 *     ``AppShell`` frame, the view switch (AgentView / SplitWorkbench /
 *     MonitorView), the ``FloatingInputBar`` and keyboard shortcuts.
 *
 * Delegates:
 *   - ``ChatTopbar``           — the header strip (agent switcher, loop /
 *     workflow / task pills, ``AgentTopbar`` cluster).
 *   - ``ChatTrailingPanels`` / ``ChatOverlayPanels`` — side panels and
 *     fixed overlays (``components/chat/ChatPanels``).
 *   - ``SplitWorkbench``       — focused agent + status rail + comparison.
 *   - ``useTeamSse``           — mount-time SSE connect + session restore
 *     (carefully sequenced so ``loadSession`` runs *before*
 *     ``connectStream`` to avoid wiping replayed mid-turn state — see the
 *     comment inside the hook).
 *   - ``useSlashCommandRegistry`` — slash / snippet / workflow command
 *     registry and the submit-time interceptors.
 *   - ``useMobileEdgeSwipes``  — mobile drawer edge-swipe gestures.
 *   - ``useTeamCommands``      — Command Palette command list.
 *
 * Stream subscriptions are split into the smallest selectors that work
 * (one primitive per ``useTeamStore`` call) to avoid the infinite loop
 * that returning a freshly-built object on every render would trigger.
 */
import { useEffect, useMemo, useRef, useState, useCallback } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { useQueryClient } from '@tanstack/react-query'
import { AgentView } from '../AgentView'
import { AppShell } from '@/components/shell/AppShell'
import { STORAGE_KEYS } from '@/lib/storage-keys'
import { WorkspaceInfoCard } from '../WorkspaceInfoCard'
import { ProjectInfoCard } from '../ProjectInfoCard'
import { useProjectQuery } from '@/queries/useProjectsQuery'
import { CodingSidebar } from '../CodingSidebar'
import { Sidebar } from '../Sidebar'
import { ChatTopbar } from '@/components/chat/ChatTopbar'
import { ChatOverlayPanels, ChatTrailingPanels } from '@/components/chat/ChatPanels'
import { WorkspaceFilesPanel } from '@/components/WorkspaceFilesPanel'
import { CodingFileViewerPanel } from '@/components/CodingFileViewerPanel'
import { CodingWorkspacePanel } from '@/components/CodingWorkspacePanel'
import { PermissionApprovalModal } from '../PermissionApprovalModal'
import { AskUserQuestionModal } from '../AskUserQuestionModal'
import { MonitorView } from '../MonitorView'
import { WebBridgeStatusDialog } from '@/components/shell/WebBridgeStatusDialog'
import { useTodosQuery } from '@/queries/useTodosQuery'
import { useSessionChapters } from '@/hooks/useSessionChapters'
import { useProvidersQuery, useRegistryQuery, useTriggerDreamMutation } from '@/queries'
import { useTeamSessionsQuery } from '@/queries/useSessionsQuery'
import { getTeamSession, getWebBridgeStatus, replyPlanApproval, resolveTeamSession, setSessionPermissionMode } from '@/api/client'
import { useShallow } from 'zustand/react/shallow'
import { useTeamStore } from '@/stores/useTeamStore'
import { useToastStore } from '@/stores/useToastStore'
import { prependSession, prependWorkspaceSession } from '@/stores/cache-invalidation-bridge'
import { useUIStore } from '@/stores/useUIStore'
import { useResizableWidth } from '@/hooks/use-resizable-width'
import { useKeyboardShortcuts } from '@/hooks/useKeyboardShortcuts'
import { useTeamAgentsQuery } from '@/queries/useAgentsQuery'
import { useFileRefsQuery } from '@/queries/useFileRefsQuery'
import { AlertCircle, ArrowRight, FolderPlus, GitBranch, X } from 'lucide-react'
import { useIsMobile } from '@/hooks/use-mobile'
import { usePlatform } from '@/hooks/use-platform'
import { useTauriDrag } from '@/hooks/use-tauri-drag'
import { useWorkspaceFileWatcher } from '@/hooks/useWorkspaceFileWatcher'
import { Button } from '@/components/ui/button'
import type { AgentStream } from '@/stores/useTeamStore'
import { PlanActionBar } from '../PlanReviewPanel'
import { type InputBarHandle } from '../InputBar'
import { FloatingInputBar } from '../FloatingInputBar'
import { SideChatPanel } from '../SideChatPanel'
import { useSideChat } from '../SideChatPanel/useSideChat'
import type { AgentCapabilities as AgentCapabilitiesType, WorkspaceFileInfo } from '@/api/types'
import { SplitWorkbench } from './SplitWorkbench'
import { useTeamCommands } from './useTeamCommands'
import { useTeamSse } from './useTeamSse'
import { useSlashCommandRegistry } from './useSlashCommandRegistry'
import { useMobileEdgeSwipes } from './useMobileEdgeSwipes'
import { VIEW_MODES, type ViewMode } from './types'
import { codingFocusId, saveLastCodingWorkspace, workspaceLabel } from '@/utils/workspace'
import { setTraySession } from '@/lib/tray'

interface TeamChatViewProps {
  sessionId?: string
  mode?: 'forge' | 'coding' | 'aim'
  workspace?: string | null
  codingSessionLoading?: boolean
}

type AgentStatus = AgentStream['status']

// Stable fallbacks so narrowed selectors below never return a fresh
// reference when the underlying stream field is absent.
const EMPTY_AGENT_STREAMS: Record<string, AgentStream> = {}
const EMPTY_BLOCKS: AgentStream['blocks'] = []
const EMPTY_REVERTED_MESSAGES: Array<{ role: string; content: string }> = []

export function TeamChatView({ sessionId, mode = 'forge', workspace = null, codingSessionLoading = false }: TeamChatViewProps) {
  // A handful of child components/hooks (file refs, command palette,
  // scheduler) only distinguish forge vs. coding — aim (the post-run
  // Discussion panel) behaves like forge for them: session-keyed, no
  // workspace-file chrome. Everywhere else in this file aim falls through
  // the non-coding branch of each `mode === 'coding'` check.
  const forgeOrCodingMode: 'forge' | 'coding' = mode === 'coding' ? 'coding' : 'forge'
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
  const [showFilesPanel, setShowFilesPanel] = useState(false)
  const [codingPanel, setCodingPanel] = useState<null | 'changed' | 'files'>(null)
  const [codingFileViewer, setCodingFileViewer] = useState<WorkspaceFileInfo | null>(null)
  const [openWorkspaceDialogKey, setOpenWorkspaceDialogKey] = useState(0)
  const [codingWorkspacePickerPortal, setCodingWorkspacePickerPortal] = useState<HTMLDivElement | null>(null)
  const [showActivity, setShowActivity] = useState(false)
  const [todosOpen, setTodosOpen] = useState(true)
  const [permissionMode, setPermissionMode] = useState<import('@/api/types').PermissionMode>('auto')
  const [showMobileActions, setShowMobileActions] = useState(false)
  const [showPalette, setShowPalette] = useState(false)
  const [fileRefsEnabled, setFileRefsEnabled] = useState(false)
  const [viewMode, setViewMode] = useState<ViewMode>('agent')
  const [sideChatOpen, setSideChatOpen] = useState(false)
  const [sideChatQuote, setSideChatQuote] = useState<string | null>(null)
  const [webBridgeEnabled, setWebBridgeEnabled] = useState(false)
  const [webBridgeDialogOpen, setWebBridgeDialogOpen] = useState(false)

  // On mobile, always force agent view — split/monitor require a wide screen.
  // Also close any desktop-only panels when shrinking to mobile.
  const effectiveViewMode: ViewMode = isMobile ? 'agent' : viewMode
  useEffect(() => {
    setCodingFileViewer(null)
  }, [workspace])

  const sendMessage    = useTeamStore((s) => s.sendMessage)
  const continueTeam   = useTeamStore((s) => s.continueTeam)
  const beginResolvedSession = useTeamStore((s) => s.beginResolvedSession)
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
  const activeWorkflowExecution = useTeamStore((s) => s.activeWorkflowExecution)
  const isConnected    = useTeamStore((s) => s.isConnected)
  const isSessionLoading = useTeamStore((s) => s.isSessionLoading)
  // Utility modal state lives in useUIStore so only one can be open at a time.
  const wikiOpen = useUIStore((s) => s.wikiOpen)
  const browserOpen = useUIStore((s) => s.browserOpen)
  const terminalOpen = useUIStore((s) => s.terminalOpen)
  const toggleWiki = useUIStore((s) => s.toggleWiki)
  const toggleScheduler = useUIStore((s) => s.toggleScheduler)
  const toggleTerminal = useUIStore((s) => s.toggleTerminal)
  const closeBrowser = useUIStore((s) => s.closeBrowser)
  const closeTerminal = useUIStore((s) => s.closeTerminal)

  useEffect(() => {
    if (browserOpen || terminalOpen) {
      setShowFilesPanel(false)
      setShowActivity(false)
    }
  }, [browserOpen, terminalOpen])
  // Sidebar collapse is shell-level state shared by all three mode sidebars;
  // AppShell renders the toggle button + Ctrl+B, these are the programmatic
  // entry points (workspace CTAs, command palette, mobile hamburger).
  const toggleSidebarCollapsed = useUIStore((s) => s.toggleSidebarCollapsed)
  const setSidebarCollapsed = useUIStore((s) => s.setSidebarCollapsed)
  const terminalResize = useResizableWidth({
    storageKey: STORAGE_KEYS.panels.terminal,
    defaultWidth: 480,
    minWidth: 320,
    maxWidth: 900,
    edge: 'left',
  })

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
  const { data: chapters = [] } = useSessionChapters(sessionIdState)

  // Tags ride on session-list rows — the stream store intentionally keeps no
  // session metadata. WebBridge remains a session capability, not a chat mode.
  const { data: sessionsData } = useTeamSessionsQuery(mode)
  const activeSessionId = sessionIdState ?? sessionId ?? null
  const sessionTags = useMemo(() => {
    if (!activeSessionId) return null
    for (const page of sessionsData?.pages ?? []) {
      const found = page.data.find((s) => s.id === activeSessionId)
      if (found) return found.tags ?? []
    }
    return null
  }, [sessionsData, activeSessionId])
  const persistedWebBridgeEnabled = sessionTags?.includes('webbridge')
  useEffect(() => {
    if (!activeSessionId) {
      setWebBridgeEnabled(false)
    } else if (persistedWebBridgeEnabled !== undefined) {
      setWebBridgeEnabled(persistedWebBridgeEnabled)
    }
  }, [activeSessionId, persistedWebBridgeEnabled])
  const providersQ = useProvidersQuery()
  const hasConfiguredModelProvider = providersQ.data?.providers.some(
    (provider) => provider.kind !== 'local' && provider.is_configured,
  ) ?? true

  // Lead capabilities — used to drive composer affordances (slash menu).
  // aim sessions are workspace-bound like coding (primary workspace = the
  // target repo) — the backend requires a workspace on every aim message.
  const agentWorkspace = mode === 'coding' || mode === 'aim' ? workspace : null
  const hasCodingWorkspace = mode !== 'coding' || Boolean(workspace)
  const isCodingSessionLoading = mode === 'coding' && codingSessionLoading

  // Watch workspace for external file changes (other editors, git, etc.)
  useWorkspaceFileWatcher(agentWorkspace)
  const { data: teamAgentsData, isLoading: teamAgentsLoading } = useTeamAgentsQuery(
    agentWorkspace,
    hasCodingWorkspace,
    mode === 'aim' ? 'aim' : 'coding',
  )
  const leadAgent = teamAgentsData?.agents?.find((a) => a.is_lead)
  const leadCapabilities: AgentCapabilitiesType | undefined = leadAgent?.capabilities
  const selectedModel = sessionModel ?? ''
  const summaryTriggerTokens = leadAgent?.summary_trigger_tokens
  const selectedThinkingLevel = sessionThinkingLevel ?? 'none'

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

  // Context window size from the model registry for the topbar budget bar.
  const contextWindowSize = useMemo(() => {
    const modelToLookup = sessionModel || leadAgent?.model
    if (!modelToLookup || !registryQ.data) return undefined
    const entry = registryQ.data.models.find((m) => m.id === modelToLookup)
    return entry?.context_length ?? undefined
  }, [sessionModel, registryQ.data, leadAgent?.model])

  // Workspace file/folder list for the InputBar's @-mention picker. Fetched
  // lazily — the query is keyed on workspace/session so coding and normal
  // modes don't share cache entries.
  const { refs: fileRefs } = useFileRefsQuery({
    mode: forgeOrCodingMode,
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

  // ── Init / reconnect ───────────────────────────────────────────────────────

  const abortRef = useTeamSse({
    sessionId,
    agentWorkspace,
    hasCodingWorkspace,
    isCodingSessionLoading,
    mode,
    inputRef,
  })

  // ── Commands / shortcuts ───────────────────────────────────────────────────

  const isEmptyIdleSession = useCallback(() => useTeamStore.getState().isEmptyIdleSession(), [])

  const handleNewSession = useCallback(() => {
    // aim sessions are per-run, created by the Pipelines Run button —
    // there is no "new chat" concept in the Discussion panel, and this
    // flow doesn't thread project_id through resolveTeamSession.
    if (mode === 'aim') return
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
  }, [beginResolvedSession, isEmptyIdleSession, mode, navigate, queryClient, sessionIdState, sessionModel, sessionThinkingLevel, workspace, abortRef])

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
        setSidebarCollapsed(false)
        setOpenWorkspaceDialogKey((value) => value + 1)
      }
      return
    }
    if (sessionIdState) {
      setShowFilesPanel((value) => {
        const nextOpen = !value
        if (nextOpen) {
          setShowActivity(false)
          closeBrowser()
          closeTerminal()
        }
        return nextOpen
      })
    }
  }, [closeBrowser, closeTerminal, isMobile, mode, workspace, sessionIdState, setSidebarCollapsed])

  const handleActivityToggle = useCallback(() => {
    setShowActivity((value) => {
      const nextOpen = !value
      if (nextOpen) {
        setShowFilesPanel(false)
        closeBrowser()
        closeTerminal()
      }
      return nextOpen
    })
  }, [closeBrowser, closeTerminal])

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
    toggleSidebarCollapsed()
  }, [isMobile, toggleSidebarCollapsed])

  const handleOpenWorkspaceDialog = useCallback(() => {
    setSidebarCollapsed(false)
    setOpenWorkspaceDialogKey((value) => value + 1)
  }, [setSidebarCollapsed])

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

  /** Plan panel → composer: quote the selected plan text with the user's comment. */
  const handlePlanQuoteComment = useCallback((quote: string, comment: string) => {
    const quoted = quote
      .trim()
      .split('\n')
      .map((line) => `> ${line}`)
      .join('\n')
    inputRef.current?.appendValue(`${quoted}\n${comment}\n`)
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

  const handleSendToSideChat = useCallback((selectedText: string) => {
    setSideChatQuote(selectedText)
    setSideChatOpen(true)
  }, [])

  const handleAddSelectionToChat = useCallback((selectedText: string) => {
    const quoted = selectedText
      .trim()
      .split('\n')
      .map((line) => `> ${line}`)
      .join('\n')
    inputRef.current?.appendValue(`${quoted}\n\n`)
    inputRef.current?.focus()
  }, [])

  const handleRequestSelectionDetails = useCallback((selectedText: string) => {
    const quoted = selectedText
      .trim()
      .split('\n')
      .map((line) => `> ${line}`)
      .join('\n')
    inputRef.current?.appendValue(`Please provide more details about this:\n\n${quoted}\n`)
    inputRef.current?.focus()
  }, [])

  const handleWebBridgeEnabledChange = useCallback((enabled: boolean) => {
    setWebBridgeEnabled(enabled)
    if (enabled) setWebBridgeDialogOpen(true)
  }, [])

  // Lifted above the panel: the side chat session (and any in-flight
  // generation + SSE stream) survives closing/reopening the panel.
  const sideChat = useSideChat(sessionIdState)
  const openSideChat = sideChat.openSideChat

  // Consume one-shot open requests from the sidebar session-row icon: the
  // panel opens once the requested session is the active one.
  const sideChatRequest = useUIStore((s) => s.sideChatRequest)
  useEffect(() => {
    if (sideChatRequest && sessionIdState === sideChatRequest) {
      setSideChatOpen(true)
      useUIStore.getState().clearSideChatRequest()
    }
  }, [sideChatRequest, sessionIdState])

  // Create the side chat session eagerly on first open so history and the
  // stream are attached before the first message is sent. Depending on the
  // callback also re-runs this when the active main session changes while the
  // panel stays open.
  useEffect(() => {
    if (sideChatOpen) openSideChat()
  }, [sideChatOpen, openSideChat])

  // Clear the quote once the side chat panel has consumed it (on close).
  useEffect(() => {
    if (!sideChatOpen) setSideChatQuote(null)
  }, [sideChatOpen])

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

  const {
    slashCommands,
    snippetCommands,
    handleSlashCommand,
    handleSnippetCommand,
    tryHandleBuiltinLoopCommand,
    tryHandleWorkflowCommand,
    expandUserCommand,
    startWorkflowRun,
    runInputsRequest,
    setRunInputsRequest,
  } = useSlashCommandRegistry({
    mode,
    workspace,
    agentWorkspace,
    sessionId,
    sessionIdState,
    selectedModel,
    selectedThinkingLevel,
    inputRef,
    handleNewSession,
  })

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
    handleWorkspaceFiles,
    handleCodingSidebarToggle,
    mode: forgeOrCodingMode,
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
    f: handleWorkspaceFiles,
    p: isMobile ? undefined : () => setShowPalette((v) => !v),
    // Ctrl+B (sidebar collapse) is registered once by AppShell.
    // Ctrl+M / Ctrl+S — open the wiki / scheduler drawers (state in useUIStore).
    m: toggleWiki,
    s: toggleScheduler,
    // Ctrl+` — toggle the AI Terminal (conventional terminal shortcut).
    '`': toggleTerminal,
    // Ctrl+I — focus the chat input (dispatched via CustomEvent so future
    // callers don't need a ref to the input).
    'i': () => window.dispatchEvent(new CustomEvent('focus-chat-input')),
    // Ctrl+; — toggle the side chat panel
    ';': () => setSideChatOpen((v) => !v),
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

  const closeCodingPanels = useCallback(() => {
    setCodingPanel(null)
    setCodingFileViewer(null)
  }, [])

  const { onTouchStart, onTouchMove, onTouchEnd, onTouchCancel } = useMobileEdgeSwipes({
    os,
    isMobile,
    mode,
    mobileSidebarOpen,
    showMobileActions,
    setMobileSidebarOpen,
    setShowMobileActions,
    closeCodingPanels,
  })

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

  // One sidebar instance per mode — the inactive mode's sidebar (and its
  // queries) stays unmounted instead of being CSS-hidden. aim-chat has no
  // in-chat sidebar at all (AimSidebar lives in the AIM layout).
  const desktopSidebar = !isMobile && mode !== 'aim'
    ? mode === 'coding'
      ? (
        <CodingSidebar
          currentSessionId={sessionIdState || undefined}
          workspace={workspace}
          openWorkspaceDialogKey={openWorkspaceDialogKey}
          workspacePickerPortal={codingWorkspacePickerPortal}
          onCommandPalette={() => setShowPalette(true)}
          mobileOpen={false}
          onMobileClose={() => {}}
        />
      )
      : (
        <Sidebar
          currentSessionId={sessionIdState || undefined}
          onCommandPalette={() => setShowPalette(true)}
          onNewChat={handleNewSession}
          mode={mode}
          mobileOpen={false}
          onMobileClose={() => {}}
        />
      )
    : null
  // On mobile the sidebar is a position:fixed overlay drawer; AppShell
  // renders it inside the body row for z-stacking, as before.
  const mobileSidebar = isMobile && mode !== 'aim'
    ? mode === 'coding'
      ? (
        <CodingSidebar
          currentSessionId={sessionIdState || undefined}
          workspace={workspace}
          openWorkspaceDialogKey={openWorkspaceDialogKey}
          workspacePickerPortal={codingWorkspacePickerPortal}
          onCommandPalette={() => setShowPalette(true)}
          mobileOpen={mobileSidebarOpen}
          onMobileClose={() => setMobileSidebarOpen(false)}
        />
      )
      : (
        <Sidebar
          currentSessionId={sessionIdState || undefined}
          onCommandPalette={() => setShowPalette(true)}
          onNewChat={handleNewSession}
          mode={mode}
          mobileOpen={mobileSidebarOpen}
          onMobileClose={() => setMobileSidebarOpen(false)}
        />
      )
    : null

  // Side panels rendered after <main> inside AppShell's body row.
  const trailingPanels = (
    <>
      <ChatTrailingPanels
        mode={mode}
        sessionId={sessionIdState}
        onQuoteComment={handlePlanQuoteComment}
        showActivity={showActivity}
        onCloseActivity={() => setShowActivity(false)}
        browserOpen={browserOpen}
        onCloseBrowser={closeBrowser}
        terminalOpen={terminalOpen}
        onCloseTerminal={closeTerminal}
        terminalResize={terminalResize}
      />
      {mode === 'coding' && <div ref={setCodingWorkspacePickerPortal} className="contents" />}
      {sideChatOpen && sessionIdState && (
        <SideChatPanel
          isOpen={sideChatOpen}
          onClose={() => setSideChatOpen(false)}
          initialQuote={sideChatQuote}
          onQuoteConsumed={() => setSideChatQuote(null)}
          blocks={sideChat.blocks}
          currentBlocks={sideChat.currentBlocks}
          isWorking={sideChat.isWorking}
          error={sideChat.error}
          sideChatId={sideChat.sideChatId}
          onSend={sideChat.sendMessage}
          onStop={() => void sideChat.stopGeneration()}
        />
      )}
    </>
  )

  // On desktop, Coding panels sit in AppShell's outer trailing column — the
  // same structural slot Forge uses. This constrains both the chat *and its
  // topbar*; mobile keeps its full-screen overlay behavior.
  const fullHeightTrailing = (
    <>
      {mode === 'coding' && workspace && !isMobile && codingFileViewer !== null && (
        <CodingFileViewerPanel
          workspace={codingFileViewer.sourceWorkspace ?? workspace}
          file={codingFileViewer}
          mobile={false}
          desktopOverlay={false}
          onAddComment={handleAddFileComment}
          onSendToChat={handleSendToChat}
          onClose={() => setCodingFileViewer(null)}
        />
      )}
      {mode === 'coding' && workspace && !isMobile && codingPanel !== null && (
        <CodingWorkspacePanel
          key={codingPanel}
          workspace={workspace}
          open
          initialTab={codingPanel}
          mobile={false}
          desktopOverlay={false}
          selectedFilePath={codingFileViewer?.path ?? null}
          onFileSelect={handleCodingFileSelect}
          onClose={closeCodingPanels}
          sessionId={sessionIdState}
          projectId={projectIdState}
          isWorking={isTeamWorking}
        />
      )}
      {mode === 'coding' && workspace && isMobile && codingPanel !== null && (
        <CodingWorkspacePanel
          key={codingPanel}
          workspace={workspace}
          open
          initialTab={codingPanel}
          mobile
          selectedFilePath={codingFileViewer?.path ?? null}
          onFileSelect={handleCodingFileSelect}
          onClose={closeCodingPanels}
          sessionId={sessionIdState}
          projectId={projectIdState}
          isWorking={isTeamWorking}
        />
      )}
      {mode === 'coding' && workspace && isMobile && codingFileViewer !== null && (
        <CodingFileViewerPanel
          workspace={codingFileViewer.sourceWorkspace ?? workspace}
          file={codingFileViewer}
          mobile
          onAddComment={handleAddFileComment}
          onSendToChat={handleSendToChat}
          onClose={() => setCodingFileViewer(null)}
        />
      )}
      {mode !== 'coding' && showFilesPanel ? (
        <WorkspaceFilesPanel
          open
          sessionId={sessionIdState}
          onClose={() => setShowFilesPanel(false)}
        />
      ) : null}
    </>
  )
  const handleComposerSubmit = useCallback(async (content: string, files?: File[]) => {
    if (webBridgeEnabled) {
      try {
        const status = await getWebBridgeStatus()
        if (!status.connected) {
          pushToast({
            tone: 'error',
            title: 'WebBridge is not connected',
            description: 'Connect the browser extension before sending this message.',
          })
          setWebBridgeDialogOpen(true)
          return false
        }
      } catch {
        pushToast({
          tone: 'error',
          title: 'Could not check WebBridge',
          description: 'Reconnect the browser extension before sending this message.',
        })
        setWebBridgeDialogOpen(true)
        return false
      }
    }

    // While a plan is pending review, a text-only message is the revision
    // feedback — a normal send would just queue behind the blocked agent turn.
    const pendingPlan = useTeamStore.getState().planApproval
    if (pendingPlan && (!files || files.length === 0)) {
      const planSessionId = useTeamStore.getState().sessionId
      if (planSessionId) {
        try {
          await replyPlanApproval(planSessionId, pendingPlan.requestId, 'revise', content)
          useTeamStore.setState({ planApproval: null })
          pushToast({ tone: 'info', title: 'Revision sent — agent is updating the plan' })
        } catch (err) {
          pushToast({
            tone: 'error',
            title: 'Failed to send revision',
            description: err instanceof Error ? err.message : undefined,
          })
        }
        return true
      }
    }
    if (await tryHandleWorkflowCommand(content)) return true
    if (mode === 'coding' && (await tryHandleBuiltinLoopCommand(content))) return true
    const shell = content.startsWith('!')
    const command = shell ? content.slice(1).trim() : content
    const expanded = shell ? `!${command}` : await expandUserCommand(content)
    const current = useTeamStore.getState()
    await sendMessage(expanded, files, {
      mode,
      workspace,
      model: current.sessionId ? selectedModel || null : null,
      thinkingLevel: current.sessionId ? selectedThinkingLevel || null : null,
      fastMode: current.sessionFastMode,
      shell,
      webBridgeEnabled,
    })
    return true
  }, [
    expandUserCommand,
    mode,
    pushToast,
    selectedModel,
    selectedThinkingLevel,
    sendMessage,
    tryHandleBuiltinLoopCommand,
    tryHandleWorkflowCommand,
    webBridgeEnabled,
    workspace,
  ])

  // Modals rendered after the body row (fixed-position —
  // DOM order only matters for z-stacking). WikiPanel/SchedulerPanel live
  // at the route root now (``RootOverlayPanels`` in __root.tsx) so they
  // open in every mode.
  const overlayPanels = (
    <ChatOverlayPanels
      showPalette={showPalette}
      paletteCommands={paletteCommands}
      onClosePalette={() => setShowPalette(false)}
      runInputsRequest={runInputsRequest}
      onCancelRunInputs={() => setRunInputsRequest(null)}
      onRunInputs={async (values) => {
        if (!runInputsRequest) return
        await startWorkflowRun(runInputsRequest.name, values)
        setRunInputsRequest(null)
        pushToast({ tone: 'success', title: `${runInputsRequest.name} started` })
      }}
    />
  )

  return (
    <AppShell
      sidebar={desktopSidebar}
      mobileSidebar={mobileSidebar}
      trailing={trailingPanels}
      fullHeightTrailing={fullHeightTrailing}
      overlay={overlayPanels}
      mainId="main"
      mainRef={mainColumnRef}
      onTouchStart={onTouchStart}
      onTouchMove={onTouchMove}
      onTouchEnd={onTouchEnd}
      onTouchCancel={onTouchCancel}
      header={
        <ChatTopbar
          dragHandlers={dragHandlers}
          isMacOverlay={isMacOverlay}
          isMobile={isMobile}
          mode={mode}
          workspace={workspace}
          sessionId={sessionIdState}
          sessionTitle={sessionTitle}
          codingIdentityLabel={codingIdentityLabel}
          activeAgent={activeAgent}
          agentNames={agentNames}
          agentStatuses={agentStatuses}
          onSelectAgent={setActiveAgent}
          effectiveViewMode={effectiveViewMode}
          viewMode={viewMode}
          onViewModeChange={setViewMode}
          activeLoop={activeLoop}
          activeWorkflowExecution={activeWorkflowExecution}
          onDismissWorkflowFailed={() =>
            useTeamStore.setState((state) => {
              state.activeWorkflowExecution = null
            })
          }
          isTeamWorking={isTeamWorking}
          chapters={chapters}
          splitAgentCount={splitAgentNames.length}
          headerTokens={headerTokens}
          contextUsed={contextUsed}
          contextWindowSize={contextWindowSize}
          summaryTriggerTokens={summaryTriggerTokens}
          dreamRunning={dreamMutation.isPending}
          terminalOpen={terminalOpen}
          onToggleTerminal={toggleTerminal}
          onOpenScheduler={toggleScheduler}
          onOpenMobileSidebar={() => setMobileSidebarOpen(true)}
          onCodingSidebarToggle={handleCodingSidebarToggle}
          codingPanelOpen={codingPanel !== null}
          showFilesPanel={showFilesPanel}
          onWorkspaceFiles={handleWorkspaceFiles}
          onToggleFilesPanel={handleWorkspaceFiles}
          mobileActionsOpen={showMobileActions}
          onMobileActionsOpenChange={setShowMobileActions}
          onWiki={() => { toggleWiki(); closeMobileActionsMenu() }}
          wikiActive={wikiOpen}
          onScheduler={() => { toggleScheduler(); closeMobileActionsMenu() }}
          onCompact={() => { useTeamStore.getState().compactTeam(); closeMobileActionsMenu() }}
        />
      }
    >
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
            onFocusAgent={(name) => {
              setActiveAgent(name)
              setViewMode(splitAgentNames.length > 1 ? 'split' : 'agent')
            }}
          />
        ) : effectiveViewMode === 'split' && splitAgentNames.length > 0 ? (
          <div className="min-h-0 flex-1 p-3">
            <SplitWorkbench
              agentNames={splitAgentNames}
              leadName={leadName}
              activeAgent={activeAgent}
              agentStreams={gridAgentStreams ?? EMPTY_AGENT_STREAMS}
              todos={todos}
              isContinuing={isContinuing}
              onContinue={continueTeam}
              onSelectAgent={setActiveAgent}
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
          <div className="relative flex flex-1 items-center justify-center overflow-hidden px-5 py-8 sm:px-8">
            <div className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden="true">
              <div className="absolute left-1/2 top-1/2 h-80 w-80 -translate-x-1/2 -translate-y-1/2 rounded-full bg-(--color-accent)/10 blur-3xl" />
              <div className="absolute left-[calc(50%-10rem)] top-[calc(50%-8rem)] h-40 w-40 rounded-full border border-(--color-border-subtle)" />
              <div className="absolute bottom-[calc(50%-12rem)] left-[calc(50%+7rem)] h-24 w-24 rounded-full border border-(--color-border-subtle)" />
            </div>
            <section className="relative w-full max-w-lg overflow-hidden rounded-3xl border border-(--color-border) bg-(--bg-card)/95 shadow-xl shadow-black/10">
              <div className="absolute inset-x-0 top-0 h-px bg-linear-to-r from-transparent via-(--color-accent)/60 to-transparent" aria-hidden="true" />
              <div className="p-5 sm:p-6">
                <div className="flex flex-col items-center text-center">
                  <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-(--color-accent)/12 text-(--color-accent) ring-1 ring-inset ring-(--color-accent)/20 shadow-lg shadow-(--color-accent)/10">
                    <FolderPlus size={23} strokeWidth={1.8} aria-hidden="true" />
                  </div>
                  <div className="mt-3.5 inline-flex items-center gap-1.5 rounded-full border border-(--color-border-subtle) bg-(--bg-page)/70 px-2.5 py-1 text-[0.65rem] font-semibold uppercase tracking-[0.12em] text-(--color-text-muted)">
                    <GitBranch size={12} aria-hidden="true" />
                    Coding workspace
                  </div>
                  <h2 className="mt-2.5 text-xl font-semibold tracking-tight text-(--color-text)">Start with a project folder</h2>
                  <p className="mt-1.5 max-w-sm text-sm leading-5 text-(--color-text-muted)">
                    Open a local repository to give your coding team files, source control, and project context.
                  </p>
                </div>

                <div className="mt-5 grid gap-1 rounded-2xl border border-(--color-border-subtle) bg-(--bg-page)/65 p-1.5 text-left sm:grid-cols-2">
                  <div className="flex gap-2.5 rounded-xl px-2.5 py-2.5">
                    <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-(--bg-key) font-mono text-[0.65rem] font-semibold text-(--color-accent) ring-1 ring-(--color-border)">1</span>
                    <div>
                      <p className="text-xs font-semibold text-(--color-text)">Choose a folder</p>
                      <p className="mt-0.5 text-xs leading-4 text-(--color-text-muted)">Select any local repository or project directory.</p>
                    </div>
                  </div>
                  <div className="flex gap-2.5 rounded-xl border-t border-(--color-border-subtle) px-2.5 py-2.5 sm:border-l sm:border-t-0">
                    <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-(--bg-key) font-mono text-[0.65rem] font-semibold text-(--color-accent) ring-1 ring-(--color-border)">2</span>
                    <div>
                      <p className="text-xs font-semibold text-(--color-text)">Start building</p>
                      <p className="mt-0.5 text-xs leading-4 text-(--color-text-muted)">Create a focused coding session with your team.</p>
                    </div>
                  </div>
                </div>

                <div className="mt-5 flex flex-col items-center gap-2.5">
                  <Button type="button" className="h-10 rounded-xl px-4 shadow-lg shadow-(--color-accent)/20" onClick={handleOpenWorkspaceDialog}>
                    <FolderPlus size={17} aria-hidden="true" />
                    Open workspace
                    <ArrowRight size={16} aria-hidden="true" />
                  </Button>
                  <p className="text-center text-xs text-(--color-text-subtle)">You can also reopen a recent workspace from the sidebar.</p>
                </div>
              </div>
            </section>
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
            chapters={activeAgent === leadName ? chapters : undefined}
            onAddSelectionToChat={handleAddSelectionToChat}
            onRequestSelectionDetails={handleRequestSelectionDetails}
            onSendToSideChat={handleSendToSideChat}
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
        <WebBridgeStatusDialog open={webBridgeDialogOpen} onOpenChange={setWebBridgeDialogOpen} />
        <PlanActionBar onRevise={() => inputRef.current?.focus()} />
        {(mode !== 'coding' || workspace) && (
          <FloatingInputBar
            ref={inputRef}
            boundsRef={mainColumnRef}
            onSubmit={handleComposerSubmit}
            onStop={() => useTeamStore.getState().stopTeam()}
            onSlashCommand={(id) => {
              if (id === 'btw') {
                setSideChatOpen(true)
              } else {
                handleSlashCommand(id)
              }
            }}
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
            agentMode={mode === 'aim' ? 'aim' : 'coding'}
            todos={todos}
            todosOpen={todosOpen}
            onTodosOpenChange={setTodosOpen}
            sessionId={sessionIdState}
            onWiki={toggleWiki}
            wikiActive={wikiOpen}
            onActivity={handleActivityToggle}
            activityActive={showActivity}
            webBridgeEnabled={webBridgeEnabled}
            onWebBridgeEnabledChange={handleWebBridgeEnabledChange}
            permissionMode={permissionMode}
            onPermissionModeChange={handlePermissionModeChange}
          />
        )}
    </AppShell>
  )
}
