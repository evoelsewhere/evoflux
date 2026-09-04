import type { WorkspaceOpener } from '@/api/tauri-workspace'

/** Human label for an opener's category, shown under its name. */
export function openerDescription(opener: WorkspaceOpener): string {
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
 * Label for writing a copy of a workspace file somewhere else.
 *
 * On desktop the file is already on disk and the action opens the OS save
 * dialog, so "download" would describe the wrong thing; only the browser
 * build actually downloads anything.
 */
export function saveCopyLabel(isTauri: boolean): string {
  return isTauri ? 'Save a copy…' : 'Download'
}

/** Label for the "reveal in the OS file manager" action on this platform. */
export function revealLabel(os: string | null | undefined): string {
  if (os === 'macos') return 'Reveal in Finder'
  if (os === 'windows') return 'Show in File Explorer'
  return 'Show in folder'
}

/**
 * Join a workspace root with a POSIX-relative path for display and clipboard.
 *
 * Windows roots keep backslashes so the result can be pasted into Explorer, a
 * terminal, or an editor's "open file" box unchanged.
 */
export function absoluteWorkspacePath(root: string, relativePath: string): string {
  const trimmedRoot = root.replace(/[\\/]+$/, '')
  const isWindowsRoot = trimmedRoot.includes('\\') && !trimmedRoot.includes('/')
  const separator = isWindowsRoot ? '\\' : '/'
  const relative = isWindowsRoot ? relativePath.replace(/\//g, '\\') : relativePath
  return relative ? `${trimmedRoot}${separator}${relative}` : trimmedRoot
}
