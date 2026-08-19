// API Response Types

export type DiagnosticsStatus = 'ok' | 'warn' | 'fail'

export interface DiagnosticsCheck {
  id: string
  label: string
  status: DiagnosticsStatus
  detail: string
  hint: string | null
}

export interface DiagnosticsResponse {
  checks: DiagnosticsCheck[]
  summary: DiagnosticsStatus
}

export interface PlanStep {
  tool: string
  args: Record<string, unknown>
  summary: string
  /** Workspace-relative path when the step mutates a file. */
  path?: string
  diff_stat?: { additions?: number | null; deletions?: number | null }
}

export interface PlanApprovalPending {
  requestId: string
  sessionId: string
  /** Agent-authored markdown plan document (may be empty for legacy plans). */
  plan: string
  steps: PlanStep[]
}

export interface TurnChangedFile {
  path: string
  status: 'added' | 'modified' | 'removed' | 'changed'
  additions?: number | null
  deletions?: number | null
}

export interface TurnChangesPending {
  sessionId: string
  additions: number
  deletions: number
  files: TurnChangedFile[]
}

export type PlanDecision = 'approved' | 'rejected' | 'revise'

export interface AskUserQuestionItem {
  question: string
  options: string[]
  strict?: boolean
  kind?: 'text' | 'agent_spawn'
  agentSpawn?: {
    blueprint: string
    defaultModel: string
    defaultThinkingLevel: string | null
  }
}

export interface AskUserQuestionPending {
  requestId: string
  sessionId: string
  questions: AskUserQuestionItem[]
}

export type PermissionMode = 'ask' | 'accept-edits' | 'plan' | 'auto' | 'bypass'

export interface PermissionRequestPending {
  requestId: string
  sessionId: string
  tool: string
  patterns: string[]
  metadata: Record<string, unknown>
}

export interface AgentToolInfo {
  name: string
  description: string
}

export interface AgentSkillInfo {
  name: string
  description: string
}

export interface AgentInputCapabilities {
  vision: boolean
  document_text: boolean
  audio: boolean
  video: boolean
}

export interface AgentOutputCapabilities {
  text: boolean
  image: boolean
  audio: boolean
}

export interface AgentCapabilities {
  input: AgentInputCapabilities
  output: AgentOutputCapabilities
}

export interface AgentInfo {
  name: string
  description: string
  model: string | null
  summary_trigger_tokens?: number
  tools: AgentToolInfo[]
  /** MCP server names this agent was configured with. Includes servers that
   *  exist but contribute no tools (e.g. not yet ready). */
  mcp_servers?: string[]
  skills: AgentSkillInfo[]
  capabilities?: AgentCapabilities
}

export interface TeamAgentInfo extends AgentInfo {
  is_lead: boolean
}

export interface TeamBlueprintInfo extends AgentInfo {
  live_instances: string[]
}

export interface TeamAgentsResponse {
  agents: TeamAgentInfo[]
  blueprints: TeamBlueprintInfo[]
  mode?: string
  workspace?: string | null
}

export interface WorkspaceValidationResponse {
  workspace: string
}

export interface WorktreeInfo {
  name: string
  directory: string
  branch?: string | null
  managed: boolean
}

export interface WorktreeCreateResponse extends WorktreeInfo {
  source_workspace: string
}

export interface CodingWorkspaceTreeWorktree {
  path: string
  name: string
  managed: boolean
}

export interface CodingWorkspaceTreeRepository {
  // null only for a worktree whose source repo is itself hidden/deleted.
  workspace_id: string | null
  path: string
  name: string
  worktrees: CodingWorkspaceTreeWorktree[]
  // The project this repo belongs to, if any — a real FK lookup done
  // server-side, not something to reconstruct by matching paths against a
  // separately-fetched project list.
  project_id: string | null
}

export interface CodingWorkspaceTreeResponse {
  repositories: CodingWorkspaceTreeRepository[]
  projects: CodingProject[]
}

export interface WorkspaceBrowseResponse {
  path: string
  parent: string | null
  directories: Array<{ name: string; path: string }>
}

export interface WorkspaceGitDiffResponse {
  workspace: string
  is_git_repo: boolean
  diff: string
  untracked?: string[]
  truncated?: boolean
}

export interface WorkspaceStatusResponse {
  workspace: string
  name: string
  is_git_repo: boolean
  branch?: string | null
  dirty?: { staged: number; unstaged: number; untracked: number }
  head?: { sha: string; subject: string; timestamp: number } | null
}

export interface CodingWorkspaceFilesResponse {
  workspace: string
  files: WorkspaceFileInfo[]
  truncated: boolean
}

export type CodingDiagnosticsStatus = 'ready' | 'unavailable' | 'unsupported'

export interface CodingLspDiagnostic {
  range?: {
    start?: { line?: number; character?: number }
    end?: { line?: number; character?: number }
  }
  severity?: 1 | 2 | 3 | 4
  code?: string | number
  source?: string
  message: string
}

export interface CodingDiagnosticsResponse {
  workspace: string
  path: string
  language: string | null
  status: CodingDiagnosticsStatus
  diagnostics: CodingLspDiagnostic[]
  message: string | null
}

export type CodingSemanticAction =
  | 'hover'
  | 'code_actions'
  | 'rename'
  | 'format'
  | 'organize_imports'
  | 'document_symbols'
  | 'workspace_symbols'

export interface CodingSemanticRequest {
  action: CodingSemanticAction
  path: string
  content?: string | null
  line?: number | null
  column?: number | null
  end_line?: number | null
  end_column?: number | null
  new_name?: string | null
  query?: string | null
  diagnostics?: CodingLspDiagnostic[]
  tab_size?: number
  insert_spaces?: boolean
}

export interface CodingSemanticResponse {
  workspace: string
  path: string
  action: CodingSemanticAction
  language: string | null
  status: CodingDiagnosticsStatus
  result: unknown
  capabilities: Record<string, unknown>
  message: string | null
}

export type ChangeSetOrigin = 'lsp' | 'ai' | 'agent' | 'review' | 'git'
export type ChangeSetStatus = 'pending' | 'applied' | 'rejected' | 'partial'
export type ChangeSetFileStatus = 'pending' | 'applied' | 'rejected'

