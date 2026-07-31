import type { ContentBlock, AgentUsage, TeamCommandResponse, PlanApprovalPending, PermissionRequestPending, AskUserQuestionPending, TurnChangesPending } from '@/api/types'

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
  usage: AgentUsage
  _completionBase: number
  _completionEstimated?: number
  _turnStartedAt?: number | null
  model: string | null
  lastError: string | null
  revertedCount?: number
  revertedMessages?: Array<{ role: string; content: string }>
  _revertedSuffix?: ContentBlock[]
}

export interface ActiveLoop {
  prompt: string | null
  limit: number
  remaining: number
  used: number
  paused: boolean
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
  sessionTitle: string | null
  sessionTags: string[]
  sessionModel: string | null
  sessionThinkingLevel: string | null
  sessionFastMode: boolean
  isTeamWorking: boolean
  isContinuing: boolean
  isConnected: boolean
  /** True while ``loadSession`` is fetching history for the current session. */
  isSessionLoading: boolean
  error: string | null
  activeLoop: ActiveLoop | null
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
  sendLoopCommand: (command: string, prompt?: string, options?: { mode?: string; workspace?: string | null; model?: string | null; thinkingLevel?: string | null; fastMode?: boolean }) => Promise<void>
  stopTeam: () => Promise<void>
  connectStream: () => AbortController
  loadTeamStatus: (
    workspace?: string | null,
    mode?: 'coding' | 'aim' | null,
  ) => Promise<void>
  loadSession: (
    sessionId: string,
    workspace?: string | null,
    mode?: 'coding' | 'aim' | null,
  ) => Promise<void>
  beginResolvedSession: (sessionId: string | null, options?: { mode?: string; workspace?: string | null; model?: string | null; thinkingLevel?: string | null; fastMode?: boolean; skipInitialRestore?: boolean }) => void
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
  removePendingMessage: (id: string) => void
  _handleSSEEvent: (type: string, data: unknown) => void
  _drainCacheInvalidations: () => CacheInvalidation[]
  _abortController: AbortController | null
}

export type TeamStore = TeamStoreState & TeamStoreActions
