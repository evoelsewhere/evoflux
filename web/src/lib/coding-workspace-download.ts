import { codingWorkspaceFileUrl } from '@/api/client'
import { saveWorkspaceFileFromUrl } from '@/lib/workspace-file-save'
import type { WorkspaceFileInfo } from '@/api/types'

/** Save a copy of a coding-workspace file outside the repository. */
export async function downloadCodingWorkspaceFile(
  workspace: string,
  file: Pick<WorkspaceFileInfo, 'path' | 'name'>,
): Promise<void> {
  const url = codingWorkspaceFileUrl(workspace, file.path, { download: true })
  await saveWorkspaceFileFromUrl(url, file.name)
}
