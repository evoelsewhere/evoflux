export interface ChunkMetadata {
  heading?: string
  headingBreadcrumb?: string[]
  headingLevel?: number
  lineStart: number
  lineEnd: number
  sourceFile: string
  sourceType: string
  chunkIndex: number
  contextBefore?: string
  contextAfter?: string
  sectionType?: 'prose' | 'code' | 'list' | 'table' | 'config'
}

export interface Chunk {
  content: string
  metadata: ChunkMetadata
}

export interface ChunkerOptions {
  chunkSize?: number
  chunkOverlap?: number
  minChunkSize?: number
  strategy?: 'auto' | 'heading' | 'paragraph' | 'character' | 'code'
}

const DEFAULT_CHUNK_SIZE = 1000
const DEFAULT_CHUNK_OVERLAP = 200
const DEFAULT_MIN_CHUNK_SIZE = 100

const CODE_EXTENSIONS = new Set([
  'ts', 'tsx', 'js', 'jsx', 'py', 'java', 'go', 'rs', 'c', 'cpp', 'h', 'hpp',
  'cs', 'rb', 'php', 'swift', 'kt', 'lua', 'sh', 'bash', 'sql', 'r', 'scala', 'dart'
])

const MARKDOWN_EXTENSIONS = new Set(['md', 'mdx'])

export function semanticChunk(
  content: string,
  filePath: string,
  options?: ChunkerOptions
): Chunk[] {
  const chunkSize = options?.chunkSize ?? DEFAULT_CHUNK_SIZE
  const chunkOverlap = options?.chunkOverlap ?? DEFAULT_CHUNK_OVERLAP
  const minChunkSize = options?.minChunkSize ?? DEFAULT_MIN_CHUNK_SIZE
  const ext = filePath.split('.').pop()?.toLowerCase() || ''

  let strategy = options?.strategy || 'auto'
  if (strategy === 'auto') {
    if (MARKDOWN_EXTENSIONS.has(ext)) strategy = 'heading'
    else if (CODE_EXTENSIONS.has(ext)) strategy = 'code'
    else strategy = 'paragraph'
  }

  let chunks: Chunk[] = []
  switch (strategy) {
    case 'heading': chunks = chunkByHeading(content, filePath, ext, chunkSize, chunkOverlap, minChunkSize); break
    case 'code': chunks = chunkByCode(content, filePath, ext, chunkSize, chunkOverlap, minChunkSize); break
    case 'paragraph': chunks = chunkByParagraph(content, filePath, ext, chunkSize, chunkOverlap, minChunkSize); break
    case 'character': chunks = chunkByCharacter(content, filePath, ext, chunkSize, chunkOverlap); break
    default: chunks = chunkByParagraph(content, filePath, ext, chunkSize, chunkOverlap, minChunkSize)
  }

  return addContextWindows(chunks)
}

function addContextWindows(chunks: Chunk[]): Chunk[] {
  for (let i = 0; i < chunks.length; i++) {
    if (i > 0) {
      const prevLines = chunks[i - 1].content.split('\n')
      chunks[i].metadata.contextBefore = prevLines.slice(-3).join('\n').substring(0, 200)
    }
    if (i < chunks.length - 1) {
      const nextLines = chunks[i + 1].content.split('\n')
      chunks[i].metadata.contextAfter = nextLines.slice(0, 3).join('\n').substring(0, 200)
    }
  }
  return chunks
}

// ==================== Heading-based chunking ====================

interface HeadingBlock {
  heading: string
  level: number
  lineStart: number
  breadcrumb: string[]
  content: string
}

