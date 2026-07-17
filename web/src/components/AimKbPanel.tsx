/**
 * AimKbPanel — the Knowledge Base feature: a READ-ONLY window onto the
 * project's document repo (aim_<name>_document), tree on the left,
 * preview on the right (aim-mode-shell-ux-spec.md v2.2 §3.5, reuse per §7:
 * the coding workspace's real folder tree, not a flat list).
 *
 * The one action here is Reindex: rebuild the local aim_units index from
 * KB frontmatter after a manual `git pull` (the repo is the system of
 * record; the table is a per-machine projection). Everything that WRITES
 * knowledge lives in Pipelines — one job, one place.
 *
 * Preview renders by kind: markdown gets its YAML frontmatter lifted into
 * a key/value strip (unit docs carry phase/wave/assignee there) with the
 * body as rich markdown; yaml/json/config files get a code block; images
 * render inline; anything else falls back to plain text.
 */

import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FileText, Loader2, RefreshCw } from 'lucide-react'
import {
  codingWorkspaceFileUrl,
  listCodingWorkspaceFiles,
  reindexAimProject,
} from '@/api/client'
import { takeAimKbOpenPath } from '@/lib/aimHandoff'
import { queryKeys } from '@/queries/keys'
import { MarkdownBlock, CodeBlock } from '@/utils/markdown'
import { buildTree } from '@/utils/workspaceFileTree'
import { TreeNodeView } from '@/components/CodingWorkspacePanel'
import { formatBytes } from '@/utils/format'
import type { CodingProject, ProjectWorkspaceItem, WorkspaceFileInfo } from '@/api/types'

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

const EMPTY_CHANGED_PATHS = new Set<string>()

const IMAGE_EXTENSIONS = new Set(['png', 'jpg', 'jpeg', 'gif', 'svg', 'webp'])
const CODE_EXTENSIONS = new Set([
  'yaml',
  'yml',
  'json',
  'toml',
  'csv',
  'sh',
  'sql',
  'py',
  'js',
  'ts',
  'xml',
])

function extensionOf(path: string): string {
  const name = path.split('/').pop() ?? path
  const dot = name.lastIndexOf('.')
  return dot >= 0 ? name.slice(dot + 1).toLowerCase() : ''
}

/** Lift a leading YAML frontmatter block into display pairs. Handles the
 * flat `key: value` + `- item` list shape the AIM KB uses — anything more
 * exotic stays readable because unmatched lines append to the last key. */
export function splitFrontmatter(source: string): {
  meta: Array<[string, string]>
  body: string
} {
  const match = /^---\r?\n([\s\S]*?)\r?\n---\r?\n?/.exec(source)
  if (!match) return { meta: [], body: source }
  const meta: Array<[string, string]> = []
  for (const rawLine of match[1].split(/\r?\n/)) {
    const line = rawLine.trim()
    if (!line) continue
    const kv = /^([A-Za-z0-9_.-]+):\s*(.*)$/.exec(line)
    if (kv) {
      meta.push([kv[1], kv[2]])
    } else if (meta.length > 0) {
      const item = line.replace(/^-\s*/, '')
      const last = meta[meta.length - 1]
      last[1] = last[1] ? `${last[1]}, ${item}` : item
    }
  }
  return { meta, body: source.slice(match[0].length) }
}

