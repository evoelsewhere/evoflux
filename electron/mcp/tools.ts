import {
  listKBs, getKB, listSources, listDocuments, listChunks,
  getKBStats, type KBRow, type SearchResult
} from '../../src/engine/db/kb-repo'
import { hybridSearch } from '../../src/engine/kb/hybrid-search'

export const TOOL_DEFINITIONS = [
  {
    name: 'kb_search',
    description: 'Search a knowledge base using hybrid vector + BM25 search. Returns relevant document chunks with similarity scores.',
    inputSchema: {
      type: 'object' as const,
      properties: {
        kb_id: { type: 'string', description: 'Knowledge base ID (e.g. "kb-xxxxxxxxxx")' },
        query: { type: 'string', description: 'Search query text' },
        limit: { type: 'number', description: 'Maximum number of results (default: 10)' },
        extensions: { type: 'array', items: { type: 'string' }, description: 'Filter by file extensions (e.g. ["md", "ts"])' },
        path_glob: { type: 'string', description: 'Filter by path glob pattern (e.g. "src/**")' }
      },
      required: ['kb_id', 'query']
    }
  },
  {
    name: 'kb_list',
    description: 'List all knowledge bases with their stats (document count, chunk count, size).',
    inputSchema: { type: 'object' as const, properties: {} }
  },
  {
    name: 'kb_get_info',
    description: 'Get detailed information about a knowledge base including config, stats, and sources.',
    inputSchema: {
      type: 'object' as const,
      properties: {
        kb_id: { type: 'string', description: 'Knowledge base ID' }
      },
      required: ['kb_id']
    }
  },
  {
    name: 'kb_list_documents',
    description: 'List all documents in a knowledge base with metadata (name, path, size, chunk count, status).',
    inputSchema: {
      type: 'object' as const,
      properties: {
        kb_id: { type: 'string', description: 'Knowledge base ID' }
      },
      required: ['kb_id']
    }
  },
  {
    name: 'kb_get_document',
    description: 'Get a specific document content preview and its chunks.',
    inputSchema: {
      type: 'object' as const,
      properties: {
        doc_id: { type: 'string', description: 'Document ID (e.g. "doc-xxxxxxxxxx")' }
      },
      required: ['doc_id']
    }
  },
  {
    name: 'kb_get_chunks',
    description: 'Get all chunks for a document with content and metadata.',
    inputSchema: {
      type: 'object' as const,
      properties: {
        doc_id: { type: 'string', description: 'Document ID' }
      },
      required: ['doc_id']
    }
  }
]

export async function handleToolCall(name: string, args: Record<string, unknown>): Promise<{ content: Array<{ type: string; text: string }> }> {
  switch (name) {
    case 'kb_search':
      return handleSearch(args)
    case 'kb_list':
      return handleList()
    case 'kb_get_info':
      return handleGetInfo(args)
    case 'kb_list_documents':
      return handleListDocuments(args)
    case 'kb_get_document':
      return handleGetDocument(args)
    case 'kb_get_chunks':
      return handleGetChunks(args)
    default:
      return { content: [{ type: 'text', text: `Unknown tool: ${name}` }] }
  }
}

async function handleSearch(args: Record<string, unknown>): Promise<{ content: Array<{ type: string; text: string }> }> {
  const kbId = String(args.kb_id)
  const query = String(args.query)
  const limit = Number(args.limit) || 10
  const extensions = args.extensions as string[] | undefined
  const pathGlob = args.path_glob as string | undefined

  const results = await hybridSearch(kbId, query, {
    limit,
    filters: { extensions, pathGlob }
  })

  if (results.length === 0) {
    return { content: [{ type: 'text', text: `No results found for "${query}" in knowledge base ${kbId}.` }] }
  }

  const parts = [`Found ${results.length} results for "${query}":\n`]
  for (const r of results) {
    let meta: Record<string, unknown> = {}
    try { meta = JSON.parse(r.metadata_json || '{}') } catch {}
    parts.push(`### ${r.doc_name} (score: ${r.hybrid_score.toFixed(3)})`)
    if (meta.heading) parts.push(`Section: ${meta.heading}`)
    parts.push(`Path: ${r.doc_path}`)
    parts.push(`\n${r.content.substring(0, 500)}`)
    parts.push('')
  }

  return { content: [{ type: 'text', text: parts.join('\n') }] }
}

