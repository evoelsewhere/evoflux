import {
  AppWindow,
  ChevronDown,
  Code2,
  FolderOpen,
  Loader2,
  RefreshCw,
  SquareTerminal,
} from 'lucide-react'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { tauriOpenWorkspaceWith, type WorkspaceOpener } from '@/api/tauri-workspace'
import { useWorkspaceOpenersQuery } from '@/queries/useWorkspaceOpenersQuery'
import { useToastStore } from '@/stores/useToastStore'

interface OpenWithMenuProps {
  /** Absolute workspace root to open; null shows the workspace picker action. */
  workspace: string | null
  onChooseWorkspace?: () => void
}

function OpenerIcon({ opener }: { opener: WorkspaceOpener }) {
  if (opener.icon_data_url) {
    return (
      <span className="flex size-6 shrink-0 items-center justify-center" aria-hidden="true">
        <img
          src={opener.icon_data_url}
          alt=""
          className="size-6 object-contain"
          draggable={false}
        />
      </span>
    )
  }

  const Fallback = opener.kind === 'editor'
    ? Code2
    : opener.kind === 'terminal'
      ? SquareTerminal
      : FolderOpen
  return (
    <span
      className="flex size-6 shrink-0 items-center justify-center rounded-md border border-(--color-border) bg-(--bg-key) text-(--color-text-muted)"
      aria-hidden="true"
    >
      <Fallback size={13} strokeWidth={1.8} />
    </span>
  )
}

function openerDescription(opener: WorkspaceOpener): string {
  switch (opener.kind) {
    case 'editor':
      return 'Editor'
    case 'terminal':
      return 'Terminal'
    case 'file_manager':
      return 'File manager'
  }
}

/**
 * "Open in" topbar dropdown — lists desktop apps that can open the current
 * workspace (detected natively by the Rust opener catalog). Desktop-only;
 * the parent decides whether to render it at all.
 */
export function OpenWithMenu({ workspace, onChooseWorkspace }: OpenWithMenuProps) {
  const pushToast = useToastStore((state) => state.push)
  const openersQuery = useWorkspaceOpenersQuery(workspace !== null)
  const openers = openersQuery.data ?? []

  const openWith = async (opener: WorkspaceOpener) => {
    if (!workspace) return
    try {
      await tauriOpenWorkspaceWith(workspace, opener.id)
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
        aria-label="Choose a workspace folder"
        title="Choose a workspace folder"
      >
        <FolderOpen size={14} />
        <span>Open folder</span>
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
        <AppWindow size={14} />
        <span>Open in</span>
        <ChevronDown
          size={11}
          className="text-(--color-text-subtle) transition-transform group-data-[popup-open]:rotate-180"
        />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-60">
        <div className="px-1.5 py-1 text-xs font-medium text-(--color-text-muted)">
          Open workspace in
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