export function AimKbPanel({ project }: { project: CodingProject }) {
  const queryClient = useQueryClient()
  const kbPath = resolveAimRolePath(project, 'kb')
  const [selected, setSelected] = useState<WorkspaceFileInfo | null>(null)
  // A unit's "KB doc" quick action lands here with a doc to open — held
  // until the file listing arrives, then consumed.
  const [pendingOpenPath, setPendingOpenPath] = useState<string | null>(
    () => takeAimKbOpenPath(),
  )

  const filesQuery = useQuery({
    queryKey: ['aim-kb-files', kbPath ?? ''],
    queryFn: () => listCodingWorkspaceFiles(kbPath as string),
    enabled: Boolean(kbPath),
    staleTime: 15_000,
  })

  useEffect(() => {
    if (!pendingOpenPath || !filesQuery.data) return
    const file = filesQuery.data.files.find((f) => f.path === pendingOpenPath)
    if (file) setSelected(file)
    setPendingOpenPath(null)
  }, [pendingOpenPath, filesQuery.data])

  const tree = useMemo(
    () => buildTree(filesQuery.data?.files ?? []),
    [filesQuery.data],
  )
  const fileCount = filesQuery.data?.files.length ?? 0

  const extension = selected ? extensionOf(selected.path) : ''
  const isImage = IMAGE_EXTENSIONS.has(extension)

  const contentQuery = useQuery({
    queryKey: ['aim-kb-file', kbPath ?? '', selected?.path ?? ''],
    queryFn: async () => {
      const res = await fetch(codingWorkspaceFileUrl(kbPath as string, selected!.path))
      if (!res.ok) throw new Error(`Failed to read ${selected!.path}`)
      return res.text()
    },
    enabled: Boolean(kbPath && selected) && !isImage,
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
            {kbPath.split(/[\\/]/).filter(Boolean).pop()} · {fileCount} files · read-only
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
        {/* Folder tree — same component the coding workspace uses (§7). */}
        <div className="w-72 shrink-0 overflow-y-auto border-r border-(--color-border) p-2">
          {filesQuery.isLoading ? (
            <p className="px-2 py-1 text-xs text-(--color-text-subtle)">Loading…</p>
          ) : fileCount === 0 ? (
            <p className="px-2 py-1 text-xs text-(--color-text-subtle)">
              KB is empty — run the assess pipeline.
            </p>
          ) : (
            <TreeNodeView
              node={tree}
              depth={0}
              selectedPath={selected?.path ?? null}
              onFileSelect={setSelected}
              changedPaths={EMPTY_CHANGED_PATHS}
            />
          )}
        </div>

        {/* Preview */}
        <div className="min-w-0 flex-1 overflow-y-auto">
          {!selected ? (
            <p className="p-4 text-xs text-(--color-text-subtle)">Select a file to read.</p>
          ) : (
            <div className="flex h-full min-h-0 flex-col">
              <div className="flex shrink-0 items-center gap-2 border-b border-(--color-border) px-4 py-2">
                <FileText size={12} className="shrink-0 text-(--color-text-subtle)" />
                <span className="min-w-0 truncate font-mono text-xs text-(--color-text-2)">
                  {selected.path}
                </span>
                <span className="ml-auto shrink-0 text-[10px] text-(--color-text-subtle)">
                  {formatBytes(selected.size)}
                </span>
              </div>
              <div className="min-h-0 flex-1 overflow-y-auto p-4">
                <FilePreview
                  kbPath={kbPath}
                  file={selected}
                  extension={extension}
                  isImage={isImage}
                  content={contentQuery.data}
                  loading={contentQuery.isLoading}
                  error={contentQuery.isError}
                />
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function FilePreview({
  kbPath,
  file,
  extension,
  isImage,
  content,
  loading,
  error,
}: {
  kbPath: string
  file: WorkspaceFileInfo
  extension: string
  isImage: boolean
  content: string | undefined
  loading: boolean
  error: boolean
}) {
  if (isImage) {
    return (
      <img
        src={codingWorkspaceFileUrl(kbPath, file.path)}
        alt={file.path}
        className="max-h-full max-w-full rounded border border-(--color-border)"
      />
    )
  }
  if (loading) {
    return (
      <p className="flex items-center gap-1.5 text-xs text-(--color-text-subtle)">
        <Loader2 size={12} className="animate-spin" /> Loading {file.path}…
      </p>
    )
  }
  if (error) {
    return <p className="text-xs text-(--color-error)">Failed to read {file.path}</p>
  }
  const text = content ?? ''

  if (extension === 'md') {
    const { meta, body } = splitFrontmatter(text)
    return (
      <div>
        {meta.length > 0 && (
          <div className="mb-4 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 rounded-md bg-(--bg-key) px-3 py-2">
            {meta.map(([key, value]) => (
              <div key={key} className="contents">
                <span className="font-mono text-[10px] uppercase tracking-wider text-(--color-text-subtle)">
                  {key}
                </span>
                <span className="min-w-0 break-words text-xs text-(--color-text-2)">
                  {value || '—'}
                </span>
              </div>
            ))}
          </div>
        )}
        <div className="prose prose-sm max-w-none text-sm text-(--color-text)">
          <MarkdownBlock content={body} />
        </div>
      </div>
    )
  }

  if (CODE_EXTENSIONS.has(extension)) {
    return (
      <CodeBlock language={extension} rawText={text}>
        {text}
      </CodeBlock>
    )
  }

  return (
    <pre className="whitespace-pre-wrap font-mono text-xs text-(--color-text-2)">{text}</pre>
  )
}
