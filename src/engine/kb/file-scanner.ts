import { readdir, stat } from 'fs/promises'
import { join, extname, basename, relative, resolve } from 'path'
import { detectFileType, getFileName, type FileCategory } from '../file-reader/file-detector'

export interface ScannedFile {
  path: string
  relativePath: string
  name: string
  extension: string
  size: number
  modifiedAt: number
  isBinary: boolean
  category: FileCategory
  language?: string
  parser: 'plain' | 'markitdown' | 'markdown' | 'csv' | 'skip'
}

export interface ScanOptions {
  maxDepth?: number
  maxFiles?: number
  includeHidden?: boolean
  fileTypes?: string[]
  excludePatterns?: string[]
}

const DEFAULT_EXCLUDE = [
  'node_modules', '.git', 'dist', 'out', '.next', '__pycache__',
  '.venv', 'venv', '.cache', 'coverage', '.idea', '.vscode',
  'build', 'target', 'bin', 'obj', '.gradle', '.npm', '.yarn',
  '.evoflux'
]

export async function scanDirectory(dirPath: string, options?: ScanOptions): Promise<ScannedFile[]> {
  const maxDepth = options?.maxDepth ?? 20
  const maxFiles = options?.maxFiles ?? 10000
  const includeHidden = options?.includeHidden ?? false
  const fileTypes = options?.fileTypes?.map(e => e.toLowerCase())
  const excludePatterns = options?.excludePatterns ?? DEFAULT_EXCLUDE
  const rootPath = resolve(dirPath)
  const results: ScannedFile[] = []

  async function walk(currentPath: string, depth: number): Promise<void> {
    if (depth > maxDepth || results.length >= maxFiles) return

    let entries: string[]
    try {
      entries = await readdir(currentPath)
    } catch {
      return
    }

    for (const entry of entries) {
      if (results.length >= maxFiles) return
      if (!includeHidden && entry.startsWith('.')) continue
      if (excludePatterns.includes(entry)) continue

      const fullPath = join(currentPath, entry)

      let fileStat
      try {
        fileStat = await stat(fullPath)
      } catch {
        continue
      }

      if (fileStat.isDirectory()) {
        await walk(fullPath, depth + 1)
        continue
      }

      if (!fileStat.isFile()) continue

      const ext = extname(entry).replace('.', '').toLowerCase()
      const typeInfo = detectFileType(fullPath)

      if (typeInfo.parser === 'skip') continue
      if (fileTypes && fileTypes.length > 0 && !fileTypes.includes(ext)) continue

      results.push({
        path: fullPath,
        relativePath: relative(rootPath, fullPath),
        name: getFileName(fullPath),
        extension: ext,
        size: fileStat.size,
        modifiedAt: fileStat.mtimeMs,
        isBinary: typeInfo.isBinary,
        category: typeInfo.category,
        language: typeInfo.language,
        parser: typeInfo.parser
      })
    }
  }

  await walk(rootPath, 0)
  return results
}

export async function scanFiles(filePaths: string[]): Promise<ScannedFile[]> {
  const results: ScannedFile[] = []

  for (const filePath of filePaths) {
    try {
      const fileStat = await stat(filePath)
      if (!fileStat.isFile()) continue

      const ext = extname(filePath).replace('.', '').toLowerCase()
      const typeInfo = detectFileType(filePath)

      if (typeInfo.parser === 'skip') continue

      results.push({
        path: filePath,
        relativePath: basename(filePath),
        name: getFileName(filePath),
        extension: ext,
        size: fileStat.size,
        modifiedAt: fileStat.mtimeMs,
        isBinary: typeInfo.isBinary,
        category: typeInfo.category,
        language: typeInfo.language,
        parser: typeInfo.parser
      })
    } catch {
      continue
    }
  }

  return results
}