export interface ChangeSetFileProposal {
  path: string
  proposed_content: string
  base_hash?: string | null
  document_version?: number | null
}

export interface ChangeSetCreateRequest {
  origin: ChangeSetOrigin
  title: string
  description?: string | null
  files?: ChangeSetFileProposal[]
  workspace_edit?: Record<string, unknown> | null
  verification_commands?: string[]
}

export interface ChangeSetFile {
  path: string
  base_hash: string | null
  proposed_hash: string
  document_version: number | null
  diff: string
  additions: number
  deletions: number
  status: ChangeSetFileStatus
}

export interface ChangeSetResponse {
  id: string
  workspace: string
  origin: ChangeSetOrigin
  title: string
  description: string | null
  status: ChangeSetStatus
  snapshot_hash: string | null
  verification_commands: string[]
  verification: Array<Record<string, unknown>>
  created_at: number
  updated_at: number
  files: ChangeSetFile[]
}

export interface ChangeSetFileContent {
  path: string
  base_hash: string | null
  proposed_hash: string
  original_content: string
  proposed_content: string
  document_version: number | null
  status: ChangeSetFileStatus
}

export type ProblemSource = 'lsp' | 'static' | 'build' | 'test' | 'ai_review' | 'security' | 'plugin'
export type ProblemSeverity = 'error' | 'warning' | 'info' | 'hint'
export type ProblemStatus = 'open' | 'dismissed' | 'suppressed'

export interface CodingProblem {
  id: string
  workspace: string
  source: ProblemSource
  scope: string
  message: string
  severity: ProblemSeverity
  path: string | null
  line: number | null
  column: number | null
  end_line: number | null
  end_column: number | null
  code: string | null
  title: string | null
  details: string | null
  fix: Record<string, unknown> | null
  suppression_key: string
  provenance: Record<string, unknown>
  session_id: string | null
  status: ProblemStatus
  created_at: number
  updated_at: number
}

export interface ProblemsResponse {
  problems: CodingProblem[]
  counts: Record<'error' | 'warning' | 'info' | 'hint' | 'total', number>
}

export type EditorAiAction =
  | 'explain_code'
  | 'fix_diagnostic'
  | 'refactor_selection'
  | 'generate_tests'
  | 'generate_documentation'
  | 'find_problems'
  | 'simplify_code'
  | 'convert_pattern'
  | 'propagate_api_change'
  | 'explain_failure'

export interface EditorSelectionContext {
  text: string
  start_line: number
  start_column: number
  end_line: number
  end_column: number
}

export interface EditorContextRequest {
  session_id?: string | null
  active_file: string
  content: string
  document_version?: number | null
  selection?: EditorSelectionContext | null
  cursor_symbol?: string | null
  diagnostics?: CodingLspDiagnostic[]
  mention_paths?: string[]
  relevant_terminal_failure?: string | null
}

export interface EditorActionRequest extends EditorContextRequest {
  action: EditorAiAction
  instruction?: string | null
}

export interface EditorContextResponse {
  context: Record<string, unknown>
}

export interface EditorActionResponse {
  kind: 'explanation' | 'changes' | 'findings'
  summary: string
  explanation: string | null
  verification_commands: string[]
  context: Record<string, unknown>
  change_set: ChangeSetResponse | null
  findings: string[]
}

export type GitAIAction =
  | 'self_review'
  | 'generate_commit_message'
  | 'explain_commit'
  | 'generate_pr_description'
  | 'summarize_pull_request'
  | 'propose_conflict_resolution'
  | 'review_resolved_conflicts'

export interface GitAIRequest {
  session_id: string
  action: GitAIAction
  reference?: string | null
  remote_context?: Record<string, unknown> | null
}

export interface GitAIResponse {
  kind: 'review' | 'text' | 'pr' | 'changes'
  summary: string
  message: string | null
  title: string | null
  body: string | null
  findings: string[]
  change_set: ChangeSetResponse | null
  evidence_sha256: string
}

export type SearchEverywhereKind =
  | 'file'
  | 'folder'
  | 'symbol'
  | 'code'
  | 'git_branch'
  | 'git_commit'
  | 'problem'
  | 'skill'
  | 'workflow'

export interface SearchEverywhereItem {
  id: string
  kind: SearchEverywhereKind
  label: string
  description: string
  path: string | null
  line: number | null
  metadata: Record<string, unknown> | null
}

export interface SearchEverywhereResponse {
  items: SearchEverywhereItem[]
}

export interface LanguageServerDetectedRepository {
  workspace: string
  name: string
  file_count: number
}

export type LanguageServerState = 'ready' | 'missing' | 'update_available'
export type LanguageServerSource = 'managed' | 'system' | 'missing'

export interface LanguageServerStatus {
  language_id: string
  display_name: string
  extensions: string[]
  detected: boolean
  file_count: number
  repositories: LanguageServerDetectedRepository[]
  state: LanguageServerState
  source: LanguageServerSource
  command: string | null
  installed_version: string | null
  expected_version: string | null
  installable: boolean
  installer: 'npm' | 'uv' | null
  installer_available: boolean
  install_hint: string
}

export interface LanguageServerOverview {
  workspaces: string[]
  cache_dir: string
  servers: LanguageServerStatus[]
}

// ── Code context (/api/code-context) ────────────────────────────────────────

export interface CodeGraphStatusResponse {
  indexed: boolean
  files: number
  nodes: number
  edges: number
  indexing: boolean
  index_phase: string | null
  index_progress: number | null
  index_message: string | null
  index_error: string | null
}

export interface CodeGraphNode {
  id: string
  workspace_id: string
  kind: string
  name: string
  qualified_name: string
  file_path: string
  language: string
  line_start: number
  line_end: number
  signature: string | null
  docstring: string | null
}

export interface CodeGraphSearchResponse {
  nodes: CodeGraphNode[]
}

export type CodeGraphOperation =
  | 'definition'
  | 'callers'
  | 'callees'
  | 'references'
  | 'impact'
  | 'neighborhood'
