import { searchChunksByVector, searchChunksByBM25, type SearchResult } from '../db/kb-repo'
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

  const [vectorResults, bm25Results] = await Promise.all([
    (async () => {
      try {
        const queryEmbedding = await embed(query, 'query')
        return applyFilters(searchChunksByVector(kbId, Array.from(queryEmbedding), limit * 2), options?.filters)
      } catch { return [] }
    })(),
    Promise.resolve(applyFilters(searchChunksByBM25(kbId, query, limit * 2), options?.filters))
  ])

  return reciprocalRankFusion(vectorResults, bm25Results, {
    limit,
    vectorWeight,
    bm25Weight,
    minScore
  })
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
