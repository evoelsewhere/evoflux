import type { ContentBlock, AgentUsage, TeamCommandResponse, PlanApprovalPending, PermissionRequestPending, AskUserQuestionPending, TurnChangesPending, GoalResponse, PermissionMode } from '@/api/types'

export interface PendingMessage {
  id: string
  sessionId?: string | null
  content: string
  submittedAt?: number
}

export type ActivityKind = 'spawn' | 'dismiss' | 'inbox' | 'handoff' | 'status' | 'done' | 'delegation'

export interface ActivityItem {
  id: string
  kind: ActivityKind
  agent: string
  timestamp: Date
  /** Brief description rendered in the feed. */
  label: string
  /** Structured handoff artifact (for kind === 'handoff'). */
  artifact?: Record<string, unknown>
  /** Extra metadata (e.g. from_agent for inbox/handoff). */
  meta?: Record<string, unknown>
}

export type CacheInvalidation =
  | { kind: 'wiki' }
  | { kind: 'workspace_files'; sessionId: string }
  | { kind: 'coding_workspace'; workspace: string }
  | { kind: 'coding_workspace_paths'; workspace: string; paths: string[] }
  | { kind: 'scheduler' }
  | { kind: 'todos'; sessionId: string }
  | { kind: 'team_agents' }
  | { kind: 'team_sessions' }

export interface SetupRequiredNotice {
  agent: string
  message: string
  action: { type?: string; tab?: string }
}

export interface AgentStream {
  blocks: ContentBlock[]
  currentBlocks: ContentBlock[]
  currentText: string
  currentThinking: string
  status: 'idle' | 'working' | 'offline' | 'error'
  phase: 'ingress' | 'model_calling' | null
  usage: AgentUsage
  _completionBase: number
  _completionEstimated?: number
  /** Turn-scoped output estimate, so the live counter moves between the
   *  per-model-call totals the backend publishes. Reset with the turn. */
  _turnCompletionEstimated?: number
  _turnStartedAt?: number | null
  model: string | null
  lastError: string | null
  revertedCount?: number
  revertedMessages?: Array<{ role: string; content: string }>
  _revertedSuffix?: ContentBlock[]
}

export interface ActiveWorkflowExecution {
  executionId: string
  definitionName: string
  status: string
  nodeId: string | null
  nodeIndex: number | null
  totalNodes: number
  error: string | null
}

export interface BrowserTabInfo {
  index: number
  url: string
  title: string
}

export interface BrowserSessionInfo {
  active: boolean
  cdpUrl: string | null
  cdpHttp: string | null
  currentUrl: string | null
  currentTitle: string | null
  tabs: BrowserTabInfo[]
  lastAction: string | null
}

export interface TeamStoreState {
  agentStreams: Record<string, AgentStream>
  activeAgent: string | null
  leadName: string | null
  agentNames: string[]
  liveAgentNames: string[] | null
  sidebarOpen: boolean
  sessionId: string | null
  projectId: string | null
  /**
   * Set while the user is sitting in a chat they started that has no session
   * row yet. A new chat is not persisted until its first message, so this is
   * what tells a blank ``/`` apart from a cold boot: the first stays blank,
   * the second reopens the newest session. ``folderId`` is the folder the
   * chat was started from — it rides along with the first message so the
   * session is filed on arrival rather than created loose and moved.
   * ``workspace`` is the Work folder picked before there was a session to
   * point at, and travels the same way: the very first turn already runs in
   * the folder the user chose, instead of in the default sandbox until they
   * can change it afterwards.
   */
  newChatDraft: { folderId: string | null; workspace: string | null } | null
  sessionTitle: string | null
  sessionTags: string[]
  sessionPermissionMode: PermissionMode
  sessionModel: string | null
  sessionThinkingLevel: string | null
  sessionFastMode: boolean
  isTeamWorking: boolean
  isContinuing: boolean
  isConnected: boolean
  /** True while ``loadSession`` is fetching history for the current session. */
  isSessionLoading: boolean
  /** Last failure while fetching an older transcript page. */
  historyLoadError: string | null
  error: string | null
  activeGoal: GoalResponse | null
  activeWorkflowExecution: ActiveWorkflowExecution | null
  setupRequired: SetupRequiredNotice | null
  browserSession: BrowserSessionInfo | null
  planApproval: PlanApprovalPending | null
  turnChanges: TurnChangesPending | null
  /** When true and ``turnChanges`` is set, ChangesReviewPanel is visible. */
  turnChangesOpen: boolean
  permissionRequest: PermissionRequestPending | null
  askUserQuestion: AskUserQuestionPending | null
    _pendingMessages: PendingMessage[]
  _sessionGeneration: number
  hasMore: boolean
  nextCursor: string | null
  _leadRevertTime: number | null
  _workspace: string | null
  _loadingOlder: boolean
  /**
   * True when this session's view was painted from a snapshot rather than
   * loaded. Consumers use it to know the transcript on screen is a cached
   * one being reconciled, not a fresh load.
   */
  _restoredFromCache: boolean
  _resolvedSessionReadyId: string | null
  _unloading: boolean
  cacheInvalidations: CacheInvalidation[]
  activityLog: ActivityItem[]
}

export interface TeamStoreActions {
  sendMessage: (content: string, files?: File[], options?: { mode?: string; workspace?: string | null; model?: string | null; thinkingLevel?: string | null; fastMode?: boolean; shell?: boolean; webBridgeEnabled?: boolean }) => Promise<void>
  setSessionModelSettings: (model: string | null, thinkingLevel: string | null, fastMode?: boolean) => void
  continueTeam: () => Promise<void>
  compactTeam: () => Promise<void>
  undoTeam: () => Promise<TeamCommandResponse | undefined>
  redoTeam: () => Promise<void>
  sendGoalCommand: (command: string, objective?: string, options?: { mode?: string; workspace?: string | null; model?: string | null; thinkingLevel?: string | null; fastMode?: boolean }) => Promise<void>
  stopTeam: () => Promise<void>
  connectStream: () => AbortController
  loadTeamStatus: (
    workspace?: string | null,
    mode?: 'coding' | null,
    sessionId?: string | null,
  ) => Promise<void>
  loadSession: (
    sessionId: string,
    workspace?: string | null,
    mode?: 'coding' | null,
  ) => Promise<void>
  beginResolvedSession: (sessionId: string | null, options?: { mode?: string; workspace?: string | null; projectId?: string | null; folderId?: string | null; model?: string | null; thinkingLevel?: string | null; fastMode?: boolean; skipInitialRestore?: boolean }) => void
  loadOlderMessages: () => Promise<void>
  setActiveAgent: (name: string) => void
  cycleActiveAgent: (dir: 'next' | 'prev') => void
  toggleSidebar: () => void
  dismissSetupRequired: () => void
  dismissTurnChanges: () => void
  showTurnChanges: () => void
  isEmptyIdleSession: () => boolean
  consumeResolvedSessionReady: (sessionId: string, workspace?: string | null) => boolean
  /** Reset local chat state. Retained for stale async-generation guards in tests. */
  newSession: () => void
  /**
   * Point an unsaved Work chat at a local folder (``null`` = the default
   * session sandbox). A no-op once the session exists, which owns its
   * workspace on the row and changes it through the workspace endpoint.
   */
  setDraftWorkspace: (workspace: string | null) => void
  removePendingMessage: (id: string) => void
  _handleSSEEvent: (type: string, data: unknown) => void
  _drainCacheInvalidations: () => CacheInvalidation[]
  _abortController: AbortController | null
}

export type TeamStore = TeamStoreState & TeamStoreActions
