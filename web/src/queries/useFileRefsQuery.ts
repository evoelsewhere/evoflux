/**
 * Workspace file/folder list for the InputBar's @-mention picker.
 *
 * Hits one of two existing endpoints depending on mode:
 *   - coding:  GET /api/team/workspace/files/list?workspace=...
 *   - normal:  GET /api/team/{session_id}/files
 *
 * Both return a flat list of files (max 500, gitignore-aware). Folder entries
 * are derived client-side from the path prefixes so the user can also reference
 * directories with `@some/dir/`.
 *
 * The query is gated on input-bar activation (``enabled``) so we don't walk the
 * workspace on every chat-view mount — the picker only fetches when the user
 * actually opens the composer or types ``@``.
 */
import { useCallback, useMemo } from 'react'
import { useQueries, useQuery } from '@tanstack/react-query'
import { listCodingWorkspaceFiles, listWorkspaceFiles } from '@/api/client'
import type { WorkspaceFileInfo } from '@/api/types'
import type { FileRef } from '@/components/InputBar.mentions'
import { agentPath } from '@/utils/repository-paths'
import { workspaceLabel } from '@/utils/workspace'
import { queryKeys } from './keys'

// Both endpoints share the same row shape but differ on the envelope. We only
// care about ``files`` here, so normalise to that.
interface FileListing { files: WorkspaceFileInfo[] }

interface UseFileRefsQueryArgs {
  mode: 'work' | 'coding'
  sessionId?: string | null
  workspace?: string | null
  /** Coding: every repository of the session's project, primary included. */
  repositories?: readonly string[]
  /** Only fetch when the input bar wants the list (focus / @ keystroke). */
  enabled?: boolean
}

/** Derive folder entries from a flat file list by walking each path's prefixes. */
function deriveDirs(files: readonly { path: string }[]): string[] {
  const dirs = new Set<string>()
  for (const f of files) {
    const parts = f.path.split('/')
    // Last segment is the file basename — skip it. Every earlier segment
    // forms a directory path when joined cumulatively.
    for (let i = 1; i < parts.length; i++) {
      dirs.add(parts.slice(0, i).join('/'))
    }
  }
  return [...dirs].sort()
}

function basename(p: string): string {
  const i = p.lastIndexOf('/')
  return i === -1 ? p : p.slice(i + 1)
}

export function useFileRefsQuery({
  mode,
  sessionId,
  workspace,
  repositories,
  enabled = true,
}: UseFileRefsQueryArgs) {
  const isCoding = mode === 'coding'
  const hasWorkspace = isCoding ? Boolean(workspace) : Boolean(sessionId)

  const query = useQuery<FileListing>({
    queryKey: isCoding
      ? queryKeys.fileRefs.coding(workspace ?? '')
      : queryKeys.fileRefs.session(sessionId ?? ''),
    queryFn: async (): Promise<FileListing> => {
      const res = isCoding
        ? await listCodingWorkspaceFiles(workspace as string)
        : await listWorkspaceFiles(sessionId as string)
      return { files: res.files }
    },
    enabled: enabled && hasWorkspace,
    // Files change frequently while an agent writes them. 30s is a comfortable
    // window for casual @-mention use; users can re-fetch by closing/reopening
    // the menu (refetchOnMount runs when the query is re-enabled).
    staleTime: 30_000,
  })

  // The project's other repositories. Their files are referenced by absolute
  // path, which the agent can open from its primary repository.
  const siblingsKey = isCoding && workspace
    ? (repositories ?? []).filter((repository) => repository !== workspace).join('\0')
    : ''
  const siblings = useMemo(() => (siblingsKey ? siblingsKey.split('\0') : []), [siblingsKey])
  // Stable, so TanStack Query only re-combines when a listing changes — the
  // chat view re-renders on every streamed token.
  const combine = useCallback(
    (results: Array<{ data?: FileListing }>) =>
      results.map((result, index) => ({
        root: siblings[index] ?? '',
        files: result.data?.files ?? [],
      })),
    [siblings],
  )
  const siblingListings = useQueries({
    queries: siblings.map((repository) => ({
      queryKey: queryKeys.fileRefs.coding(repository),
      queryFn: async (): Promise<FileListing> => {
        const res = await listCodingWorkspaceFiles(repository)
        return { files: res.files }
      },
      enabled,
      staleTime: 30_000,
    })),
    combine,
  })

  // Build the combined files+dirs list once per query response. Files appear
  // first so the most common case (referencing a file) is at the top.
  const refs = useMemo<FileRef[]>(() => {
    const listings: Array<{ root: string | null; files: readonly WorkspaceFileInfo[] }> = [
      { root: null, files: query.data?.files ?? [] },
      ...siblingListings,
    ]
    // Another repository's entries insert their absolute path but show (and
    // match) as `<repository>/<path>`.
    const located = (root: string | null, path: string): Pick<FileRef, 'path' | 'label'> =>
      root && workspace
        ? { path: agentPath(workspace, root, path), label: `${workspaceLabel(root)}/${path}` }
        : { path }
    const fileRefs: FileRef[] = listings.flatMap(({ root, files }) =>
      files.map((f) => ({
        ...located(root, f.path),
        name: f.name,
        type: 'file' as const,
      })),
    )
    const rootRefs: FileRef[] = siblingListings.map(({ root }) => ({
      path: root.replace(/\\/g, '/'),
      label: workspaceLabel(root),
      name: workspaceLabel(root),
      type: 'directory' as const,
    }))
    const dirRefs: FileRef[] = listings.flatMap(({ root, files }) =>
      deriveDirs(files).map((p) => ({
        ...located(root, p),
        name: basename(p),
        type: 'directory' as const,
      })),
    )
    return [...fileRefs, ...rootRefs, ...dirRefs]
  }, [query.data, siblingListings, workspace])

  return { refs, isLoading: query.isLoading, error: query.error }
}
