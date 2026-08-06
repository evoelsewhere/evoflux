import { useCallback, useState } from 'react'
import { Folder, FolderOpen, Loader2 } from 'lucide-react'

import { browseWorkspaces } from '@/api/client'
import { usePlatform } from '@/hooks/use-platform'
import { useToastStore } from '@/stores/useToastStore'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'

interface WorkspaceFolderPickerProps {
  /** Currently selected workspace path, or null when none. */
  workspace: string | null
  onSelect: (path: string) => void
  /** Optional start directory for the web browser dialog. Falls back to
   *  ``workspace`` when unset. */
  initialPath?: string | null
  /** Tauri native-picker dialog title. */
  title?: string
  className?: string
}

/**
 * Folder-picker trigger shared by forms that need a workspace directory path
 * (e.g. the scheduler's optional Work workspace). Uses the native Tauri
 * folder picker on desktop and the backend directory browser elsewhere.
 */
export function WorkspaceFolderPicker({
  workspace,
  onSelect,
  initialPath = null,
  title = 'Choose workspace folder',
  className,
}: WorkspaceFolderPickerProps) {
  const { isTauri, os } = usePlatform()
  const pushToast = useToastStore((state) => state.push)
  const [browserOpen, setBrowserOpen] = useState(false)
  const [browserPath, setBrowserPath] = useState<string | null>(null)
  const [browserParent, setBrowserParent] = useState<string | null>(null)
  const [browserDirs, setBrowserDirs] = useState<Array<{ name: string; path: string }>>([])
  const [browserLoading, setBrowserLoading] = useState(false)
  const [browserError, setBrowserError] = useState<string | null>(null)

  const isTauriMobile = isTauri && (os === 'ios' || os === 'android')

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
    const startPath = workspace ?? initialPath
    if (!isTauri || isTauriMobile) {
      setBrowserOpen(true)
      void loadBrowser(startPath)
      return
    }

    try {
      const { open } = await import('@tauri-apps/plugin-dialog')
      const selected = await open({
        directory: true,
        multiple: false,
        title,
        defaultPath: startPath ?? undefined,
      })
      if (typeof selected === 'string') onSelect(selected)
    } catch (error) {
      pushToast({
        tone: 'error',
        title: 'Could not open folder picker',
        description: error instanceof Error ? error.message : String(error),
      })
    }
  }, [initialPath, isTauri, isTauriMobile, loadBrowser, onSelect, pushToast, title, workspace])

  const confirmBrowser = useCallback(() => {
    if (!browserPath) return
    onSelect(browserPath)
    setBrowserOpen(false)
  }, [browserPath, onSelect])

  return (
    <>
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={() => { void chooseFolder() }}
        className={className}
      >
        <FolderOpen className="size-3.5" aria-hidden="true" />
        Choose folder…
      </Button>

      <Dialog open={browserOpen} onOpenChange={setBrowserOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
            <DialogDescription>
              The scheduled task will run with this folder as its workspace.
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
            <Button type="button" disabled={!browserPath || browserLoading} onClick={confirmBrowser}>
              Use this folder
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
