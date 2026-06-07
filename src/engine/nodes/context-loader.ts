import { BaseNode, type NodeMetadata, type NodeOutput, type NodeRunContext } from '../node-factory'
import type { VariablePool } from '../variable-pool'
import { detectFileType, getExtension } from '../file-reader/file-detector'
import { parseMarkdownToText } from '../file-reader/markdown-parser'
import { convertFile } from '../file-reader/markitdown'
import { buildTree, treeToString } from '../file-reader/directory-tree'
import { NodeExecutionError } from '../errors'

interface ContextLoaderConfig {
  root_path?: string
  file_types?: string[]
  exclude_patterns?: string[]
  max_files?: number
  max_total_chars?: number
  include_tree?: boolean
  include_file_content?: boolean
  tree_only?: boolean
  convert_office_docs?: boolean
  convert_pdfs?: boolean
}

interface FileContent {
  path: string
  relativePath: string
  content: string
  language?: string
  size: number
}

const DEFAULT_EXCLUDE = ['node_modules', '.git', 'dist', 'out', '.next', '__pycache__', '.venv', 'venv', '.cache', 'coverage']
const DEFAULT_FILE_TYPES = ['ts', 'tsx', 'js', 'jsx', 'py', 'java', 'go', 'rs', 'c', 'cpp', 'h', 'cs', 'rb', 'php', 'swift', 'kt', 'json', 'yaml', 'yml', 'toml', 'md', 'mdx', 'txt', 'html', 'css', 'scss', 'sql', 'sh', 'dockerfile']

export class ContextLoaderNode extends BaseNode<ContextLoaderConfig> {
  readonly type = 'context-loader'

  getMetadata(): NodeMetadata {
    return {
      type: 'context-loader',
      label: 'Context Loader',
      icon: 'database',
      category: 'tools',
      description: 'Load directory tree as structured context for LLM. Tree + file content.',
      inputs: [
        { name: 'root_path', label: 'Root Path', type: 'string', required: true }
      ],
      outputs: [
        { name: 'context', label: 'Context', type: 'string', required: false },
        { name: 'tree', label: 'Tree', type: 'string', required: false },
        { name: 'files_loaded', label: 'Files Loaded', type: 'number', required: false },
        { name: 'files_skipped', label: 'Files Skipped', type: 'number', required: false }
      ],
      defaultConfig: {
        file_types: DEFAULT_FILE_TYPES,
        exclude_patterns: DEFAULT_EXCLUDE,
        max_files: 50,
        max_total_chars: 100000,
        include_tree: true,
        include_file_content: true,
        tree_only: false,
        convert_office_docs: false,
        convert_pdfs: false
      }
    }
  }

  async run(
    inputs: Record<string, unknown>,
    config: unknown,
    _pool: VariablePool,
    context: NodeRunContext
  ): Promise<NodeOutput> {
    const cfg = config as ContextLoaderConfig
    const rootPath = String(inputs.root_path || cfg.root_path || '')

    if (!rootPath) {
      throw new NodeExecutionError(context.nodeId, this.type, 'Root path is required')
    }

    const fs = await import('fs/promises')
    const path = await import('path')

    const excludePatterns = cfg.exclude_patterns || DEFAULT_EXCLUDE
    const maxFiles = cfg.max_files || 50
    const maxTotalChars = cfg.max_total_chars || 100000
    const includeTree = cfg.include_tree !== false
    const includeContent = cfg.include_file_content !== false
    const treeOnly = cfg.tree_only || false
    const fileTypes = (cfg.file_types || DEFAULT_FILE_TYPES).map(t => t.startsWith('.') ? t.substring(1).toLowerCase() : t.toLowerCase())

    // Build tree
    let treeStr = ''
    if (includeTree || treeOnly) {
      const { readdirSync, statSync } = await import('fs')
      const tree = buildTree(
        rootPath,
        (p) => { try { return readdirSync(p) } catch { return [] } },
        (p) => { try { return statSync(p).isDirectory() } catch { return false } },
        { excludePatterns, maxDepth: 8, maxEntries: 500, showFiles: !treeOnly }
      )
      if (tree) treeStr = treeToString(tree)
    }

    if (treeOnly) {
      return { context: treeStr, tree: treeStr, files_loaded: 0, files_skipped: 0 }
    }

    // Scan files
    const files: FileContent[] = []
    let skipped = 0

    async function scan(dirPath: string, depth: number): Promise<void> {
      if (depth > 8 || files.length >= maxFiles) return

      let entries: string[]
      try {
        entries = await fs.readdir(dirPath)
      } catch {
        return
      }

      for (const entry of entries) {
        if (files.length >= maxFiles) break
        if (entry.startsWith('.')) continue
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
          if (fileTypes.length > 0 && !fileTypes.includes(ext)) {
            skipped++
            continue
          }

          const info = detectFileType(entry)
          if (info.isBinary || info.parser === 'skip') {
            skipped++
            continue
          }

          try {
            let content: string
            if (info.parser === 'markitdown' && (cfg.convert_office_docs || cfg.convert_pdfs)) {
              const result = await convertFile(fullPath)
              content = result.content
            } else if (info.parser === 'markdown') {
              const raw = await fs.readFile(fullPath, 'utf-8')
              content = parseMarkdownToText(raw)
            } else {
              content = await fs.readFile(fullPath, 'utf-8')
            }

            files.push({
              path: fullPath,
              relativePath: path.relative(rootPath, fullPath),
              content,
              language: info.language,
              size: stat.size
            })
          } catch {
            skipped++
          }
        }
      }
    }

    await scan(rootPath, 0)

    // Build context string
    const parts: string[] = []

    if (includeTree && treeStr) {
      parts.push('## Project Structure\n```\n' + treeStr + '\n```\n')
    }

    if (includeContent) {
      let totalChars = parts.join('').length
      for (const file of files) {
        const header = `## File: ${file.relativePath}`
        const block = file.language
          ? `${header}\n\`\`\`${file.language}\n${file.content}\n\`\`\`\n`
          : `${header}\n${file.content}\n`

        if (totalChars + block.length > maxTotalChars) break
        parts.push(block)
        totalChars += block.length
      }
    }

    return {
      context: parts.join('\n'),
      tree: treeStr,
      files_loaded: files.length,
      files_skipped: skipped
    }
  }
}