function handleList(): { content: Array<{ type: string; text: string }> } {
  const kbs = listKBs()
  if (kbs.length === 0) {
    return { content: [{ type: 'text', text: 'No knowledge bases found.' }] }
  }

  const parts = ['Knowledge Bases:\n']
  for (const kb of kbs) {
    let stats: Record<string, unknown> = {}
    try { stats = JSON.parse(kb.stats_json) } catch {}
    parts.push(`- **${kb.name}** (ID: ${kb.id})`)
    parts.push(`  ${kb.description || 'No description'}`)
    parts.push(`  Docs: ${stats.totalDocs || 0}, Chunks: ${stats.totalChunks || 0}, Size: ${formatBytes(Number(stats.totalSize) || 0)}`)
    parts.push('')
  }

  return { content: [{ type: 'text', text: parts.join('\n') }] }
}

function handleGetInfo(args: Record<string, unknown>): { content: Array<{ type: string; text: string }> } {
  const kbId = String(args.kb_id)
  const kb = getKB(kbId)
  if (!kb) return { content: [{ type: 'text', text: `Knowledge base ${kbId} not found.` }] }

  const sources = listSources(kbId)
  const stats = getKBStats(kbId)
  let config: Record<string, unknown> = {}
  try { config = JSON.parse(kb.config_json) } catch {}

  const parts = [
    `# ${kb.name}`,
    `ID: ${kb.id}`,
    `Description: ${kb.description || 'None'}`,
    '',
    '## Statistics',
    `- Documents: ${stats.totalDocs} (${stats.indexedDocs} indexed)`,
    `- Chunks: ${stats.totalChunks}`,
    `- Size: ${formatBytes(stats.totalSize)}`,
    `- Progress: ${stats.indexedPercent}%`,
    '',
    '## Configuration',
    `- Chunk Size: ${config.chunkSize || 1000}`,
    `- Chunk Overlap: ${config.chunkOverlap || 200}`,
    `- Strategy: ${config.strategy || 'auto'}`,
    '',
    '## Sources'
  ]

  for (const src of sources) {
    parts.push(`- ${src.type}: ${src.path} (${src.status}, ${src.file_count} files)`)
  }

  return { content: [{ type: 'text', text: parts.join('\n') }] }
}

function handleListDocuments(args: Record<string, unknown>): { content: Array<{ type: string; text: string }> } {
  const kbId = String(args.kb_id)
  const docs = listDocuments(kbId)
  if (docs.length === 0) return { content: [{ type: 'text', text: `No documents in knowledge base ${kbId}.` }] }

  const parts = [`Documents in KB ${kbId} (${docs.length} total):\n`]
  for (const doc of docs) {
    parts.push(`- **${doc.name}** (ID: ${doc.id})`)
    parts.push(`  Path: ${doc.path}`)
    parts.push(`  Size: ${formatBytes(doc.size || 0)}, Chunks: ${doc.chunk_count}, Status: ${doc.status}`)
  }

  return { content: [{ type: 'text', text: parts.join('\n') }] }
}

function handleGetDocument(args: Record<string, unknown>): { content: Array<{ type: string; text: string }> } {
  const docId = String(args.doc_id)
  const { getDocument } = require('../../src/engine/db/kb-repo')
  const doc = getDocument(docId)
  if (!doc) return { content: [{ type: 'text', text: `Document ${docId} not found.` }] }

  const parts = [
    `# ${doc.name}`,
    `Path: ${doc.path}`,
    `Extension: ${doc.extension || 'none'}`,
    `Size: ${formatBytes(doc.size || 0)}`,
    `Chunks: ${doc.chunk_count}`,
    `Status: ${doc.status}`,
    '',
    '## Content Preview',
    doc.content_preview || 'No preview available'
  ]

  return { content: [{ type: 'text', text: parts.join('\n') }] }
}

function handleGetChunks(args: Record<string, unknown>): { content: Array<{ type: string; text: string }> } {
  const docId = String(args.doc_id)
  const chunks = listChunks(docId)
  if (chunks.length === 0) return { content: [{ type: 'text', text: `No chunks for document ${docId}.` }] }

  const parts = [`Chunks for document ${docId} (${chunks.length} total):\n`]
  for (const ch of chunks) {
    let meta: Record<string, unknown> = {}
    try { meta = JSON.parse(ch.metadata_json || '{}') } catch {}
    parts.push(`### Chunk #${ch.chunk_index}${meta.heading ? ` - ${meta.heading}` : ''}`)
    if (meta.lineStart) parts.push(`Lines: ${meta.lineStart}-${meta.lineEnd}`)
    parts.push(ch.content)
    parts.push('')
  }

  return { content: [{ type: 'text', text: parts.join('\n') }] }
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}
