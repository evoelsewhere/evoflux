import { BaseNode, type NodeMetadata, type NodeOutput, type NodeRunContext } from '../node-factory'
import type { VariablePool } from '../variable-pool'
import { detectFileType, getExtension } from '../file-reader/file-detector'
import { NodeExecutionError } from '../errors'

interface FileExplorerConfig {
  root_path?: string
  file_types?: string[]
  exclude_patterns?: string[]
  max_depth?: number
  max_files?: number
  include_hidden?: boolean
}

export interface FileInfo {
  path: string
  relativePath: string
  name: string
  extension: string
  size: number
  modifiedAt: number
  isBinary: boolean
  category: string
  language?: string
}

const DEFAULT_EXCLUDE = ['node_modules', '.git', 'dist', 'out', '.next', '__pycache__', '.venv', 'venv', '.cache', 'coverage']

export class FileExplorerNode extends BaseNode<FileExplorerConfig> {
  readonly type = 'file-explorer'

  getMetadata(): NodeMetadata {
    return {
      type: 'file-explorer',
      label: 'File Explorer',
      icon: 'folder-open',
      category: 'tools',
      description: 'Browse & select local files/folders. Filter by extension. Exclude patterns.',
      inputs: [
        { name: 'root_path', label: 'Root Path', type: 'string', required: true }
      ],
      outputs: [
        { name: 'files', label: 'Files', type: 'array', required: false },
        { name: 'file_count', label: 'File Count', type: 'number', required: false },
        { name: 'root_path', label: 'Root Path', type: 'string', required: false }
      ],
      defaultConfig: {
        file_types: [],
        exclude_patterns: DEFAULT_EXCLUDE,
        max_depth: 10,
        max_files: 1000,
        include_hidden: false
      }
    }
  }

  async run(
    inputs: Record<string, unknown>,
    config: unknown,
    _pool: VariablePool,
    context: NodeRunContext
  ): Promise<NodeOutput> {
    const cfg = config as FileExplorerConfig
    const rootPath = String(inputs.root_path || cfg.root_path || '')

    if (!rootPath) {
      throw new NodeExecutionError(context.nodeId, this.type, 'Root path is required')
    }

    const fs = await import('fs/promises')
    const path = await import('path')

    const excludePatterns = cfg.exclude_patterns || DEFAULT_EXCLUDE
    const maxDepth = cfg.max_depth || 10
    const maxFiles = cfg.max_files || 1000
    const includeHidden = cfg.include_hidden || false
    const fileTypes = (cfg.file_types || []).map(t => t.startsWith('.') ? t.substring(1).toLowerCase() : t.toLowerCase())

    const files: FileInfo[] = []

    async function scan(dirPath: string, depth: number): Promise<void> {
      if (depth > maxDepth || files.length >= maxFiles) return

      let entries: string[]
      try {
        entries = await fs.readdir(dirPath)
      } catch {
        return
      }

      for (const entry of entries) {
        if (files.length >= maxFiles) break
        if (!includeHidden && entry.startsWith('.')) continue
        if (excludePatterns.includes(entry)) continue

        const fullPath = path.join(dirPath, entry)
        let stat
        try {
          stat = await fs.stat(fullPath)
        } catch {
          continue
        }

        if (stat.isDirectory()) {
          await scan(fullPath, depth + 1)
        } else {
          const ext = getExtension(entry)
          if (fileTypes.length > 0 && !fileTypes.includes(ext)) continue

          const info = detectFileType(entry)
          files.push({
            path: fullPath,
            relativePath: path.relative(rootPath, fullPath),
            name: entry,
            extension: ext,
            size: stat.size,
            modifiedAt: stat.mtimeMs,
            isBinary: info.isBinary,
            category: info.category,
            language: info.language
          })
        }
      }
    }

    await scan(rootPath, 0)

    return {
      files,
      file_count: files.length,
      root_path: rootPath
    }
  }
}
