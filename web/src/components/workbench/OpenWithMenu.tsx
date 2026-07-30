import {
  AppWindow,
  ChevronDown,
  Code2,
  FolderOpen,
  Loader2,
  MousePointer2,
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
  /** Absolute workspace root to open; null disables the menu. */
  workspace: string | null
}

function OpenerIcon({ opener }: { opener: WorkspaceOpener }) {
  const tile = 'flex size-5 shrink-0 items-center justify-center rounded-[5px] shadow-sm'

  switch (opener.id) {
    case 'vscode':
      return (
        <span className={`${tile} bg-[#1684D5] text-white`}>
          <Code2 size={12} strokeWidth={2.4} />
        </span>
      )
    case 'vscode-insiders':
      return (
        <span className={`${tile} bg-[#1F9E89] text-white`}>
          <Code2 size={12} strokeWidth={2.4} />
        </span>
      )
    case 'cursor':
      return (
        <span className={`${tile} bg-[#171717] text-white dark:bg-white dark:text-[#171717]`}>
          <MousePointer2 size={11} fill="currentColor" />
        </span>
      )
    case 'zed':
      return (
        <span className={`${tile} bg-[#111827] text-[10px] font-bold text-white`}>
          Z
        </span>
      )
    case 'sublime':
      return (
        <span className={`${tile} bg-[#FF9800] text-[10px] font-bold text-white`}>
          S
        </span>
      )
    case 'finder':
      return (
        <span className={`${tile} bg-[#4A9CF5] text-white`}>
          <FolderOpen size={12} />
        </span>
      )
    case 'explorer':
    case 'file-manager':
      return (
        <span className={`${tile} bg-[#F7C843] text-[#2563A5]`}>
          <FolderOpen size={12} fill="currentColor" fillOpacity={0.22} />
        </span>
      )
    case 'windows-terminal':
    case 'powershell':
    case 'pwsh':
      return (
        <span className={`${tile} bg-[#2563A5] text-white`}>
          <SquareTerminal size={12} />
        </span>
      )
    case 'cmd':
      return (
        <span className={`${tile} bg-[#222831] text-white`}>
          <SquareTerminal size={12} />
        </span>
      )
    case 'terminal':
    case 'iterm':
      return (
        <span className={`${tile} bg-[#3F444B] text-white`}>
          <SquareTerminal size={12} />
        </span>
      )
  }

  const Fallback = opener.kind === 'editor'
    ? Code2
    : opener.kind === 'terminal'
      ? SquareTerminal
      : FolderOpen
  return (
    <span className={`${tile} border border-(--color-border) bg-(--bg-key) text-(--color-text-muted)`}>
      <Fallback size={12} />
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
              className="gap-2.5 py-1.5"
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