export type CodeGraphFreshnessPolicy = 'fast' | 'balanced' | 'strict'

export interface CodeGraphSymbol {
  repository: string
  file_path: string
  line_start: number
  line_end: number
  symbol: string
  kind: string
  language: string
  signature: string | null
  resolution: string
  source: string | null
}

export interface CodeGraphRelation {
  kind: string
  depth: number
  cross_repo: boolean
  source_symbol: string
  source_location: string
  target_symbol: string
  target_location: string
  callsite_location: string
  callsite_source: string | null
}

export interface CodeGraphLanguageCapability {
  language: string
  extensions: string[]
  graph: boolean
  lsp: boolean
  indexed_files: number
  workspace_files: number
  coverage: number
}

export interface CodeGraphNavigateResponse {
  symbol: string
  operation: CodeGraphOperation
  strategy: string
  graph_version: string | null
  working_tree_revision: string
  freshness: 'fresh' | 'partial' | 'unavailable'
  dirty_files: number
  pending_edges: number
  matches: CodeGraphSymbol[]
  relations: CodeGraphRelation[]
  suggestions: CodeGraphSymbol[]
  capabilities: CodeGraphLanguageCapability[]
  limitations: string[]
  truncated: boolean
}

export interface CodeGraphFreshnessResponse {
  graph_version: string | null
  working_tree_revision: string
  freshness: 'fresh' | 'partial' | 'unavailable'
  indexed_files: number
  dirty_files: number
  change_source: string
}

export interface CodeGraphEdge {
  id: string
  src_id: string
  dst_id: string
  kind: string
  file_path: string | null
  line: number | null
}

export interface ProjectCodeGraphData {
  repos: ProjectRepoStatus[]
  nodes: CodeGraphNode[]
  edges: CodeGraphEdge[]
  cross_repo_edges: CrossRepoEdge[]
  node_limit_per_repo: number
  edge_limit_per_repo: number
  total_node_count: number
  total_edge_count: number
}

export interface CodeGraphReindexResponse {
  indexing: boolean
  already_running: boolean
}

export interface ProjectReindexStartedResponse {
  indexing: boolean
  repo_count: number
  already_running: number
  full: boolean
}

// Per-repo index status for a project-wide code graph view — one entry per
// workspace, not an aggregate, so the UI can offer "Build index" for
// whichever specific repo(s) haven't been indexed yet.
export interface ProjectRepoStatus {
  workspace_id: string
  path: string
  name: string
  indexed: boolean
  files: number
  nodes: number
  edges: number
  indexing: boolean
  index_phase: string | null
  index_progress: number | null
  index_message: string | null
  index_error: string | null
}

export interface ProjectCodeSearchResult {
  path: string
  node: CodeGraphNode
}

export interface ProjectCodeSearchResponse {
  results: ProjectCodeSearchResult[]
}

export interface MessageAttachment {
  filename?: string
  media_type?: string
  original_name?: string
  category?: 'text' | 'data' | 'image' | 'document' | 'audio' | 'video' | 'binary'
  url?: string        // /api/chat/files/{session_id}/{filename} or blob URL for optimistic
  preview_url?: string
  download_url?: string
  workspace_path?: string
}

export interface MessageResponse {
  id: string
  session_id: string
  role: string
  content: string | null
  reasoning_content: string | null
  // Backend returns raw dicts; cast to ToolCall shape for UI convenience.
  tool_calls: Array<Partial<ToolCall> & { id: string; function?: Partial<ToolCall['function']> }> | null
  tool_call_id: string | null
  name: string | null
  is_summary: boolean
  is_hidden: boolean
  extra: Record<string, unknown> | null
  created_at: string | null
  file_message?: boolean
  attachments: MessageAttachment[] | null
}

export interface ToolCall {
  id: string
  type: string
  function: {
    name: string
    arguments: string  // raw JSON string from API
    thought?: string | null
    thought_signature?: string | null
  }
}

export interface SessionResponse {
  id: string
  title: string | null
  agent_name: string | null
  revert?: { message_id?: string } | null
  created_at: string | null
  updated_at: string | null
  scheduled_task_name?: string | null
  mode?: string
  workspace?: string | null
  project_id?: string | null
  workspace_hidden?: boolean
  permission_mode?: string
  model?: string | null
  thinking_level?: string | null
  running?: boolean
  /** Feature tags attached at resolve time (e.g. "webbridge"); absent/[] when none. */
  tags?: string[]
  /** Sidebar folder the session is filed under; absent when unfiled. */
  folder_id?: string | null
}

// ── Session folders (sidebar grouping) ───────────────────────────────────────

export interface SessionFolder {
  id: string
  name: string
  mode: string
  /** When true, each session in the folder sees a digest of its siblings. */
  share_context: boolean
  sort_order: number
  /** Total sessions filed here — can exceed the first inline page. */
  session_count: number
  sessions: SessionResponse[]
  /** Cursor for the next page of older chats, when one exists. */
  next_cursor: string | null
  has_more: boolean
  created_at: string | null
  updated_at: string | null
}

export interface SessionFolderListResponse {
  folders: SessionFolder[]
}

// ── Coding Projects (multi-repo) ─────────────────────────────────────────────

export interface ProjectWorkspaceItem {
  workspace_id: string
  path: string
  name: string | null
  display_name: string | null
  sort_order: number
  kind: string
}

export interface CodingProject {
  id: string
  name: string
  description: string | null
  // "coding" by default (GET /team/projects?kind= filter).
  kind: string
  settings: Record<string, unknown>
  workspaces: ProjectWorkspaceItem[]
  created_at: string
  updated_at: string
}

export interface ProjectCreateRequest {
  name: string
  description?: string
  workspace_paths: string[]
  settings?: Record<string, unknown>
}

export interface AddWorkspaceToProjectRequest {
  workspace_path: string
  display_name?: string
}

// Cross-repository links are resolved from the current repository targets.
export type CrossRepoEdgeMethod = 'dynamic-symbol-resolution'

export type CrossRepoEdgeStatus = 'unresolved' | 'resolved' | 'rejected'

