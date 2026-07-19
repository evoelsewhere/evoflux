import { useMemo, useState } from 'react'
import { GitBranch, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { CrossRepoEdge, ProjectRepoStatus } from '@/api/types'

function repoLabel(path: string): string {
  return path.split(/[\\/]/).pop() || path
}

interface CellData {
  total: number
  resolved: number
  unresolved: number
  rejected: number
  edges: CrossRepoEdge[]
}

export interface RepoGraphMatrixProps {
  repos: ProjectRepoStatus[]
  crossRepoEdges: CrossRepoEdge[]
}

export function RepoGraphMatrix({ repos, crossRepoEdges }: RepoGraphMatrixProps) {
  const [selectedCell, setSelectedCell] = useState<{ src: string; dst: string } | null>(null)

  const repoIds = useMemo(() => repos.map((r) => r.workspace_id), [repos])
  const repoById = useMemo(() => new Map(repos.map((r) => [r.workspace_id, r])), [repos])

  const matrix = useMemo(() => {
    const map = new Map<string, CellData>()
    for (const edge of crossRepoEdges) {
      const src = edge.src_workspace_id
      const dst = edge.dst_workspace_id
      if (!src || !dst || src === dst) continue
      const key = `${src}→${dst}`
      const cell = map.get(key) ?? { total: 0, resolved: 0, unresolved: 0, rejected: 0, edges: [] }
      cell.total++
      if (edge.status === 'resolved') cell.resolved++
      else if (edge.status === 'unresolved') cell.unresolved++
      else if (edge.status === 'rejected') cell.rejected++
      cell.edges.push(edge)
      map.set(key, cell)
    }
    return map
  }, [crossRepoEdges])

  const maxCount = useMemo(() => {
    let max = 0
    for (const cell of matrix.values()) {
      max = Math.max(max, cell.total)
    }
    return max
  }, [matrix])

  const selectedEdges = useMemo(() => {
    if (!selectedCell) return []
    return matrix.get(`${selectedCell.src}→${selectedCell.dst}`)?.edges ?? []
  }, [selectedCell, matrix])

  if (repos.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-xs text-(--color-text-subtle)">
        No repositories to display.
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col overflow-hidden bg-(--bg-card)">
      <div className="flex flex-1 min-h-0 gap-4 p-4">
        <div className="flex-1 overflow-auto">
          <table className="border-separate border-spacing-0.5 text-[11px]">
            <thead>
              <tr>
                <th className="sticky left-0 z-(--z-panel) min-w-[120px] bg-(--bg-card) p-2 text-left text-[10px] font-medium text-(--color-text-muted)">
                  From \ To
                </th>
                {repoIds.map((id) => {
                  const repo = repoById.get(id)
                  return (
                    <th
                      key={id}
                      className="min-w-[48px] max-w-[120px] p-2 text-center text-[10px] font-medium text-(--color-text-muted)"
                    >
                      <span className="flex items-center justify-center gap-1">
                        <GitBranch size={9} />
                        <span className="truncate">{repo ? repoLabel(repo.path) : id.slice(0, 8)}</span>
                      </span>
                    </th>
                  )
                })}
              </tr>
            </thead>
            <tbody>
              {repoIds.map((srcId) => {
                const srcRepo = repoById.get(srcId)
                return (
                  <tr key={srcId}>
                    <td className="sticky left-0 z-(--z-panel) min-w-[120px] bg-(--bg-card) p-2 text-[10px] font-medium text-(--color-text)">
                      <span className="flex items-center gap-1">
                        <GitBranch size={9} className="text-(--color-text-subtle)" />
                        <span className="truncate">{srcRepo ? repoLabel(srcRepo.path) : srcId.slice(0, 8)}</span>
                      </span>
                    </td>
                    {repoIds.map((dstId) => {
                      const cell = matrix.get(`${srcId}→${dstId}`)
                      const count = cell?.total ?? 0
                      const intensity = maxCount > 0 ? count / maxCount : 0
                      const isSelected = selectedCell?.src === srcId && selectedCell?.dst === dstId
                      return (
                        <td key={dstId} className="p-0">
                          <button
                            type="button"
                            disabled={count === 0}
                            onClick={() => setSelectedCell({ src: srcId, dst: dstId })}
                            className={cn(
                              'flex h-full w-full min-h-[40px] flex-col items-center justify-center gap-0.5 rounded transition-colors',
                              count === 0
                                ? 'bg-(--bg-key)/30 text-(--color-text-subtle)'
                                : 'text-(--color-text) hover:ring-1 hover:ring-(--color-text-muted)',
                              isSelected && 'ring-2 ring-(--accent-blue)',
                            )}
                            style={
                              count > 0
                                ? {
                                    backgroundColor: `rgba(14, 165, 233, ${0.1 + intensity * 0.45})`,
                                  }
                                : undefined
                            }
                            title={
                              cell
                                ? `${count} refs · ${cell.resolved} resolved · ${cell.unresolved} unresolved · ${cell.rejected} rejected`
                                : 'No references'
                            }
                          >
                            {count > 0 ? (
                              <>
                                <span className="font-semibold tabular-nums">{count}</span>
                                <span className="text-[8px] text-(--color-text-subtle)">
                                  {cell!.resolved > 0 && `${cell!.resolved} ok`}
                                  {cell!.unresolved > 0 && `${cell!.resolved > 0 ? ' · ' : ''}${cell!.unresolved} ?`}
                                </span>
                              </>
                            ) : (
                              <span className="text-[10px]">—</span>
                            )}
                          </button>
                        </td>
                      )
                    })}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>

        {selectedCell && (
          <div className="flex w-80 flex-col gap-3 overflow-hidden rounded-lg border border-(--color-border) bg-(--bg-card) p-3 shadow-sm">
            <div className="flex items-center justify-between gap-2">
              <p className="text-xs font-medium text-(--color-text)">
                {repoLabel(repoById.get(selectedCell.src)?.path ?? selectedCell.src)} →{' '}
                {repoLabel(repoById.get(selectedCell.dst)?.path ?? selectedCell.dst)}
              </p>
              <button
                type="button"
                onClick={() => setSelectedCell(null)}
                className="flex h-6 w-6 items-center justify-center rounded text-(--color-text-muted) hover:bg-(--bg-key)"
              >
                <X size={12} />
              </button>
            </div>
            <p className="text-[10px] text-(--color-text-subtle)">{selectedEdges.length} cross-repo references</p>
            <div className="flex-1 overflow-y-auto">
              <ul className="space-y-1">
                {selectedEdges.map((edge, i) => (
                  <li
                    key={`${edge.id}-${i}`}
                    className="rounded bg-(--bg-key)/50 px-2 py-1.5 text-[10px] text-(--color-text)"
                  >
                    <span className="flex items-center gap-1.5">
                      <span
                        className={cn(
                          'h-1.5 w-1.5 rounded-full',
                          edge.status === 'resolved'
                            ? 'bg-green-500'
                            : edge.status === 'unresolved'
                              ? 'bg-(--color-error)'
                              : 'bg-(--color-text-muted)',
                        )}
                      />
                      <span className="font-mono text-(--color-text-subtle)">{edge.kind}</span>
                    </span>
                    <p className="mt-0.5 truncate text-(--color-text-subtle)" title={edge.src_node_id ?? undefined}>
                      {edge.src_node_id?.slice(0, 16)}…
                    </p>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        )}
      </div>

      <div className="flex shrink-0 items-center gap-4 border-t border-(--color-border) bg-(--bg-card)/95 px-4 py-2 text-[10px] text-(--color-text-muted)">
        <span className="flex items-center gap-1">
          <span className="h-2 w-2 rounded-full bg-green-500" /> Resolved
        </span>
        <span className="flex items-center gap-1">
          <span className="h-2 w-2 rounded-full bg-(--color-error)" /> Unresolved
        </span>
        <span className="flex items-center gap-1">
          <span className="h-2 w-2 rounded-full bg-(--color-text-muted)" /> Rejected
        </span>
        <span className="ml-auto">Darker cells = more references</span>
      </div>
    </div>
  )
}
