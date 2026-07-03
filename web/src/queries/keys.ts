export const queryKeys = {
  health: () => ['health'] as const,
  diagnostics: () => ['diagnostics'] as const,
  agents: () => ['agents'] as const,
  teamAgents: (workspace?: string | null) => workspace ? ['agents', 'team', workspace] as const : ['agents', 'team'] as const,
  team: {
    status: () => ['team', 'status'] as const,
    sessions: {
      all: () => ['team', 'sessions'] as const,
      infinite: () => ['team', 'sessions', 'infinite'] as const,
      workspace: (workspace: string) => ['team', 'sessions', 'workspace', workspace] as const,
      project: (projectId: string) => ['team', 'sessions', 'project', projectId] as const,
      list: (offset: number, limit: number) =>
        ['team', 'sessions', 'list', offset, limit] as const,
      detail: (id: string) => ['team', 'sessions', id] as const,
    },
    // Workspace-files listing per session — powers the Artifacts panel.
    files: (sessionId: string) => ['team', 'files', sessionId] as const,
  },
  // Coding-mode workspace sidebar — keyed by the absolute workspace path
  // (a single project may be shared across multiple sessions/tabs, so the
  // cache is keyed by path rather than session id). The reducer enqueues
  // ``coding_workspace`` invalidations on every file-mutating tool_end and
  // after /undo + /redo so the panel reflects disk state in real time.
  coding: {
    all: (workspace: string) => ['coding-workspace', workspace] as const,
    files: (workspace: string) =>
      ['coding-workspace-files', workspace] as const,
    diff: (workspace: string) =>
      ['coding-workspace-diff', workspace] as const,
    status: (workspace: string) =>
      ['coding-workspace-status', workspace] as const,
  },
  // Code knowledge graph panel — keyed by the absolute workspace path, like
  // the coding sidebar. Status + search share the path so a reindex can
  // invalidate both with a single prefix.
  codeGraph: {
    all: (workspace: string) => ['code-graph', workspace] as const,
    status: (workspace: string) => ['code-graph', workspace, 'status'] as const,
    search: (workspace: string, query: string) =>
      ['code-graph', workspace, 'search', query] as const,
  },
  // File references for the input bar's @-mention picker. Keyed by the
  // workspace path (coding mode) or session id (normal mode) so the two
  // origins don't share a cache entry.
  fileRefs: {
    coding: (workspace: string) => ['file-refs', 'coding', workspace] as const,
    session: (sessionId: string) => ['file-refs', 'session', sessionId] as const,
  },
  quote: () => ['quote'] as const,
  wiki: {
    all: () => ['wiki'] as const,
    tree: () => ['wiki', 'tree'] as const,
    file: (path: string) => ['wiki', 'file', path] as const,
  },
  dream: {
    config: () => ['dream', 'config'] as const,
  },
  agentFiles: {
    all: () => ['agentFiles'] as const,
    list: () => ['agentFiles', 'list'] as const,
    detail: (name: string) => ['agentFiles', 'detail', name] as const,
    registry: () => ['agentFiles', 'registry'] as const,
  },
  skillFiles: {
    all: () => ['skillFiles'] as const,
    list: () => ['skillFiles', 'list'] as const,
    detail: (name: string) => ['skillFiles', 'detail', name] as const,
  },
  commands: {
    list: (workspace?: string | null) => ['commands', 'list', workspace ?? null] as const,
  },
  snippets: {
    list: (workspace: string) => ['snippets', 'list', workspace] as const,
  },
  observability: {
    summary: (days: number) => ['observability', 'summary', days] as const,
    traces: (days: number, limit: number, offset: number) =>
      ['observability', 'traces', days, limit, offset] as const,
    infiniteTraces: (days: number, limit: number) =>
      ['observability', 'traces', 'infinite', days, limit] as const,
    trace: (traceId: string) => ['observability', 'trace', traceId] as const,
  },
  scheduler: {
    all: () => ['scheduler'] as const,
    list: () => ['scheduler', 'list'] as const,
  },
  todos: (sessionId: string) => ['todos', sessionId] as const,
  chapters: {
    list: (sessionId: string) => ['chapters', sessionId] as const,
  },
  // Merged workspace-tree + projects overview powering the coding sidebar —
  // one query, one cache entry, so "which repos are standalone vs
  // project-owned" never has to be reconciled client-side from two
  // independently-fetched lists. See GET /team/workspace/tree.
  codingOverview: () => ['coding-overview'] as const,
  projects: {
    all: () => ['projects'] as const,
    detail: (id: string) => ['projects', 'detail', id] as const,
    crossRepoEdges: (id: string) => ['projects', 'detail', id, 'cross-repo-edges'] as const,
    crossRepoStatus: (id: string) => ['projects', 'detail', id, 'cross-repo-status'] as const,
    codeGraphStatus: (id: string) => ['projects', 'detail', id, 'code-graph-status'] as const,
    codeGraphSearch: (id: string, query: string) =>
      ['projects', 'detail', id, 'code-graph-search', query] as const,
    codeGraphData: (id: string) => ['projects', 'detail', id, 'code-graph-data'] as const,
  },
  git: {
    changes: (ws: string) => ['git', ws, 'changes'] as const,
    branches: (ws: string) => ['git', ws, 'branches'] as const,
    log: (ws: string, page: number) => ['git', ws, 'log', page] as const,
    logFiles: (ws: string, sha: string) => ['git', ws, 'log', sha, 'files'] as const,
    stashes: (ws: string) => ['git', ws, 'stashes'] as const,
    jobs: (ws: string) => ['git', ws, 'jobs'] as const,
    conflicts: (ws: string) => ['git', ws, 'conflicts'] as const,
    diffView: (ws: string, path: string) => ['git', ws, 'diff-view', path] as const,
  },
  mcp: {
    all: () => ['mcp'] as const,
    list: () => ['mcp', 'list'] as const,
    detail: (name: string) => ['mcp', 'detail', name] as const,
  },
  settings: {
    sandbox: () => ['settings', 'sandbox'] as const,
    multimodal: () => ['settings', 'multimodal'] as const,
    providers: () => ['settings', 'providers'] as const,
    providerModels: (providerId: string) => ['settings', 'providers', providerId, 'models'] as const,
    providerUsage: (providerId: string) => ['settings', 'providers', providerId, 'usage'] as const,
  },
}
