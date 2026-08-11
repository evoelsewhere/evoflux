import { useCallback, useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import {
  Check,
  ChevronDown,
  Folder,
  FolderOpen,
  Loader2,
  RotateCcw,
} from 'lucide-react'

import { browseWorkspaces, updateSessionWorkspace } from '@/api/client'
import { usePlatform } from '@/hooks/use-platform'
import { queryKeys } from '@/queries/keys'
import { useToastStore } from '@/stores/useToastStore'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'

interface WorkFolderSelectorProps {
  sessionId: string | null
  workspaceRoot: string | null
  loading?: boolean
}

function folderName(path: string): string {
  const trimmed = path.replace(/[\\/]+$/, '')
  return trimmed.split(/[\\/]/).filter(Boolean).at(-1) ?? path
}

/**
 * Work-mode workspace control rendered inside the chat composer.
 *
 * Work chats always have a private session folder. The user can keep that
 * default or point the session at another local folder without opening the
 * Files workbench first.
 */
export function WorkFolderSelector({
  sessionId,
  workspaceRoot,
  loading = false,
}: WorkFolderSelectorProps) {
  const queryClient = useQueryClient()
  const { isTauri, os } = usePlatform()
  const pushToast = useToastStore((state) => state.push)
  const [saving, setSaving] = useState(false)
  const [browserOpen, setBrowserOpen] = useState(false)
  const [browserPath, setBrowserPath] = useState<string | null>(null)
  const [browserParent, setBrowserParent] = useState<string | null>(null)
  const [browserDirs, setBrowserDirs] = useState<Array<{ name: string; path: string }>>([])
  const [browserLoading, setBrowserLoading] = useState(false)
  const [browserError, setBrowserError] = useState<string | null>(null)

  const isTauriMobile = isTauri && (os === 'ios' || os === 'android')
  const isDefault = Boolean(
    sessionId && workspaceRoot && folderName(workspaceRoot) === sessionId,
  )
  const displayName = useMemo(() => {
    if (loading && !workspaceRoot) return 'Loading folder…'
    if (!workspaceRoot || isDefault) return 'Session folder'
    return folderName(workspaceRoot)
  }, [isDefault, loading, workspaceRoot])

  const applyWorkspace = useCallback(async (path: string | null) => {
    if (!sessionId || saving) return
    setSaving(true)
    try {
      const result = await updateSessionWorkspace(sessionId, path)
      queryClient.setQueryData(queryKeys.team.files(sessionId), result)
      queryClient.setQueryData(queryKeys.team.workspaceRoot(sessionId), {
        session_id: sessionId,
        workspace_root: result.workspace_root,
      })
      queryClient.removeQueries({ queryKey: queryKeys.fileRefs.session(sessionId) })
      setBrowserOpen(false)
      pushToast({
        tone: 'success',
        title: path ? `Folder changed to ${folderName(path)}` : 'Using the default session folder',
      })
    } catch (error) {
      pushToast({
        tone: 'error',
        title: 'Could not change folder',
        description: error instanceof Error ? error.message : String(error),
      })
    } finally {
      setSaving(false)
    }
  }, [pushToast, queryClient, saving, sessionId])

  const loadBrowser = useCallback(async (path?: string | null) => {
    setBrowserLoading(true)
    setBrowserError(null)
    try {
      const result = await browseWorkspaces(path)
      setBrowserPath(result.path)
      setBrowserParent(result.parent)
      setBrowserDirs(result.directories)
    } catch (error) {
      setBrowserError(error instanceof Error ? error.message : 'Unable to read this folder')
    } finally {
      setBrowserLoading(false)
    }
  }, [])

  const chooseFolder = useCallback(async () => {
    if (!sessionId || saving) return
    if (!isTauri || isTauriMobile) {
      setBrowserOpen(true)
      void loadBrowser(workspaceRoot)
      return
    }

    try {
      const { open } = await import('@tauri-apps/plugin-dialog')
      const selected = await open({
        directory: true,
        multiple: false,
        title: 'Choose folder for this Work chat',
        defaultPath: workspaceRoot ?? undefined,
      })
      if (typeof selected === 'string') await applyWorkspace(selected)
    } catch (error) {
      pushToast({
        tone: 'error',
        title: 'Could not open folder picker',
        description: error instanceof Error ? error.message : String(error),
      })
    }
  }, [applyWorkspace, isTauri, isTauriMobile, loadBrowser, pushToast, saving, sessionId, workspaceRoot])

  const disabled = !sessionId || loading || saving

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger
          disabled={disabled}
          aria-label={`Work folder: ${displayName}`}
          title={workspaceRoot ?? 'Default session folder'}
          className={cn(
            'composer-workspace-trigger flex h-7 min-w-0 max-w-52 shrink items-center gap-1.5 rounded-[7px] px-2 text-xs outline-none',
            'text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)',
            'focus-visible:ring-2 focus-visible:ring-(--color-accent)/30 disabled:cursor-not-allowed disabled:opacity-55',
          )}
        >
          {saving || (loading && !workspaceRoot) ? (
            <Loader2 className="size-3.5 animate-spin" aria-hidden="true" />
          ) : (
            <Folder className="size-3.5 text-(--color-text-subtle)" aria-hidden="true" />
          )}
          <span className="composer-workspace-name min-w-0 truncate">{displayName}</span>
          {isDefault && (
            <span className="composer-optional-badge shrink-0 rounded bg-(--bg-key) px-1 py-0.5 text-[10px] leading-none text-(--color-text-subtle)">
              Default
            </span>
          )}
          <ChevronDown className="composer-workspace-chevron size-3 shrink-0 text-(--color-text-subtle)" aria-hidden="true" />
        </DropdownMenuTrigger>

        <DropdownMenuContent side="top" align="start" className="w-72 p-1.5">
          <p className="px-2 py-1.5 text-xs font-medium text-(--color-text-muted)">Work folder</p>
          <div className="min-w-0 px-2 pb-2">
            <p className="truncate text-xs font-medium text-(--color-text-2)">{displayName}</p>
            <p className="mt-0.5 truncate font-mono text-[10px] text-(--color-text-subtle)" title={workspaceRoot ?? undefined}>
              {workspaceRoot ?? 'Preparing the session folder…'}
            </p>
          </div>
          <DropdownMenuSeparator />
          <DropdownMenuItem
            disabled={saving || isDefault}
            onClick={() => { void applyWorkspace(null) }}
            className="min-h-9 px-2"
          >
            <RotateCcw aria-hidden="true" />
            <span className="min-w-0 flex-1">
              <span className="block text-xs font-medium">Session folder</span>
              <span className="block text-[10px] text-(--color-text-subtle)">Use the default private folder</span>
            </span>
            {isDefault && <Check className="size-3.5 text-(--color-accent)" aria-hidden="true" />}
          </DropdownMenuItem>
          <DropdownMenuItem onClick={() => { void chooseFolder() }} className="min-h-9 px-2">
            <FolderOpen aria-hidden="true" />
            <span className="min-w-0 flex-1">
              <span className="block text-xs font-medium">Choose another folder…</span>
              <span className="block text-[10px] text-(--color-text-subtle)">Use a local project or folder</span>
            </span>
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <Dialog open={browserOpen} onOpenChange={setBrowserOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Choose folder for this Work chat</DialogTitle>
            <DialogDescription>
              The team will read and write files in the selected folder.
            </DialogDescription>
          </DialogHeader>

          <div className="min-w-0 space-y-2">
            <div className="truncate rounded-md border border-(--color-border) bg-(--bg-page) px-2.5 py-2 font-mono text-xs text-(--color-text-muted)" title={browserPath ?? undefined}>
              {browserPath ?? 'Loading folders…'}
            </div>
            <div className="max-h-72 min-h-40 overflow-y-auto rounded-md border border-(--color-border) p-1">
              {browserParent && (
                <button
                  type="button"
                  onClick={() => { void loadBrowser(browserParent) }}
                  className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm hover:bg-(--bg-key)"
                >
                  <Folder className="size-4 text-(--color-text-subtle)" aria-hidden="true" />
                  <span>..</span>
                </button>
              )}
              {browserDirs.map((directory) => (
                <button
                  key={directory.path}
                  type="button"
                  onClick={() => { void loadBrowser(directory.path) }}
                  className="flex w-full min-w-0 items-center gap-2 rounded px-2 py-1.5 text-left text-sm hover:bg-(--bg-key)"
                >
                  <Folder className="size-4 shrink-0 text-(--color-text-subtle)" aria-hidden="true" />
                  <span className="truncate">{directory.name}</span>
                </button>
              ))}
              {browserLoading && (
                <div className="flex items-center justify-center gap-2 py-8 text-xs text-(--color-text-muted)">
                  <Loader2 className="size-4 animate-spin" aria-hidden="true" />
                  Loading folders…
                </div>
              )}
              {!browserLoading && browserDirs.length === 0 && !browserError && (
                <p className="py-8 text-center text-xs text-(--color-text-subtle)">No subfolders here</p>
              )}
            </div>
            {browserError && <p className="text-xs text-(--color-error)">{browserError}</p>}
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setBrowserOpen(false)}>
              Cancel
            </Button>
            <Button
              type="button"
              disabled={!browserPath || browserLoading || saving}
              onClick={() => { void applyWorkspace(browserPath) }}
            >
              {saving ? <Loader2 className="size-4 animate-spin" aria-hidden="true" /> : null}
              Use this folder
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
