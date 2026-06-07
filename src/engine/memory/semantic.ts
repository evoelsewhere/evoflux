import type { MemoryGraph, SemanticUnit, SemanticType } from './memory-graph'
import { embed, cosineSimilarity } from './embedding'

export interface SemanticSearchResult {
  unit: SemanticUnit
  score: number
}

export class SemanticLayer {
  constructor(private graph: MemoryGraph) {}

  async add(content: string, type: SemanticType, metadata: Record<string, unknown> = {}): Promise<string> {
    const embedding = await embed(content, 'passage')
    return this.graph.addSemantic({ type, content, embedding, metadata })
  }

  async search(query: string, k = 5): Promise<SemanticSearchResult[]> {
    const queryEmbedding = await embed(query, 'query')
    const units = this.graph.getAllSemantic()

    const scored: SemanticSearchResult[] = []
    for (const unit of units) {
      if (!unit.embedding) continue
      const score = cosineSimilarity(queryEmbedding, unit.embedding)
      scored.push({ unit, score })
    }

    scored.sort((a, b) => b.score - a.score)
    return scored.slice(0, k)
  }

  async addBatch(items: Array<{ content: string; type: SemanticType; metadata?: Record<string, unknown> }>): Promise<string[]> {
    const ids: string[] = []
    for (const item of items) {
      const id = await this.add(item.content, item.type, item.metadata)
      ids.push(id)
    }
    return ids
  }

  getByType(type: SemanticType): SemanticUnit[] {
    return this.graph.getAllSemantic().filter(u => u.type === type)
  }

  getMostAccessed(limit: number): SemanticUnit[] {
    return this.graph.getAllSemantic()
      .sort((a, b) => b.accessCount - a.accessCount)
      .slice(0, limit)
  }
}