function parseHeadingBlocks(content: string): HeadingBlock[] {
  const lines = content.split('\n')
  const blocks: HeadingBlock[] = []
  const headingStack: Array<{ text: string; level: number }> = []
  let current: HeadingBlock | null = null

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    const headingMatch = line.match(/^(#{1,6})\s+(.+)$/)

    if (headingMatch) {
      if (current) blocks.push(current)
      const level = headingMatch[1].length
      const text = headingMatch[2].trim()

      while (headingStack.length > 0 && headingStack[headingStack.length - 1].level >= level) {
        headingStack.pop()
      }
      headingStack.push({ text, level })

      current = {
        heading: text,
        level,
        lineStart: i,
        breadcrumb: headingStack.map(h => h.text),
        content: ''
      }
    } else {
      if (!current) {
        current = { heading: '', level: 0, lineStart: i, breadcrumb: [], content: '' }
      }
      current.content += (current.content ? '\n' : '') + line
    }
  }
  if (current) blocks.push(current)

  return blocks
}

function chunkByHeading(
  content: string, filePath: string, ext: string,
  chunkSize: number, overlap: number, minChunkSize: number
): Chunk[] {
  const blocks = parseHeadingBlocks(content)
  const chunks: Chunk[] = []
  let idx = 0

  for (const block of blocks) {
    const text = (block.heading ? `${'#'.repeat(block.level)} ${block.heading}\n` : '') + block.content
    const sectionType = detectSectionType(block.content)

    if (text.length <= chunkSize) {
      if (text.trim().length >= minChunkSize) {
        chunks.push({
          content: text.trim(),
          metadata: {
            heading: block.heading || undefined,
            headingBreadcrumb: block.breadcrumb.length > 0 ? block.breadcrumb : undefined,
            headingLevel: block.level || undefined,
            lineStart: block.lineStart,
            lineEnd: block.lineStart + text.split('\n').length,
            sourceFile: filePath,
            sourceType: ext,
            chunkIndex: idx++,
            sectionType
          }
        })
      }
    } else {
      const subChunks = splitByParagraphs(text, chunkSize, overlap, minChunkSize)
      for (const sub of subChunks) {
        chunks.push({
          content: sub.text.trim(),
          metadata: {
            heading: block.heading || undefined,
            headingBreadcrumb: block.breadcrumb.length > 0 ? block.breadcrumb : undefined,
            headingLevel: block.level || undefined,
            lineStart: block.lineStart + sub.lineOffset,
            lineEnd: block.lineStart + sub.lineOffset + sub.text.split('\n').length,
            sourceFile: filePath,
            sourceType: ext,
            chunkIndex: idx++,
            sectionType
          }
        })
      }
    }
  }

  return mergeSmallChunks(chunks, minChunkSize)
}

// ==================== Code-aware chunking ====================

const CODE_BOUNDARY = /^(export\s+)?(async\s+)?(function|class|interface|type|enum|const\s+\w+\s*=\s*(\(|async|\{))/
const COMMENT_BLOCK = /^\/\*\*[\s\S]*?\*\//

function chunkByCode(
  content: string, filePath: string, ext: string,
  chunkSize: number, overlap: number, minChunkSize: number
): Chunk[] {
  const lines = content.split('\n')
  const blocks: Array<{ name: string; lineStart: number; lines: string[]; type: 'function' | 'class' | 'comment' | 'other' }> = []
  let current: { name: string; lineStart: number; lines: string[]; type: 'function' | 'class' | 'comment' | 'other' } = { name: '', lineStart: 0, lines: [], type: 'other' }

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    if (CODE_BOUNDARY.test(line) && current.lines.length > 0) {
      blocks.push(current)
      const nameMatch = line.match(/(?:function|class|interface|type|enum)\s+(\w+)/)
      const type = line.startsWith('class') ? 'class' : 'function'
      current = { name: nameMatch?.[1] || `block_${blocks.length}`, lineStart: i, lines: [], type }
    }
    current.lines.push(line)
  }
  if (current.lines.length > 0) blocks.push(current)

  const chunks: Chunk[] = []
  let idx = 0

  for (const block of blocks) {
    const text = block.lines.join('\n')
    if (text.trim().length < minChunkSize) continue

    if (text.length <= chunkSize) {
      chunks.push({
        content: text.trim(),
        metadata: {
          heading: block.name,
          headingBreadcrumb: [block.name],
          lineStart: block.lineStart,
          lineEnd: block.lineStart + block.lines.length,
          sourceFile: filePath,
          sourceType: ext,
          chunkIndex: idx++,
          sectionType: 'code'
        }
      })
    } else {
      const subChunks = splitByCharacter(text, chunkSize, overlap)
      for (const sub of subChunks) {
        chunks.push({
          content: sub.text.trim(),
          metadata: {
            heading: block.name,
            headingBreadcrumb: [block.name],
            lineStart: block.lineStart + sub.lineOffset,
            lineEnd: block.lineStart + sub.lineOffset + sub.text.split('\n').length,
            sourceFile: filePath,
            sourceType: ext,
            chunkIndex: idx++,
            sectionType: 'code'
          }
        })
      }
    }
  }

  return mergeSmallChunks(chunks, minChunkSize)
}

// ==================== Paragraph-based chunking ====================

function chunkByParagraph(
  content: string, filePath: string, ext: string,
  chunkSize: number, overlap: number, minChunkSize: number
): Chunk[] {
  const parts = splitByParagraphs(content, chunkSize, overlap, minChunkSize)
  return parts.map((p, i) => ({
    content: p.text.trim(),
    metadata: {
      lineStart: p.lineOffset,
      lineEnd: p.lineOffset + p.text.split('\n').length,
      sourceFile: filePath,
      sourceType: ext,
      chunkIndex: i,
      sectionType: detectSectionType(p.text)
    }
  })).filter(c => c.content.length >= minChunkSize)
}

// ==================== Character-based chunking ====================

function chunkByCharacter(
  content: string, filePath: string, ext: string,
  chunkSize: number, overlap: number
): Chunk[] {
  const parts = splitByCharacter(content, chunkSize, overlap)
  return parts.map((p, i) => ({
    content: p.text.trim(),
    metadata: {
      lineStart: p.lineOffset,
      lineEnd: p.lineOffset + p.text.split('\n').length,
      sourceFile: filePath,
      sourceType: ext,
      chunkIndex: i,
      sectionType: detectSectionType(p.text)
    }
  })).filter(c => c.content.length > 0)
}

// ==================== Helpers ====================

function detectSectionType(text: string): 'prose' | 'code' | 'list' | 'table' | 'config' {
  const trimmed = text.trim()
  if (/^```|^import |^export |^const |^function |^class /.test(trimmed)) return 'code'
  if (/^[-*]\s|^\d+\.\s/.test(trimmed)) return 'list'
  if (/^\|.*\|/.test(trimmed)) return 'table'
  if (/^[A-Z_]+\s*[:=]|^\w+:\s*\w+/m.test(trimmed)) return 'config'
  return 'prose'
}

interface SplitPart { text: string; lineOffset: number }

function splitByParagraphs(text: string, chunkSize: number, overlap: number, minSize: number): SplitPart[] {
  const paragraphs = text.split(/\n\n+/)
  const parts: SplitPart[] = []
  let current = ''
  let lineOffset = 0
  let currentLineOffset = 0

  for (const para of paragraphs) {
    if (current.length + para.length + 2 > chunkSize && current.length >= minSize) {
      parts.push({ text: current, lineOffset: currentLineOffset })
      const overlapText = current.substring(Math.max(0, current.length - overlap))
      current = overlapText + '\n\n' + para
      currentLineOffset = lineOffset
    } else {
      if (!current) currentLineOffset = lineOffset
      current += (current ? '\n\n' : '') + para
    }
    lineOffset += para.split('\n').length + 1
  }

  if (current.trim().length >= minSize) {
    parts.push({ text: current, lineOffset: currentLineOffset })
  }

  return parts
}

function splitByCharacter(text: string, chunkSize: number, overlap: number): SplitPart[] {
  const parts: SplitPart[] = []
  let start = 0
  let lineOffset = 0

  while (start < text.length) {
    let end = Math.min(start + chunkSize, text.length)

    if (end < text.length) {
      const breakChars = ['\n\n', '\n', '. ', ' ', '']
      for (const brk of breakChars) {
        const lastBreak = text.lastIndexOf(brk, end)
        if (lastBreak > start + chunkSize * 0.3) {
          end = lastBreak + brk.length
          break
        }
      }
    }

    const chunk = text.substring(start, end)
    parts.push({ text: chunk, lineOffset })

    lineOffset += chunk.split('\n').length - 1
    start = end - overlap
    if (start >= text.length - overlap) break
  }

  return parts
}

function mergeSmallChunks(chunks: Chunk[], minSize: number): Chunk[] {
  if (chunks.length <= 1) return chunks

  const merged: Chunk[] = []
  let i = 0

  while (i < chunks.length) {
    let current = chunks[i]

    while (i + 1 < chunks.length && current.content.length < minSize) {
      const next = chunks[i + 1]
      current = {
        content: current.content + '\n\n' + next.content,
        metadata: {
          ...current.metadata,
          lineEnd: next.metadata.lineEnd,
          chunkIndex: current.metadata.chunkIndex
        }
      }
      i++
    }

    merged.push(current)
    i++
  }

  return merged
}