export interface CrossRepoEdge {
  id: string
  src_workspace_id: string
  src_node_id: string | null
  src_file_path: string
  src_line: number | null
  raw_reference: string
  dst_name_hint: string | null
  kind: string
  status: CrossRepoEdgeStatus
  method: CrossRepoEdgeMethod | null
  confidence: number | null
  rationale: string | null
  dst_workspace_id: string | null
  dst_node_id: string | null
  dst_qualified_name: string | null
}

export interface SessionDetailResponse extends SessionResponse {
  messages: MessageResponse[]
}

export interface TeamSessionResolveResponse extends SessionResponse {
  created: boolean
}

export interface SessionPageResponse {
  data: SessionResponse[]
  /** ISO 8601 created_at of the last item; pass as `before` to fetch next page. */
  next_cursor: string | null
  has_more: boolean
}



export interface TeamStatusAgent {
  name: string
  model: string
  state: string
}

export interface TeamStatusResponse {
  team: string
  lead: TeamStatusAgent
  members: TeamStatusAgent[]
}

export type GoalStatus = 'active' | 'paused' | 'complete' | 'blocked'

export interface GoalResponse {
  session_id: string
  objective: string
  status: GoalStatus
  token_budget: number | null
  tokens_used: number
  time_used_seconds: number
  pause_reason: string | null
  blocker_streak: number
  status_details: Record<string, unknown> | null
  version: number
  created_at: string
  updated_at: string
  completed_at: string | null
}

export interface TeamHistoryResponse {
  lead: SessionDetailResponse
  members: Array<{
    name: string
    session_id: string
    messages: MessageResponse[]
  }>
  /** Durable autonomous objective attached to this session. */
  goal?: GoalResponse | null
  // Live workflow snapshot from the runner (gone after restart).
  workflow_execution?: {
    execution_id: string
    definition_name: string
    status: string
    node_id: string | null
    node_index: number | null
    total_nodes: number
  } | null
  has_more: boolean
  next_cursor: string | null
}

// ── Workflows (documents/plans/workflows-feature-plan.md) ────────────────────

export interface WorkflowInputSpec {
  name: string
  type: 'string' | 'number' | 'boolean' | 'enum'
  required: boolean
  default?: unknown
  options?: string[] | null
  description: string
}

export interface WorkflowListItem {
  name: string
  description: string
  scope: 'work' | 'coding'
  inputs: WorkflowInputSpec[]
  hash: string
  root: string
  source_path: string
  approved: boolean
  valid: boolean
  errors: string[]
  node_count: number
}

export interface WorkflowDetail {
  name: string
  raw_yaml: string
  graph: Record<string, unknown>
  hash: string
  root: string
  scope: string | null
  approved: boolean
  manifest: Record<string, unknown>
  lint_warnings: string[]
  errors: string[]
}

export interface WorkflowRunResult {
  execution_id: string
  session_id: string
}

export interface WorkflowExecutionSummary {
  id: string
  definition_name: string
  definition_hash: string
  session_id: string
  // running | waiting_gate | completed | failed | stopped
  status: string
  error: string | null
  inputs: Record<string, unknown>
  retry_of_execution_id: string | null
  outputs: Record<string, unknown>
  started_at: string
  ended_at: string | null
  // True while the in-memory runner is driving this execution; a running
  // row without it is an orphan from a backend restart ("interrupted").
  live: boolean
}

export interface WorkflowNodeRun {
  id: string
  node_id: string
  iteration: number | null
  // running | succeeded | failed | skipped
  status: string
  output: Record<string, unknown> | null
  error: string | null
  started_at: string
  ended_at: string | null
}

export interface WorkflowExecutionDetail {
  execution: WorkflowExecutionSummary
  node_runs: WorkflowNodeRun[]
}

export interface WorkflowExecutionListResponse {
  executions: WorkflowExecutionSummary[]
}

// SSE Event Types
export type SSEEventType =
  | 'session'
  | 'thinking'
  | 'message'
  | 'tool_call'
  | 'tool_start'
  | 'tool_output_delta'
  | 'tool_end'
  | 'usage'
  | 'done'
  | 'rate_limit'
  | 'provider_status'
  | 'error'
  | 'agent_status'
  | 'queued_turn_start'
  | 'inbox'
  | 'handoff'
  | 'delegation'
  | 'desktop_notification'
  | 'title_update'
  | 'summarization_start'
  | 'summarization_content'
  | 'summarization_end'
  | 'browser_session'

export interface SSEEvent {
  type: SSEEventType
  [key: string]: unknown
}

// Content Block Types
export interface ContentBlock {
  id: string
  type: 'thinking' | 'tool' | 'text' | 'user' | 'compaction' | 'provider_status' | 'widget'
  content: string
  toolName?: string
  toolArgs?: string
  toolDone?: boolean
  toolCallId?: string   // for matching tool results
  toolOutput?: string   // live output streamed before tool_end
  toolResult?: string   // the role:"tool" response content
  durationMs?: number   // completed tool duration from SSE/session logs
  startedAt?: number    // client timestamp for realtime elapsed display
  responseDurationMs?: number // assistant response duration shown in turn footer
  /** Widget-specific fields */
  widgetHtml?: string   // HTML content for widget blocks
  isStreaming?: boolean // whether widget is still streaming
  title?: string        // widget title
  /** Variant-specific metadata. ``user`` inbox blocks carry ``from_agent``;
   *  ``compaction`` blocks are content-free status markers carrying
   *  ``state: 'compacting' | 'compacted'`` and optional ``error: true``.
   *  Keeping this generic avoids one typed field
   *  per block variant. */
  extra?: Record<string, unknown> | null
  /** Timestamp when block was created (for team mode display) */
  timestamp?: Date
  /** File attachments (images, documents, etc.) — for user blocks */
  attachments?: MessageAttachment[]
}

// Chat Message Type
export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string // For user: plain text. For assistant: ignored (use blocks)
  blocks: ContentBlock[]
  agent?: string | null
  model?: string | null
  timestamp: Date
  usage?: AgentUsage
  file_message?: boolean
  attachments?: MessageAttachment[]
}

