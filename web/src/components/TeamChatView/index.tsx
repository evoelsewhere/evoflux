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
 *   - ``WorkbenchBar``         — compact identity, tool tabs and layout menu.
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
import {
  lazy,
  startTransition,
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import { useNavigate } from '@tanstack/react-router'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { AgentView } from '../AgentView'
import { RecentUsageCard } from '../ChatWelcome'
import { AppShell } from '@/components/shell/AppShell'
import { WorkspaceInfoCard } from '../WorkspaceInfoCard'
import { WorkFolderSelector } from '../WorkFolderSelector'
import { ProjectInfoCard } from '../ProjectInfoCard'
import { useProjectQuery } from '@/queries/useProjectsQuery'
import { CodingSidebar } from '../CodingSidebar'
import { Sidebar } from '../Sidebar'
import { ChatOverlayPanels, ChatTrailingPanels } from '@/components/chat/ChatPanels'
import { PermissionApprovalModal } from '../PermissionApprovalModal'
import { AskUserQuestionModal } from '../AskUserQuestionModal'
import { useTodosQuery } from '@/queries/useTodosQuery'
import { useRegistryQuery, useTriggerDreamMutation, useWebBridgeSettingsQuery } from '@/queries'
import { getSessionWorkspaceRoot, getTeamSession, getWebBridgeStatus, replyPlanApproval, resolveTeamSession, setSessionPermissionMode } from '@/api/client'
import { apiBaseUrl } from '@/api/base-url'
import { useShallow } from 'zustand/react/shallow'
import { useTeamStore } from '@/stores/useTeamStore'
import { useToastStore } from '@/stores/useToastStore'
import { prependSession, prependWorkspaceSession } from '@/stores/cache-invalidation-bridge'
import { useUIStore } from '@/stores/useUIStore'
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
import { useDirectBrowserPresence } from '@/components/BrowserViewer/useDirectBrowserPresence'
import { areWebBridgeDefaultsEnabled } from '@/components/BrowserViewer/browserPreferences'
import { WorkbenchBar } from '@/components/workbench/WorkbenchBar'
import { WorkbenchDock, WorkbenchSurface } from '@/components/workbench/WorkbenchDock'
import { useSideChat } from '../SideChatPanel/useSideChat'
import type {
  AgentCapabilities as AgentCapabilitiesType,
  CodeReviewItem,
  RepositoryCodeReviews,
  TurnChangesPending,
  WorkspaceFileInfo,
} from '@/api/types'
import { useTeamCommands } from './useTeamCommands'
import { useTeamSse } from './useTeamSse'
import { useSlashCommandRegistry } from './useSlashCommandRegistry'
import { useMobileEdgeSwipes } from './useMobileEdgeSwipes'
import { VIEW_MODES, type ViewMode } from './types'
import { shouldStartAutomaticSplit } from './auto-layout'
import { AutomaticSplitTransition } from './AutomaticSplitTransition'
import { useAutoCollapseSidebar } from './useAutoCollapseSidebar'
import { codingFocusId, saveLastCodingWorkspace, workspaceLabel } from '@/utils/workspace'
import { setTraySession } from '@/lib/tray'
import { queryKeys } from '@/queries/keys'
import {
  codeReviewSessionPrompt,
  codeReviewSessionTags,
  parseCodeReviewSessionTags,
} from '@/lib/code-review-session'

const WorkspaceFilesPanel = lazy(() =>
  import('@/components/WorkspaceFilesPanel').then((module) => ({
    default: module.WorkspaceFilesPanel,
  })),
)
const ProcessPanel = lazy(() =>
  import('@/components/ProcessPanel').then((module) => ({
    default: module.ProcessPanel,
  })),
)
const CodingFileViewerPanel = lazy(() =>
  import('@/components/CodingFileViewerPanel').then((module) => ({
    default: module.CodingFileViewerPanel,
  })),
)
const CodingWorkspacePanel = lazy(() =>
  import('@/components/CodingWorkspacePanel').then((module) => ({
    default: module.CodingWorkspacePanel,
  })),
)
const GitWorkspacePanel = lazy(() =>
  import('@/components/GitWorkspacePanel').then((module) => ({
    default: module.GitWorkspacePanel,
  })),
)
const CodingSummaryPanel = lazy(() =>
  import('@/components/CodingSummaryPanel').then((module) => ({
    default: module.CodingSummaryPanel,
  })),
)
const loadMonitorView = () =>
  import('../MonitorView').then((module) => ({ default: module.MonitorView }))
const MonitorView = lazy(loadMonitorView)
const SideChatPanel = lazy(() =>
  import('../SideChatPanel').then((module) => ({ default: module.SideChatPanel })),
)
const BrowserViewer = lazy(() =>
  import('@/components/BrowserViewer').then((module) => ({
    default: module.BrowserViewer,
  })),
)
const TerminalPanel = lazy(() =>
  import('@/components/TerminalPanel').then((module) => ({
    default: module.TerminalPanel,
  })),
)
const WikiPanel = lazy(() =>
  import('@/components/WikiPanel').then((module) => ({ default: module.WikiPanel })),
)
const SchedulerPanel = lazy(() =>
  import('@/components/SchedulerPanel').then((module) => ({
    default: module.SchedulerPanel,
  })),
)
const PluginCenterPanel = lazy(() =>
  import('@/components/PluginCenterPanel').then((module) => ({
    default: module.PluginCenterPanel,
  })),
)
const loadSplitWorkbench = () =>
  import('./SplitWorkbench').then((module) => ({
    default: module.SplitWorkbench,
  }))
const SplitWorkbench = lazy(loadSplitWorkbench)

function PanelLoadingFallback() {
  return (
    <div
      className="flex h-full min-h-32 items-center justify-center"
      role="status"
      aria-label="Loading panel"
    >
      <div className="oa-panel-loader relative h-24 w-44 overflow-hidden rounded-2xl border border-(--color-border) bg-(--bg-card)/75 p-3 shadow-lg shadow-black/8">
        <span className="oa-panel-loader-scan absolute inset-y-0 w-16" aria-hidden="true" />
        <div className="relative flex h-full gap-2.5" aria-hidden="true">
          <div className="flex w-10 shrink-0 flex-col gap-1.5 rounded-lg border border-(--color-border-subtle) bg-(--bg-page)/65 p-2">
            <span className="oa-panel-loader-block h-2.5 w-2.5 rounded-sm bg-(--skeleton-sweep)" />
            <span className="oa-panel-loader-block h-1 w-full rounded-full bg-(--skeleton-base)" />
            <span className="oa-panel-loader-block h-1 w-4/5 rounded-full bg-(--skeleton-base)" />
            <span className="oa-panel-loader-block mt-auto h-1 w-3/5 rounded-full bg-(--skeleton-base)" />
          </div>
          <div className="flex min-w-0 flex-1 flex-col gap-2">
            <div className="flex items-center gap-1.5">
              <span className="oa-panel-loader-block h-2 w-2 rounded-full bg-(--skeleton-sweep)" />
              <span className="oa-panel-loader-block h-1.5 w-14 rounded-full bg-(--skeleton-base)" />
            </div>
            <span className="oa-panel-loader-block h-5 w-full rounded-md bg-(--skeleton-base)" />
            <span className="oa-panel-loader-block h-2 w-5/6 rounded-full bg-(--skeleton-base)" />
            <span className="oa-panel-loader-block h-2 w-2/3 rounded-full bg-(--skeleton-base)" />
            <div className="mt-auto flex justify-end gap-1">
              <span className="oa-panel-loader-dot h-1.5 w-1.5 rounded-full bg-(--skeleton-sweep)" />
              <span className="oa-panel-loader-dot h-1.5 w-1.5 rounded-full bg-(--skeleton-sweep)" />
              <span className="oa-panel-loader-dot h-1.5 w-1.5 rounded-full bg-(--skeleton-sweep)" />
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

interface TeamChatViewProps {
  sessionId?: string
  mode?: 'work' | 'coding'
  workspace?: string | null
  codingSessionLoading?: boolean
}

// Stable fallbacks so narrowed selectors below never return a fresh
// reference when the underlying stream field is absent.
const EMPTY_AGENT_STREAMS: Record<string, AgentStream> = {}
const EMPTY_BLOCKS: AgentStream['blocks'] = []
const EMPTY_REVERTED_MESSAGES: Array<{ role: string; content: string }> = []
const TEAM_SESSION_ID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

interface PendingCodeReviewStart {
  sessionId: string
  prompt: string
  workspace: string
  model: string | null
  thinkingLevel: string | null
  fastMode: boolean
}

interface ActiveAgentTranscriptProps {
  activeAgent: string
  emptyState?: React.ReactNode
  isContinuing: boolean
  isLead: boolean
  onAddSelectionToChat: (selectedText: string) => void
  onContinue?: () => void
  onRequestSelectionDetails: (selectedText: string) => void
  onSendToSideChat: (selectedText: string) => void
  turnChanges: TurnChangesPending | null
}

/**
 * Per-frame stream subscription boundary.
 *
 * Keeping `currentBlocks` here prevents every token from re-rendering the
 * route shell, workbench, panels, and composer. Those surfaces now update only
 * for structural/primitive state changes; the live transcript remains hot.
 */
function ActiveAgentTranscript({
  activeAgent,
  emptyState,
  isContinuing,
  isLead,
  onAddSelectionToChat,
  onContinue,
  onRequestSelectionDetails,
  onSendToSideChat,
  turnChanges,
}: ActiveAgentTranscriptProps) {
  const blocks = useTeamStore(
    (state) => state.agentStreams[activeAgent]?.blocks ?? EMPTY_BLOCKS,
  )
  const currentBlocks = useTeamStore(
    (state) => state.agentStreams[activeAgent]?.currentBlocks ?? EMPTY_BLOCKS,
  )
  const status = useTeamStore(
    (state) => state.agentStreams[activeAgent]?.status,
  )
  const lastError = useTeamStore(
    (state) => state.agentStreams[activeAgent]?.lastError,
  )

  return (
    <AgentView
      blocks={blocks}
      currentBlocks={currentBlocks}
      isWorking={status === 'working'}
      isError={status === 'error'}
      lastError={lastError}
      isContinuing={isContinuing}
      onContinue={isLead ? onContinue : undefined}
      onAddSelectionToChat={onAddSelectionToChat}
      onRequestSelectionDetails={onRequestSelectionDetails}
      onSendToSideChat={onSendToSideChat}
      turnChanges={turnChanges}
      emptyState={emptyState}
    />
  )
}

export function TeamChatView({ sessionId, mode = 'work', workspace = null, codingSessionLoading = false }: TeamChatViewProps) {
  const workOrCodingMode: 'work' | 'coding' = mode === 'coding' ? 'coding' : 'work'
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
  const [codingFileViewer, setCodingFileViewer] = useState<WorkspaceFileInfo | null>(null)
  const [codingFileViewerMode, setCodingFileViewerMode] = useState<'file' | 'diff' | 'preview'>('file')
  const [openWorkspaceDialogKey, setOpenWorkspaceDialogKey] = useState(0)
  const [codingWorkspacePickerPortal, setCodingWorkspacePickerPortal] = useState<HTMLDivElement | null>(null)
  const [showActivity, setShowActivity] = useState(false)
  const [todosOpen, setTodosOpen] = useState(false)
  const [permissionMode, setPermissionMode] = useState<import('@/api/types').PermissionMode>('auto')
  const [showMobileActions, setShowMobileActions] = useState(false)
  const [showPalette, setShowPalette] = useState(false)
  const [fileRefsEnabled, setFileRefsEnabled] = useState(false)
  const [viewMode, setViewModeState] = useState<ViewMode>('agent')
  const [pendingViewMode, setPendingViewMode] = useState<ViewMode | null>(null)
  const [automaticSplitTransition, setAutomaticSplitTransition] = useState(false)
  const previousActiveAgentCountRef = useRef(0)
  const layoutSwitchFrameRef = useRef<number | null>(null)
  const [sideChatQuote, setSideChatQuote] = useState<string | null>(null)
  const [webBridgeEnabled, setWebBridgeEnabled] = useState(false)
  const [webBridgeDialogOpen, setWebBridgeDialogOpen] = useState(false)
  const [pendingCodeReviewStart, setPendingCodeReviewStart] =
    useState<PendingCodeReviewStart | null>(null)

  // On mobile, always force agent view — split/monitor require a wide screen.
  // Also close any desktop-only panels when shrinking to mobile.
  const effectiveViewMode: ViewMode = isMobile ? 'agent' : viewMode
  const displayedViewMode: ViewMode = isMobile
    ? 'agent'
    : pendingViewMode ?? viewMode
  const setViewMode = useCallback((nextViewMode: ViewMode) => {
    setAutomaticSplitTransition(false)
    setPendingViewMode(nextViewMode)
    if (layoutSwitchFrameRef.current !== null) {
      cancelAnimationFrame(layoutSwitchFrameRef.current)
    }
    // Let the dropdown close and its label update before React begins the
    // Markdown-heavy layout render. The transition remains interruptible.
    layoutSwitchFrameRef.current = requestAnimationFrame(() => {
      layoutSwitchFrameRef.current = null
      startTransition(() => setViewModeState(nextViewMode))
    })
  }, [])
  const completeAutomaticSplit = useCallback(() => {
    setViewMode('split')
  }, [setViewMode])

  useEffect(() => {
    if (pendingViewMode === null || pendingViewMode !== viewMode) return
    const frame = requestAnimationFrame(() => setPendingViewMode(null))
    return () => cancelAnimationFrame(frame)
  }, [pendingViewMode, viewMode])

  useEffect(() => () => {
    if (layoutSwitchFrameRef.current !== null) {
      cancelAnimationFrame(layoutSwitchFrameRef.current)
    }
  }, [])

  // Remove first-click network/transform latency. Hidden layout code is
  // downloaded while the browser is idle; transcript data is not subscribed
  // or rendered until the layout is actually requested.
  useEffect(() => {
    if (isMobile) return
    const preload = () => {
      void loadSplitWorkbench()
      void loadMonitorView()
    }
    if (typeof window.requestIdleCallback === 'function') {
      const idleId = window.requestIdleCallback(preload, { timeout: 1_000 })
      return () => window.cancelIdleCallback(idleId)
    }
    const timer = window.setTimeout(preload, 200)
    return () => window.clearTimeout(timer)
  }, [isMobile])
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
  const turnChanges = useTeamStore((s) => s.turnChanges)

  const dreamMutation = useTriggerDreamMutation()
  const pushToast = useToastStore((s) => s.push)

  const activeAgent    = useTeamStore((s) => s.activeAgent)
  const agentNames     = useTeamStore((s) => s.agentNames)
  const isTeamWorking  = useTeamStore((s) => s.isTeamWorking)
  const isContinuing   = useTeamStore((s) => s.isContinuing)
  const sessionIdState = useTeamStore((s) => s.sessionId)
  useDirectBrowserPresence(sessionIdState)
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
  const sessionTags    = useTeamStore((s) => s.sessionTags)
  const sessionModel   = useTeamStore((s) => s.sessionModel)
  const sessionThinkingLevel = useTeamStore((s) => s.sessionThinkingLevel)
  const sessionFastMode = useTeamStore((s) => s.sessionFastMode)
  const leadName       = useTeamStore((s) => s.leadName)
  const isConnected    = useTeamStore((s) => s.isConnected)
  const isSessionLoading = useTeamStore((s) => s.isSessionLoading)
  const workbenchTabs = useUIStore((s) => s.workbenchTabs)
  const activeWorkbenchTool = useUIStore((s) => s.activeWorkbenchTool)
  const workbenchOpen = useUIStore((s) => s.workbenchOpen)
  const workbenchMaximized = useUIStore((s) => s.workbenchMaximized)
  const pullRequestsScope = useUIStore((s) => s.pullRequestsScope)
  const openWorkbenchTool = useUIStore((s) => s.openWorkbenchTool)
  const createWorkbenchTab = useUIStore((s) => s.createWorkbenchTab)
  const restoreWorkbenchTabs = useUIStore((s) => s.restoreWorkbenchTabs)
  const toggleWorkbenchTool = useUIStore((s) => s.toggleWorkbenchTool)
  const closeWorkbenchTab = useUIStore((s) => s.closeWorkbenchTab)
  const closeWorkbenchTool = useUIStore((s) => s.closeWorkbenchTool)
  const updateWorkbenchTab = useUIStore((s) => s.updateWorkbenchTab)
  const wikiOpen = workbenchTabs.some((tab) => tab.tool === 'wiki')
  const browserOpen = workbenchTabs.some((tab) => tab.tool === 'browser')
  const sideChatOpen = workbenchTabs.some((tab) => tab.tool === 'side-chat')
  const toggleWiki = useUIStore((s) => s.toggleWiki)
  const toggleScheduler = useUIStore((s) => s.toggleScheduler)
  const toggleBrowser = useUIStore((s) => s.toggleBrowser)
  const toggleTerminal = useUIStore((s) => s.toggleTerminal)
  const openGitChanges = useUIStore((s) => s.openGitChanges)
  const previousWorkbenchSessionRef = useRef(sessionIdState)

  useEffect(() => {
    if (previousWorkbenchSessionRef.current !== sessionIdState) {
      closeWorkbenchTool('terminal')
      closeWorkbenchTool('browser')
      closeWorkbenchTool('side-chat')
      previousWorkbenchSessionRef.current = sessionIdState
    }
    if (!sessionIdState) {
      closeWorkbenchTool('terminal')
      closeWorkbenchTool('browser')
      closeWorkbenchTool('side-chat')
      if (mode !== 'coding') closeWorkbenchTool('files')
    }
    if (mode !== 'coding') {
      closeWorkbenchTool('graph')
      closeWorkbenchTool('source-control')
      closeWorkbenchTool('pull-requests')
    }
    if (mode === 'coding' && !workspace) {
      closeWorkbenchTool('files')
      closeWorkbenchTool('graph')
      closeWorkbenchTool('source-control')
    }
  }, [closeWorkbenchTool, mode, sessionIdState, workspace])

  // Terminal processes intentionally survive WebSocket disconnects. Restore
  // them as top-level Workbench tabs instead of rebuilding a nested tab bar.
  useEffect(() => {
    if (!sessionIdState) return
    let alive = true
    void fetch(`${apiBaseUrl()}/team/${sessionIdState}/terminals`)
      .then(async (response) => {
        if (!response.ok) return []
        const body = (await response.json()) as { terminals?: { id?: string }[] }
        return (body.terminals ?? [])
          .map((terminal) => terminal.id)
          .filter((id): id is string => Boolean(id))
      })
      .then((ids) => {
        if (alive && ids.length > 0) {
          restoreWorkbenchTabs(
            'terminal',
            ids.map((id) => ({ id })),
          )
        }
      })
      .catch(() => {})
    return () => {
      alive = false
    }
  }, [restoreWorkbenchTabs, sessionIdState])
  // Sidebar collapse is shell-level state shared by all three mode sidebars;
  // AppShell renders the toggle button + Ctrl+B, these are the programmatic
  // entry points (workspace CTAs, command palette, mobile hamburger).
  const toggleSidebarCollapsed = useUIStore((s) => s.toggleSidebarCollapsed)
  const setSidebarCollapsed = useUIStore((s) => s.setSidebarCollapsed)

  // The Workbench writes its width directly to the DOM while dragging, so
  // observe the resulting conversation width instead of waiting for pointer-up.
  useAutoCollapseSidebar({ mainColumnRef, workbenchOpen, isMobile })

  // Finalized blocks update on turn boundaries and feed composer history.
  // The hot `currentBlocks` array is intentionally subscribed inside
  // ActiveAgentTranscript so each token cannot re-render this route shell.
  const activeBlocks        = useTeamStore((s) => s.activeAgent ? s.agentStreams[s.activeAgent]?.blocks : undefined)
  const activeCurrentBlockCount = useTeamStore(
    (s) => s.activeAgent ? s.agentStreams[s.activeAgent]?.currentBlocks.length ?? 0 : 0,
  )
  const hasActiveStream     = useTeamStore((s) => Boolean(s.activeAgent && s.agentStreams[s.activeAgent]))
  const activeGoal          = useTeamStore((s) => s.activeGoal)

  // Per-purpose narrowed subscriptions — the full ``agentStreams`` map gets a
  // new reference on every streamed token, so subscribing to it wholesale
  // re-rendered this entire shell per SSE event. ``useShallow`` keeps the
  // derived array/object identities stable while statuses are unchanged.
  const splitAgentNames = useTeamStore(useShallow(
    (s) => s.agentNames.filter((name) => s.agentStreams[name]?.status !== 'offline'),
  ))
  const activeAgentCount = useTeamStore(
    (s) => s.agentNames.reduce(
      (count, name) => count + (s.agentStreams[name]?.status === 'working' ? 1 : 0),
      0,
    ),
  )
  useEffect(() => {
    const previousActiveCount = previousActiveAgentCountRef.current
    previousActiveAgentCountRef.current = activeAgentCount
    if (!shouldStartAutomaticSplit({
      previousActiveCount,
      activeCount: activeAgentCount,
      viewMode,
      isMobile,
    })) return

    const frame = requestAnimationFrame(() => setAutomaticSplitTransition(true))
    return () => cancelAnimationFrame(frame)
  }, [activeAgentCount, isMobile, viewMode])
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
  const activeSessionId = sessionIdState ?? sessionId ?? null
  const validWorkSessionId = activeSessionId && TEAM_SESSION_ID_RE.test(activeSessionId)
    ? activeSessionId
    : null
  const reviewSessionContext = useMemo(
    () => parseCodeReviewSessionTags(sessionTags),
    [sessionTags],
  )
  const persistedWebBridgeEnabled = sessionTags?.includes('webbridge')
  const webBridgeSettings = useWebBridgeSettingsQuery()
  const webBridgePolicyEnabled = webBridgeSettings.data?.enabled !== false
  useEffect(() => {
    let cancelled = false
    if (!webBridgePolicyEnabled) {
      setWebBridgeEnabled(false)
      return
    }
    const requested = activeSessionId
      ? sessionTags === undefined
        ? null
        : Boolean(persistedWebBridgeEnabled)
      : areWebBridgeDefaultsEnabled()
    if (requested === null) return

    // Fail closed while connection state is unknown. A persisted session tag
    // or the new-chat default is only a preference; it must never make the UI
    // appear enabled before a live extension has been verified.
    setWebBridgeEnabled(false)
    if (!requested) return
    void getWebBridgeStatus()
      .then((status) => {
        if (!cancelled && status.connected) setWebBridgeEnabled(true)
      })
      .catch(() => {
        // Backend/status failures stay disabled.
      })
    return () => {
      cancelled = true
    }
  }, [activeSessionId, persistedWebBridgeEnabled, sessionTags, webBridgePolicyEnabled])
  // Lead capabilities — used to drive composer affordances (slash menu).
  const agentWorkspace = mode === 'coding' ? workspace : null
  const workWorkspaceQuery = useQuery({
    queryKey: queryKeys.team.workspaceRoot(validWorkSessionId ?? ''),
    queryFn: () => getSessionWorkspaceRoot(validWorkSessionId as string),
    enabled: mode === 'work' && Boolean(validWorkSessionId),
    staleTime: 30_000,
  })
  const workbenchWorkspace = mode === 'work'
    ? workWorkspaceQuery.data?.workspace_root ?? null
    : agentWorkspace
  const hasCodingWorkspace = mode !== 'coding' || Boolean(workspace)
  const isCodingSessionLoading = mode === 'coding' && codingSessionLoading

  // Watch workspace for external file changes (other editors, git, etc.)
  useWorkspaceFileWatcher(agentWorkspace)
  const { data: teamAgentsData, isLoading: teamAgentsLoading } = useTeamAgentsQuery(
    agentWorkspace,
    hasCodingWorkspace,
    'coding',
  )
  const leadAgent = teamAgentsData?.agents?.find((a) => a.is_lead)
  const leadCapabilities: AgentCapabilitiesType | undefined = leadAgent?.capabilities
  const selectedModel = sessionModel ?? ''
  const selectedThinkingLevel = sessionThinkingLevel

  // When the user selects a session model override, derive capabilities from
  // the model registry so file-upload affordances match the selected model.
  // Also used as fallback when the team hasn't started yet (leadCapabilities
  // is undefined) but we know which model will be used.
  const registryQ = useRegistryQuery()
  // The registry is the authoritative usable-model view and is already needed
  // for capabilities. Avoid a separate providers request on every chat mount
  // just to decide whether the setup banner should be visible.
  const hasConfiguredModelProvider =
    registryQ.isLoading || (registryQ.data?.models.length ?? 0) > 0
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
    mode: workOrCodingMode,
    sessionId: sessionIdState,
    workspace,
    enabled: fileRefsEnabled && (mode === 'coding' ? Boolean(workspace) : Boolean(sessionIdState)),
  })

  // ── Init / reconnect ───────────────────────────────────────────────────────

  const abortRef = useTeamSse({
    sessionId,
    agentWorkspace,
    hasCodingWorkspace,
    isCodingSessionLoading,
    mode,
  })

  // A newly-created review session is routed first, restored by useTeamSse,
  // and only then receives its one-time context prompt. Waiting for the route
  // and restore avoids racing the previous session's stream with the new send.
  useEffect(() => {
    const pending = pendingCodeReviewStart
    if (!pending || sessionId !== pending.sessionId) return
    const state = useTeamStore.getState()
    if (state.sessionId !== pending.sessionId || state.isSessionLoading) return
    setPendingCodeReviewStart(null)
    void state.sendMessage(pending.prompt, undefined, {
      mode: 'coding',
      workspace: pending.workspace,
      model: pending.model,
      thinkingLevel: pending.thinkingLevel,
      fastMode: pending.fastMode,
    }).then(() => {
      const error = useTeamStore.getState().error
      pushToast(
        error
          ? {
              tone: 'error',
              title: 'Review chat could not start',
              description: error,
            }
          : {
              tone: 'success',
              title: 'Review context sent',
              description: 'This PR/MR is now linked to its Coding session.',
            },
      )
    })
  }, [pendingCodeReviewStart, pushToast, sessionId, isSessionLoading])

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
  }, [beginResolvedSession, isEmptyIdleSession, mode, navigate, queryClient, sessionIdState, sessionModel, sessionThinkingLevel, workspace, abortRef])

  const handleOpenCodeReviewChat = useCallback(async (
    repository: RepositoryCodeReviews,
    item: CodeReviewItem,
  ) => {
    const tags = codeReviewSessionTags(repository, item)
    const carryModel = sessionIdState ? sessionModel : null
    const carryThinkingLevel = sessionIdState ? sessionThinkingLevel : null
    const carryFastMode = sessionIdState ? sessionFastMode : false
    try {
      const session = await resolveTeamSession({
        mode: 'coding',
        workspace: repository.project_id ? undefined : repository.workspace,
        project_id: repository.project_id,
        model: carryModel,
        thinkingLevel: carryThinkingLevel,
        tags,
        tagMatch: 'contains',
      })
      if (session.id === sessionIdState) {
        useTeamStore.setState({ sessionTags: session.tags ?? tags })
        useUIStore.getState().closeWorkbench()
        pushToast({
          tone: 'info',
          title: 'Already in this review chat',
          description: `Review #${item.number} is linked to the current session.`,
        })
        return
      }
      abortRef.current?.abort()
      abortRef.current = null
      inputRef.current?.setValue('')
      inputRef.current?.setFiles([])
      beginResolvedSession(session.id, {
        mode: 'coding',
        workspace: session.workspace ?? repository.workspace,
        model: session.model ?? carryModel,
        thinkingLevel: session.thinking_level ?? carryThinkingLevel,
        fastMode: carryFastMode,
        skipInitialRestore: session.created,
      })
      useTeamStore.setState({
        projectId: session.project_id ?? repository.project_id,
        sessionTags: session.tags ?? tags,
      })
      prependSession(queryClient, session)
      if (repository.project_id) {
        void queryClient.invalidateQueries({
          queryKey: queryKeys.team.sessions.project(repository.project_id),
        })
      } else {
        prependWorkspaceSession(queryClient, repository.workspace, session)
        saveLastCodingWorkspace(repository.workspace)
      }
      const resolvedWorkspace = session.workspace ?? repository.workspace
      const focusId = codingFocusId({
        project_id: session.project_id ?? repository.project_id,
        workspace: resolvedWorkspace,
      })
      if (session.created) {
        setPendingCodeReviewStart({
          sessionId: session.id,
          prompt: codeReviewSessionPrompt(repository, item),
          workspace: resolvedWorkspace,
          model: session.model ?? carryModel,
          thinkingLevel: session.thinking_level ?? carryThinkingLevel,
          fastMode: carryFastMode,
        })
      } else {
        pushToast({
          tone: 'info',
          title: 'Review chat reopened',
          description: `Continuing the linked session for review #${item.number}.`,
        })
      }
      useUIStore.getState().closeWorkbench()
      navigate(
        focusId
          ? {
              to: '/coding/$focusId/$sessionId',
              params: { focusId, sessionId: session.id },
            }
          : { to: '/coding' },
      )
    } catch (err) {
      pushToast({
        tone: 'error',
        title: 'Unable to open review chat',
        description: err instanceof Error ? err.message : String(err),
      })
    }
  }, [
    abortRef,
    beginResolvedSession,
    navigate,
    pushToast,
    queryClient,
    sessionFastMode,
    sessionIdState,
    sessionModel,
    sessionThinkingLevel,
  ])

  const handleWorkspaceFiles = useCallback(() => {
    if (mode === 'coding') {
      if (workspace) {
        if (isMobile) setMobileSidebarOpen(false)
        toggleWorkbenchTool('files')
      } else {
        setSidebarCollapsed(false)
        setOpenWorkspaceDialogKey((value) => value + 1)
      }
      return
    }
    if (sessionIdState) {
      toggleWorkbenchTool('files')
    }
  }, [isMobile, mode, workspace, sessionIdState, setSidebarCollapsed, toggleWorkbenchTool])

  const handleActivityToggle = useCallback(() => {
    setShowActivity((value) => {
      const nextOpen = !value
      return nextOpen
    })
  }, [])

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
    inputRef.current?.setQuoteContext(quote)
    inputRef.current?.appendValue(comment)
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

  /** Editor context menu → Chat: append selected code block to composer */
  const handleAddCodeToChat = useCallback((code: string, path: string, startLine: number, endLine: number) => {
    const lineRef = startLine === endLine ? `L${startLine}` : `L${startLine}-L${endLine}`
    inputRef.current?.appendValue(`@${path}#${lineRef}\n\`\`\`\n${code}\n\`\`\`\n`)
    inputRef.current?.focus()
  }, [])

  const handleSendToSideChat = useCallback((selectedText: string) => {
    setSideChatQuote(selectedText)
    openWorkbenchTool('side-chat')
  }, [openWorkbenchTool])

  const handleAddSelectionToChat = useCallback((selectedText: string) => {
    inputRef.current?.setQuoteContext(selectedText)
    inputRef.current?.focus()
  }, [])

  const handleRequestSelectionDetails = useCallback((selectedText: string) => {
    inputRef.current?.setQuoteContext(selectedText)
    inputRef.current?.appendValue('Please provide more details about this.')
    inputRef.current?.focus()
  }, [])

  const handleWebBridgeEnabledChange = useCallback(async (enabled: boolean) => {
    if (!enabled) {
      setWebBridgeEnabled(false)
      return
    }

    // The popover disables this action while disconnected, but keep the
    // parent defensive so keyboard/race/programmatic calls cannot bypass it.
    setWebBridgeEnabled(false)
    try {
      const status = await getWebBridgeStatus()
      if (status.connected) {
        setWebBridgeEnabled(true)
        return
      }
    } catch {
      // Use the same disconnected UX for status failures.
    }
    pushToast({
      tone: 'error',
      title: 'WebBridge is not connected',
      description: 'Connect the browser extension before enabling WebBridge.',
    })
    setWebBridgeDialogOpen(true)
  }, [pushToast])

  // Lifted above the panel: the side chat session (and any in-flight
  // generation + SSE stream) survives closing/reopening the panel.
  const sideChat = useSideChat(sessionIdState)
  const openSideChat = sideChat.openSideChat

  // Consume one-shot open requests from the sidebar session-row icon: the
  // panel opens once the requested session is the active one.
  const sideChatRequest = useUIStore((s) => s.sideChatRequest)
  useEffect(() => {
    if (sideChatRequest && sessionIdState === sideChatRequest) {
      openWorkbenchTool('side-chat')
      useUIStore.getState().clearSideChatRequest()
    }
  }, [openWorkbenchTool, sideChatRequest, sessionIdState])

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
    setCodingFileViewerMode('file')
  }, [])

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
    queryClient.fetchQuery({
      queryKey: queryKeys.team.sessions.detail(sessionIdState),
      queryFn: () => getTeamSession(sessionIdState),
      staleTime: 30_000,
    })
      .then((session) => {
        if (!cancelled && session.permission_mode) {
          setPermissionMode(session.permission_mode as import('@/api/types').PermissionMode)
        }
      })
      .catch(() => {/* non-fatal */})
    return () => { cancelled = true }
  }, [queryClient, sessionIdState])

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
    tryHandleBuiltinGoalCommand,
    tryHandleWorkflowCommand,
    expandUserCommand,
    startWorkflowRun,
    runInputsRequest,
    setRunInputsRequest,
    runGoalCommand,
  } = useSlashCommandRegistry({
    mode,
    workspace,
    agentWorkspace,
    workspaceRoots: activeProject?.workspaces.map((item) => item.path),
    sessionId,
    sessionIdState,
    selectedModel,
    selectedThinkingLevel,
    inputRef,
    handleNewSession,
  })

  const cycleViewMode = useCallback(() => {
    const currentViewMode = pendingViewMode ?? viewMode
    const idx = VIEW_MODES.indexOf(currentViewMode)
    setViewMode(VIEW_MODES[(idx + 1) % VIEW_MODES.length])
  }, [pendingViewMode, setViewMode, viewMode])

  const commands = useTeamCommands({
    viewMode,
    cycleViewMode,
    setViewMode,
    handleWorkspaceFiles,
    handleCodingSidebarToggle,
    mode: workOrCodingMode,
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
    // Ctrl+M / Ctrl+S / Ctrl+K — open Memory, Scheduler, or Plugins.
    m: toggleWiki,
    s: toggleScheduler,
    k: () => toggleWorkbenchTool('plugins'),
    t: toggleBrowser,
    g: mode === 'coding' && workspace ? openGitChanges : undefined,
    // Ctrl+` — toggle the AI Terminal (conventional terminal shortcut).
    '`': toggleTerminal,
    // Ctrl+I — focus the chat input (dispatched via CustomEvent so future
    // callers don't need a ref to the input).
    'i': () => window.dispatchEvent(new CustomEvent('focus-chat-input')),
    // Ctrl+; — toggle the side chat tool.
    ';': () => toggleWorkbenchTool('side-chat'),
  })

  // Agent cycling is exposed through the command palette ("Next Agent" /
  // "Previous Agent") on purpose. Bare Tab must never be captured here: a
  // window-level preventDefault on Tab removes sequential focus navigation from
  // every surface this view is mounted under (sidebar, topbar, composer,
  // settings, dialogs), which leaves the app unusable by keyboard.

  const closeCodingPanels = useCallback(() => {
    closeWorkbenchTool('files')
    setCodingFileViewer(null)
  }, [closeWorkbenchTool])

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
    activeCurrentBlockCount === 0
  const historySkeleton = (
    <div className="relative flex min-h-0 flex-1 flex-col overflow-hidden" aria-hidden="true">
      <div className="flex-1 overflow-hidden">
        <div className="mx-auto max-w-4xl space-y-8 px-3 py-4">
          <div className="flex justify-end">
            <div className="skeleton-shimmer h-9 w-44 rounded-2xl" />
          </div>
          <div className="space-y-2.5">
            <div className="skeleton-shimmer h-3.5 w-3/4 rounded-lg" />
            <div className="skeleton-shimmer h-3.5 w-full rounded-lg" />
            <div className="skeleton-shimmer h-3.5 w-2/3 rounded-lg" />
            <div className="skeleton-shimmer mt-1 h-3.5 w-5/6 rounded-lg" />
          </div>
          <div className="flex justify-end">
            <div className="skeleton-shimmer h-9 w-32 rounded-2xl" />
          </div>
          <div className="space-y-2.5">
            <div className="skeleton-shimmer h-3.5 w-1/2 rounded-lg" />
            <div className="skeleton-shimmer h-3.5 w-5/6 rounded-lg" />
            <div className="skeleton-shimmer h-3.5 w-3/4 rounded-lg" />
          </div>
        </div>
      </div>
    </div>
  )

  // ── Render ─────────────────────────────────────────────────────────────────

  // One sidebar instance per mode — the inactive mode's sidebar (and its
  // queries) stays unmounted instead of being CSS-hidden.
  const desktopSidebar = !isMobile
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
  const mobileSidebar = isMobile
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

  // Workbench lives in AppShell's full-height trailing column so opening it
  // constrains both the conversation canvas and the compact topbar.
  const workbenchPanel = (
    <WorkbenchDock
        mode={mode}
        sessionId={sessionIdState}
        workspace={workspace}
      >
      <Suspense fallback={<PanelLoadingFallback />}>
        {mode === 'coding' && workspace && (
          <>
            <WorkbenchSurface tool="overview">
              {(_tab, active) => (
                <CodingSummaryPanel
                  workspace={workspace}
                  sessionId={sessionIdState}
                  open={active}
                  isWorking={isTeamWorking}
                  onOpenFile={(path) => {
                    setCodingFileViewer({
                      path,
                      name: path.split('/').pop() ?? path,
                      size: 0,
                      mtime: 0,
                      mime: 'text/plain',
                    })
                    setCodingFileViewerMode('diff')
                  }}
                />
              )}
            </WorkbenchSurface>
            <WorkbenchSurface tool="files">
              <CodingWorkspacePanel
                workspace={workspace}
                open
                view="files"
                embedded
                selectedFilePath={codingFileViewer?.path ?? null}
                selectedFile={codingFileViewer}
                onFileSelect={handleCodingFileSelect}
                initialFileViewMode={codingFileViewerMode}
                onAddFileComment={handleAddFileComment}
                onSendFileToChat={handleSendToChat}
                onClose={() => closeWorkbenchTool('files')}
                projectId={projectIdState}
              />
            </WorkbenchSurface>
            <WorkbenchSurface tool="graph">
              <CodingWorkspacePanel
                workspace={workspace}
                open
                view="graph"
                embedded
                selectedFilePath={codingFileViewer?.path ?? null}
                onFileSelect={handleCodingFileSelect}
                onClose={() => closeWorkbenchTool('graph')}
                projectId={projectIdState}
              />
            </WorkbenchSurface>
          </>
        )}
        {mode !== 'coding' && (
          <WorkbenchSurface tool="files">
            <WorkspaceFilesPanel
              open
              embedded
              sessionId={sessionIdState}
              onClose={() => closeWorkbenchTool('files')}
            />
          </WorkbenchSurface>
        )}
        <WorkbenchSurface tool="terminal">
          {(tab, active) => (
            <TerminalPanel
              sessionId={sessionIdState}
              terminalId={tab.id}
              active={active}
            />
          )}
        </WorkbenchSurface>
        <WorkbenchSurface tool="processes">
          {(_tab, active) => (
            <ProcessPanel active={active} currentSessionId={sessionIdState} />
          )}
        </WorkbenchSurface>
        <WorkbenchSurface tool="browser">
          {(tab, active) => (
            <BrowserViewer
              sessionId={sessionIdState}
              tabId={tab.id}
              initialUrl={tab.initialUrl}
              open={browserOpen}
              visible={active}
              embedded
              onNewTab={(url) => createWorkbenchTab('browser', {
                initialUrl: url,
                title: 'New tab',
              })}
              onTitleChange={(title) => updateWorkbenchTab(tab.id, { title })}
              onClose={() => closeWorkbenchTab(tab.id)}
            />
          )}
        </WorkbenchSurface>
        {sessionIdState && (
          <WorkbenchSurface tool="side-chat">
            <SideChatPanel
              isOpen={sideChatOpen}
              embedded
              onClose={() => closeWorkbenchTool('side-chat')}
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
          </WorkbenchSurface>
        )}
        <WorkbenchSurface tool="wiki">
          <WikiPanel
            open={wikiOpen}
            embedded
            onClose={() => closeWorkbenchTool('wiki')}
          />
        </WorkbenchSurface>
        <WorkbenchSurface tool="scheduler">
          <SchedulerPanel
            open={workbenchTabs.some((tab) => tab.tool === 'scheduler')}
            embedded
            onClose={() => closeWorkbenchTool('scheduler')}
            contextMode={workOrCodingMode}
            contextWorkspace={mode === 'coding' ? workspace : null}
          />
        </WorkbenchSurface>
        <WorkbenchSurface tool="plugins">
          <PluginCenterPanel />
        </WorkbenchSurface>
        {mode === 'coding' && (
          <>
            <WorkbenchSurface tool="source-control">
              {(_tab, active) => (
                <GitWorkspacePanel
                  open={active}
                  view="changes"
                  scope="session"
                  workspace={workspace}
                  projectId={projectIdState}
                  focus={null}
                  onOpenInChat={handleOpenCodeReviewChat}
                  onOpenWorkspace={handleOpenWorkspaceDialog}
                />
              )}
            </WorkbenchSurface>
            <WorkbenchSurface tool="pull-requests">
              {(_tab, active) => (
                <GitWorkspacePanel
                  open={active}
                  view="reviews"
                  scope={pullRequestsScope}
                  workspace={workspace}
                  projectId={projectIdState}
                  focus={reviewSessionContext}
                  onOpenInChat={handleOpenCodeReviewChat}
                  onOpenWorkspace={handleOpenWorkspaceDialog}
                />
              )}
            </WorkbenchSurface>
          </>
        )}
      </Suspense>
    </WorkbenchDock>
  )

  // Contextual panels that only constrain the body row.
  const trailingPanels = (
    <>
      <ChatTrailingPanels
        onQuoteComment={handlePlanQuoteComment}
        showActivity={showActivity}
        onCloseActivity={() => setShowActivity(false)}
        workspace={workspace}
        mode={mode}
        onOpenChangedFile={(path) => {
          if (mode === 'coding' && workspace) {
            setCodingFileViewer({
              path,
              name: path.split('/').pop() ?? path,
              size: 0,
              mtime: 0,
              mime: 'text/plain',
            })
            setCodingFileViewerMode('diff')
          }
        }}
      />
      {mode === 'coding' && <div ref={setCodingWorkspacePickerPortal} className="contents" />}
    </>
  )

  // On desktop, Coding panels sit in AppShell's outer trailing column — the
  // same structural slot Work uses. This constrains both the chat *and its
  // topbar*; mobile keeps its full-screen overlay behavior.
  const fullHeightTrailing = (
    <>
      {workbenchPanel}
      {mode === 'coding'
        && workspace
        && !isMobile
        && !workbenchMaximized
        && codingFileViewer !== null
        && !(workbenchOpen && activeWorkbenchTool === 'files')
        && (
        <Suspense fallback={<PanelLoadingFallback />}>
          <CodingFileViewerPanel
            key={`${codingFileViewer.path}:${codingFileViewerMode}`}
            workspace={codingFileViewer.sourceWorkspace ?? workspace}
            file={codingFileViewer}
            mobile={false}
            desktopOverlay={false}
            initialViewMode={codingFileViewerMode}
            onAddComment={handleAddFileComment}
            onSendToChat={handleSendToChat}
            onAddCodeToChat={handleAddCodeToChat}
            onClose={() => {
              setCodingFileViewer(null)
              setCodingFileViewerMode('file')
            }}
          />
        </Suspense>
      )}
    </>
  )
  const handleComposerSubmit = useCallback(async (content: string, files?: File[]) => {
    if (webBridgeEnabled) {
      try {
        const status = await getWebBridgeStatus()
        if (!status.connected) {
          setWebBridgeEnabled(false)
          pushToast({
            tone: 'error',
            title: 'WebBridge is not connected',
            description: 'Connect the browser extension before sending this message.',
          })
          setWebBridgeDialogOpen(true)
          return false
        }
      } catch {
        setWebBridgeEnabled(false)
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
    if (/^\/loop(?:\s|:|$)/.test(content.trim())) {
      pushToast({
        tone: 'error',
        title: '/loop has been removed',
        description: 'Use /goal <objective> to start durable autonomous work.',
      })
      return true
    }
    if (await tryHandleBuiltinGoalCommand(content)) return true
    if (await tryHandleWorkflowCommand(content)) return true
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
    tryHandleBuiltinGoalCommand,
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
      mainHidden={workbenchMaximized && activeWorkbenchTool !== null}
      mainId="main"
      mainRef={mainColumnRef}
      onTouchStart={onTouchStart}
      onTouchMove={onTouchMove}
      onTouchEnd={onTouchEnd}
      onTouchCancel={onTouchCancel}
      header={
        <WorkbenchBar
          dragHandlers={dragHandlers}
          isMacOverlay={isMacOverlay}
          isMobile={isMobile}
          identity={codingIdentityLabel ?? activeAgent ?? sessionTitle ?? 'EvoFlux'}
          activeAgent={activeAgent}
          agentNames={agentNames}
          onSelectAgent={setActiveAgent}
          viewMode={displayedViewMode}
          onViewModeChange={setViewMode}
          onOpenMobileSidebar={() => setMobileSidebarOpen(true)}
          mode={mode}
          workspace={workbenchWorkspace}
          onChooseWorkspace={mode === 'coding' ? handleOpenWorkspaceDialog : undefined}
          reviewContext={mode === 'coding' ? reviewSessionContext : null}
          onOpenReviewContext={() => openWorkbenchTool('pull-requests')}
          webBridgeEnabled={webBridgeEnabled}
          onWebBridgeEnabledChange={handleWebBridgeEnabledChange}
          webBridgePopoverOpen={webBridgeDialogOpen}
          onWebBridgePopoverOpenChange={setWebBridgeDialogOpen}
        />
      }
    >
        {automaticSplitTransition && (
          <AutomaticSplitTransition
            activeAgentCount={activeAgentCount}
            onComplete={completeAutomaticSplit}
          />
        )}
        {setupRequired && (
          <div className="mx-3 mt-3 flex flex-col gap-3 rounded-xl border border-(--accent-blue)/40 bg-(--accent-blue-soft) p-3 text-sm text-(--color-text) shadow-sm sm:flex-row sm:items-center sm:justify-between">
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
          <Suspense fallback={<PanelLoadingFallback />}>
            <MonitorView
              agentNames={agentNames}
              leadName={leadName}
              agentStreams={gridAgentStreams ?? EMPTY_AGENT_STREAMS}
              onFocusAgent={(name) => {
                setActiveAgent(name)
                setViewMode(splitAgentNames.length > 1 ? 'split' : 'agent')
              }}
            />
          </Suspense>
        ) : effectiveViewMode === 'split' && splitAgentNames.length > 0 ? (
          <div className="min-h-0 flex-1 p-3">
            <Suspense fallback={<PanelLoadingFallback />}>
              <SplitWorkbench
                agentNames={splitAgentNames}
                leadName={leadName}
                activeAgent={activeAgent}
                agentStreams={gridAgentStreams ?? EMPTY_AGENT_STREAMS}
                todos={todos}
                isContinuing={isContinuing}
                onContinue={continueTeam}
                onSelectAgent={setActiveAgent}
                showTurnChanges={mode === 'coding'}
              />
            </Suspense>
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
          <div className="relative flex flex-1 items-center justify-center overflow-y-auto px-3 py-3 sm:px-5">
            <div className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden="true">
              <div className="absolute left-1/2 top-1/2 h-96 w-96 -translate-x-1/2 -translate-y-1/2 rounded-full bg-(--color-accent)/8 blur-3xl" />
            </div>
            <div className="@container/coding-empty relative w-full max-w-[620px] overflow-hidden rounded-xl border border-(--color-border) bg-(--bg-card)/95 shadow-md shadow-black/8">
              <div className="absolute inset-x-0 top-0 h-px bg-linear-to-r from-transparent via-(--color-accent)/60 to-transparent" aria-hidden="true" />
              <div className="grid @[36rem]/coding-empty:grid-cols-[minmax(13rem,0.68fr)_minmax(22.5rem,1.32fr)]">
                <section className="flex flex-col border-b border-(--color-border-subtle) p-3 @[36rem]/coding-empty:border-b-0 @[36rem]/coding-empty:border-r">
                  <div className="flex items-center gap-2">
                    <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-(--color-accent)/12 text-(--color-accent) ring-1 ring-inset ring-(--color-accent)/20 shadow-sm shadow-(color:--color-accent)/10">
                      <FolderPlus size={16} strokeWidth={1.8} aria-hidden="true" />
                    </div>
                    <div className="inline-flex w-fit items-center gap-1 rounded-full border border-(--color-border-subtle) bg-(--bg-page)/70 px-2 py-0.5 text-[0.56rem] font-semibold uppercase tracking-[0.12em] text-(--color-text-muted)">
                      <GitBranch size={9} aria-hidden="true" />
                      Coding workspace
                    </div>
                  </div>
                  <h2 className="mt-1.5 text-sm leading-4.5 font-semibold tracking-tight text-(--color-text)">Start with a project folder</h2>
                  <p className="mt-1 text-[10px] leading-3.5 text-(--color-text-muted)">
                    Open a repository to give your coding team files, source control, and project context.
                  </p>

                  <div className="mt-2 grid gap-1 @[28rem]/coding-empty:grid-cols-2 @[36rem]/coding-empty:grid-cols-1">
                    <div className="flex items-center gap-2 rounded-lg bg-(--bg-page)/55 px-2 py-1.5">
                      <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-(--bg-key) font-mono text-[0.6rem] font-semibold text-(--color-accent) ring-1 ring-(--color-border)">1</span>
                      <p className="text-[10px] font-semibold text-(--color-text)">Choose a folder</p>
                    </div>
                    <div className="flex items-center gap-2 rounded-lg bg-(--bg-page)/55 px-2 py-1.5">
                      <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-(--bg-key) font-mono text-[0.6rem] font-semibold text-(--color-accent) ring-1 ring-(--color-border)">2</span>
                      <p className="text-[10px] font-semibold text-(--color-text)">Start building</p>
                    </div>
                  </div>

                  <div className="mt-auto pt-2.5">
                    <Button type="button" size="sm" className="h-8 w-full rounded-lg px-3 text-[11px] shadow-sm shadow-(color:--color-accent)/15" onClick={handleOpenWorkspaceDialog}>
                      <FolderPlus size={13} aria-hidden="true" />
                      Open workspace
                      <ArrowRight size={12} aria-hidden="true" />
                    </Button>
                  </div>
                </section>

                <div className="flex items-center p-1.5 @[36rem]/coding-empty:p-2">
                  <RecentUsageCard className="relative border-0 bg-transparent p-0 shadow-none" />
                </div>
              </div>
            </div>
          </div>
        ) : showHistorySkeleton ? (
          historySkeleton
        ) : activeAgent && hasActiveStream ? (
          <ActiveAgentTranscript
            activeAgent={activeAgent}
            isContinuing={isContinuing && activeAgent === leadName}
            isLead={activeAgent === leadName}
            onContinue={continueTeam}
            onAddSelectionToChat={handleAddSelectionToChat}
            onRequestSelectionDetails={handleRequestSelectionDetails}
            onSendToSideChat={handleSendToSideChat}
            turnChanges={
              mode === 'coding'
                && activeAgent === leadName
                && turnChanges?.sessionId === sessionIdState
                ? turnChanges
                : null
            }
            emptyState={
              mode === 'coding' && workspace ? (
                <div className="flex flex-col items-center justify-center py-16">
                  {projectIdState ? (
                    activeProject && <ProjectInfoCard project={activeProject} />
                  ) : (
                    <WorkspaceInfoCard
                      workspace={workspace}
                      onSuggestion={(suggestion) => {
                        inputRef.current?.setValue(suggestion)
                        inputRef.current?.focus()
                      }}
                    />
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
              <WorkspaceInfoCard
                       workspace={workspace}
                       onSuggestion={(suggestion) => {
                         inputRef.current?.setValue(suggestion)
                         inputRef.current?.focus()
                       }}
                     />
            )}
          </div>
        ) : sessionId && !isConnected ? (
          historySkeleton
        ) : null}

        <PermissionApprovalModal />
        <AskUserQuestionModal />
        <PlanActionBar onRevise={() => inputRef.current?.focus()} />
        {(mode !== 'coding' || workspace) && (
          <FloatingInputBar
            ref={inputRef}
            boundsRef={mainColumnRef}
            onSubmit={handleComposerSubmit}
            onStop={() => useTeamStore.getState().stopTeam()}
            goal={activeGoal}
            onGoalCommand={(command) => { void runGoalCommand(command) }}
            onSlashCommand={(id) => {
              if (id === 'btw') {
                openWorkbenchTool('side-chat')
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
            agentMode="coding"
            todos={todos}
            todosOpen={todosOpen}
            onTodosOpenChange={setTodosOpen}
            sessionId={sessionIdState}
            onWiki={toggleWiki}
            wikiActive={workbenchOpen && wikiOpen && activeWorkbenchTool === 'wiki'}
            onActivity={handleActivityToggle}
            activityActive={showActivity}
            workspaceSelector={mode === 'work' ? (
              <WorkFolderSelector
                sessionId={validWorkSessionId}
                workspaceRoot={workWorkspaceQuery.data?.workspace_root ?? null}
                loading={workWorkspaceQuery.isLoading}
              />
            ) : undefined}
            permissionMode={permissionMode}
            onPermissionModeChange={handlePermissionModeChange}
          />
        )}
    </AppShell>
  )
}
