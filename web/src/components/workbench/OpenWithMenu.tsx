import { AppWindow, ChevronDown, Code2, FolderOpen, Loader2, SquareTerminal } from 'lucide-react'
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
  /** Absolute workspace root to open; null disables the menu. */
  workspace: string | null
}

function openerIcon(kind: WorkspaceOpener['kind']) {
  switch (kind) {
    case 'editor':
      return Code2
    case 'terminal':
      return SquareTerminal
    case 'file_manager':
      return FolderOpen
  }
}

/**
 * "Open in" topbar dropdown — lists desktop apps that can open the current
 * workspace (detected natively by the Rust opener catalog). Desktop-only;
 * the parent decides whether to render it at all.
 */
export function OpenWithMenu({ workspace }: OpenWithMenuProps) {
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

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        disabled={workspace === null}
        className="group flex h-7 items-center gap-1.5 rounded-lg px-2 text-xs font-medium text-(--color-text-muted) outline-none transition-colors hover:bg-(--bg-key) hover:text-(--color-text) disabled:pointer-events-none disabled:opacity-50 data-[popup-open]:bg-(--bg-key) data-[popup-open]:text-(--color-text)"
        aria-label="Open workspace in a desktop app"
        title={workspace === null ? 'No workspace selected' : 'Open workspace in…'}
      >
        <AppWindow size={14} />
        <span>Open in</span>
        <ChevronDown
          size={11}
          className="text-(--color-text-subtle) transition-transform group-data-[popup-open]:rotate-180"
        />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-52">
        <div className="px-1.5 py-1 text-xs font-medium text-(--color-text-muted)">
          Open workspace in
        </div>
        {openersQuery.isLoading && (
          <DropdownMenuItem disabled>
            <Loader2 size={15} className="animate-spin" />
            <span>Detecting apps…</span>
          </DropdownMenuItem>
        )}
        {!openersQuery.isLoading && openers.length === 0 && (
          <DropdownMenuItem disabled>
            <span>No supported apps found</span>
          </DropdownMenuItem>
        )}
        {openers.map((opener) => {
          const Icon = openerIcon(opener.kind)
          return (
            <DropdownMenuItem key={opener.id} onClick={() => void openWith(opener)}>
              <Icon size={15} />
              <span className="truncate">{opener.name}</span>
            </DropdownMenuItem>
          )
        })}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