// Agent Usage Stats
export interface AgentUsage {
  promptTokens: number
  completionTokens: number
  totalTokens: number
  cachedTokens: number
  turnPromptTokens?: number
  turnCompletionTokens?: number
  turnTotalTokens?: number
  turnCachedTokens?: number
}

// ── Wiki ─────────────────────────────────────────────────────────────────────

/** One row in the wiki tree — surfaced from YAML frontmatter. */
export interface WikiFileInfo {
  /** Path relative to EVOFLUX_WIKI_DIR, e.g. 'topics/auth.md'. */
  path: string
  description: string
  updated: string | null
  tags: string[]
  /** ``high|medium|low`` from frontmatter; ``null`` when unspecified. */
  confidence?: string | null
  /** Source slugs that contributed (e.g. ``session-a1b2c3d4``). */
  sources?: string[]
}

/** Full wiki tree grouped by subdirectory.  Mirrors the Karpathy LLM-Wiki
 *  page-type split: concepts (``topics``), entities, sources, comparisons.
 */
export interface WikiTree {
  /** Root files: USER.md, INDEX.md, LOG.md, LINT.md (any that exist). */
  system: WikiFileInfo[]
  /** notes/ — raw note entries written by tools/agents. */
  notes: WikiFileInfo[]
  /** imports/ — raw imported evidence. */
  imports: WikiFileInfo[]
  /** topics/ — curated concepts, techniques, and project knowledge. */
  topics: WikiFileInfo[]
  /** entities/ — curated people, tools, organisations, and products. */
  entities: WikiFileInfo[]
  /** sources/ — curated summaries and provenance per ingested source. */
  sources: WikiFileInfo[]
  /** comparisons/ — curated comparisons, trade-offs, and decisions. */
  comparisons: WikiFileInfo[]
}

/** Raw contents of a single wiki file. */
export interface WikiFile {
  path: string
  content: string
  description: string
  updated: string | null
  tags: string[]
  confidence?: string | null
  sources?: string[]
}

// ── Agent management ────────────────────────────────────────────────────────

/** Lightweight row for the agents list. Invalid files have `valid=false`. */
export interface AgentSummary {
  name: string
  role: 'lead' | 'member'
  description: string | null
  model: string | null
  tools: string[]
  mcp: string[]
  skills: string[]
  valid: boolean
  error: string | null
}

/** Parsed frontmatter config — matches backend AgentConfig. */
export interface AgentConfig {
  name: string
  role: 'lead' | 'member'
  description?: string | null
  system_prompt?: string
  tools?: string[]
  skills?: string[]
  model?: string | null
  fallback_model?: string | null
  thinking_level?: string | null
  responses_api?: boolean | null
}

/** Full view of one agent — raw file + parsed config. */
export interface AgentDetail {
  name: string
  path: string
  content: string
  config: AgentConfig | null
  error: string | null
}

export interface AgentDeleteResponse {
  name: string
}

export interface AgentListResponse {
  agents: AgentSummary[]
}

export interface AgentBulkModelResult {
  name: string
  ok: boolean
  error: string | null
}

export interface AgentBulkModelResponse {
  results: AgentBulkModelResult[]
}

// ── Skill management ────────────────────────────────────────────────────────

export type SkillMode = 'work' | 'coding'

export interface SkillRuntimeSettingsUpdate {
  settings_id: string
  modes: SkillMode[]
  allow_implicit_invocation: boolean
  user_invocable: boolean
}

export interface SkillDiagnostic {
  code: string
  message: string
  severity: 'warning' | 'error'
}

export interface SkillSummary {
  name: string
  description: string
  display_name: string | null
  short_description: string | null
  default_prompt: string | null
  allow_implicit_invocation: boolean
  user_invocable: boolean
  resource_count: number
  symlinked: boolean
  diagnostics: SkillDiagnostic[]
  shadowed_paths: string[]
  valid: boolean
  error: string | null
  built_in: boolean
  editable: boolean
  settings_editable: boolean
  settings_id: string
  settings_overridden: boolean
  source: string
  modes: SkillMode[]
  dependencies: Record<string, unknown>[]
}

export interface SkillBundleFile {
  path: string
  size: number
  media_type: string
  content: string | null
  encoding: 'utf-8' | 'base64' | null
  editable: boolean
}

export interface SkillBundleFileWrite {
  path: string
  content: string
  encoding: 'utf-8' | 'base64'
}

export interface SkillDetail {
  name: string
  path: string
  content: string
  description: string
  display_name: string | null
  short_description: string | null
  default_prompt: string | null
  allow_implicit_invocation: boolean
  user_invocable: boolean
  resource_count: number
  symlinked: boolean
  diagnostics: SkillDiagnostic[]
  shadowed_paths: string[]
  error: string | null
  built_in: boolean
  editable: boolean
  settings_editable: boolean
  settings_id: string
  settings_overridden: boolean
  source: string
  modes: SkillMode[]
  dependencies: Record<string, unknown>[]
  bundle_truncated: boolean
  files: SkillBundleFile[]
}

export interface SkillDeleteResponse {
  name: string
}

export interface SkillListResponse {
  skills: SkillSummary[]
}

// ── Slash commands ──────────────────────────────────────────────────────────

export interface CommandSummary {
  name: string
  description: string
  source: string
}

export interface CommandListResponse {
  commands: CommandSummary[]
}

export interface CommandRenderResponse {
  name: string
  content: string
}

// ── Snippets ───────────────────────────────────────────────────────────────

export interface SnippetSummary {
  name: string
  description: string
  source: string
}

export interface SnippetListResponse {
  snippets: SnippetSummary[]
}

export interface SnippetRenderResponse {
  name: string
  content: string
}

/**
 * Workspace paths the server's snapshot restore touched during a
 * ``undo`` / ``redo`` command. Empty lists mean the restore had no
 * filesystem effect (or no snapshot was recorded) — the client uses
 * that as a signal to skip the Coding Workspace cache invalidation
 * entirely, saving a full ``git diff`` fetch on a 30k-file workspace.
 */
export interface ChangedPaths {
  added: string[]
  modified: string[]
  removed: string[]
}

