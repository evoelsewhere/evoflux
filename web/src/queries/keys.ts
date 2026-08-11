export const queryKeys = {
  health: () => ['health'] as const,
  diagnostics: () => ['diagnostics'] as const,
  agents: () => ['agents'] as const,
  teamAgents: (workspace?: string | null, mode?: string | null) =>
    workspace
      ? (['agents', 'team', workspace, mode ?? 'coding'] as const)
      : (['agents', 'team'] as const),
  team: {
    status: () => ['team', 'status'] as const,
    sessions: {
      all: () => ['team', 'sessions'] as const,
      // No-arg form is the invalidation prefix covering every mode variant.
      infinite: (mode?: string | null) =>
        mode
          ? (['team', 'sessions', 'infinite', mode] as const)
          : (['team', 'sessions', 'infinite'] as const),
      workspace: (workspace: string) => ['team', 'sessions', 'workspace', workspace] as const,
      project: (projectId: string) => ['team', 'sessions', 'project', projectId] as const,
      list: (offset: number, limit: number) =>
        ['team', 'sessions', 'list', offset, limit] as const,
      detail: (id: string) => ['team', 'sessions', id] as const,
    },
    // Sidebar folders — one entry per mode, holding the folders *and* their
    // sessions (see GET /team/session-folders), so filing a session
    // invalidates a single key. The no-arg form is the every-mode prefix.
    sessionFolders: (mode: string) => ['team', 'session-folders', mode] as const,
    sessionFoldersAll: () => ['team', 'session-folders'] as const,
    // Workspace-files listing per session — powers the Artifacts panel.
    files: (sessionId: string) => ['team', 'files', sessionId] as const,
    // Effective root only — powers desktop "Open in" without scanning files.
    workspaceRoot: (sessionId: string) => ['team', 'workspace-root', sessionId] as const,
    processes: () => ['team', 'processes'] as const,
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
    all: (workspace: string) => ['code-context', workspace] as const,
    status: (workspace: string) => ['code-context', workspace, 'status'] as const,
    freshness: (workspace: string) => ['code-context', workspace, 'freshness'] as const,
    capabilities: (workspace: string) => ['code-context', workspace, 'capabilities'] as const,
    search: (workspace: string, query: string) =>
      ['code-context', workspace, 'search', query] as const,
    query: (workspace: string, query: string) =>
      ['code-context', workspace, 'query', query] as const,
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
    // No-arg form is the invalidation prefix for every discovery scope.
    registry: (workspaces?: readonly string[], mode?: string | null) =>
      workspaces === undefined && mode === undefined
        ? (['agentFiles', 'registry'] as const)
        : (['agentFiles', 'registry', workspaces ?? [], mode ?? null] as const),
  },
  skillFiles: {
    all: () => ['skillFiles'] as const,
    list: (workspaces?: readonly string[], mode?: string | null) =>
      workspaces === undefined && mode === undefined
        ? (['skillFiles', 'list'] as const)
        : (['skillFiles', 'list', workspaces ?? [], mode ?? null] as const),
    detail: (name: string, workspaces?: readonly string[], mode?: string | null) =>
      workspaces === undefined && mode === undefined
        ? (['skillFiles', 'detail', name] as const)
        : (['skillFiles', 'detail', name, workspaces ?? [], mode ?? null] as const),
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
    sessionList: (sessionId: string) => ['scheduler', 'list', 'session', sessionId] as const,
  },
  todos: (sessionId: string) => ['todos', sessionId] as const,
  // Merged workspace-tree + projects overview powering the coding sidebar —
  // one query, one cache entry, so "which repos are standalone vs
  // project-owned" never has to be reconciled client-side from two
  // independently-fetched lists. See GET /team/workspace/tree.
  codingOverview: () => ['coding-overview'] as const,
  projects: {
    all: () => ['projects'] as const,
    detail: (id: string) => ['projects', 'detail', id] as const,
    crossRepoEdges: (id: string) => ['projects', 'detail', id, 'cross-repo-edges'] as const,
    codeGraphStatus: (id: string) => ['projects', 'detail', id, 'code-context-status'] as const,
    codeGraphSearch: (id: string, query: string) =>
      ['projects', 'detail', id, 'code-context-search', query] as const,
    codeGraphData: (id: string, nodeLimit?: number, edgeLimit?: number) =>
      nodeLimit === undefined && edgeLimit === undefined
        ? (['projects', 'detail', id, 'code-context-data'] as const)
        : (['projects', 'detail', id, 'code-context-data', nodeLimit, edgeLimit] as const),
    aimAll: () => ['projects', 'aim'] as const,
    aimMeta: () => ['projects', 'aim', 'meta'] as const,
    aimSummary: (id: string) => ['projects', 'detail', id, 'aim-summary'] as const,
    aimUnits: (id: string, wave?: number) =>
      ['projects', 'detail', id, 'aim-units', wave ?? null] as const,
    aimRun: (id: string, runId: string) =>
      ['projects', 'detail', id, 'aim-run', runId] as const,
  },
  git: {
    reviews: (scope?: string) =>
      scope
        ? ['git', 'reviews', scope] as const
        : ['git', 'reviews'] as const,
    connections: () => ['git', 'review-connections'] as const,
    repository: (ws: string) => ['git', ws, 'repository'] as const,
    changes: (ws: string) => ['git', ws, 'changes'] as const,
    branches: (ws: string) => ['git', ws, 'branches'] as const,
    remotes: (ws: string) => ['git', ws, 'remotes'] as const,
    tags: (ws: string) => ['git', ws, 'tags'] as const,
    log: (ws: string, scope?: string | number) =>
      typeof scope === 'string'
        ? ['git', ws, 'log', scope] as const
        : ['git', ws, 'log'] as const,
    logFiles: (ws: string, sha: string) => ['git', ws, 'log-files', sha] as const,
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
  plugins: {
    all: () => ['plugins'] as const,
    list: () => ['plugins', 'list'] as const,
    credentials: (installationId: string) =>
      ['plugins', 'credentials', installationId] as const,
  },
  settings: {
    sandbox: () => ['settings', 'sandbox'] as const,
    versionControl: () => ['settings', 'version-control'] as const,
    webbridge: () => ['settings', 'webbridge'] as const,
    multimodal: () => ['settings', 'multimodal'] as const,
    providers: () => ['settings', 'providers'] as const,
    providerModels: (providerId: string) => ['settings', 'providers', providerId, 'models'] as const,
    providerUsage: (providerId: string) => ['settings', 'providers', providerId, 'usage'] as const,
  },
}
