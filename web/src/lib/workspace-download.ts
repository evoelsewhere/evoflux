import { workspaceMediaUrl } from '@/api/client'
import { saveWorkspaceFileFromUrl } from '@/lib/workspace-file-save'
import type { WorkspaceFileInfo } from '@/api/types'

/** Save a copy of a session-workspace file outside the workspace. */
export async function downloadWorkspaceFile(
  sessionId: string,
  file: Pick<WorkspaceFileInfo, 'path' | 'name'>,
): Promise<void> {
  const url = workspaceMediaUrl(sessionId, file.path, { download: true })
  await saveWorkspaceFileFromUrl(url, file.name)
}