export interface TeamCommandResponse {
  status: string
  session_id: string
  command: 'continue' | 'compact' | 'undo' | 'redo'
  message?: MessageResponse
  /**
   * Present on ``undo`` / ``redo`` responses only. The client uses
   * the union of all three buckets to drive a scoped
   * ``coding_workspace_paths`` invalidation — splicing the cached git
   * diff for just these paths instead of refetching the whole repo.
   */
  changed_paths?: ChangedPaths
}

// ── Registry (dropdown catalog) ─────────────────────────────────────────────

export interface ToolCatalogEntry {
  name: string
  description: string
  /** Tier membership: null = every tier; e.g. ['work'] restricts to that mode. */
  tiers: string[] | null
  /** Lead-only tools are never granted to members — hidden from member pickers. */
  lead_only: boolean
}

export interface SkillCatalogEntry {
  name: string
  description: string
  display_name?: string | null
  short_description?: string | null
  allow_implicit_invocation?: boolean
  user_invocable?: boolean
  modes: SkillMode[]
  dependencies: Record<string, unknown>[]
}

export interface ModelCatalogEntry {
  id: string       // provider:model
  provider: string
  model: string
  vision: boolean
  input_audio: boolean
  input_video: boolean
  output_image: boolean
  output_video: boolean
  summary_trigger_tokens: number
  /** Maximum context window size in tokens. null = unknown. */
  context_length: number | null
  /** Non-empty only for models that support extended thinking. Used to show/hide ThinkingPill. */
  thinking_levels: string[]
  thinking_control?: string | null
  thinking_default_level?: string | null
  thinking_default_enabled?: boolean | null
  thinking_source?: string | null
  interfaces?: string[]
}

export interface RegistryResponse {
  tools: ToolCatalogEntry[]
  skills: SkillCatalogEntry[]
  providers: string[]
  models: ModelCatalogEntry[]
}

// ── Workspace files (artifacts panel) ────────────────────────────────────────
//
// Flat recursive listing of a session's agent workspace (``.evoflux/team/{sid}``).
// File bytes are fetched through ``/api/team/{sid}/media/{path}`` — the same
// proxy that renders inline markdown images.

export interface WorkspaceFileInfo {
  path: string   // POSIX-separated, relative to the workspace root
  name: string   // Basename
  size: number   // Bytes
  mtime: number  // Seconds since epoch
  mime: string   // MIME type (guessed)
  // Absolute path of the repo this file was listed from. Only set when the
  // file came from a multi-repo project tree (MultiRepoFileTree) — a project
  // session's "workspace" is just the primary repo, so a file picked from a
  // different member repo must carry its own root for the viewer to resolve
  // the right absolute path. Omitted (falls back to the ambient workspace)
  // for single-workspace listings.
  sourceWorkspace?: string
}

export interface WorkspaceFilesResponse {
  session_id: string
  files: WorkspaceFileInfo[]
  truncated: boolean
  workspace_root: string | null
}

export interface WorkspaceRootResponse {
  session_id: string
  workspace_root: string
}

// ── Process manager ─────────────────────────────────────────────────────────

export type ManagedProcessKind = 'command' | 'preview' | 'terminal'

export interface ManagedProcess {
  id: string
  kind: ManagedProcessKind
  label: string
  command: string
  session_id: string | null
  session_title: string | null
  pid: number | null
  cwd: string | null
  elapsed_seconds: number
  killable: boolean
  metadata: {
    port?: number
    url?: string
    reused?: boolean
    workspace?: string
    terminal_id?: string
  }
}

export interface ProcessListResponse {
  processes: ManagedProcess[]
}

// ── Scheduler ───────────────────────────────────────────────────────────────

export type ScheduledTaskMode = 'work' | 'coding'

export interface ScheduledTaskResponse {
  id: string
  name: string
  // Routing target — every task delivers to the team lead of the matching
  // team (default lead for ``normal``, workspace lead for ``coding``).
  // See documents/docs/agent/tools.md#scheduler-builtinschedulepy.
  mode: ScheduledTaskMode
  workspace: string | null
  project_id: string | null
  schedule_type: 'at' | 'every' | 'cron'
  at_datetime: string | null
  every_seconds: number | null
  cron_expression: string | null
  timezone: string
  prompt: string
  session_id: string | null
  enabled: boolean
  status: string
  run_count: number
  last_run_at: string | null
  last_error: string | null
  next_fire_at: string | null
  created_at: string
  updated_at: string
}

export interface ScheduledTaskCreate {
  name: string
  mode?: ScheduledTaskMode
  workspace?: string | null
  project_id?: string | null
  schedule_type: 'at' | 'every' | 'cron'
  at_datetime?: string | null
  every_seconds?: number | null
  cron_expression?: string | null
  timezone?: string
  prompt: string
  session_id?: string | null
  enabled?: boolean
}

export interface ScheduledTaskListResponse {
  tasks: ScheduledTaskResponse[]
}

export type TodoTier = 'trivial' | 'simple' | 'multi_step' | 'complex'

export interface TodoItem {
  task_id: string
  content: string
  status: 'pending' | 'in_progress' | 'completed' | 'cancelled'
  priority: 'high' | 'medium' | 'low'
  tier?: TodoTier
  dependencies?: string[]
  assigned_to?: string | null
  claimed_by?: string | null
}

export interface TodosResponse {
  todos: TodoItem[]
}

// ── Git / Source Control ────────────────────────────────────────────────────

export interface ChangedFile {
  path: string
  status: 'modified' | 'added' | 'deleted' | 'renamed' | 'untracked' | 'unmerged'
  staged: boolean
  old_path?: string
}

export interface GitChangesResponse {
  is_git_repo: boolean
  branch: string | null
  ahead: number
  behind: number
  files: ChangedFile[]
}

export interface GitRepository {
  is_git_repo: boolean
  root: string | null
  branch: string | null
  detached: boolean
  upstream: string | null
  head_sha: string | null
  head_subject: string | null
  user_name: string | null
  user_email: string | null
}

export interface GitCloneResult {
  workspace: string
  name: string
  remote_url: string
}

export interface GitRemote {
  name: string
  fetch_url: string
  push_url: string
}

