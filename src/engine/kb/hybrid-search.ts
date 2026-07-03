import { searchChunksByVector, searchChunksByBM25, type SearchResult, type VectorSearchOptions } from '../db/kb-repo'
import { searchEntities, type WikiEntity } from '../db/wiki-repo'
import { embed } from '../memory/embedding'

export interface HybridSearchOptions {
  limit?: number
  vectorWeight?: number
  bm25Weight?: number
  minScore?: number
  vectorOnly?: boolean
  bm25Only?: boolean
  filters?: {
    extensions?: string[]
    pathGlob?: string
  }
  includeInsights?: boolean
  includeEntities?: boolean
}

export interface UnifiedSearchResult {
  type: 'chunk' | 'entity' | 'insight'
  id: string
  content: string
  score: number
  source?: string
  metadata?: Record<string, unknown>
}

export async function hybridSearch(
  kbId: string,
  query: string,
  options?: HybridSearchOptions
): Promise<SearchResult[]> {
  const limit = options?.limit ?? 10
  const vectorWeight = options?.vectorWeight ?? 0.6
  const bm25Weight = options?.bm25Weight ?? 0.4
  const minScore = options?.minScore ?? 0

  if (options?.bm25Only) {
    return searchChunksByBM25(kbId, query, limit)
  }

  if (options?.vectorOnly) {
    const queryEmbedding = await embed(query, 'query')
    return searchChunksByVector(kbId, Array.from(queryEmbedding), limit)
  }

  const expandedQuery = expandQuery(query)

  const [vectorResults, bm25Results] = await Promise.all([
    (async () => {
      try {
        const queryEmbedding = await embed(expandedQuery, 'query')
        const vectorOpts: VectorSearchOptions = {
          limit: limit * 2,
          extensions: options?.filters?.extensions,
          pathGlob: options?.filters?.pathGlob,
          minScore: 0
        }
        return searchChunksByVector(kbId, Array.from(queryEmbedding), vectorOpts)
      } catch { return [] }
    })(),
    Promise.resolve(applyFilters(searchChunksByBM25(kbId, expandedQuery, limit * 2), options?.filters))
  ])

  const results = reciprocalRankFusion(vectorResults, bm25Results, {
    limit: limit * 2,
    vectorWeight,
    bm25Weight,
    minScore: 0
  })

  const expanded = addContextExpansion(results, kbId)

  return expanded
    .sort((a, b) => b.hybrid_score - a.hybrid_score)
    .slice(0, limit)
}

export async function unifiedSearch(
  kbId: string,
  query: string,
  options?: HybridSearchOptions
): Promise<UnifiedSearchResult[]> {
  const limit = options?.limit ?? 10
  const results: UnifiedSearchResult[] = []

  const chunkResults = await hybridSearch(kbId, query, { ...options, limit: Math.ceil(limit * 0.6) })
  for (const r of chunkResults) {
    results.push({
      type: 'chunk', id: r.chunk_id, content: r.content, score: r.hybrid_score,
      source: r.doc_name, metadata: { doc_path: r.doc_path, heading: r.metadata_json ? JSON.parse(r.metadata_json) : undefined }
    })
  }

  if (options?.includeEntities !== false) {
    const entityResults = searchEntities(kbId, query, Math.ceil(limit * 0.2))
    for (const e of entityResults) {
      results.push({
        type: 'entity', id: e.id, content: `${e.name} (${e.type}): ${e.summary || ''}`,
        score: 0.5, source: 'wiki', metadata: { entity_type: e.type }
      })
    }
  }

  results.sort((a, b) => b.score - a.score)
  return results.slice(0, limit)
}

function expandQuery(query: string): string {
  const intent = classifyIntent(query)
  const expansions: string[] = [query]

  switch (intent) {
    case 'definition':
      expansions.push('what is', 'definition', 'meaning')
      break
    case 'howto':
      expansions.push('how to', 'step', 'guide', 'tutorial', 'example')
      break
    case 'why':
      expansions.push('reason', 'because', 'rationale', 'advantage')
      break
    case 'comparison':
      expansions.push('difference', 'compare', 'versus', 'alternative')
      break
    case 'troubleshooting':
      expansions.push('error', 'fix', 'solution', 'problem', 'issue')
      break
  }

  return expansions.join(' ')
}

function classifyIntent(query: string): 'definition' | 'howto' | 'why' | 'comparison' | 'troubleshooting' | 'general' {
  const lower = query.toLowerCase()
  if (/^what is|^what are|^define|^meaning of/.test(lower)) return 'definition'
  if (/^how to|^how do|^how can|^how does|^guide|^tutorial|^step/.test(lower)) return 'howto'
  if (/^why |^why does|^reason|^what.*reason/.test(lower)) return 'why'
  if (/^difference|^compare|^vs|^versus|^which.*better|^alternative/.test(lower)) return 'comparison'
  if (/^fix|^error|^problem|^issue|^troubleshoot|^debug|^solve/.test(lower)) return 'troubleshooting'
  return 'general'
}

function addContextExpansion(results: SearchResult[], _kbId: string): SearchResult[] {
  const expanded: SearchResult[] = []
  const seen = new Set<string>()

  for (const r of results) {
    if (!seen.has(r.chunk_id)) {
      seen.add(r.chunk_id)
      expanded.push(r)
    }
  }

  return expanded
}

interface FusionOptions {
  limit: number
  vectorWeight: number
  bm25Weight: number
  minScore: number
}

function applyFilters(results: SearchResult[], filters?: { extensions?: string[]; pathGlob?: string }): SearchResult[] {
  if (!filters) return results
  return results.filter(r => {
    if (filters.extensions && filters.extensions.length > 0) {
      const ext = r.doc_extension?.toLowerCase()
      if (!ext || !filters.extensions.map(e => e.toLowerCase()).includes(ext)) return false
    }
    if (filters.pathGlob) {
      const pattern = filters.pathGlob.replace(/\*/g, '.*').replace(/\?/g, '.')
      const regex = new RegExp(`^${pattern}$`, 'i')
      if (!regex.test(r.doc_path)) return false
    }
    return true
  })
}

function reciprocalRankFusion(
  vectorResults: SearchResult[],
  bm25Results: SearchResult[],
  options: FusionOptions
): SearchResult[] {
  const K = 60
  const scoreMap = new Map<string, { result: SearchResult; score: number }>()

  for (let i = 0; i < vectorResults.length; i++) {
    const r = vectorResults[i]
    const rrf = options.vectorWeight / (K + i + 1)
    const existing = scoreMap.get(r.chunk_id)
    if (existing) {
      existing.score += rrf
    } else {
      scoreMap.set(r.chunk_id, { result: { ...r, vector_score: r.vector_score }, score: rrf })
    }
  }

  for (let i = 0; i < bm25Results.length; i++) {
    const r = bm25Results[i]
    const rrf = options.bm25Weight / (K + i + 1)
    const existing = scoreMap.get(r.chunk_id)
    if (existing) {
      existing.score += rrf
    } else {
      scoreMap.set(r.chunk_id, { result: { ...r, bm25_score: r.bm25_score }, score: rrf })
    }
  }

  const results: SearchResult[] = []
  for (const [, { result, score }] of scoreMap) {
    if (score < options.minScore) continue
    results.push({ ...result, hybrid_score: score })
  }

  results.sort((a, b) => b.hybrid_score - a.hybrid_score)
  return results.slice(0, options.limit)
}
