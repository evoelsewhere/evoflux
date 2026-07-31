/**
 * ChangesReviewPanel — Cursor-like post-turn file changes list.
 *
 * Opens on explicit review actions after a ``turn_changes`` SSE event. Lists
 * files mutated during the turn with +/− counts; selecting a file focuses
 * the coding file viewer / source-control review surface when available.
 */
import { useMemo, useState } from 'react'
import { FileDiff, FileMinus2, FilePlus2, FilePenLine, X } from 'lucide-react'

import { ListEnter } from '@/components/motion/ListEnter'
import { SidePanel } from '@/components/shell/SidePanel'
import { useIsMobile } from '@/hooks/use-mobile'
import { STORAGE_KEYS } from '@/lib/storage-keys'
import { cn } from '@/lib/utils'
import { useTeamStore } from '@/stores/useTeamStore'
import { useUIStore } from '@/stores/useUIStore'
import type { TurnChangedFile } from '@/api/types'

function StatusIcon({ status }: { status: TurnChangedFile['status'] }) {
  if (status === 'added') return <FilePlus2 size={14} className="text-(--color-success)" aria-hidden />
  if (status === 'removed') return <FileMinus2 size={14} className="text-(--color-error)" aria-hidden />
  return <FilePenLine size={14} className="text-(--color-warning)" aria-hidden />
}

interface ChangesReviewPanelProps {
  workspace?: string | null
  mode?: 'work' | 'coding' | 'aim'
  onOpenFile?: (path: string) => void
}

export function ChangesReviewPanel({
  workspace,
  mode = 'work',
  onOpenFile,
}: ChangesReviewPanelProps) {
  const turnChanges = useTeamStore((s) => s.turnChanges)
  const turnChangesOpen = useTeamStore((s) => s.turnChangesOpen)
  const dismissTurnChanges = useTeamStore((s) => s.dismissTurnChanges)
  const openWorkbenchTool = useUIStore((s) => s.openWorkbenchTool)
  const openGitChanges = useUIStore((s) => s.openGitChanges)
  const isMobile = useIsMobile()
  const [selected, setSelected] = useState<string | null>(null)

  const open = Boolean(turnChangesOpen && turnChanges && turnChanges.files.length > 0)
  const files = turnChanges?.files ?? []
  const additions = turnChanges?.additions ?? 0
  const deletions = turnChanges?.deletions ?? 0

  const title = useMemo(() => {
    const n = files.length
    return `${n} file${n === 1 ? '' : 's'} changed`
  }, [files.length])

  if (!open || !turnChanges) return null

  return (
    <SidePanel
      onClose={dismissTurnChanges}
      storageKey={STORAGE_KEYS.panels.changes}
      defaultWidth={360}
      minWidth={280}
      maxWidth={560}
      mobileOverlay={isMobile}
      ariaLabel="Turn file changes"
      resizeLabel="Resize changes panel"
    >
      <div className="flex h-full min-h-0 flex-col bg-(--bg-page)">
        <header className="flex shrink-0 items-center gap-2 border-b border-(--color-border) px-3 py-2.5">
          <FileDiff size={15} className="shrink-0 text-(--color-text-muted)" aria-hidden />
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium text-(--color-text)">{title}</p>
            <p className="font-mono text-[11px] tabular-nums text-(--color-text-muted)">
              <span className="text-(--color-success)">+{additions}</span>
              {' '}
              <span className="text-(--color-error)">−{deletions}</span>
            </p>
          </div>
          <button
            type="button"
            onClick={dismissTurnChanges}
            className="focus-ring-control press-control flex h-8 w-8 items-center justify-center rounded-md text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
            aria-label="Close changes"
          >
            <X size={14} />
          </button>
        </header>

        <ul className="min-h-0 flex-1 overflow-y-auto py-1">
          {files.map((file, index) => (
            <ListEnter key={file.path} index={index} basePx={4}>
              <li>
                <button
                  type="button"
                  onClick={() => {
                    setSelected(file.path)
                    onOpenFile?.(file.path)
                    if (mode === 'coding' && workspace) {
                      openGitChanges()
                    } else {
                      openWorkbenchTool('files')
                    }
                  }}
                  className={cn(
                    'flex w-full items-start gap-2 px-3 py-2 text-left transition-colors hover:bg-(--bg-key)',
                    selected === file.path && 'bg-(--bg-key)',
                  )}
                >
                  <StatusIcon status={file.status} />
                  <span className="min-w-0 flex-1 break-all font-mono text-xs text-(--color-text)">
                    {file.path}
                  </span>
                  {(file.additions != null || file.deletions != null) && (
                    <span className="shrink-0 font-mono text-[10px] tabular-nums text-(--color-text-muted)">
                      {file.additions != null && (
                        <span className="text-(--color-success)">+{file.additions}</span>
                      )}
                      {file.deletions != null && (
                        <span className="ml-1 text-(--color-error)">−{file.deletions}</span>
                      )}
                    </span>
                  )}
                </button>
              </li>
            </ListEnter>
          ))}
        </ul>

        {mode === 'coding' && workspace && (
          <footer className="shrink-0 border-t border-(--color-border) px-3 py-2">
            <button
              type="button"
              onClick={openGitChanges}
              className="focus-ring-control w-full rounded-md border border-(--color-border) bg-(--bg-card) px-3 py-2 text-xs font-medium text-(--color-text) transition-colors hover:bg-(--bg-key)"
            >
              Open Git changes
            </button>
          </footer>
        )}
      </div>
    </SidePanel>
  )
}
