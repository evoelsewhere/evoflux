import type { SkillBundleFile, SkillBundleFileWrite } from '@/api/types'

export interface SkillBundleDraftFile {
  path: string
  content: string | null
  encoding: 'utf-8' | 'base64' | null
  size: number
  mediaType: string
  editable: boolean
  originalPath?: string
  originalContent?: string | null
  originalEncoding?: 'utf-8' | 'base64' | null
}

export function skillBundleFilesFromApi(files: SkillBundleFile[]): SkillBundleDraftFile[] {
  return files.map((file) => ({
    path: file.path,
    originalPath: file.path,
    originalContent: file.content,
    originalEncoding: file.encoding,
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
    const changed =
      !file.originalPath ||
      file.originalPath !== file.path ||
      file.content !== file.originalContent ||
      file.encoding !== file.originalEncoding
    if (changed) {
      writes.push({
        path: file.path,
        content: file.content,
        encoding: file.encoding,
      })
    }
  }
  return { files: writes, deletedFiles: [...removed] }
}
