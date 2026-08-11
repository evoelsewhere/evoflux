export type CodingFileViewerHost = 'files' | 'standalone' | null

export function shouldClearFilesEditor(
  host: CodingFileViewerHost,
  workbenchOpen: boolean,
  hasFilesTab: boolean,
): boolean {
  return host === 'files' && (!workbenchOpen || !hasFilesTab)
}

export function shouldShowStandaloneEditor(
  host: CodingFileViewerHost,
  workbenchOpen: boolean,
  activeWorkbenchTool: string | null,
): boolean {
  return host === 'standalone' && !(workbenchOpen && activeWorkbenchTool === 'files')
}
