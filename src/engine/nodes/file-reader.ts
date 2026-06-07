import { BaseNode, type NodeMetadata, type NodeOutput, type NodeRunContext } from '../node-factory'
import type { VariablePool } from '../variable-pool'
import { convertFile } from '../file-reader/markitdown'
import { parseMarkdownToText, parseMarkdownToStructured } from '../file-reader/markdown-parser'
import { detectFileType, getFileName, getExtension, getLanguage } from '../file-reader/file-detector'
import { NodeExecutionError } from '../errors'

interface FileReaderConfig {
  path?: string
  mode?: 'auto' | 'markdown' | 'plain' | 'structured'
  max_size_mb?: number
}

export class FileReaderNode extends BaseNode<FileReaderConfig> {
  readonly type = 'file-reader'

  getMetadata(): NodeMetadata {
    return {
      type: 'file-reader',
      label: 'File Reader',
      icon: 'file-text',
      category: 'tools',
      description: 'Read file content. Auto-detect format. markitdown for office/pdf/images.',
      inputs: [
        { name: 'path', label: 'File Path', type: 'string', required: true }
      ],
      outputs: [
        { name: 'content', label: 'Content', type: 'string', required: false },
        { name: 'metadata', label: 'Metadata', type: 'object', required: false }
      ],
      defaultConfig: { mode: 'auto', max_size_mb: 10 }
    }
  }

  async run(
    inputs: Record<string, unknown>,
    config: unknown,
    _pool: VariablePool,
    context: NodeRunContext
  ): Promise<NodeOutput> {
    const cfg = config as FileReaderConfig
    const filePath = String(inputs.path || cfg.path || '')
    const mode = cfg.mode || 'auto'
    const maxSizeMb = cfg.max_size_mb || 10

    if (!filePath) {
      throw new NodeExecutionError(context.nodeId, this.type, 'File path is required')
    }

    const fs = await import('fs/promises')

    let stat
    try {
      stat = await fs.stat(filePath)
    } catch {
      throw new NodeExecutionError(context.nodeId, this.type, `File not found: ${filePath}`)
    }

    if (stat.size > maxSizeMb * 1024 * 1024) {
      throw new NodeExecutionError(context.nodeId, this.type, `File too large: ${(stat.size / 1024 / 1024).toFixed(1)}MB (max: ${maxSizeMb}MB)`)
    }

    const info = detectFileType(filePath)
    const fileName = getFileName(filePath)
    const ext = getExtension(filePath)
    const language = getLanguage(filePath)

    let content: string
    let convertedBy: string

    if (mode === 'plain') {
      const result = await readAsPlainText(filePath)
      content = result
      convertedBy = 'plain_text'
    } else if (mode === 'markdown') {
      const result = await convertFile(filePath, { useMarkitdown: true })
      content = result.content
      convertedBy = result.convertedBy
    } else if (mode === 'structured') {
      const raw = await readAsPlainText(filePath)
      const structured = parseMarkdownToStructured(raw)
      content = JSON.stringify(structured, null, 2)
      convertedBy = 'structured'
    } else {
      // auto mode
      if (info.parser === 'skip') {
        content = `[Binary file: ${fileName}]`
        convertedBy = 'binary_skip'
      } else if (info.parser === 'markitdown') {
        const result = await convertFile(filePath)
        content = result.content
        convertedBy = result.convertedBy
      } else if (info.parser === 'markdown') {
        const raw = await readAsPlainText(filePath)
        content = parseMarkdownToText(raw)
        convertedBy = 'markdown_parser'
      } else {
        const result = await readAsPlainText(filePath)
        content = result
        convertedBy = 'plain_text'
      }
    }

    const lineCount = content.split('\n').length

    return {
      content,
      metadata: {
        path: filePath,
        name: fileName,
        extension: ext,
        size: stat.size,
        format: info.category,
        language,
        line_count: lineCount,
        char_count: content.length,
        converted_by: convertedBy
      }
    }
  }
}

async function readAsPlainText(filePath: string): Promise<string> {
  const fs = await import('fs/promises')
  return fs.readFile(filePath, 'utf-8')
}
