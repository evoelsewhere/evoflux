import type { SkillBundleFile, SkillBundleFileWrite } from '@/api/types'

export interface SkillBundleDraftFile {
  path: string
  content: string | null
  encoding: 'utf-8' | 'base64' | null
  size: number
  mediaType: string
  editable: boolean
  originalPath?: string
}

export function skillBundleFilesFromApi(files: SkillBundleFile[]): SkillBundleDraftFile[] {
  return files.map((file) => ({
    path: file.path,
    originalPath: file.path,
    content: file.content,
    encoding: file.encoding,
    size: file.size,
    mediaType: file.media_type,
    editable: file.editable,
  }))
}

export function getSkillBundleChanges(
  files: SkillBundleDraftFile[],
  deletedFiles: string[],
): { files: SkillBundleFileWrite[]; deletedFiles: string[] } {
  const removed = new Set(deletedFiles)
  const writes: SkillBundleFileWrite[] = []
  for (const file of files) {
    if (file.content === null || file.encoding === null) continue
    if (file.originalPath && file.originalPath !== file.path) removed.add(file.originalPath)
    if (!file.originalPath || file.originalPath !== file.path || file.editable) {
      writes.push({
        path: file.path,
        content: file.content,
        encoding: file.encoding,
      })
    }
  }
  return { files: writes, deletedFiles: [...removed] }
}
