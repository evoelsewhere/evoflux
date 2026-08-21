import { keepPreviousData, useQuery } from '@tanstack/react-query'
import type { QueryKey } from '@tanstack/react-query'
import {
  AlertCircle,
  ArrowUpRight,
  Check,
  ChevronDown,
  CircleDot,
  FileCode2,
  GitBranch,
  Loader2,
  Network,
  RefreshCw,
  Search,
  Sparkles,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import type {
  ProjectCodeSearchResponse,
  ProjectRepoStatus,
  WorkspaceFileInfo,
} from '@/api/types'
import { getIntlLocale } from '@/i18n'
import { cn } from '@/lib/utils'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from './ui/dropdown-menu'

export interface CodeGraphSummary {
  indexed: number
  failed: number
  files: number
  symbols: number
  relations: number
  coverage: number
}

export interface CodeGraphOverviewProps {
  scopeName: string
  repositoryCount: number
  repos: ProjectRepoStatus[]
  summary: CodeGraphSummary
  statusLoading: boolean
  statusError: boolean
  reindexError: boolean
  isBusy: boolean
  onReindex: (full: boolean) => void
  searchKey: (query: string) => QueryKey
  searchGraph: (query: string, signal: AbortSignal) => Promise<ProjectCodeSearchResponse>
  renderExplorer: (open: boolean, onOpenChange: (open: boolean) => void) => React.ReactNode
  onFileSelect?: (file: WorkspaceFileInfo | null) => void
}

export const CODE_GRAPH_SEARCH_DEBOUNCE_MS = 80

function repoLabel(path: string): string {
  return path.split(/[\\/]/).pop() || path
}

function resultToFile(
  result: ProjectCodeSearchResponse['results'][number],
): WorkspaceFileInfo {
  const { node, path } = result
  return {
    path: node.file_path,
    name: node.file_path.split(/[\\/]/).pop() ?? node.file_path,
    size: 0,
    mtime: 0,
    mime: 'text/plain',
    sourceWorkspace: path,
  }
}

function compactNumber(value: number): string {
  return new Intl.NumberFormat(getIntlLocale(), {
    notation: value >= 1_000 ? 'compact' : 'standard',
    maximumFractionDigits: 1,
  }).format(value)
}

function RepositoryRow({ repo }: { repo: ProjectRepoStatus }) {
  const progress = Math.round((repo.index_progress ?? 0) * 100)
  const detail = repo.indexing
    ? repo.index_message ?? 'Building index…'
    : repo.index_error
      ? repo.index_error
      : repo.indexed
        ? `${compactNumber(repo.nodes)} symbols · ${compactNumber(repo.edges)} relations`
        : 'Waiting for first index'

  return (
    <div className="group relative overflow-hidden rounded-lg border border-(--color-border-subtle) bg-(--bg-card) px-3 py-2.5">
      {repo.indexing && (
        <span
          className="absolute inset-x-0 bottom-0 h-0.5 bg-(--accent-blue) transition-[width] duration-500"
          style={{ width: `${progress}%` }}
        />
      )}
      <div className="flex items-center gap-2.5">
        <span
          className={cn(
            'flex h-7 w-7 shrink-0 items-center justify-center rounded-md border',
            repo.index_error
              ? 'border-(--color-error)/30 bg-(--color-error)/10 text-(--color-error)'
              : repo.indexing
                ? 'border-(--accent-blue)/30 bg-(--accent-blue)/10 text-(--accent-blue)'
                : repo.indexed
                  ? 'border-(--accent-green)/30 bg-(--accent-green)/10 text-(--accent-green)'
                  : 'border-(--color-border) bg-(--bg-key) text-(--color-text-subtle)',
          )}
        >
          {repo.indexing ? (
            <Loader2 size={13} className="animate-spin" />
          ) : repo.index_error ? (
            <AlertCircle size={13} />
          ) : repo.indexed ? (
            <Check size={13} />
          ) : (
            <GitBranch size={13} />
          )}
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex items-center justify-between gap-2">
            <span className="truncate text-xs font-medium text-(--color-text)" title={repo.path}>
              {repoLabel(repo.path)}
            </span>
            <span className="shrink-0 font-mono text-[10px] text-(--color-text-subtle)">
              {repo.indexing ? `${progress}%` : compactNumber(repo.files)} files
            </span>
          </span>
          <span
            className={cn(
              'mt-0.5 block truncate text-[10px]',
              repo.index_error ? 'text-(--color-error)' : 'text-(--color-text-subtle)',
            )}
            title={detail}
          >
            {detail}
          </span>
        </span>
      </div>
    </div>
  )
}

export function CodeGraphOverview({
  scopeName,
  repositoryCount,
  repos,
  summary,
  statusLoading,
  statusError,
  reindexError,
  isBusy,
  onReindex,
  searchKey,
  searchGraph,
  renderExplorer,
  onFileSelect,
}: CodeGraphOverviewProps) {
  const [query, setQuery] = useState('')
  const [debounced, setDebounced] = useState('')
  const [explorerOpen, setExplorerOpen] = useState(false)

  useEffect(() => {
    const id = window.setTimeout(
      () => setDebounced(query.trim()),
      CODE_GRAPH_SEARCH_DEBOUNCE_MS,
    )
    return () => window.clearTimeout(id)
  }, [query])

  const results = useQuery({
    queryKey: searchKey(debounced),
    queryFn: ({ signal }) => searchGraph(debounced, signal),
    enabled: debounced.length >= 2 && summary.indexed > 0,
    staleTime: 30_000,
    placeholderData: keepPreviousData,
  })

  const grouped = useMemo(() => {
    const groups = new Map<string, ProjectCodeSearchResponse['results']>()
    for (const match of results.data?.results ?? []) {
      const list = groups.get(match.path) ?? []
      list.push(match)
      groups.set(match.path, list)
    }
    return [...groups.entries()]
  }, [results.data])

  const coveragePct = Math.round(summary.coverage * 100)
  const allReady = repos.length > 0 && summary.indexed === repos.length && summary.failed === 0
  const repositoryWord = repositoryCount === 1 ? 'repository' : 'repositories'

  return (
    <div className="@container/code-graph flex h-full min-h-0 flex-col bg-(--bg-page)">
      <section className="shrink-0 border-b border-(--color-border) bg-(--bg-card) px-3 py-3 @[42rem]/code-graph:px-4 @[42rem]/code-graph:py-4">
        <div className="flex flex-col items-stretch gap-3 @[28rem]/code-graph:flex-row @[28rem]/code-graph:items-start @[28rem]/code-graph:justify-between">
          <div className="flex min-w-0 items-start gap-3">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-(--accent-blue)/25 bg-(--accent-blue)/10 text-(--accent-blue)">
              <Network size={17} />
            </span>
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <h2 className="truncate text-sm font-semibold text-(--color-text)">Code graph</h2>
                {allReady && (
                  <span className="inline-flex items-center gap-1 rounded-full bg-(--accent-green)/10 px-1.5 py-0.5 text-[9px] font-medium text-(--accent-green)">
                    <CircleDot size={8} /> Ready
                  </span>
                )}
              </div>
              <p className="mt-0.5 truncate text-[11px] text-(--color-text-subtle)">
                {scopeName} · {repositoryCount} {repositoryWord}
              </p>
            </div>
          </div>

          <div className="flex shrink-0 items-center gap-2 self-end @[28rem]/code-graph:self-auto">
            <button
              type="button"
              onClick={() => setExplorerOpen(true)}
              disabled={summary.indexed === 0}
              className="inline-flex h-8 items-center gap-1.5 rounded-md border border-(--color-border) bg-(--bg-card) px-2.5 text-xs font-medium text-(--color-text) transition-colors hover:bg-(--bg-hover) disabled:cursor-not-allowed disabled:opacity-45"
            >
              Explore <ArrowUpRight size={12} />
            </button>
            <div className="flex h-8 overflow-hidden rounded-md bg-(--color-text) text-(--bg-page)">
              <button
                type="button"
                onClick={() => onReindex(false)}
                disabled={isBusy}
                className="inline-flex items-center gap-1.5 px-2.5 text-xs font-semibold transition-opacity hover:opacity-80 disabled:opacity-50"
              >
                {isBusy ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
                {isBusy ? 'Indexing' : summary.indexed > 0 ? 'Refresh' : 'Build index'}
              </button>
              <DropdownMenu>
                <DropdownMenuTrigger
                  aria-label="Index options"
                  disabled={isBusy}
                  className="flex items-center border-l border-(--bg-page)/20 px-1.5 hover:opacity-75 disabled:opacity-50"
                >
                  <ChevronDown size={12} />
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem onClick={() => onReindex(true)}>
                    Force full rebuild
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          </div>
        </div>

        <div className="mt-3 grid grid-cols-1 gap-3 @[44rem]/code-graph:mt-4 @[44rem]/code-graph:grid-cols-[minmax(180px,0.75fr)_minmax(260px,1.4fr)]">
          <div className="flex items-center gap-4 rounded-lg border border-(--color-border-subtle) bg-(--bg-card) p-3">
            <div
              className="relative flex h-16 w-16 shrink-0 items-center justify-center rounded-full"
              style={{
                background: `conic-gradient(var(--accent-blue) ${coveragePct * 3.6}deg, var(--bg-key) 0deg)`,
              }}
            >
              <span className="absolute inset-[5px] rounded-full bg-(--bg-card)" />
              <span className="relative font-mono text-sm font-semibold text-(--color-text)">{coveragePct}%</span>
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-xs font-medium text-(--color-text)">
                {statusLoading
                  ? 'Reading graph status…'
                  : statusError
                    ? 'Could not read graph status'
                    : `${summary.indexed} of ${repos.length} ${repositoryWord} ready`}
              </p>
              <p className="mt-1 text-[10px] leading-relaxed text-(--color-text-subtle)">
                {summary.failed > 0
                  ? `${summary.failed} ${repositoryWord} need attention.`
                  : isBusy
                    ? 'Graph data updates while repositories are scanned.'
                    : 'Search symbols or open the explorer to inspect relationships.'}
              </p>
              <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-(--color-text-muted)">
                <span><strong className="font-mono text-(--color-text)">{compactNumber(summary.symbols)}</strong> symbols</span>
                <span><strong className="font-mono text-(--color-text)">{compactNumber(summary.relations)}</strong> relations</span>
              </div>
            </div>
          </div>

          <div className="grid max-h-[148px] grid-cols-1 gap-2 overflow-y-auto pr-1 @[52rem]/code-graph:max-h-[124px] @[52rem]/code-graph:grid-cols-2">
            {statusLoading ? (
              <div className="col-span-full flex items-center justify-center gap-2 rounded-lg border border-(--color-border-subtle) py-8 text-xs text-(--color-text-subtle)">
                <Loader2 size={13} className="animate-spin" /> Loading repositories…
              </div>
            ) : repos.map((repo) => <RepositoryRow key={repo.workspace_id} repo={repo} />)}
          </div>
        </div>

        {reindexError && (
          <p className="mt-2 flex items-center gap-1.5 text-[10px] text-(--color-error)">
            <AlertCircle size={11} /> Could not start index refresh. Try again.
          </p>
        )}
      </section>

      <div className="shrink-0 border-b border-(--color-border) bg-(--bg-card) p-3">
        <label
          className={cn(
            'flex h-9 items-center gap-2 rounded-lg border border-(--color-border) bg-(--bg-input) px-3 transition-colors focus-within:border-(--color-border-strong)',
            summary.indexed === 0 && 'opacity-55',
          )}
        >
          <Search size={14} className="shrink-0 text-(--color-text-subtle)" />
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Escape') setQuery('')
            }}
            disabled={summary.indexed === 0}
            placeholder={summary.indexed > 0 ? 'Search symbols, files, or definitions…' : 'Build the index to search code'}
            className="min-w-0 flex-1 bg-transparent text-xs text-(--color-text) outline-none placeholder:text-(--color-text-subtle)"
          />
          {results.isFetching && <Loader2 size={12} className="animate-spin text-(--color-text-subtle)" />}
        </label>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        {summary.indexed === 0 ? (
          <div className="flex h-full min-h-32 flex-col items-center justify-center text-center">
            <span className="mb-3 flex h-10 w-10 items-center justify-center rounded-lg bg-(--bg-key) text-(--color-text-subtle)">
              <Sparkles size={17} />
            </span>
            <p className="text-xs font-medium text-(--color-text-muted)">Your graph starts here</p>
            <p className="mt-1 max-w-xs text-[10px] leading-relaxed text-(--color-text-subtle)">
              Build an index to connect symbols, files, and calls in this code graph.
            </p>
          </div>
        ) : debounced.length < 2 ? (
          <div className="flex h-full min-h-28 flex-col items-center justify-center text-center">
            <Network size={20} className="mb-2 text-(--color-text-subtle)" />
            <p className="text-xs text-(--color-text-muted)">Search the code graph</p>
            <p className="mt-1 text-[10px] text-(--color-text-subtle)">Type at least 2 characters from a function, class, module, or file name.</p>
          </div>
        ) : results.isError ? (
          <p className="px-2 py-4 text-xs text-(--color-error)">Search failed. Check the repository index and try again.</p>
        ) : !results.isLoading && grouped.length === 0 ? (
          <p className="px-2 py-4 text-xs text-(--color-text-subtle)">No graph results for “{debounced}”.</p>
        ) : (
          <div className={cn('space-y-4', results.isFetching && 'opacity-70')}>
            {grouped.map(([path, matches]) => (
              <section key={path}>
                <div className="mb-1.5 flex items-center gap-1.5 px-1">
                  <GitBranch size={10} className="text-(--color-text-subtle)" />
                  <h3 className="text-[10px] font-semibold uppercase tracking-[0.08em] text-(--color-text-muted)">
                    {repoLabel(path)}
                  </h3>
                  <span className="text-[9px] text-(--color-text-subtle)">{matches.length}</span>
                </div>
                <div className="grid grid-cols-1 gap-1.5 @[42rem]/code-graph:grid-cols-2">
                  {matches.map((result) => (
                    <button
                      key={result.node.id}
                      type="button"
                      onClick={() => onFileSelect?.(resultToFile(result))}
                      className="group flex min-w-0 items-start gap-2.5 rounded-lg border border-transparent bg-(--bg-card) px-3 py-2.5 text-left transition-colors hover:border-(--color-border) hover:bg-(--bg-hover)"
                    >
                      <FileCode2 size={14} className="mt-0.5 shrink-0 text-(--accent-blue)" />
                      <span className="min-w-0 flex-1">
                        <span className="flex items-center gap-1.5">
                          <span className="truncate font-mono text-xs font-medium text-(--color-text)">{result.node.name}</span>
                          <span className="shrink-0 rounded bg-(--bg-key) px-1 py-0.5 font-mono text-[8px] uppercase text-(--color-text-subtle)">{result.node.kind}</span>
                        </span>
                        <span className="mt-1 block truncate font-mono text-[10px] text-(--color-text-subtle)">
                          {result.node.file_path}:{result.node.line_start}
                        </span>
                      </span>
                    </button>
                  ))}
                </div>
              </section>
            ))}
          </div>
        )}
      </div>

      {renderExplorer(explorerOpen, setExplorerOpen)}
    </div>
  )
}
