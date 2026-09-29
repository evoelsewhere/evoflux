import { useState } from 'react'
import {
  AppWindow,
  ChevronDown,
  FolderOpen,
  Loader2,
  RefreshCw,
} from 'lucide-react'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { tauriOpenWorkspaceWith, type WorkspaceOpener } from '@/api/tauri-workspace'
import { openerDescription } from '@/lib/workspace-openers'
import { OpenerIcon } from './OpenerIcon'
import { useWorkspaceOpenersQuery } from '@/queries/useWorkspaceOpenersQuery'
import { useToastStore } from '@/stores/useToastStore'

interface OpenWithMenuProps {
  /** Absolute workspace root to open; null shows the workspace picker action. */
  workspace: string | null
  /**
   * Every repository the session works in, *workspace* first. With more
   * than one, the menu asks which repository the app should open.
   */
  repositories?: readonly string[]
  onChooseWorkspace?: () => void
}

function repositoryName(path: string): string {
  return path.replace(/[\\/]+$/, '').split(/[\\/]/).pop() || path
}

/**
 * "Open in" topbar dropdown — lists desktop apps that can open the current
 * workspace (detected natively by the Rust opener catalog). Desktop-only;
 * the parent decides whether to render it at all.
 */
export function OpenWithMenu({ workspace, repositories = [], onChooseWorkspace }: OpenWithMenuProps) {
  const pushToast = useToastStore((state) => state.push)
  const openersQuery = useWorkspaceOpenersQuery(workspace !== null)
  const openers = openersQuery.data ?? []
  // The repository chosen in this menu; falls back to the primary when the
  // choice leaves the session's repository list (another session opened).
  const [chosen, setChosen] = useState<string | null>(null)
  const target = chosen && repositories.includes(chosen) ? chosen : workspace
  const choosesRepository = workspace !== null && repositories.length > 1

  const openWith = async (opener: WorkspaceOpener) => {
    if (!target) return
    try {
      await tauriOpenWorkspaceWith(target, opener.id)
    } catch (error) {
      pushToast({
        tone: 'error',
        title: `Could not open ${opener.name}`,
        description: error instanceof Error ? error.message : String(error),
      })
    }
  }

  if (workspace === null) {
    return (
      <button
        type="button"
        onClick={onChooseWorkspace}
        disabled={!onChooseWorkspace}
        className="group flex h-7 items-center gap-1.5 rounded-lg px-2 text-xs font-medium text-(--color-text-muted) outline-none transition-colors hover:bg-(--bg-key) hover:text-(--color-text) disabled:pointer-events-none disabled:opacity-50"
        aria-label="Open a folder as a project"
        title="Open a folder as a project"
      >
        <FolderOpen size={14} className="shrink-0" />
        <span className="workbench-openwith-label">Open folder</span>
      </button>
    )
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        className="group flex h-7 items-center gap-1.5 rounded-lg px-2 text-xs font-medium text-(--color-text-muted) outline-none transition-colors hover:bg-(--bg-key) hover:text-(--color-text) data-[popup-open]:bg-(--bg-key) data-[popup-open]:text-(--color-text)"
        aria-label="Open workspace in a desktop app"
        title="Open workspace in…"
      >
        <AppWindow size={14} className="shrink-0" />
        {/* Drops to the icon alone when the bar is narrow; the name stays in
            the accessible name and the tooltip. */}
        <span className="workbench-openwith-label">Open in</span>
        <ChevronDown
          size={11}
          className="text-(--color-text-subtle) transition-transform group-data-[popup-open]:rotate-180"
        />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-60">
        {choosesRepository && (
          <>
            <div className="px-1.5 py-1 text-xs font-medium text-(--color-text-muted)">
              Repository
            </div>
            <DropdownMenuRadioGroup value={target} onValueChange={(value) => setChosen(value as string)}>
              {repositories.map((repository) => (
                <DropdownMenuRadioItem key={repository} value={repository} title={repository}>
                  <span className="min-w-0 truncate">{repositoryName(repository)}</span>
                </DropdownMenuRadioItem>
              ))}
            </DropdownMenuRadioGroup>
            <DropdownMenuSeparator />
          </>
        )}
        <div className="px-1.5 py-1 text-xs font-medium text-(--color-text-muted)">
          {choosesRepository && target ? `Open ${repositoryName(target)} in` : 'Open workspace in'}
        </div>
        {openersQuery.isLoading && (
          <DropdownMenuItem disabled>
            <Loader2 size={15} className="animate-spin" />
            <span>Detecting apps…</span>
          </DropdownMenuItem>
        )}
        {openersQuery.isError && openers.length === 0 && (
          <DropdownMenuItem onClick={() => void openersQuery.refetch()}>
            <RefreshCw size={14} />
            <span>Retry app detection</span>
          </DropdownMenuItem>
        )}
        {!openersQuery.isLoading && !openersQuery.isError && openers.length === 0 && (
          <DropdownMenuItem disabled>
            <span>No supported apps found</span>
          </DropdownMenuItem>
        )}
        {openers.map((opener) => {
          return (
            <DropdownMenuItem
              key={opener.id}
              onClick={() => void openWith(opener)}
              className="gap-2.5 py-1.5 pl-1"
            >
              <OpenerIcon opener={opener} />
              <span className="min-w-0 flex-1">
                <span className="block truncate">{opener.name}</span>
                <span className="block text-[10px] leading-3 text-(--color-text-subtle)">
                  {openerDescription(opener)}
                </span>
              </span>
            </DropdownMenuItem>
          )
        })}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
