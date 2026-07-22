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
}

export interface PlanApprovalPending {
  requestId: string
  sessionId: string
  /** Agent-authored markdown plan document (may be empty for legacy plans). */
  plan: string
  steps: PlanStep[]
}

export type PlanDecision = 'approved' | 'rejected' | 'revise'

export interface AskUserQuestionItem {
  question: string
  options: string[]
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

// ── Code knowledge graph (/api/code-graph) ──────────────────────────────────

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

// Result of triggering a project-wide reindex with a single call — the
// backend starts every repo's index job and, for multi-repo projects, chains
// into cross-repo resolve automatically once they all settle.
export interface ProjectReindexStartedResponse {
  indexing: boolean
  repo_count: number
  already_running: number
  will_resolve: boolean
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
  category?: 'text' | 'image' | 'document'
  url?: string        // /api/chat/files/{session_id}/{filename} or blob URL for optimistic
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
  // "coding" (default) or "aim" — the two kinds never see each other's
  // projects (GET /team/projects?kind= filter).
  kind: string
  settings: Record<string, unknown>
  workspaces: ProjectWorkspaceItem[]
  created_at: string
  updated_at: string
}

// ── AIM mode (documents/plans/aim-mode-shell-ux-spec.md v2.2) ────────────────

export interface AimUnitOut {
  id: string
  module: string
  name: string
  kind: string
  phase: string
  wave: number | null
  assignee: string | null
  depends_on: string[]
  complexity: Record<string, unknown>
  kb_doc_path: string | null
  updated_at: string
}

export interface AimPhaseCounts {
  inventory: number
  understood: number
  designed: number
  converted: number
  equivalent: number
  cutover: number
}

/** Backend-authoritative AIM vocabulary (GET /team/projects/aim/meta) — the
 * source of truth the UI reads instead of hardcoding the phase set. */
export interface AimMeta {
  unit_phases: string[]
  project_phases: string[]
  phase_labels: Record<string, string>
  phase_next_pipeline: Record<string, string | null>
}

export interface AimProjectSummary {
  project_id: string
  total_units: number
  phase_counts: AimPhaseCounts
  equivalent_pct: number
  latest_run_at: string | null
}

export interface AimRunOut {
  id: string
  unit_id: string
  kind: string
  verdict: string
  case_set: string | null
  stats: Record<string, unknown>
  report_path: string | null
  session_id: string | null
  workflow_execution_id: string | null
  created_at: string
  // Parsed report.json contents — only populated by GET .../aim/runs/{id}.
  report: Record<string, unknown> | null
}

export interface AimProjectCreateRequest {
  name: string
  rulebook_id: string
  rulebook_version?: string
  source_paths: string[]
  target_path: string
  kb_path: string
}

export interface AimManifestPreview {
  rulebook_id: string
  rulebook_version: string
  source_identities: string[]
  target_identities: string[]
  phase: string
}

export interface AimProjectJoinRequest {
  name: string
  kb_path: string
  source_paths: string[]
  target_path: string
}

// One row of the project-wide run history (Runs & Reports table).
export interface AimRunListItem {
  id: string
  unit_id: string
  unit: string
  kind: string
  verdict: string
  case_set: string | null
  report_path: string | null
  session_id: string | null
  workflow_execution_id: string | null
  created_at: string
}

export interface AimReindexResponse {
  created: number
  updated: number
  unchanged: number
}

export interface AimRulebookFile {
  path: string
  content: string
}

export interface AimRulebook {
  id: string
  // 'project' = resolved from the KB repo's own rulebook/ override;
  // 'builtin' = one of the shared packs shipped with EvoFlux.
  source: 'project' | 'builtin'
  manifest: Record<string, unknown>
  files: AimRulebookFile[]
}

// Result of POST /team/projects/aim/detect on a conventional project root
// (<name>/{aim_source_base/*, aim_<name>_document, aim_target_source}).
export interface AimLayoutDetection {
  root: string
  project_name: string
  source_paths: string[]
  kb_path: string
  target_path: string
  has_manifest: boolean
  source_identity_map: Record<string, string | null>
  target_identity_map: Record<string, string | null>
  warnings: string[]
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

// method distinguishes "certain" links (static_fqn/static_manifest_exact)
// from lower-confidence ones (static_manifest_package/lexical) and
// AI-inferred ones (llm) — the UI badges these differently. 'embedding' is
// no longer produced (the vector layer was removed in favor of FTS5 lexical
// search) but stays valid so historical rows still deserialize/display.
export type CrossRepoEdgeMethod =
  | 'static_fqn'
  | 'static_manifest_exact'
  | 'static_manifest_package'
  | 'embedding'
  | 'lexical'
  | 'llm'

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

export type CrossRepoResolveRequest = Record<string, never>
// Empty: the backend always runs Tier 0 + Tier A + lexical Tier B.

export interface CrossRepoResolveStats {
  reattached: number
  static_resolved: number
  lexical_resolved: number
  still_unresolved: number
}

export interface CrossRepoResolveJob {
  project_id: string
  status: 'running' | 'done' | 'error'
  phase: string
  progress: number
  message: string
  error: string | null
  stats: CrossRepoResolveStats | null
}

export interface CrossRepoResolveStatusResponse {
  running: boolean
  job: CrossRepoResolveJob | null
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

export interface TeamHistoryResponse {
  lead: SessionDetailResponse
  members: Array<{
    name: string
    session_id: string
    messages: MessageResponse[]
  }>
  loop_status?: {
    prompt: string | null
    limit: number
    remaining: number
    used: number
    paused: boolean
  } | null
  // Live workflow snapshot from the runner — same live-state semantics as
  // loop_status (gone after restart).
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
  scope: 'forge' | 'coding' | 'aim'
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

export interface Chapter {
  id: string
  session_id: string
  title: string
  summary: string | null
  message_id: string | null
  wiki_paths: string[]
  created_at: string
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
  | 'desktop_notification'
  | 'title_update'
  | 'summarization_start'
  | 'summarization_content'
  | 'summarization_end'
  | 'browser_session'
  | 'chapter_created'

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
   *  ``compaction`` blocks carry ``state: 'compacting' | 'compacted'`` and
   *  optional ``error: true``. Keeping this generic avoids one typed field
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
  /** imports/ — raw imported Memory v2 documents. */
  imports: WikiFileInfo[]
  /** wiki/ — Memory v2 curated and source-compiled pages. */
  wiki: WikiFileInfo[]
  /** topics/ — legacy concept pages (abstract ideas, techniques). */
  topics: WikiFileInfo[]
  /** entities/ — legacy concrete things (people, tools, orgs, products). */
  entities: WikiFileInfo[]
  /** sources/ — legacy one-page summaries per ingested source. */
  sources: WikiFileInfo[]
  /** comparisons/ — legacy X-vs-Y pages. */
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
  temperature?: number | null
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

export interface SkillSummary {
  name: string
  description: string
  valid: boolean
  error: string | null
  built_in: boolean
  editable: boolean
  source: string
}

export interface SkillDetail {
  name: string
  path: string
  content: string
  description: string
  error: string | null
  built_in: boolean
  editable: boolean
  source: string
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
  /** Tier membership: null = every tier; e.g. ['forge'] restricts to that mode. */
  tiers: string[] | null
  /** Lead-only tools are never granted to members — hidden from member pickers. */
  lead_only: boolean
}

export interface SkillCatalogEntry {
  name: string
  description: string
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
}

export interface RegistryResponse {
  tools: ToolCatalogEntry[]
  skills: SkillCatalogEntry[]
  providers: string[]
  models: ModelCatalogEntry[]
}

// ── Workspace files (artifacts panel) ────────────────────────────────────────
//
// Flat recursive listing of a session's agent workspace (``.EvoFlux/team/{sid}``).
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

// ── Scheduler ───────────────────────────────────────────────────────────────

export type ScheduledTaskMode = 'forge' | 'coding'

export interface ScheduledTaskResponse {
  id: string
  name: string
  // Routing target — every task delivers to the team lead of the matching
  // team (default lead for ``normal``, workspace lead for ``coding``).
  // See documents/docs/agent/tools.md#scheduler-builtinschedulepy.
  mode: ScheduledTaskMode
  workspace: string | null
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
  branch: string | null
  ahead: number
  behind: number
  files: ChangedFile[]
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
  author: string
  date: string
  message: string
}

export interface GitLogResponse {
  entries: GitLogEntry[]
  has_more: boolean
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

// ── WebBridge ────────────────────────────────────────────────────────────────

export interface WebBridgeExtensionInfo {
  extension_id: string
  browser: string
  version: string
  protocol_version: number
  capabilities: Record<string, unknown>
  paired: boolean
  connected_at: number
  current_url: string
  current_title: string
}

export interface WebBridgeStatusResponse {
  connected: boolean
  extensions: WebBridgeExtensionInfo[]
}

export interface WebBridgePairingCodeResponse {
  code: string
  expires_in: number
}

export interface WebBridgePairingInfo {
  pairing_id: string
  label: string
  browser: string
  version: string
  scopes: string[]
  created_at: string
  last_seen_at: string
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
}

export interface WebBridgeAuditResponse {
  entries: WebBridgeAuditEntry[]
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

export interface SideChatCreateResponse {
  side_chat_id: string
  title: string
}
