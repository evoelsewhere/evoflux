/**
 * Context-menu capabilities for Code mode's file trees.
 *
 * A plain factory rather than a hook: ``MultiRepoFileTree`` builds one bundle
 * per repository while mapping over a project's workspaces, which rules out
 * calling hooks. Callers pass the query client they already hold.
 */
import type { QueryClient } from '@tanstack/react-query'

import {
  codingWorkspaceFileUrl,
  copyCodingWorkspaceEntry,
  createCodingWorkspaceEntry,
  deleteCodingWorkspaceEntry,
  moveCodingWorkspaceEntry,
} from '@/api/client'
import {
  isTauriAvailable,
  tauriOpenWorkspaceFile,
  tauriRevealWorkspacePath,
} from '@/api/tauri-workspace'
import { downloadCodingWorkspaceFile } from '@/lib/coding-workspace-download'
import { openExternalUrl } from '@/lib/open-external'
import { queryKeys } from '@/queries/keys'
import type { FileExplorerEntry, FileExplorerMenuActions } from '@/components/FileExplorerContextMenu'

/** Path of ``name`` inside ``parentDir`` ('' = workspace root). */
function childPath(parentDir: string, name: string): string {
  return parentDir ? `${parentDir}/${name}` : name
}

/** Path of ``name`` in the same directory as ``path``. */
function siblingPath(path: string, name: string): string {
  const index = path.lastIndexOf('/')
  return index < 0 ? name : `${path.slice(0, index + 1)}${name}`
}

export async function readCodingWorkspaceText(workspace: string, path: string): Promise<string> {
  const response = await fetch(codingWorkspaceFileUrl(workspace, path))
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  return response.text()
}

export function codingExplorerMenuActions({
  workspace,
  queryClient,
  onPreview,
  onChanged,
}: {
  /** Absolute path of the repository the entries belong to. */
  workspace: string
  queryClient: QueryClient
  /** Show the entry in the panel's viewer. */
  onPreview?: (entry: FileExplorerEntry) => void
  /** Called after a mutation so native trees can re-read from disk. */
  onChanged?: () => void
}): FileExplorerMenuActions {
  const invalidate = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.coding.files(workspace) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.coding.diff(workspace) }),
    ])
    onChanged?.()
  }

  return {
    root: workspace,
    onPreview,
    onOpenExternally: async (entry) => {
      if (isTauriAvailable()) {
        await tauriOpenWorkspaceFile(workspace, entry.path)
        return
      }
      await openExternalUrl(codingWorkspaceFileUrl(workspace, entry.path))
    },
    onReveal: isTauriAvailable()
      ? (entry) => tauriRevealWorkspacePath(workspace, entry.path)
      : undefined,
    readText: (entry) => readCodingWorkspaceText(workspace, entry.path),
    onDownload: (entry) => downloadCodingWorkspaceFile(workspace, entry),
    onCreate: async (parentDir, name, kind) => {
      await createCodingWorkspaceEntry(workspace, childPath(parentDir, name), kind)
      await invalidate()
    },
    onRename: async (entry, name) => {
      await moveCodingWorkspaceEntry(workspace, entry.path, siblingPath(entry.path, name))
      await invalidate()
    },
    onDuplicate: async (entry, name) => {
      await copyCodingWorkspaceEntry(workspace, entry.path, siblingPath(entry.path, name))
      await invalidate()
    },
    onDelete: async (entry) => {
      await deleteCodingWorkspaceEntry(workspace, entry.path, { recursive: entry.isDirectory })
      await invalidate()
    },
  }
}
