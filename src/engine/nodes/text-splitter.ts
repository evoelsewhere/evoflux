import { BaseNode, type NodeMetadata, type NodeOutput, type NodeRunContext } from '../node-factory'
import type { VariablePool } from '../variable-pool'
import { NodeExecutionError } from '../errors'

interface TextSplitterConfig {
  text?: string
  strategy?: 'character' | 'sentence' | 'paragraph' | 'recursive'
  chunk_size?: number
  chunk_overlap?: number
  separator?: string
}

export class TextSplitterNode extends BaseNode<TextSplitterConfig> {
  readonly type = 'text-splitter'

  getMetadata(): NodeMetadata {
    return {
      type: 'text-splitter',
      label: 'Text Splitter',
      icon: 'scissor',
      category: 'tools',
      description: 'Split text into chunks for RAG pipelines. Supports character, sentence, paragraph, and recursive strategies.',
      inputs: [
        { name: 'text', label: 'Text', type: 'string', required: true }
      ],
      outputs: [
        { name: 'chunks', label: 'Chunks', type: 'array', required: false },
        { name: 'count', label: 'Chunk Count', type: 'number', required: false },
        { name: 'first', label: 'First Chunk', type: 'string', required: false }
      ],
      defaultConfig: { strategy: 'recursive', chunk_size: 1000, chunk_overlap: 200 }
    }
  }

  async run(
    inputs: Record<string, unknown>,
    config: unknown,
    _pool: VariablePool,
    context: NodeRunContext
  ): Promise<NodeOutput> {
    const cfg = config as TextSplitterConfig
    const text = String(inputs.text || cfg.text || '')
    const strategy = cfg.strategy || 'recursive'
    const chunkSize = cfg.chunk_size || 1000
    const chunkOverlap = cfg.chunk_overlap || 200
    const separator = cfg.separator || '\n'

    if (!text) {
      throw new NodeExecutionError(context.nodeId, this.type, 'Text input is required')
    }

    let chunks: string[]

    switch (strategy) {
      case 'character':
        chunks = splitByCharacter(text, chunkSize, chunkOverlap)
        break
      case 'sentence':
        chunks = splitBySentence(text, chunkSize, chunkOverlap)
        break
      case 'paragraph':
        chunks = splitByParagraph(text, chunkSize, separator)
        break
      case 'recursive':
        chunks = splitRecursive(text, chunkSize, chunkOverlap)
        break
      default:
        chunks = splitRecursive(text, chunkSize, chunkOverlap)
    }

    return {
      chunks,
      count: chunks.length,
      first: chunks[0] || '',
      total_chars: text.length
    }
  }
}

function splitByCharacter(text: string, chunkSize: number, overlap: number): string[] {
  const chunks: string[] = []
  const step = Math.max(1, chunkSize - overlap)
  for (let i = 0; i < text.length; i += step) {
    chunks.push(text.substring(i, i + chunkSize))
  }
  return chunks
}

function splitBySentence(text: string, chunkSize: number, overlap: number): string[] {
  const sentences = text.match(/[^.!?]+[.!?]+[\s]*/g) || [text]
  return mergeChunks(sentences, chunkSize, overlap)
}

function splitByParagraph(text: string, chunkSize: number, separator: string): string[] {
  const paragraphs = text.split(separator).filter(p => p.trim())
  const chunks: string[] = []
  let current = ''

  for (const para of paragraphs) {
    if (current.length + para.length > chunkSize && current.length > 0) {
      chunks.push(current.trim())
      current = ''
    }
    current += (current ? separator : '') + para
  }
  if (current.trim()) chunks.push(current.trim())
  return chunks
}

function splitRecursive(text: string, chunkSize: number, overlap: number): string[] {
  const separators = ['\n\n', '\n', '. ', ' ', '']
  return recursiveSplit(text, separators, chunkSize, overlap)
}

function recursiveSplit(text: string, separators: string[], chunkSize: number, overlap: number): string[] {
  if (text.length <= chunkSize) return [text]

  const sep = separators[0] || ''
  const remaining = separators.slice(1)

  const parts = sep ? text.split(sep) : splitByCharacter(text, chunkSize, overlap)

  const chunks: string[] = []
  let current = ''

  for (const part of parts) {
    if (current.length + part.length + sep.length > chunkSize && current.length > 0) {
      chunks.push(current.trim())
      const overlapText = current.substring(Math.max(0, current.length - overlap))
      current = overlapText + sep + part
    } else {
      current += (current ? sep : '') + part
    }
  }
  if (current.trim()) chunks.push(current.trim())

  if (chunks.length <= 1 && text.length > chunkSize && remaining.length > 0) {
    return recursiveSplit(text, remaining, chunkSize, overlap)
  }

  return chunks.length > 0 ? chunks : [text]
}

function mergeChunks(parts: string[], maxSize: number, overlap: number): string[] {
  const chunks: string[] = []
  let current = ''

  for (const part of parts) {
    if (current.length + part.length > maxSize && current.length > 0) {
      chunks.push(current.trim())
      current = current.substring(Math.max(0, current.length - overlap)) + part
    } else {
      current += part
    }
  }
  if (current.trim()) chunks.push(current.trim())
  return chunks
}