export interface GitTag {
  name: string
  sha: string
  subject: string
  date: string
}

export interface GitCommitResponse {
  sha: string
  message: string
}

export interface GitBranch {
  name: string
  current: boolean
  remote: string | null
  ahead: number
  behind: number
}

export interface GitMergeResponse {
  success: boolean
  conflicts: string[]
  message: string
}

export interface GitJobOut {
  workspace: string
  op: string
  status: string
  message: string
  error: string | null
}

export interface GitLogEntry {
  sha: string
  short_sha: string
  parent_shas: string[]
  refs: string[]
  author: string
  date: string
  message: string
}

export interface GitLogResponse {
  entries: GitLogEntry[]
  has_more: boolean
  next_skip: number | null
}

export interface GitLogFile {
  path: string
  status: string
}

export interface GitStash {
  index: number
  message: string
  sha: string
}

export interface GitConflictsResponse {
  conflicted: boolean
  operation: string | null
  files: { path: string; status: string }[]
}

export type GitServerProvider =
  | 'github'
  | 'gitlab'
  | 'bitbucket_cloud'
  | 'bitbucket_server'
  | 'gitea'
  | 'azure_devops'

export type GitServerConnectionScope = 'server' | 'repository'

export interface GitServerConnection {
  id: string
  name: string
  provider: GitServerProvider
  domain: string
  base_url: string
  token_url: string
  host: string
  scope: GitServerConnectionScope
  workspace_id: string | null
  token_env_var: string
  has_token: boolean
  username: string | null
  verify_ssl: boolean
  created_at: string
  updated_at: string
}

export interface GitServerConnectionInput {
  name: string
  provider: GitServerProvider
  domain: string
  base_url?: string
  scope: GitServerConnectionScope
  workspace_id: string | null
  token?: string
  token_env_var?: string | null
  username?: string | null
  verify_ssl: boolean
}

export interface CodeReviewItem {
  number: number
  title: string
  state: string
  draft: boolean
  author: string | null
  author_avatar_url: string | null
  source_branch: string
  target_branch: string
  updated_at: string
  web_url: string
  labels: string[]
  review_status: string | null
  pipeline_status: string | null
  comment_count: number | null
}

export interface RepositoryCodeReviews {
  workspace_id: string
  project_id: string | null
  workspace: string
  name: string
  remote_url: string | null
  repository: string | null
  detected_provider: GitServerProvider | null
  suggested_domain: string | null
  suggested_base_url: string | null
  connection_id: string | null
  provider: GitServerProvider | null
  items: CodeReviewItem[]
  error: string | null
}

export interface CodeReviewsResponse {
  repositories: RepositoryCodeReviews[]
  total: number
}

export interface CodeReviewCreateInput {
  title: string
  body?: string
  source_branch: string
  target_branch: string
}

export interface CodeReviewCreateResult {
  provider: GitServerProvider
  repository: string
  number: number
  web_url: string
  title: string
}

export interface CodeReviewComment {
  stable_id: string
  id: string
  thread_id: string
  parent_id: string | null
  kind: 'conversation' | 'inline' | string
  body: string
  author: string | null
  created_at: string
  updated_at: string
  resolved: boolean | null
  path: string | null
  line: number | null
  side: string | null
  commit_id: string | null
  can_reply: boolean
  can_resolve: boolean
}

export interface CodeReviewCheck {
  id: string
  name: string
  status: string
  url: string
}

export interface CodeReviewSummary {
  description: string | null
  author: string | null
  created_at: string | null
  updated_at: string | null
  source_branch: string | null
  target_branch: string | null
  reviewers: string[]
  assignees: string[]
  commit_count: number | null
  changed_files: number | null
  additions: number | null
  deletions: number | null
}

export interface CodeReviewFile {
  path: string
  old_path: string | null
  status: 'added' | 'modified' | 'deleted' | 'renamed' | 'copied' | string
  additions: number | null
  deletions: number | null
  patch: string | null
  patch_truncated: boolean
  binary: boolean
  can_comment: boolean
  commit_id: string | null
  base_commit_id: string | null
  start_commit_id: string | null
  position_kind: 'diff' | 'file'
}

export interface CodeReviewContext {
  provider: GitServerProvider
  repository: string
  number: number
  summary: CodeReviewSummary
  review: Record<string, unknown>
  changes: unknown
  files: CodeReviewFile[] | null
  files_truncated: number
  comments: CodeReviewComment[]
  comments_truncated: number
  approvals: Array<{ id: string; author: string | null; state: string }>
  checks: { summary: string; items: CodeReviewCheck[] }
  state: string
  draft: boolean
  mergeability: {
    mergeable: unknown
    conflicts: boolean
    merged: boolean
  }
  permissions: {
    connection_scope: GitServerConnectionScope
    credential_configured: boolean
  }
  capabilities: Record<string, boolean>
}

export type CodeReviewAction =
  | 'comment'
  | 'inline_comment'
  | 'reply'
  | 'resolve_thread'
  | 'reopen_thread'
  | 'approve'
  | 'request_changes'
  | 'update'
  | 'checks'
  | 'merge'
  | 'close'
  | 'reopen'

export interface CodeReviewActionInput {
  action: CodeReviewAction
  body?: string
  thread_id?: string
  path?: string
  old_path?: string
  line?: number
  side?: 'LEFT' | 'RIGHT'
  commit_id?: string
  base_commit_id?: string
  start_commit_id?: string
  reviewer_id?: string
  idempotency_key?: string
  updates?: Record<string, unknown>
  merge_method?: string
  commit_title?: string
}

// ── WebBridge ────────────────────────────────────────────────────────────────

export interface WebBridgeExtensionInfo {
  extension_id: string
  browser: string
  version: string
  protocol_version: number
  capabilities: Record<string, unknown>
  connected_at: number
  current_url: string
  current_title: string
  automation?: WebBridgeAutomationState
}

export interface WebBridgeTextWatchState {
  id: string
  tab_id: number
  page_url: string
  needle: string
  state: 'armed' | 'matched'
  expires_at: number
}

