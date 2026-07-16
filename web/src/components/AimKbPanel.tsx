/**
 * AimKbPanel — the Knowledge Base feature: a READ-ONLY window onto the
 * project's document repo (aim_<name>_document), tree on the left,
 * markdown on the right (aim-mode-shell-ux-spec.md v2.2 §3.5).
 *
 * The one action here is Reindex: rebuild the local aim_units index from
 * KB frontmatter after a manual `git pull` (the repo is the system of
 * record; the table is a per-machine projection). Everything that WRITES
 * knowledge lives in Pipelines — one job, one place.
 */

import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FileText, Loader2, RefreshCw } from 'lucide-react'
import {
  codingWorkspaceFileUrl,
  listCodingWorkspaceFiles,
  reindexAimProject,
} from '@/api/client'
import { queryKeys } from '@/queries/keys'
import { MarkdownBlock } from '@/utils/markdown'
import { cn } from '@/lib/utils'
import type { CodingProject, ProjectWorkspaceItem } from '@/api/types'

export function resolveAimRolePath(
  project: CodingProject,
  role: 'kb' | 'target' | 'source',
): string | null {
  return resolveAimRoleWorkspaces(project, role)[0]?.path ?? null
}

/** Every workspace mapped to an AIM role on this machine — `source` may
 * hold several repos, kb/target normally exactly one. */
export function resolveAimRoleWorkspaces(
  project: CodingProject,
  role: 'kb' | 'target' | 'source',
): ProjectWorkspaceItem[] {
  const aim = project.settings?.aim as
    | { roles?: Record<string, string[]> }
    | undefined
  const ids = aim?.roles?.[role] ?? []
  const found: ProjectWorkspaceItem[] = []
  for (const id of ids) {
    const workspace = project.workspaces.find((w) => w.workspace_id === id)
    if (workspace) found.push(workspace)
  }
  return found
}

export function AimKbPanel({ project }: { project: CodingProject }) {
  const queryClient = useQueryClient()
  const kbPath = resolveAimRolePath(project, 'kb')
  const [selected, setSelected] = useState<string | null>(null)

  const filesQuery = useQuery({
    queryKey: ['aim-kb-files', kbPath ?? ''],
    queryFn: () => listCodingWorkspaceFiles(kbPath as string),
    enabled: Boolean(kbPath),
    staleTime: 15_000,
  })

  const mdFiles = useMemo(
    () =>
      (filesQuery.data?.files ?? [])
        .filter((f) => f.path.endsWith('.md') || f.path.endsWith('.yaml'))
        .map((f) => f.path)
        .sort(),
    [filesQuery.data],
  )

  const contentQuery = useQuery({
    queryKey: ['aim-kb-file', kbPath ?? '', selected ?? ''],
    queryFn: async () => {
      const res = await fetch(codingWorkspaceFileUrl(kbPath as string, selected as string))
      if (!res.ok) throw new Error(`Failed to read ${selected}`)
      return res.text()
    },
    enabled: Boolean(kbPath && selected),
  })

  const reindex = useMutation({
    mutationFn: () => reindexAimProject(project.id),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.projects.aimSummary(project.id),
      })
      void queryClient.invalidateQueries({
        queryKey: ['projects', 'detail', project.id, 'aim-units'],
      })
    },
  })

  if (!kbPath) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-xs text-(--color-text-muted)">
          No KB repo mapped on this machine — rejoin the project via the wizard.
        </p>
      </div>
    )
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center justify-between gap-2 border-b border-(--color-border) px-4 py-3">
        <p className="min-w-0 truncate text-sm font-medium text-(--color-text)">
          Knowledge Base
          <span className="ml-2 text-[10px] font-normal text-(--color-text-subtle)">
            {kbPath.split(/[\\/]/).filter(Boolean).pop()} · read-only
          </span>
        </p>
        <button
          type="button"
          onClick={() => reindex.mutate()}
          disabled={reindex.isPending}
          title="Rebuild the local unit index from KB frontmatter (after git pull)"
          className="flex shrink-0 items-center gap-1 rounded px-2 py-1 text-xs text-(--color-text-2) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
        >
          {reindex.isPending ? (
            <Loader2 size={12} className="animate-spin" />
          ) : (
            <RefreshCw size={12} />
          )}
          Reindex
          {reindex.data && (
            <span className="text-[10px] text-(--color-text-subtle)">
              +{reindex.data.created} ~{reindex.data.updated}
            </span>
          )}
        </button>
      </div>

      <div className="flex min-h-0 flex-1">
        {/* File tree (flat, dir-prefixed — the KB layout is shallow by design) */}
        <div className="w-64 shrink-0 overflow-y-auto border-r border-(--color-border) p-2">
          {filesQuery.isLoading ? (
            <p className="px-2 py-1 text-xs text-(--color-text-subtle)">Loading…</p>
          ) : mdFiles.length === 0 ? (
            <p className="px-2 py-1 text-xs text-(--color-text-subtle)">
              KB is empty — run the assess pipeline.
            </p>
          ) : (
            mdFiles.map((path) => (
              <button
                key={path}
                type="button"
                onClick={() => setSelected(path)}
                className={cn(
                  'flex w-full items-center gap-1.5 truncate rounded px-2 py-1 text-left text-xs transition-colors',
                  selected === path
                    ? 'bg-(--bg-key) text-(--color-text)'
                    : 'text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text)',
                )}
                title={path}
              >
                <FileText size={11} className="shrink-0" />
                <span className="truncate">{path}</span>
              </button>
            ))
          )}
        </div>

        {/* Markdown viewer */}
        <div className="min-w-0 flex-1 overflow-y-auto p-4">
          {!selected ? (
            <p className="text-xs text-(--color-text-subtle)">Select a file to read.</p>
          ) : contentQuery.isLoading ? (
            <p className="flex items-center gap-1.5 text-xs text-(--color-text-subtle)">
              <Loader2 size={12} className="animate-spin" /> Loading {selected}…
            </p>
          ) : contentQuery.isError ? (
            <p className="text-xs text-(--color-error)">Failed to read {selected}</p>
          ) : selected.endsWith('.md') ? (
            <div className="prose prose-sm max-w-none text-sm text-(--color-text)">
              <MarkdownBlock content={contentQuery.data ?? ''} />
            </div>
          ) : (
            <pre className="whitespace-pre-wrap font-mono text-xs text-(--color-text-2)">
              {contentQuery.data}
            </pre>
          )}
        </div>
      </div>
    </div>
  )
}
