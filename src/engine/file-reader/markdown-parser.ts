export interface MarkdownHeading {
  level: number
  text: string
}

export interface MarkdownCodeBlock {
  lang: string
  code: string
}

export interface MarkdownLink {
  text: string
  url: string
}

export interface MarkdownTable {
  headers: string[]
  rows: string[][]
}

export interface MarkdownAST {
  headings: MarkdownHeading[]
  codeBlocks: MarkdownCodeBlock[]
  links: MarkdownLink[]
  tables: MarkdownTable[]
  plainText: string
  frontmatter: Record<string, unknown> | null
}

export function parseMarkdownToText(md: string): string {
  let text = md

  // Strip frontmatter
  text = text.replace(/^---[\s\S]*?---\n?/, '')

  // Headings: keep as text
  text = text.replace(/^(#{1,6})\s+(.+)$/gm, (_, hashes: string, title: string) => {
    return `${'#'.repeat(hashes.length)} ${title}`
  })

  // Code blocks: preserve content
  text = text.replace(/```[\w]*\n([\s\S]*?)```/g, (_: string, code: string) => code.trim())

  // Inline code
  text = text.replace(/`([^`]+)`/g, '$1')

  // Bold/italic
  text = text.replace(/\*\*\*(.+?)\*\*\*/g, '$1')
  text = text.replace(/\*\*(.+?)\*\*/g, '$1')
  text = text.replace(/\*(.+?)\*/g, '$1')
  text = text.replace(/___(.+?)___/g, '$1')
  text = text.replace(/__(.+?)__/g, '$1')
  text = text.replace(/_(.+?)_/g, '$1')

  // Images: ![alt](src) → alt (must be before links)
  text = text.replace(/!\[([^\]]*)\]\([^)]+\)/g, '$1')

  // Links: [text](url) → text
  text = text.replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')

  // Lists: keep bullets
  text = text.replace(/^[\s]*[-*+]\s+/gm, '- ')
  text = text.replace(/^[\s]*\d+\.\s+/gm, (match: string) => match)

  // Blockquotes
  text = text.replace(/^>\s?/gm, '')

  // Horizontal rules
  text = text.replace(/^[-*_]{3,}\s*$/gm, '---')

  // HTML tags
  text = text.replace(/<[^>]+>/g, '')

  // Multiple blank lines
  text = text.replace(/\n{3,}/g, '\n\n')

  return text.trim()
}

export function parseMarkdownToStructured(md: string): MarkdownAST {
  return {
    headings: extractHeadings(md),
    codeBlocks: extractCodeBlocks(md),
    links: extractLinks(md),
    tables: extractTables(md),
    plainText: parseMarkdownToText(md),
    frontmatter: extractFrontmatter(md)
  }
}

function extractFrontmatter(md: string): Record<string, unknown> | null {
  const match = md.match(/^---\n([\s\S]*?)\n---/)
  if (!match) return null

  const result: Record<string, unknown> = {}
  for (const line of match[1].split('\n')) {
    const colonIdx = line.indexOf(':')
    if (colonIdx > 0) {
      const key = line.substring(0, colonIdx).trim()
      const value = line.substring(colonIdx + 1).trim()
      result[key] = value
    }
  }
  return result
}

function extractHeadings(md: string): MarkdownHeading[] {
  const headings: MarkdownHeading[] = []
  const regex = /^(#{1,6})\s+(.+)$/gm
  let match: RegExpExecArray | null
  while ((match = regex.exec(md)) !== null) {
    headings.push({ level: match[1].length, text: match[2].trim() })
  }
  return headings
}

function extractCodeBlocks(md: string): MarkdownCodeBlock[] {
  const blocks: MarkdownCodeBlock[] = []
  const regex = /```(\w*)\n([\s\S]*?)```/g
  let match: RegExpExecArray | null
  while ((match = regex.exec(md)) !== null) {
    blocks.push({ lang: match[1] || 'text', code: match[2].trim() })
  }
  return blocks
}

function extractLinks(md: string): MarkdownLink[] {
  const links: MarkdownLink[] = []
  const regex = /\[([^\]]+)\]\(([^)]+)\)/g
  let match: RegExpExecArray | null
  while ((match = regex.exec(md)) !== null) {
    links.push({ text: match[1], url: match[2] })
  }
  return links
}

function extractTables(md: string): MarkdownTable[] {
  const tables: MarkdownTable[] = []
  const tableRegex = /\|(.+)\|\n\|[-| ]+\|\n((?:\|.+\|\n?)+)/g
  let match: RegExpExecArray | null
  while ((match = tableRegex.exec(md)) !== null) {
    const headers = match[1].split('|').map(h => h.trim()).filter(Boolean)
    const rows = match[2].trim().split('\n').map(row =>
      row.split('|').map(cell => cell.trim()).filter(Boolean)
    )
    tables.push({ headers, rows })
  }
  return tables
}