export interface WebBridgeTeachRecordingState {
  tab_id: number
  title: string
  state: string
  action_count: number
}

export interface WebBridgeIssueCaptureState {
  tab_id: number
  page_url: string
  expires_at: number
  entry_count: number
}

export interface WebBridgeHumanControlState {
  tab_id: number
  acquired_at: number
  expires_at: number
}

export interface WebBridgeAutomationState {
  updated_at?: number
  active_tab_id?: number | null
  text_watches?: WebBridgeTextWatchState[]
  teach_recording?: WebBridgeTeachRecordingState | null
  issue_capture?: WebBridgeIssueCaptureState | null
  human_control_lease?: WebBridgeHumanControlState | null
  agent_control_tab_ids?: number[]
}

export interface WebBridgeStatusResponse {
  connected: boolean
  extensions: WebBridgeExtensionInfo[]
}

export interface WebBridgeLaunchBrowserResponse {
  ok: boolean
  browser?: string
  message: string
}

export interface WebBridgeAuditEntry {
  ts: number
  session_id: string
  extension_id: string | null
  action: string
  url: string
  success: boolean
  error: string | null
  direction: 'agent_out' | 'browser_in'
}

export interface WebBridgeAuditResponse {
  entries: WebBridgeAuditEntry[]
}

export interface WebBridgeTeachAction {
  kind: 'navigate' | 'click' | 'fill' | 'select' | 'set_checked'
  selector?: string
  url?: string
  value?: string
  values?: string[]
  checked?: boolean
  secret?: boolean
  parameter?: string
}

export interface WebBridgeTeachDraft {
  id: string
  pairing_id: string
  session_id: string
  tab_id: number
  title: string
  origin: string
  start_url: string
  actions: WebBridgeTeachAction[]
  parameter_names: string[]
  capture_warnings: string[]
  status: 'draft' | 'approved' | 'replay_failed'
  replay_count: number
  created_at: string
  approved_at: string | null
  last_replayed_at: string | null
  last_error: string | null
  replay_execution_id: string | null
  replay_next_step: number
  replay_state: 'idle' | 'ready' | 'in_flight' | 'ambiguous' | 'completed'
  replay_in_flight_step: number | null
  workflow_yaml: string
}

export interface WebBridgeTeachDraftReplayResponse {
  draft: WebBridgeTeachDraft
  steps: Array<{ kind: string; success: boolean; error: string | null }>
  execution_id: string
  next_step: number | null
}

// ── Side Chat ─────────────────────────────────────────────────────────────────

export interface SideChatSession {
  id: string
  main_session_id: string
  title: string
  created_at: string
}

export interface SideChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  blocks: ContentBlock[]
  agent?: string | null
  timestamp: Date
}

// ── Portable Agent Plugins ──────────────────────────────────────────────────

export interface PluginDiagnostic {
  severity: 'warning' | 'error'
  code: string
  message: string
  scope: string
}

export interface PluginSkillComponent {
  name: string
  description: string
  path: string
  valid: boolean
  diagnostics: PluginDiagnostic[]
}

export interface PluginMcpComponent {
  name: string
  transport: string
  valid: boolean
  config: Record<string, unknown>
  diagnostics: PluginDiagnostic[]
}

export interface PluginTrustCommand {
  server: string
  executable: string
  args: string[]
}

export interface PluginTrustRemoteHost {
  server: string
  transport: string
  host: string
  url: string
}

export interface PluginTrustCapability {
  name: string
  source: string
}

export interface PluginTrustReview {
  executable_commands: PluginTrustCommand[]
  remote_hosts: PluginTrustRemoteHost[]
  environment_fields: string[]
  capabilities: PluginTrustCapability[]
}

export interface PluginManifest {
  $schema: string
  name: string
  version: string | null
  description: string | null
  author: { name?: string; email?: string; url?: string } | null
  homepage: string | null
  repository: string | null
  license: string | null
  keywords: string[] | null
  extensions: Record<string, Record<string, unknown>>
}

export interface PluginInspection {
  root: string
  valid: boolean
  manifest: PluginManifest | null
  diagnostics: PluginDiagnostic[]
  skills: PluginSkillComponent[]
  mcp_servers: PluginMcpComponent[]
  trust: PluginTrustReview
  extension_namespaces: string[]
  content_sha256: string | null
}

export interface PluginInstallation {
  id: string
  name: string
  version: string | null
  description: string | null
  root: string
  source_type: 'builtin' | 'installed' | 'linked'
  source_ref: string
  content_sha256: string
  enabled: boolean
  installed_at: string
  updated_at: string
}

export interface PluginMcpRuntimeStatus {
  installation_id: string | null
  plugin_name: string | null
  server_name: string
  runtime_name: string
  transport: string
  enabled: boolean
  state: 'stopped' | 'starting' | 'ready' | 'error'
  error: string | null
  tool_names: string[]
  started_at: string | null
}

export interface PluginListItem {
  installation: PluginInstallation
  inspection: PluginInspection
  credentials: PluginCredentialState
  capabilities: {
    can_enable: boolean
    can_edit: boolean
    can_pack: boolean
    can_update: boolean
    can_uninstall: boolean
  }
}

export interface PluginListResponse {
  plugins: PluginListItem[]
  mcp_servers: PluginMcpRuntimeStatus[]
}

export interface PluginOperationResponse {
  installation: PluginInstallation
  inspection: PluginInspection
}

export interface PluginWorkspaceEntry {
  path: string
  name: string
  kind: 'file' | 'directory'
  size: number
}

export interface PluginWorkspaceFileResponse {
  root: string
  path: string
  content: string
}

export interface PluginWorkspaceMutationResponse {
  ok: boolean
  inspection: PluginInspection
}

export interface PluginCredentialFieldState {
  key: string
  label: string
  type: 'text' | 'secret' | 'url' | 'boolean'
  env: string
  required: boolean
  description: string
  placeholder: string
  configured: boolean
  value: string | boolean | null
}

export interface PluginCredentialState {
  supported: boolean
  configured: boolean
  fields: PluginCredentialFieldState[]
  error: string | null
}

export interface SideChatCreateResponse {
  side_chat_id: string
  title: string
}
