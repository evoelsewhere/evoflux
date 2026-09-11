import { Code2, FolderOpen, SquareTerminal } from 'lucide-react'

import type { WorkspaceOpener } from '@/api/tauri-workspace'

/**
 * Icon for one "Open with" catalog entry.
 *
 * The native shell extracts the installed app's real icon; the lucide
 * glyphs are the fallback for platforms where icon extraction is
 * unavailable (Linux) or fails for a single app.
 */
export function OpenerIcon({ opener, size = 6 }: { opener: WorkspaceOpener; size?: 5 | 6 }) {
  const box = size === 5 ? 'size-5' : 'size-6'
  if (opener.icon_data_url) {
    return (
      <span className={`flex ${box} shrink-0 items-center justify-center`} aria-hidden="true">
        <img src={opener.icon_data_url} alt="" className={`${box} object-contain`} draggable={false} />
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
      className={`flex ${box} shrink-0 items-center justify-center rounded-md border border-(--color-border) bg-(--bg-key) text-(--color-text-muted)`}
      aria-hidden="true"
    >
      <Fallback size={13} strokeWidth={1.8} />
    </span>
  )
}
